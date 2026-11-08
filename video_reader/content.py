"""Lightweight, revision-bound time directories over existing Reader material.

No embedding model, transcript rewriting, implicit ASR or whole-video indexing job.
Native previews remain approximate; exact evidence uses the ordinary Reader.
"""
from __future__ import annotations

import copy
import hashlib
from io import BytesIO
import math
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata

from .common import ReaderError, UNTRUSTED, digest, read_json, write_json
from .delivery import freeze_preview, original_page
from .review import document, material_id, overlay


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def terms(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    words = re.findall(r'[a-z0-9]+', value)
    for run in re.findall(r'[\u3400-\u9fff]+', value):
        words.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return set(words)


def validate_assets(frames):
    for frame in frames:
        if frame.get('asset_sha256') and (not Path(frame['path']).is_file() or
                hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest() != frame['asset_sha256']):
            raise ReaderError('Native content image changed or disappeared')


def evidence_frames(reader, session, requests, *, binding=None):
    """Return local evidence for a material binding without exposing its layout."""
    data = reader.load(session)
    binding = binding or {}
    cid = binding.get('cid')
    if cid is not None and str(data.get('platform_metadata', {}).get('cid')) != str(cid):
        raise ReaderError('Evidence part/CID changed; keep the original task snapshot')
    if 'account_scope' in binding and binding['account_scope'] != (data.get('authentication') or {}).get('account_marker'):
        raise ReaderError('Evidence belongs to another account scope')
    if len(requests) > 4:
        raise ReaderError('Requested evidence needs a narrower set')
    frames = []
    for request in requests:
        points = request.get('timestamps') or [(request['start'] + request['end']) / 2]
        if len(points) > 6:
            raise ReaderError('Evidence request exceeds six exact frames')
        material = reader.read(session, start=request['start'], end=request['end'], timestamps=points,
                               max_frames=len(points), verify=False, temporal=False, _delivery=False)
        frames.extend({**frame, 'asset_sha256': hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest()}
                      for frame in material['visual']['frames'])
    return frames


def _capture(reader, target, source, context, offline, refresh=False):
    from .catalog import account_scope
    if re.fullmatch(r'v_[a-f0-9]{24}', target or ''):
        data = reader.load(target)
        canonical = data['source']['canonical']
        scope = (data.get('authentication') or {}).get('account_marker')
        if scope != account_scope(reader.config, canonical):
            raise ReaderError('Content material belongs to a different account scope')
        selected_context = reader._reading_context(data, context, source)
        speech = reader._speech(data, 0, data['metadata']['duration_seconds'], source, selected_context)
        segments, review = overlay(reader.directory(target), speech, speech.get('segments', []))
        from .sources import file_identity
        binding = {'source': canonical, 'source_identity': digest(data['source']['identity']),
            'media_identity': file_identity(data['media_path']), 'account_scope': scope,
            'session_id': target, 'speech_source': source, 'context': selected_context,
            'speech_material': material_id(speech), 'review_snapshot': review['snapshot_id'],
            'review_revision': review['revision'], 'coverage': speech.get('coverage', {})}
        frames = [{**f,'asset_sha256':hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()}
                  for f in {f['id']: f for r in data['reads'] for f in r['frames']
                            if f.get('id') and Path(f['path']).is_file()}.values()]
        return {'binding': binding, 'segments': segments, 'frames': frames, 'title': data['title'],
            'duration': data['metadata']['duration_seconds'], 'precision': 'source_frame',
            'has_video': data['metadata'].get('has_video', False), 'speech': speech}
    if source not in ('auto', 'captions') or context:
        raise ReaderError('ASR/context-selected content needs an opened v_ session; native previews provide captions only')
    from .sources import resolve
    canonical = resolve(target)['canonical']
    for owned in reader.materials([canonical])[canonical]:
        if owned['media_available']:
            return _capture(reader, owned['session_id'], source, context, offline, refresh)
    scope = account_scope(reader.config, canonical)
    native_path = reader.cache/'content'/'native'/(digest([canonical, scope])+'.json')
    if native_path.is_file() and not refresh:
        captured = read_json(native_path)
        if captured['binding']['account_scope'] != scope:
            raise ReaderError('Native content belongs to another account')
        validate_assets(captured['frames'])
        return captured
    from .platform import PlatformError
    options = {'density': 'dense', 'max_frames': 48}
    try:
        result = reader.preview(target, offline=True, **options)
    except PlatformError as error:
        if offline or error.code != 'offline_cache_miss':
            raise
        result = reader.preview(target, **options)
    preview = original_page(reader, result)
    if preview.get('source_session_id'):
        return _capture(reader, preview['source_session_id'], source, context, offline, refresh)
    caption = preview.get('caption') or {}
    speech = {'source': 'captions', 'track': {'source': canonical,
        **{key: caption.get(key) for key in ('kind', 'language')}}, 'segments': caption.get('segments', [])}
    snapshot, segments = document(speech)
    scope = result['delivery']['binding']['account_scope']
    if scope != account_scope(reader.config, canonical):
        raise ReaderError('Native preview account scope does not match current material access')
    duration = preview.get('duration_seconds')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ReaderError('Content directory needs a known positive source duration')
    frames = []
    for frame in preview.get('frames', []):
        raw = Path(frame['path']).read_bytes()
        from PIL import Image
        with Image.open(BytesIO(raw)) as img:
            img.verify()
        identity = hashlib.sha256(raw).hexdigest()
        asset = reader.cache/'content'/'assets'/(identity + Path(frame['path']).suffix)
        asset.parent.mkdir(parents=True, exist_ok=True)
        if not asset.is_file():
            fd, temporary = tempfile.mkstemp(dir=asset.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                os.replace(temporary, asset)
            finally:
                Path(temporary).unlink(missing_ok=True)
        frames.append({**frame, 'path': str(asset), 'asset_sha256': identity})
    captured = {'binding': {'source': canonical, 'account_scope': scope, 'part': preview.get('part'),
        'cid': preview.get('cid'), 'material_level': 'native_preview', 'speech_source': 'captions',
        'native_assets': digest([(f['id'], f.get('time'), f['asset_sha256']) for f in frames]),
        'context': None, 'speech_material': snapshot, 'review_snapshot': snapshot, 'review_revision': 0,
        'coverage': {'complete': bool(segments), 'kind': 'native_caption_track',
                     'missing_ranges': [] if segments else [[0, duration]]}},
        'captured_at': time.time(), 'segments': segments, 'frames': frames, 'title': preview.get('title', ''),
        'duration': duration, 'precision': preview.get('frame_precision', 'approximate_native_snapshot'),
        'has_video': True, 'speech': speech}
    write_json(native_path, captured)
    return captured


def _frame(frame, precision):
    return {**copy.deepcopy(frame), 'timestamp_seconds': frame.get('timestamp_seconds', frame.get('time')),
            'precision': frame.get('precision', precision)}


def _directory(reader, captured, block_seconds):
    binding = {**captured['binding'], 'block_seconds': block_seconds}
    identity = 'ci_' + digest(binding)
    path = reader.cache/'content'/f'{identity}.json'
    reused = path.is_file()
    if reused:
        result = read_json(path)
        validate_assets(result.get('frame_assets',[]))
    else:
        blocks = []
        for index in range(math.ceil(captured['duration']/block_seconds)):
            lo, hi = index*block_seconds, min((index+1)*block_seconds, captured['duration'])
            selected = [s for s in captured['segments'] if s['end'] > lo and s['start'] < hi]
            blocks.append({'id': f'{identity}:{index}', 'start': lo, 'end': hi,
                'segments': selected, 'text': '\n'.join(s['text'] for s in selected),
                'text_available': bool(selected)})
        result = {'index_id': identity, 'binding': binding, 'title': captured['title'],
            'duration_seconds': captured['duration'], 'blocks': blocks,
            'frame_assets': captured['frames'],
            'source_content_policy': UNTRUSTED, 'index_is_reading_evidence': False}
        write_json(path, result)
    result = copy.deepcopy(result)
    result.pop('frame_assets',None)
    result['cache_reused'] = reused
    for block in result['blocks']:
        frames = [_frame(f, captured['precision']) for f in captured['frames']]
        block['frame_refs'] = [f for f in frames if isinstance(f['timestamp_seconds'], (int, float))
                               and block['start'] <= f['timestamp_seconds'] < block['end']]
        block['gaps'] = ([] if block['text_available'] else ['no_ready_text']) + (
            [] if block['frame_refs'] else ['no_cached_frame_in_block'])
        block['read_parameters'] = {'start': block['start'], 'end': block['end'],
            'timestamps': [(block['start']+block['end'])/2], 'source': captured['binding']['speech_source'],
            'context': captured['binding']['context']}
    return result


def execute(reader, target, action='index', query='', block_ids=None, source='auto', context=None,
            block_seconds=120, offset=0, limit=20, index_id=None, offline=False, refresh=False, delivery=True):
    if action == 'validate':
        if not re.fullmatch(r'ci_[a-f0-9]{24}', index_id or ''):
            raise ReaderError('Specify a returned content index_id')
        saved = read_json(reader.cache/'content'/f'{index_id}.json')
        binding = saved['binding']
        from .catalog import account_scope
        if binding['account_scope'] != account_scope(reader.config, binding['source']):
            raise ReaderError('Content account changed')
        if binding.get('session_id'):
            current = _capture(reader, binding['session_id'], binding['speech_source'], binding['context'], True)
        else:
            native = reader.cache/'content'/'native'/(digest([binding['source'],binding['account_scope']])+'.json')
            current = read_json(native)
        if {**current['binding'], 'block_seconds': binding['block_seconds']} != binding:
            raise ReaderError('Content source/speech/review changed; rebuild the directory')
        validate_assets(current['frames'])
        validate_assets(saved.get('frame_assets',[]))
        return {'index_id': index_id, 'binding': binding, 'valid': True}
    if action not in ('index', 'query', 'storyboard', 'material'):
        raise ReaderError('Content action must be index/query/storyboard/material/validate')
    if type(block_seconds) is not int or not 15 <= block_seconds <= 600:
        raise ReaderError('block_seconds must be 15..600')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ReaderError('Content offset/limit must be >=0 and 1..100')
    if not isinstance(query, str) or len(query) > 1000 or not isinstance(offline, bool):
        raise ReaderError('Content query must be at most 1000 characters; offline must be boolean')
    if block_ids is not None and (not isinstance(block_ids, list) or any(not isinstance(b, str) for b in block_ids)):
        raise ReaderError('block_ids must be a list of returned block IDs')
    if not isinstance(refresh, bool):
        raise ReaderError('refresh must be boolean')
    captured = _capture(reader, target, source, context, offline, refresh)
    result = _directory(reader, captured, block_seconds)
    if index_id is not None and index_id != result['index_id']:
        raise ReaderError('Content index changed (source/account/speech/review); rebuild the directory before selecting blocks')
    blocks = result['blocks']
    if block_ids is not None:
        wanted = set(block_ids)
        if wanted - {b['id'] for b in blocks}:
            raise ReaderError('Block IDs do not belong to the current content index')
        blocks = [b for b in blocks if b['id'] in wanted]
    if action == 'query':
        if not normalized(query):
            raise ReaderError('Content query must contain letters or numbers')
        query_terms, needle = terms(query), normalized(query)
        scored = []
        for block in blocks:
            haystack = normalized(block['text'])
            matched = sorted(query_terms & terms(block['text']))
            score = (100 if needle in haystack else 0) + len(matched)
            if score:
                scored.append({**block, 'score': score, 'matched_terms': matched})
        blocks = sorted(scored, key=lambda b: (-b['score'], b['start']))
        result.update(query=query, retrieval='lexical_candidates_host_selects', text_match_found=bool(blocks),
            continuation_hint='A text miss does not rule out visual or misrecognized content; inspect the directory/storyboard and request local Reader evidence.')
    page_limit = min(limit, reader.config['page_frames'], 12) if action == 'storyboard' else limit
    selected = blocks[offset:offset+page_limit]
    result.update(blocks=selected, total_blocks=len(blocks), offset=offset,
        next_offset=offset+len(selected) if offset+len(selected) < len(blocks) else None,
        observation='directory_not_confirmed_observed', action=action)
    if not delivery:
        return result
    if action in ('index', 'query'):
        # A directory is navigation. Full original sentences remain in material.
        for block in result['blocks']:
            block.pop('segments')
            text = block.pop('text')
            block.update(text_preview=text[:240], text_characters=len(text), text_preview_complete=len(text) <= 240)
        return freeze_preview(reader, result, captured['binding']['account_scope'])
    if not selected:
        return result
    if action == 'material' and len(selected) != 1:
        raise ReaderError('Select exactly one block for material; use storyboard for multiple blocks')
    frames = []
    if captured['binding'].get('session_id'):
        points = [(b['start']+b['end'])/2 for b in selected]
        if captured['has_video']:
            material = reader.read(captured['binding']['session_id'], start=selected[0]['start'], end=selected[-1]['end'],
                timestamps=points, max_frames=len(points), source=source, context=context, verify=False, temporal=False,
                _delivery=False)
            frames = material['visual']['frames']
    else:
        available = [_frame(f, captured['precision']) for f in captured['frames']]
        for block in selected:
            candidates = [f for f in available if block['start'] <= f['timestamp_seconds'] < block['end']]
            if candidates:
                frames.append(min(candidates, key=lambda f: abs(f['timestamp_seconds']-(block['start']+block['end'])/2)))
    result['visual'] = {'frames': list({f['id']: f for f in frames}.values()),
        'precision': captured['precision'], 'complete_continuous_coverage': False}
    for block in selected:
        block['frame_refs'] = [f for f in result['visual']['frames'] if
            block['start'] <= f['timestamp_seconds'] < block['end']]
        if block['frame_refs']:
            block['gaps'] = [gap for gap in block['gaps'] if gap != 'no_cached_frame_in_block']
    result['material_level'] = 'content_blocks'
    if action == 'storyboard':
        for block in result['blocks']:
            block.pop('segments')
            text = block.pop('text')
            block.update(text_preview=text[:240], text_characters=len(text), text_preview_complete=len(text) <= 240)
    return freeze_preview(reader, result, captured['binding']['account_scope'])
