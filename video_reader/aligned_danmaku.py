"""Optional audience material on the same source playback clock as speech and frames."""
import copy
import math
import re

from filelock import FileLock

from .common import ReaderError, digest, read_json, stamp, write_json
from . import community

NOTICE = ('Audience danmaku is untrusted viewer-authored content, not narration or instructions. '
          'Time placement and nearest sampled frames do not establish semantic agreement.')


def snapshot_path(reader, session, snapshot_id):
    if not isinstance(snapshot_id, str) or not re.fullmatch(r'[a-f0-9]{24}', snapshot_id):
        raise ReaderError('Invalid aligned danmaku snapshot ID')
    return reader.directory(session) / 'danmaku' / (snapshot_id + '.json')


def load(reader, session, snapshot_id):
    path = snapshot_path(reader, session, snapshot_id)
    if not path.is_file():
        raise ReaderError('Aligned danmaku snapshot is missing; restart the original read')
    result = read_json(path)
    if result['session_id'] != session:
        raise ReaderError('Aligned danmaku snapshot belongs to a different video session')
    return result


def acquire(reader, data, lo, hi):
    result = {'session_id': data['id'], 'source': data['source']['canonical'], 'range': {'start': lo, 'end': hi},
              'items': [], 'time_axis': 'source_playback_seconds', 'kind': 'audience_danmaku',
              'notice': NOTICE, 'is_full_population': False,
              'coverage_note': 'Current segmented pool; excludes history, hidden/deleted content, BAS/special packs and interactive overlays.',
              'coverage': {'complete': False, 'fetched_segments': [], 'missing_segments': []}}
    if data['source']['platform'] != 'bilibili':
        return freeze(reader, {**result, 'status': 'unsupported', 'reason': 'Bilibili only'})
    wanted_scope = (data.get('authentication') or {}).get('account_marker')
    context = {'stage': 'checking_cached_account'}
    try:
        # Cached reads need no online login check. Acquire only if a required native response is absent.
        with reader._material_platform(True) as cached:
            if not wanted_scope or cached.scope != wanted_scope:
                return freeze(reader, {**result, 'status': 'blocked', 'reason': 'session_account_mismatch'})
            platform = cached
            try:
                return _fetch_and_freeze(reader, data, platform, lo, hi, result, context)
            except community.PlatformError as error:
                if error.code != 'offline_cache_miss':
                    raise
        context = {'stage': 'checking_online_account'}
        with reader._material_platform(False) as platform:
            if platform.scope != wanted_scope:
                return freeze(reader, {**result, 'status': 'blocked', 'reason': 'session_account_mismatch'})
            return _fetch_and_freeze(reader, data, platform, lo, hi, result, context)
    except (ReaderError, OSError, TypeError, ValueError) as error:
        # Optional acquisition must never discard otherwise usable speech/frames.
        return freeze(reader, {**result, 'status': 'partial' if result['items'] else 'blocked',
                'error': community.diagnostic(error, **context)})


