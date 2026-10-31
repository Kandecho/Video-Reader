"""A small autonomous round: acquire evidence, ask the host, archive, optionally deliver."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
import math
from pathlib import Path
import re
import time
import uuid

from filelock import FileLock, Timeout

from . import host as agent_host, schedule as agent_schedule
from .memory import Memory
from video_reader import preview
from video_reader.platform import Platform, PlatformError
from video_reader.common import ReaderError, UNTRUSTED, digest, read_json, write_json
from video_reader.sources import resolve


def validate(options):
    if not isinstance(options['directory'], str) or not options['directory'].strip():
        raise ReaderError('agent.directory must be a nonempty path')
    for key in ('executable', 'model'):
        value = options['host'][key]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ReaderError(f'agent.host.{key} must be a nonempty string or null')
    for key, minimum, maximum in [('candidate_count', 1, 20), ('preview_count', 1, 6),
                                  ('max_recommendations', 1, 5), ('max_caption_chars', 1000, 100000)]:
        value = options[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ReaderError(f'agent.{key} must be an integer in {minimum}..{maximum}')
    if options['max_recommendations'] > options['preview_count']:
        raise ReaderError('max_recommendations cannot exceed preview_count')
    if (not isinstance(options['deep_read']['enabled'], bool)
            or isinstance(options['deep_read']['max_videos'], bool)
            or not isinstance(options['deep_read']['max_videos'], int)
            or not 0 <= options['deep_read']['max_videos'] <= 3
            or isinstance(options['deep_read']['max_duration_seconds'], bool)
            or not isinstance(options['deep_read']['max_duration_seconds'], (float, int))
            or not math.isfinite(options['deep_read']['max_duration_seconds'])
            or options['deep_read']['max_duration_seconds'] <= 0):
        raise ReaderError('Invalid bounded deep_read settings')
    for section, keys in [(options, ('reconsider_hours',)),
                          (options['host'], ('timeout_seconds',))]:
        for key in keys:
            value = section[key]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ReaderError(f'{key} must be finite and positive')
    if not isinstance(options['delivery']['enabled'], bool):
        raise ReaderError('delivery.enabled must be true or false')
    recipient = options['delivery']['recipient_uid']
    if recipient is not None and (isinstance(recipient, bool) or not re.fullmatch(r'[1-9]\d{0,19}', str(recipient))):
        raise ReaderError('recipient_uid must be a positive UID')
    if options['delivery']['enabled'] and recipient is None:
        raise ReaderError('Configure a recipient before enabling private delivery')
    agent_schedule.validate(options['wake'])
    daily = options['daily']
    if not isinstance(daily['enabled'], bool):
        raise ReaderError('daily.enabled must be true or false')
    agent_schedule.clock_minutes(daily['time'])
    agent_schedule.local_zone(daily['timezone'])
    if daily['enabled'] and recipient is None:
        raise ReaderError('Daily delivery requires a configured recipient')


class Agent:
    def __init__(self, reader, *, offline=False, platform=None):
        self.reader, self.options = reader, copy.deepcopy(reader.config['agent'])
        self.options['directory'] = str((reader.config_path.parent / self.options['directory']).resolve())
        validate(self.options)
        self.platform = platform or Platform(reader.config, offline=offline,
            write_endpoints=('https://api.vc.bilibili.com/web_im/v1/web_im/send_msg',))
        self.scope = self.platform.scope
        self.root = Path(self.options['directory'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(self.root, self.scope)
        self.lock = FileLock(str(self.root / 'round.lock'), timeout=0)

    def directory(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'round_[a-f0-9]{32}', run_id):
            raise ReaderError('Invalid agent round ID')
        return self.root / 'rounds' / self.scope / run_id

    def _cached_material(self, item):
        for path in self.reader.cache.glob('v_*/manifest.json'):
            try:
                data = read_json(path)
                if (data['source'].get('canonical') != item['url']
                        or data.get('authentication', {}).get('account_marker') != self.scope):
                    continue
                return self._source_material(data['id'], item, transcribe=False)
            except (ReaderError, OSError, ValueError, KeyError):
                continue
        return None

    def _source_material(self, session, item, *, transcribe):
        images = self.reader.read(session, max_frames=5, verify=False, temporal=False, _delivery=False)
        speech = self.reader.transcript(session, limit=200, transcribe=transcribe, verify=False, _delivery=False)
        source = resolve(item['url'])
        gaps = ['sampled_frames_not_continuous_viewing', 'speech_not_proofread_by_this_round']
        if speech.get('next_offset') is not None:
            gaps.append('speech_page_truncated')
        if not speech.get('segments'):
            gaps.append('no_usable_speech_not_proof_of_silence')
        return {'url': item['url'], 'title': images['title'], 'bvid': source['bvid'], 'part': source['page'],
                'duration_seconds': images['metadata']['duration_seconds'], 'session_id': session,
                'frames': images['visual']['frames'],
                'caption': {'segments': speech.get('segments', []), 'source': speech.get('source'),
                            'status': speech.get('status'), 'proofread': False},
                'material_level': 'source_frames_and_machine_speech' if transcribe else 'cached_source_excerpt',
                'reading_status': 'previewed_not_read', 'gaps': gaps, 'notice': UNTRUSTED}

    def _prepare(self, query='', *, trial_day=None):
        if not isinstance(query, str) or len(query) > 200:
            raise ReaderError('Agent query must contain at most 200 characters')
        run_id = 'round_' + uuid.uuid4().hex
        directory = self.directory(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        packet = {'run_id': run_id, 'account_scope': self.scope, 'query': query,
                  'max_recommendations': self.options['max_recommendations'],
                  'memory': self.memory.context(query), 'candidates': [], 'previews': [], 'failures': [],
                  'notice': UNTRUSTED, 'delivery_enabled': self.options['delivery']['enabled']}
        if trial_day:
            packet.update(trial_day=trial_day, selection_policy='homepage_first_daily_trial', max_recommendations=1)
        self.memory.save_run(run_id, 'preparing', packet)
        try:
            rows = preview.candidates(self.platform, query, self.options['candidate_count'], fresh=bool(trial_day))
            excluded = set() if trial_day else self.memory.excluded(self.options['reconsider_hours'])
            packet['candidates'] = rows[:1] if trial_day else [item for item in rows if item['url'] not in excluded]
            if trial_day and not packet['candidates']:
                packet['failures'].append({'stage': 'homepage_first', 'error': 'no_real_video_in_homepage_response'})
            for item in packet['candidates']:
                if len(packet['previews']) >= self.options['preview_count']:
                    break
                try:
                    material = self._cached_material(item) or preview.preview(self.platform, item['url'])
                    caption = material.get('caption')
                    if caption:
                        kept, characters = [], 0
                        for segment in caption.get('segments', []):
                            characters += len(segment['text'])
                            if characters > self.options['max_caption_chars']:
                                material['gaps'].append('caption_truncated_for_context')
                                break
                            kept.append(segment)
                        material['caption'] = {**caption, 'segments': kept}
                    packet['previews'].append(material)
                    self.memory.record_video(item['url'], 'previewed', 'Awaiting host assessment; not complete reading')
                except ReaderError as error:
                    packet['failures'].append({'url': item['url'], 'error': str(error)})
                    if isinstance(error, PlatformError) and 'paused' in error.code:
                        break
                    if trial_day and not self.platform.status().get('paused'):
                        packet['previews'].append({**item, 'frames': [], 'caption': None,
                            'material_level': 'metadata_only', 'reading_status': 'not_read',
                            'gaps': ['preview_failed_link_only'], 'notice': UNTRUSTED})
        except ReaderError as error:
            packet['failures'].append({'stage': 'discovery', 'error': str(error)})
        packet['cost'] = {'requests': sum(item['cache'] == 'miss' for item in self.platform.trace),
                          'cache_hits': sum(item['cache'] == 'hit' for item in self.platform.trace),
                          'response_bytes': sum(item['bytes'] for item in self.platform.trace)}
        packet['status'] = 'prepared'
        write_json(directory / 'packet.json', packet)
        self.memory.save_run(run_id, 'prepared', packet)
        return packet

    def prepare(self, query=''):
        try:
            with self.lock:
                return self._prepare(query)
        except Timeout:
            raise ReaderError('Another video-agent round is active') from None

    def daily_day(self, now=None):
        instant = now or datetime.now(timezone.utc)
        return instant.astimezone(agent_schedule.local_zone(self.options['daily']['timezone'])).date().isoformat()

    def daily_due(self, now=None):
        instant = now or datetime.now(timezone.utc)
        local = instant.astimezone(agent_schedule.local_zone(self.options['daily']['timezone']))
        return local.strftime('%H:%M') >= self.options['daily']['time']

    def _prepare_daily(self, now=None):
        if self.options['daily']['enabled'] and not self.daily_due(now):
            return {'status': 'before_daily_time'}
        recipient = self.options['delivery']['recipient_uid']
        if recipient is None:
            raise ReaderError('Configure the daily recipient first')
        day = self.daily_day(now)
        path = self.root / 'daily' / self.scope / f'{recipient}-{day}.json'
        if path.is_file():
            return self.memory.load_run(read_json(path)['run_id'])
        packet = self._prepare(trial_day=day)
        write_json(path, {'run_id': packet['run_id'], 'day': day, 'recipient_uid': recipient})
        return packet

    def prepare_daily(self, *, now=None):
        try:
            with self.lock:
                return self._prepare_daily(now)
        except Timeout:
            raise ReaderError('Another scroll round is active') from None

    def _decisions(self, packet, result):
        rows = result.get('decisions') if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise ReaderError('Host result needs a decisions array')
        known = {item['url']: item for item in packet['previews']}
        seen, decisions = set(), []
        for row in rows:
            if not isinstance(row, dict) or row.get('url') not in known or row['url'] in seen:
                raise ReaderError('Every host decision must name a unique prepared URL')
            if not isinstance(row.get('recommend'), bool) or not isinstance(row.get('needs_deep_read'), bool):
                raise ReaderError('Host decisions require boolean recommend and needs_deep_read')
            reason = row.get('reason')
            if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 600:
                raise ReaderError('Each host decision needs a reason of 1..600 characters')
            if row['recommend'] and row['needs_deep_read']:
                raise ReaderError('Insufficient material cannot also be a recommendation')
            material = known[row['url']]
            if row['recommend'] and not material.get('frames') and not (material.get('caption') or {}).get('segments'):
                raise ReaderError('Metadata-only material cannot justify a content recommendation')
            seen.add(row['url'])
            decisions.append({'url': row['url'], 'recommend': row['recommend'], 'reason': reason.strip(),
                              'needs_deep_read': row['needs_deep_read'], 'title': material.get('title') or row['url'],
                              'material_level': material['material_level'], 'gaps': material['gaps']})
        if seen != set(known):
            raise ReaderError('Host must account for every prepared preview')
        if sum(row['recommend'] for row in decisions) > self.options['max_recommendations']:
            raise ReaderError('Host exceeded the recommendation limit')
        return decisions

    def _finish(self, run_id, decision, dry_run=True):
        packet = self.memory.load_run(run_id)
        if packet.get('status') != 'prepared':
            return packet
        decisions = self._decisions(packet, decision)
        status = 'acquisition_failed' if packet['failures'] and not packet['previews'] else 'finished'
        result = {**packet, 'status': status, 'decisions': decisions, 'dry_run': dry_run,
                  'selected': [row for row in decisions if row['recommend']], 'delivery': {'status': 'not_sent'}}
        if packet.get('trial_day'):
            result['selected'] = decisions
        for row in decisions:
            self.memory.record_video(row['url'], 'recommended' if row['recommend'] and not dry_run else 'previewed', row['reason'])
            self.memory.remember(row['reason'], 'observation', row['url'])
        self.memory.save_run(run_id, status, result)
        self._archive(result)
        if not dry_run:
            result['delivery'] = self.deliver(run_id)
            self.memory.save_run(run_id, status, result)
            self._archive(result)
        return result

    def finish(self, run_id, decision, dry_run=True):
        try:
            with self.lock:
                return self._finish(run_id, decision, dry_run)
        except Timeout:
            raise ReaderError('Another video-agent round is active') from None

    def _archive(self, result):
        directory = self.directory(result['run_id'])
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / 'result.json', result)
        lines = ['# 视频选片记录', '', f"轮次：{result['run_id']}", f"状态：{result['status']}", '']
        for row in result.get('decisions', []):
            lines.extend([f"## {'推荐' if row['recommend'] else '暂缓'}：{row['title']}", row['url'], row['reason'],
                          f"材料：{row['material_level']}；缺项：{', '.join(row['gaps']) or '未报告'}", ''])
        for failure in result.get('failures', []):
            lines.append('缺项：' + json.dumps(failure, ensure_ascii=False))
        lines.append('投递：' + json.dumps(result.get('delivery', {}), ensure_ascii=False))
        (directory / 'archive.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def run(self, query='', *, dry_run=True, evaluator=None, daily=False):
        try:
            with self.lock:
                packet = self._prepare_daily() if daily else self._prepare(query)
                if packet.get('status') != 'prepared':
                    return packet
                try:
                    decision = ((evaluator or agent_host.decide)(packet, self.directory(packet['run_id']), self.options['host'])
                                if packet['previews'] else {'decisions': []})
                    assessed = self._decisions(packet, decision)
                    if self.options['deep_read']['enabled'] and not self.platform.offline:
                        changed = self._deepen(packet, assessed)
                        if changed:
                            write_json(self.directory(packet['run_id']) / 'packet.json', packet)
                            self.memory.save_run(packet['run_id'], 'prepared', packet)
                            decision = (evaluator or agent_host.decide)(packet, self.directory(packet['run_id']), self.options['host'])
                    return self._finish(packet['run_id'], decision, dry_run)
                except (ReaderError, OSError, ValueError) as error:
                    result = {**packet, 'status': 'failed', 'error': str(error), 'delivery': {'status': 'not_sent'}}
                    self.memory.save_run(packet['run_id'], 'failed', result)
                    self._archive(result)
                    raise ReaderError(f"Round {packet['run_id']} failed; local archive retained: {type(error).__name__}") from None
        except Timeout:
            raise ReaderError('Another video-agent round is active') from None

    def _deepen(self, packet, assessed):
        changed = 0
        for row in assessed:
            if not row['needs_deep_read'] or changed >= self.options['deep_read']['max_videos']:
                continue
            item = next(material for material in packet['previews'] if material['url'] == row['url'])
            duration = item.get('duration_seconds')
            if (not duration or duration > self.options['deep_read']['max_duration_seconds']
                    or self.platform.status().get('paused')):
                continue
            try:
                opened = self.reader.open(row['url'])
                session = opened['session_id']
                item.update(self._source_material(session, item, transcribe=True))
                changed += 1
            except (ReaderError, OSError) as error:
                packet['failures'].append({'url': row['url'], 'stage': 'deep_read', 'error': type(error).__name__})
                break
        return changed

    def _send(self, text, sources):
        recipient = self.options['delivery']['recipient_uid']
        if recipient is None or not self.platform.sender or not self.platform.csrf:
            raise ReaderError('Private delivery needs a recipient and the component login/CSRF token')
        if len(text) > 450:
            raise ReaderError('Private message exceeds the local short-message limit')
        if not self.memory.reserve_delivery(recipient, sources):
            return {'status': 'duplicate_or_uncertain_not_resent'}
        form = {'msg[sender_uid]': self.platform.sender, 'msg[receiver_id]': str(recipient),
                'msg[receiver_type]': 1, 'msg[msg_type]': 1, 'msg[msg_status]': 0,
                'msg[content]': json.dumps({'content': text}, ensure_ascii=False),
                'msg[timestamp]': int(time.time()), 'msg[new_face_version]': 0,
                'msg[dev_id]': str(uuid.uuid4()).upper(), 'csrf': self.platform.csrf, 'csrf_token': self.platform.csrf}
        try:
            response = self.platform.request('https://api.vc.bilibili.com/web_im/v1/web_im/send_msg', form=form)
            accepted = isinstance(response, dict) and response.get('code') == 0 and (response.get('data') or {}).get('msg_key')
            status = 'accepted_not_receipt_verified' if accepted else 'uncertain'
            self.memory.delivery_result(recipient, sources, status)
            return {'status': status, 'receipt_verified': False, 'message_key': str(response['data']['msg_key']) if accepted else None}
        except ReaderError as error:
            status = 'rejected' if isinstance(error, PlatformError) and error.code.startswith('platform_code:') else 'uncertain'
            self.memory.delivery_result(recipient, sources, status)
            return {'status': status, 'error': str(error), 'automatic_retry': False}

    def deliver(self, run_id):
        try:
            with self.lock:
                result = self.memory.load_run(run_id)
                delivery = self._deliver(run_id)
                if delivery['status'] != 'duplicate_or_uncertain_not_resent':
                    result['delivery'] = delivery
                    self.memory.save_run(run_id, result['status'], result)
                    self._archive(result)
                return delivery
        except Timeout:
            raise ReaderError('Another video-agent round is active') from None

    def _deliver(self, run_id):
        result = self.memory.load_run(run_id)
        selected = result.get('selected') or []
        if not selected:
            return {'status': 'nothing_to_send'}
        trial_day = result.get('trial_day')
        if trial_day and trial_day != self.daily_day():
            return {'status': 'stale_daily_not_sent'}
        if not (self.options['daily']['enabled'] if trial_day else self.options['delivery']['enabled']):
            return {'status': 'disabled_local_archive_only'}
        if trial_day and not self.daily_due():
            return {'status': 'before_daily_time'}
        lines, included = [], []
        for row in selected:
            prefix = '首页首条试用｜' if trial_day else ''
            block = f"{prefix}{row['title'][:50]}\n{row['url']}\n{row['reason'][:80]}"
            if len('\n\n'.join([*lines, block])) <= 430:
                lines.append(block)
                included.append(row)
        if not lines:
            return {'status': 'message_too_long_local_archive_only'}
        sources = [f'homepage_first:{trial_day}'] if trial_day else [row['url'] for row in included]
        return self._send('\n\n'.join(lines), sources)

    def test_message(self, confirm=False):
        if not confirm:
            raise ReaderError('Sending the first test message requires explicit confirmation')
        text = 'Video Reader 测试私信：已按你的授权发送首次一条测试消息。后续推荐将简短投递并本地留档；目前自动唤醒与日常私信仍关闭。'
        return self._send(text, ['first_test_message'])

    def tick(self, query='', *, now=None, evaluator=None):
        wake = self.options['wake']
        if not wake['enabled']:
            return {'status': 'disabled', 'next_run': None}
        now = now or datetime.now(timezone.utc)
        path = self.root / 'wake.json'
        with FileLock(str(self.root / 'wake.lock'), timeout=0):
            state = read_json(path) if path.is_file() else {}
            signature = digest({'wake': wake, 'scope': self.scope, 'query': query})
            if state.get('signature') != signature or not state.get('next_run'):
                state = {'signature': signature, 'next_run': agent_schedule.next_run(now, wake).isoformat()}
                write_json(path, state)
                return {'status': 'scheduled', **state}
            if now < datetime.fromisoformat(state['next_run']):
                return {'status': 'waiting', **state}
            if not agent_schedule.in_window(now, wake):
                state['next_run'] = agent_schedule.next_run(now, wake).isoformat()
                write_json(path, state)
                return {'status': 'outside_window', **state}
            if self.platform.status().get('paused'):
                return {'status': 'platform_paused', **state}
            try:
                result = self.run(query, dry_run=False, evaluator=evaluator)
                state['last_run'] = result['run_id']
                return {'status': result['status'], 'run_id': result['run_id']}
            finally:
                ended = now if evaluator is not None else datetime.now(timezone.utc)
                state['next_run'] = agent_schedule.next_run(ended, wake).isoformat()
                write_json(path, state)

    def status(self):
        daily_runs = []
        for path in sorted((self.root / 'daily' / self.scope).glob('*.json'), reverse=True)[:7]:
            record = read_json(path)
            result = self.memory.load_run(record['run_id'])
            first = (result.get('candidates') or [{}])[0]
            daily_runs.append({**record, 'status': result['status'], 'delivery': result.get('delivery'),
                               'video': {key: first.get(key) for key in ('title', 'url')},
                               'assessment': result.get('decisions', []),
                               'failures': result.get('failures', []), 'error': result.get('error')})
        task_status = self.root / 'task' / 'last.json'
        return {'account_scope': self.scope, 'memory_backend': 'sqlite_fts5_trigram',
                'directory': str(self.root), 'delivery_enabled': self.options['delivery']['enabled'],
                'recipient_configured': self.options['delivery']['recipient_uid'] is not None,
                'wake': self.options['wake'], 'network': self.platform.status(),
                'daily': self.options['daily'],
                'daily_runs': daily_runs,
                'task_runner': read_json(task_status) if task_status.is_file() else None,
                'recent_runs': self.memory.recent_runs(),
                'deliveries': self.memory.delivery_status(self.options['delivery']['recipient_uid'])}
