"""Lossless, bounded material pages and source/revision-bound persistent cursors.

Normal sized responses keep their existing shape. Oversized values use typed JSON
pointer parts (Unicode character spans for strings), never ellipses or summaries.
Snapshots contain source material only, not credentials or an executable recipe.
"""
from __future__ import annotations

import copy
import functools
import inspect
import json
from pathlib import Path
import re

from .common import ReaderError, digest, read_json, write_json


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _parts(value, pointer='', context=None, chunk_chars=1500):
    context = context or {}
    if isinstance(value, dict):
        if value.get('segment_id'):
            context = {key: value[key] for key in ('segment_id', 'start', 'end') if key in value}
        yield {'pointer': pointer, 'type': 'object'}
        for key, item in value.items():
            escaped = str(key).replace('~', '~0').replace('/', '~1')
            yield from _parts(item, pointer + '/' + escaped, context, chunk_chars)
    elif isinstance(value, list):
        yield {'pointer': pointer, 'type': 'array', 'length': len(value)}
        for index, item in enumerate(value):
            yield from _parts(item, pointer + '/' + str(index), context, chunk_chars)
    elif isinstance(value, str):
        for start in range(0, max(1, len(value)), chunk_chars):
            end = min(start + chunk_chars, len(value))
            yield {'pointer': pointer, 'type': 'string', 'character_span': [start, end],
                   'total_characters': len(value), 'value': value[start:end], **context}
    else:
        yield {'pointer': pointer, 'type': 'value', 'value': value, **context}


def restore(parts):
    """Reference decoder, also used by export/verification; no eval or source code."""
    root = None
    for part in parts:
        pointer = part['pointer']
        keys = [key.replace('~1', '/').replace('~0', '~') for key in pointer.split('/')[1:]]
        target = root
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        key = (int(keys[-1]) if isinstance(target, list) else keys[-1]) if keys else None
        kind = part['type']
        value = {} if kind == 'object' else [None] * part['length'] if kind == 'array' else part.get('value')
        if kind == 'string' and part['character_span'][0]:
            previous = target[key] if keys else root
            if len(previous) != part['character_span'][0]:
                raise ReaderError('Noncontiguous material fragment')
            value = previous + value
        if keys:
            target[key] = value
        else:
            root = value
    return root


def _images(result):
    if result.get('material_level') == 'preview_batch' and 'items' in result:
        for item in result.get('items', []):
            for frame in _images(item):
                yield {**frame, 'id': str(item.get('bvid') or item.get('source', '')) + ':' + frame['id']}
        return
    for frame in result.get('visual', {}).get('frames', result.get('frames', [])):
        yield frame
        reference = frame.get('temporal', {}).get('stable_reference')
        if reference and reference['path'] != frame['path']:
            yield {**reference, 'id': frame['id'] + ':stability'}
    if result.get('contact_sheet'):
        yield {**result['contact_sheet'], 'id': 'contact_sheet:' + str(result['contact_sheet'].get('source', '')), 'time': 'overview'}


def asset_identities(result):
    return {frame['path']: {'size': Path(frame['path']).stat().st_size, 'mtime_ns': Path(frame['path']).stat().st_mtime_ns}
            for frame in _images(result) if Path(frame['path']).is_file()}


