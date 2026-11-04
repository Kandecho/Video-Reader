"""Explicit selected-video batches; one resumable Reader delivery per step.

No scheduler, recommendation policy, preference learning or private delivery.
An unacknowledged page is replayed after interruption instead of being skipped.
"""
import hashlib
from pathlib import Path
import re
import time
import uuid

from filelock import FileLock

from video_reader.common import ReaderError, digest, read_json, write_json
from video_reader.delivery import original_page
from video_reader.platform import credentials, PlatformError
from video_reader.review import overlay
from video_reader.sources import resolve


class Batch:
    def __init__(self, reader, offline=False):
        if not isinstance(offline, bool):
            raise ReaderError('offline must be true or false')
        self.reader, self.offline = reader, offline
        try:
            self.scope = credentials(reader.config)['account_marker']
        except PlatformError as error:
            if str(error) not in ('login_required', 'managed_login_disabled'):
                raise
            self.scope = 'anonymous'
        from .store import Store
        store=Store.from_settings(reader.config,reader.config_path)
        self.root=store.directory/'batches'/self.scope
        self.legacy_root=(reader.config_path.parent/(reader.config.get('agent') or {}).get('directory','data/agent')).resolve()/'batches'/self.scope

    def directory(self, batch_id):
        if not re.fullmatch(r'batch_[a-f0-9]{32}', batch_id or ''):
            raise ReaderError('Invalid batch ID')
        legacy=self.legacy_root/batch_id
        return legacy if (legacy/'batch.json').is_file() else self.root/batch_id

    def load(self, batch_id):
        path = self.directory(batch_id) / 'batch.json'
        if not path.is_file():
            raise ReaderError('Batch not found in the current account scope')
        return read_json(path)

    def save(self, state):
        state['updated_at'] = time.time()
        write_json(self.directory(state['batch_id']) / 'batch.json', state)

    def start(self, sources, task='', source='auto'):
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20 or any(not isinstance(item, str) for item in sources):
            raise ReaderError('Choose 1..20 video sources or existing session IDs')
        if not isinstance(task, str) or len(task) > 4000 or source not in ('auto','captions','asr','qwen'):
            raise ReaderError('Use a task of at most 4000 characters and an existing speech source')
        items = []
        for value in sources:
            item = {'source': value, 'status': 'pending', 'phase': 'open', 'delivered_segment_ids': [], 'failures': []}
            try:
                if re.fullmatch(r'v_[a-f0-9]{24}', value):
                    data = self.reader.load(value)
                    item.update(session_id=value, canonical=data['source']['canonical'])
                else:
                    item['canonical'] = resolve(value)['canonical']
            except (ReaderError, OSError, ValueError) as error:
                item.update(status='failed', error=str(error))
            items.append(item)
        state = {'schema': 1, 'batch_id': 'batch_' + uuid.uuid4().hex, 'account_scope': self.scope,
                 'task': task, 'speech_source': source, 'items': items, 'created_at': time.time(),
                 'sequence': 0, 'last_acknowledged': None, 'pending_delivery': None}
        self.save(state)
        return self.status(state['batch_id'])

    def status(self, batch_id):
        state = self.load(batch_id)
        finished = all(item['status'] in ('delivered','delivered_with_gaps','failed') for item in state['items']) and not state['pending_delivery']
        delivered = all(item['status'] == 'delivered' for item in state['items']) and not state['pending_delivery']
        return {'batch_id': batch_id, 'account_scope': self.scope, 'task': state['task'],
            'items': [{key: item.get(key) for key in ('source','canonical','session_id','status','phase','error','gap')} for item in state['items']],
            'pending_cursor': (state.get('pending_delivery') or {}).get('cursor'),
            'last_acknowledged': state['last_acknowledged'],
            'all_material_delivered': delivered, 'processing_finished': bool(finished),
            'batch_status': 'complete' if delivered else 'partial' if finished else 'active',
            'host_observation': 'not_inferred', 'messages_sent': 0, 'scheduler_changed': False}

    def _cached(self, value):
        source = resolve(value)
        for record in self.reader.materials([source['canonical']])[source['canonical']]:
            try:
                self.reader.load(record['session_id'])
            except ReaderError:
                continue
            if record['media_available']:
                return record['session_id']
        return None

    def _material(self, state, item):
        reader, source = self.reader, state['speech_source']
        if item['phase'] == 'open':
            session = item.get('session_id') or self._cached(item['source'])
            if not session:
                if self.offline:
                    raise ReaderError('offline_source_cache_miss')
                opened = reader.open(item['source'], task=state['task'], strategy='adaptive')
                session = opened['session_id']
            item['session_id'] = session
            item['canonical'] = reader.load(session)['source']['canonical']
            result = reader.read(session, strategy='adaptive', task=state['task'], source=source, verify=False, temporal=False)
            item.update(frame_cursor=result['delivery']['next_cursor'], phase='frames' if result['delivery']['next_cursor'] else 'speech')
            return result
        if item['phase'] == 'frames':
            result = reader.continue_read(item['session_id'], item['frame_cursor'])
            item.update(frame_cursor=result['delivery']['next_cursor'], phase='frames' if result['delivery']['next_cursor'] else 'speech')
            return result
        session = item['session_id']
        if item.get('speech_cursor'):
            result = reader.continue_read(session, item['speech_cursor'])
        else:
            previous = item['delivered_segment_ids']
            result = reader.transcript(session, source=source, offset=len(previous), verify=False, max_chunks=1)
            index=reader.speech_index(session,source)
            ready_ids,ready_signatures,review=index['segment_ids'],index['signatures'],index['review']
            old_review = item.get('delivered_review', {})
            revision_changed = old_review.get('snapshot_id') == review['snapshot_id'] and old_review.get('revision') != review['revision']
            if previous != ready_ids[:len(previous)] or item.get('delivered_signatures', []) != ready_signatures[:len(previous)] or (previous and revision_changed):
                # Qwen seam assembly or an external edit can revise earlier text.
                # Deliver that new snapshot explicitly; do not skip by old offset.
                result = reader.transcript(session, source=source, verify=False, transcribe=False)
                item['material_restart_reason'] = 'Earlier speech changed; the new snapshot is delivered from its beginning'
            item['ready_segment_ids'] = ready_ids
            item['ready_signatures'], item['ready_review'] = ready_signatures, review
        material = original_page(reader, result)
        item['speech_cursor'] = result['delivery']['next_cursor']
        if not item['speech_cursor']:
            item['delivered_segment_ids'] = item.get('ready_segment_ids', [])
            item['delivered_signatures'], item['delivered_review'] = item.get('ready_signatures', []), item.get('ready_review', {})
            if material.get('coverage', {}).get('complete'):
                item['phase'] = 'done'
            elif material.get('status') == 'no_audio_stream':
                item.update(phase='done', stream_absence='no_audio_stream')
            elif material.get('status') == 'unavailable':
                item.update(phase='done', gap=material.get('reason') or material['status'])
        return result

    def next(self, batch_id, after_cursor=None):
        directory = self.directory(batch_id)
        with FileLock(str(directory / 'batch.lock'), timeout=600):
            state = self.load(batch_id)
            pending = state.get('pending_delivery')
            if pending:
                if after_cursor in (None, state['last_acknowledged']):
                    response = read_json(directory / pending['file'])
                    if response.get('material', {}).get('delivery'):
                        saved = response['material']['delivery']
                        response['material'] = self.reader.continue_read(response['session_id'], saved['snapshot_id'] + ':' + str(saved['page']))
                    return response
                if after_cursor != pending['cursor']:
                    raise ReaderError('Acknowledgment does not match this batch delivery')
                state['last_acknowledged'] = pending['cursor']
                item = state['items'][pending['item_index']]
                if item['phase'] == 'done':
                    item['status'] = 'delivered_with_gaps' if item.get('gap') else 'delivered'
                state['pending_delivery'] = None
                self.save(state)
            elif after_cursor not in (None, state['last_acknowledged']):
                raise ReaderError('Unknown batch acknowledgment')
            index = next((i for i, item in enumerate(state['items']) if item['status'] in ('pending','active')), None)
            if index is None:
                return self.status(batch_id)
            item = state['items'][index]
            item['status'] = 'active'
            self.save(state)
            try:
                material = self._material(state, item)
                response = {'batch_id': batch_id, 'item_index': index, 'source': item['canonical'],
                    'session_id': item['session_id'], 'material': material,
                    'material_restart_reason': item.pop('material_restart_reason', None),
                    'host_observation': 'not_inferred', 'messages_sent': 0}
            except (ReaderError, OSError, ValueError, KeyError) as error:
                item.update(status='failed', error=str(error))
                item['failures'].append({'phase': item['phase'], 'error': str(error), 'at': time.time()})
                response = {'batch_id': batch_id, 'item_index': index, 'source': item['source'],
                            'status': 'item_failed', 'error': str(error), 'messages_sent': 0}
            state['sequence'] += 1
            cursor = batch_id + ':' + str(state['sequence'])
            response.update(next_ack_cursor=cursor, continuation_hint='After inspecting this page, pass next_ack_cursor as after_cursor. Omit it to replay after an uncertain response.')
            name = 'delivery-' + str(state['sequence']) + '.json'
            write_json(directory / name, response)
            state['pending_delivery'] = {'cursor': cursor, 'item_index': index, 'file': name}
            self.save(state)
            return response

    def retry(self, batch_id, item_index):
        directory = self.directory(batch_id)
        with FileLock(str(directory / 'batch.lock'), timeout=600):
            state = self.load(batch_id)
            if state['pending_delivery']:
                raise ReaderError('Acknowledge the pending delivery before retrying an item')
            if type(item_index) is not int or not 0 <= item_index < len(state['items']):
                raise ReaderError('item_index is outside this batch')
            item = state['items'][item_index]
            if item['status'] not in ('failed','delivered_with_gaps'):
                raise ReaderError('Only a failed or incomplete item can be retried')
            item.update(status='pending', phase='open', frame_cursor=None, speech_cursor=None, delivered_segment_ids=[], delivered_signatures=[], delivered_review={})
            item.pop('error', None)
            item.pop('gap', None)
            self.save(state)
        return self.status(batch_id)