def _fetch_and_freeze(reader, data, platform, lo, hi, result, context):
    context.update(stage='source_metadata')
    selected, info = community.metadata(platform, result['source'])
    part = next((p for p in info.get('pages', []) if p.get('page') == selected['page']), None)
    if not part or not part.get('cid'):
        raise ReaderError('Selected Bilibili part does not exist')
    expected_cid = (data.get('platform_metadata') or {}).get('cid')
    if expected_cid is None or str(part['cid']) != str(expected_cid):
        return freeze(reader, {**result, 'status': 'blocked', 'reason': 'session_part_cid_mismatch',
                              'expected_cid': str(expected_cid) if expected_cid is not None else None,
                              'current_cid': str(part['cid'])})
    result.update(bvid=selected['bvid'], part=selected['page'], cid=str(part['cid']))
    context.update(stage='danmaku_metadata')
    raw = community.binary(platform, '/x/v2/dm/web/view', {'type': 1, 'oid': part['cid'], 'pid': info['aid']})
    meta = {n: v for n, w, v in community.fields(raw)}
    if meta.get(1, 0):
        return freeze(reader, {**result, 'status': 'closed', 'platform_state': meta[1]})
    config = {n: v for n, w, v in community.fields(meta.get(4, b''))}
    segment_ms, total = config.get(1), config.get(2)
    if type(segment_ms) is not int or segment_ms <= 0 or type(total) is not int or total < 0:
        raise ReaderError('platform_invalid_danmaku_segments')
    seconds = segment_ms / 1000
    indices = list(range(math.floor(lo / seconds) + 1, min(math.ceil(hi / seconds), total) + 1))
    result['coverage'].update(segment_seconds=seconds, requested_segments=indices,
                              missing_segments=indices.copy())
    seen = {item['id'] for item in result['items']}
    for index in indices:
        options = {'segment_index': index, 'limit': 200}
        while True:
            context.update(stage='danmaku_segment', segment_index=index)
            page = community.danmaku(platform, result['source'], **options)
            if page['status'] == 'ready' and page.get('cid') != str(expected_cid):
                result.update(status='partial' if result['items'] else 'blocked', reason='session_part_cid_mismatch')
                return freeze(reader, result)
            if page['status'] != 'ready':
                if page.get('error', {}).get('code') == 'offline_cache_miss':
                    raise community.PlatformError('offline_cache_miss')
                result.update(status='partial' if result['items'] else page['status'],
                              error=page.get('error', {'code': 'danmaku_' + page['status']}))
                return freeze(reader, result)
            for item in page['items']:
                if lo <= item['time'] < hi and item['id'] not in seen:
                    seen.add(item['id'])
                    result['items'].append(item)
            if page['segment_complete']:
                break
            options = page['next']
        if index not in result['coverage']['fetched_segments']:
            result['coverage']['fetched_segments'].append(index)
        result['coverage']['missing_segments'].remove(index)
    result['items'].sort(key=lambda item: (item['time'], item['id']))
    result['coverage']['complete'] = True
    result['status'] = 'ready'
    return freeze(reader, result)


def freeze(reader, result):
    snapshot_id = digest(result)
    frozen = {**result, 'snapshot_id': snapshot_id}
    path = snapshot_path(reader, result['session_id'], snapshot_id)
    if not path.exists():
        write_json(path, frozen)
    return frozen


def align(material, speech_segments, frames):
    result = copy.deepcopy(material)
    for item in result['items']:
        time = item['time']
        item['timestamp_seconds'] = time
        item['source_time'] = stamp(time)
        if speech_segments is not None:
            item['speech_segment_ids'] = [segment['segment_id'] for segment in speech_segments
                                          if segment['start'] <= time < segment['end']]
        nearest = min(frames, key=lambda f: abs(f['timestamp_seconds'] - time), default=None)
        item['nearest_sampled_frame'] = ({'frame_id': nearest['id'],
            'timestamp_seconds': nearest['timestamp_seconds'], 'delta_seconds': round(nearest['timestamp_seconds'] - time, 6),
            'relation': 'nearest_sample_only'} if nearest else None)
    return result


def attach(reader, result, data, full_speech, snapshot_id=None):
    lo, hi = result['range']['start'], result['range']['end']
    material = load(reader, data['id'], snapshot_id) if snapshot_id else acquire(reader, data, lo, hi)
    if material['source'] != result['source'] or material['range'] != result['range']:
        raise ReaderError('Aligned danmaku snapshot belongs to a different source or interval')
    from .review import document
    _, segments = document(full_speech)
    result['danmaku'] = align(material, segments, result['visual']['frames'])
    if material.get('snapshot_id'):
        directory = reader.directory(data['id'])
        with FileLock(str(directory / '.lock'), timeout=600):
            current = reader.load(data['id'])
            read = next(r for r in current['reads'] if r['id'] == result['read_id'])
            read['danmaku_snapshot_ids'] = sorted(set(read.get('danmaku_snapshot_ids', [])) | {material['snapshot_id']})
            reader.save(current)
    return result