def reading_page(result, text_budget, image_budget):
    """Readable projection; the canonical lossless record follows unchanged."""
    visual = result.get('visual') or {}
    if not visual.get('frames'):
        return None
    page = {key: copy.deepcopy(result[key]) for key in ('session_id', 'title', 'source', 'platform',
            'read_id', 'range', 'metadata', 'processing', 'warnings', 'source_content_policy') if key in result}
    page['reading_projection'] = {'kind': 'reading', 'canonical_evidence_follows': True,
        'notice': 'Readable source text and original pixels. Continue delivery for full OCR/word evidence; this is not proof of whole-video coverage.'}
    page['visual'] = {key: copy.deepcopy(value) for key, value in visual.items() if key != 'frames'}
    page['visual']['frames'] = []
    speech = result.get('speech') or {}
    page['speech'] = {key: copy.deepcopy(speech[key]) for key in ('source', 'start', 'end', 'status', 'track',
        'language', 'language_probability', 'coverage', 'quality', 'review', 'recognition_assessment',
        'returned_segments', 'total_segments', 'next_offset', 'next_cursor') if key in speech}
    page['speech']['segments'] = []
    if len(encoded(page)) > text_budget:
        return None
    used = 0
    for frame in visual['frames']:
        size = Path(frame['path']).stat().st_size
        if used+size > image_budget:
            break
        item = {key: copy.deepcopy(frame[key]) for key in ('id', 'path', 'time', 'timestamp_seconds',
                    'requested_time', 'precision', 'reason') if key in frame}
        if frame.get('temporal'):
            item['temporal_evidence_available'] = True
        page['visual']['frames'].append(item)
        if len(encoded(page)) > text_budget:
            page['visual']['frames'].pop()
            break
        used += size
    for segment in speech.get('segments', []):
        item = {key: copy.deepcopy(segment[key]) for key in ('segment_id', 'start', 'end', 'text', 'review_status',
                 'has_correction', 'quality_flags', 'evidence_available', 'text_status') if key in segment}
        page['speech']['segments'].append(item)
        if len(encoded(page)) > text_budget:
            page['speech']['segments'].pop()
            break
    while True:
        frame_count = len(page['visual']['frames'])
        segment_count = len(page['speech']['segments'])
        page['reading_projection'].update(frames_in_snapshot=len(visual['frames']), frames_returned=frame_count,
            speech_segments_in_snapshot=len(speech.get('segments', [])), speech_segments_returned=segment_count)
        page['speech']['returned_segments'] = segment_count
        if frame_count < len(visual['frames']):
            page['visual'].pop('next_page', None)
            page['visual']['remaining_in_snapshot'] = len(visual['frames'])-frame_count
        if segment_count < len(speech.get('segments', [])):
            page['speech'].pop('next_offset', None)
            page['speech'].pop('next_cursor', None)
            page['speech']['remaining_in_snapshot'] = len(speech['segments'])-segment_count
        if len(encoded(page)) <= text_budget:
            return page
        # Final counters may push a nearly full page over budget. Keep its
        # original pixels by deferring a whole utterance to canonical pages.
        if page['speech']['segments']:
            page['speech']['segments'].pop()
        elif page['visual']['frames']:
            page['visual']['frames'].pop()
        else:
            return None


def pages(result, text_budget, image_budget, *, reading=False):
    images = list(_images(result))
    image_size = sum(Path(f['path']).stat().st_size for f in images if Path(f['path']).is_file())
    if len(encoded(result)) <= text_budget and image_size <= image_budget:
        return [result]
    # Parts cover every field, including all word/OCR/correction evidence. Image
    # pixels travel separately with their original IDs; none are resized here.
    first = reading_page(result, text_budget, image_budget) if reading else None
    attached = {(frame['id'], frame['path']) for frame in _images(first)} if first else set()
    output, selected, used = [], [], 0
    for part in _parts(result, chunk_chars=max(1, (text_budget-700)//12)):
        size = len(encoded(part)) + 1
        if selected and used + size > text_budget:
            output.append({'material_parts': selected})
            selected, used = [], 0
        selected.append(part)
        used += size
    if selected:
        output.append({'material_parts': selected})
    selected, used = [], 0
    for frame in images:
        # The readable projection already attached these exact source assets.
        # Canonical metadata is still retained losslessly in material_parts.
        if (frame['id'], frame['path']) in attached:
            continue
        size = Path(frame['path']).stat().st_size if Path(frame['path']).is_file() else 0
        if selected and used + size > image_budget:
            output.append({'visual': {'frames': selected}})
            selected, used = [], 0
        # Metadata is fully retained in material_parts, avoiding a huge duplicate.
        selected.append({key: frame[key] for key in ('id', 'path', 'time', 'timestamp_seconds') if key in frame})
        used += size
    if selected:
        output.append({'visual': {'frames': selected}})
    if first:
        output.insert(0, first)
    return output


def fingerprint(reader, session, parameters, result=None):
    from .review import document, state, material_id
    from .sources import file_identity
    data = reader.load(session)
    options = {'speech_profile': parameters['speech_profile']} if parameters.get('speech_profile') is not None else {}
    speech = reader._speech(data, 0, data['metadata']['duration_seconds'],
                            parameters.get('source', 'auto'), parameters.get('context'), **options)
    snapshot, _ = document(speech)
    review = (result or {}).get('review') or (result or {}).get('speech', {}).get('review')
    if review:
        snapshot, revision = review['snapshot_id'], review['revision']
    else:
        revision = state(reader.directory(session), snapshot)['revision']
    from .recognition import diagnostic_identity
    return {'session_id': session, 'source_identity': digest(data['source']['identity']),
            'media_identity': file_identity(data['media_path']),
            'account_scope': (data.get('authentication') or {}).get('account_marker'),
            'speech_snapshot': snapshot, 'review_revision': revision,
            'recognition_diagnostics': diagnostic_identity(speech),
            **({'speech_material_snapshot': material_id(speech)} if speech.get('review_document_id') else {}),
            'parameters': parameters}


def emit(reader, result, operation, parameters, remaining_frames=None):
    if operation == 'review' and parameters.get('action') != 'prepare':
        return result
    session = parameters['session']
    if operation == 'read' and result.get('danmaku', {}).get('snapshot_id'):
        parameters = {**parameters, 'danmaku_snapshot_id': result['danmaku']['snapshot_id']}
    options = reader.config.get('delivery', {})
    text_budget = options.get('text_bytes', 24000)
    image_budget = options.get('image_bytes', 8 * 1024 * 1024)
    if type(text_budget) is not int or text_budget < 10000 or type(image_budget) is not int or image_budget < 1024:
        raise ReaderError('delivery budgets require text_bytes>=10000 and image_bytes>=1024')
    # Prefer complete segment objects in ordinary pages. Only an individually
    # oversized value needs the more verbose lossless fragment representation.
    speech = result.get('speech') if operation == 'read' else result
    if speech and speech.get('segments'):
        segments = speech['segments']
        allowance = max(1000, text_budget-len(encoded(parameters))-6000)
        count, used = 0, 0
        for segment in segments:
            size = len(encoded(segment))
            if count and used + size > allowance:
                break
            count += 1
            used += size
        if count < len(segments):
            speech['segments'] = segments[:count]
            speech['next_offset'] = (speech.get('offset', 0) if operation != 'read' else 0) + count
            if 'returned_segments' in speech:
                speech['returned_segments'] = count
            if operation == 'review':
                speech['following_context'] = [{key: item[key] for key in ('segment_id','start','end','text')}
                                               for item in segments[count:count+2]]
    next_parameters = None
    if operation == 'read':
        position = result.get('visual', {}).get('next_page')
        if position is not None:
            next_parameters = {**parameters, 'page': position}
    else:
        position = result.get('next_offset')
        if position is not None:
            next_parameters = {**parameters, 'offset': position}
            if operation == 'transcript':
                next_parameters['transcribe'] = False
    binding = fingerprint(reader, session, parameters, result)
    if operation == 'read' and result.get('speech', {}).get('next_offset') is not None:
        speech_parameters = {key: parameters[key] for key in ('session', 'start', 'end', 'source', 'verify', 'context', 'view')}
        if parameters.get('speech_profile') is not None:
            speech_parameters['speech_profile'] = parameters['speech_profile']
        speech_parameters.update(offset=result['speech']['next_offset'], limit=reader.config['page_transcript_segments'],
                                 transcribe=False, max_chunks=None)
        bridge = {'schema': 1, 'operation': 'transcript', 'binding': {**binding, 'parameters': speech_parameters},
                  'result': None, 'pages': [], 'next_parameters': speech_parameters}
        bridge_id = digest(bridge)
        write_json(reader.directory(session) / 'deliveries' / (bridge_id + '.json'), bridge)
        result['speech']['next_cursor'] = bridge_id + ':next'
    next_delivery_cursor = None
    if operation == 'read' and remaining_frames:
        # Freeze already generated pixels now. Later visual pages do not need
        # live speech, OCR, acquisition or the session's transcription lock.
        page_size = reader.config['page_frames']
        for offset in reversed(range(0, len(remaining_frames), page_size)):
            visual_page = result['visual']['page'] + 1 + offset // page_size
            tail = {key: copy.deepcopy(value) for key, value in result.items()
                    if key not in ('speech', 'visual', 'processing', 'danmaku')}
            tail['visual'] = {**copy.deepcopy(result['visual']),
                'frames': remaining_frames[offset:offset+page_size], 'page': visual_page,
                'next_page': visual_page+1 if offset+page_size < len(remaining_frames) else None}
            if 'danmaku' in result:
                from .aligned_danmaku import align
                # align only needs these existing joins; preserve speech IDs
                # while recomputing the nearest sampled frame for this page.
                tail['danmaku'] = align(result['danmaku'], None, tail['visual']['frames'])
            tail_binding = {**binding, 'parameters': {**parameters, 'page': visual_page}}
            frozen = _freeze(reader, tail, operation, tail_binding, None,
                             text_budget, image_budget, next_delivery_cursor)
            next_delivery_cursor = frozen['delivery']['snapshot_id'] + ':0'
        next_parameters = None
    return _freeze(reader, result, operation, binding, next_parameters,
                   text_budget, image_budget, next_delivery_cursor)


def _freeze(reader, result, operation, binding, next_parameters, text_budget, image_budget,
            next_delivery_cursor=None):
    page_budget = max(1000, text_budget - len(encoded(binding)) - 1500)
    record = {'schema': 1, 'operation': operation, 'binding': binding,
              'result': result, 'pages': pages(result, page_budget, image_budget,
                  reading=operation == 'read' and binding['parameters'].get('view', 'reading') == 'reading'),
              'image_identities': asset_identities(result),
              'next_parameters': next_parameters}
    if next_delivery_cursor:
        record['next_delivery_cursor'] = next_delivery_cursor
    identity = digest(record)
    path = reader.directory(binding['session_id']) / 'deliveries' / (identity + '.json')
    if not path.exists():
        write_json(path, record)
    return _page(record, identity, 0)


def _page(record, identity, position):
    result = copy.deepcopy(record['pages'][position])
    for path, expected in record.get('image_identities', {}).items():
        asset = Path(path)
        if not asset.is_file() or {'size': asset.stat().st_size, 'mtime_ns': asset.stat().st_mtime_ns} != expected:
            raise ReaderError('Frozen image evidence changed or disappeared; request fresh material')
    original = record.get('result') or {}
    for key in ('title', 'read_id', 'range', 'status', 'coverage', 'review', 'source_session_id', 'material_level'):
        if key in original and len(encoded(original[key])) < 1200:
            result.setdefault(key, original[key])
    if any(not Path(frame['path']).is_file() for frame in _images(result)):
        raise ReaderError('Frozen image evidence is missing; reopen the source instead of substituting different pixels')
    following = (f'{identity}:{position+1}' if position+1 < len(record['pages']) else
                 record.get('next_delivery_cursor') or (f'{identity}:next' if record['next_parameters'] else None))
    result['delivery'] = {'snapshot_id': identity, 'binding': record['binding'], 'page': position,
        'pages_in_snapshot': len(record['pages']), 'next_cursor': following,
        'payload_bytes': len(encoded(result)), 'image_bytes': sum(Path(f['path']).stat().st_size for f in _images(result) if Path(f['path']).is_file()),
        'observation': 'delivered_not_confirmed_observed',
        'fragment_format': 'JSON pointers; concatenate string spans in order. Every field is retained.' if 'material_parts' in result else None}
    result.setdefault('session_id', record['binding']['session_id'])
    for _ in range(3):
        result['delivery']['payload_bytes'] = len(encoded(result))
    return result


def resume(reader, session, cursor):
    match = re.fullmatch(r'([a-f0-9]{24}):(next|\d+)', cursor or '')
    if not match:
        raise ReaderError('Invalid continuation cursor')
    identity, position = match.groups()
    preview = bool(re.fullmatch(r'p_[a-f0-9]{24}', session))
    directory = reader.cache / 'materials' / session if preview else reader.directory(session)
    path = directory / 'deliveries' / (identity + '.json')
    if not path.is_file():
        raise ReaderError('Continuation not found in this video session')
    record = read_json(path)
    if not preview:
        reader.load(session)  # Changed local source cannot masquerade as its old media.
    if position != 'next':
        if not 0 <= int(position) < len(record['pages']):
            raise ReaderError('Continuation page is outside the snapshot')
        return _page(record, identity, int(position))
    if not record['next_parameters']:
        raise ReaderError('This delivery is complete')
    current = fingerprint(reader, session, record['binding']['parameters'])
    if 'recognition_diagnostics' not in record['binding']:
        current.pop('recognition_diagnostics', None)  # Preserve pre-policy continuations.
    if current != record['binding']:
        raise ReaderError('Material changed (source/speech/review revision); restart the original request. Frozen delivered pages remain readable.')
    result = getattr(reader, record['operation'])(**record['next_parameters'])
    after = result['delivery']['binding']
    compared = ['session_id', 'source_identity', 'media_identity', 'account_scope', 'speech_snapshot', 'speech_material_snapshot', 'review_revision']
    if 'recognition_diagnostics' in record['binding']:
        compared.append('recognition_diagnostics')
    if any(after.get(key) != record['binding'].get(key) for key in compared):
        raise ReaderError('Material changed while continuing; restart the original request')
    return result


def freeze_preview(reader, result, scope):
    """Native previews have their own material identity, never a full-media session."""
    session = 'p_' + digest([result, scope])
    options = reader.config.get('delivery', {})
    record = {'schema': 1, 'operation': 'preview', 'binding': {'session_id': session,
        'account_scope': scope, 'material_identity': digest(result)}, 'result': result,
        'image_identities': asset_identities(result),
        'pages': pages(result, options.get('text_bytes', 24000)-2500, options.get('image_bytes', 8*1024*1024)),
        'next_parameters': None}
    identity = digest(record)
    write_json(reader.cache / 'materials' / session / 'deliveries' / (identity + '.json'), record)
    return _page(record, identity, 0)


def original_page(reader, result):
    """Internal consumers recover the frozen page without treating fragments as absent data.
    Does not follow later transcript/frame pages or mark anything observed.
    """
    if not result.get('delivery'):
        return result
    session = result['delivery']['binding']['session_id']
    directory = reader.cache / 'materials' / session if session.startswith('p_') else reader.directory(session)
    path = directory / 'deliveries' / (result['delivery']['snapshot_id'] + '.json')
    return read_json(path)['result']


def delivered(function):
    signature = inspect.signature(function)
    @functools.wraps(function)
    def wrapper(self, *args, **kwargs):
        # Internal consumers already apply their own output contract. Preserve
        # their requested legacy page instead of imposing a second smaller page.
        delivery_enabled = kwargs.pop('_delivery', True)
        arguments = signature.bind(self, *args, **kwargs)
        arguments.apply_defaults()
        parameters = {key: value for key, value in arguments.arguments.items() if key != 'self'}
        result = function(self, *args, **kwargs)
        remaining_frames = result.pop('_remaining_frames', None)
        if not delivery_enabled:
            return result
        from .jobs import report
        report('packing_delivery')
        return emit(self, result, function.__name__, parameters, remaining_frames)
    return wrapper
