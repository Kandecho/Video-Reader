"""Resolve an existing frame ID in its own session, then inspect original pixels."""
from pathlib import Path
import hashlib
import math
from filelock import FileLock
from PIL import Image

from .common import ReaderError, digest, stamp, write_json
from .vendor import frames


def _validate_view(width, region):
    if type(width) is not int or not 64 <= width <= 3840:
        raise ReaderError('width must be 64..3840')
    if region is not None and (not isinstance(region, list) or len(region) != 4 or
        any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in region) or
        not region[0] < region[2] or not region[1] < region[3]):
        raise ReaderError('region must be normalized [left,top,right,bottom] within 0..1')


def _extract(data, output, time, width, region):
    native_width = data['metadata'].get('width') or width
    try:
        selected, _ = frames.extract_at_timestamps(data['media_path'], output, [time],
            resolution=max(width, native_width) if region else width, max_frames=1)
    except SystemExit as error:
        raise ReaderError(str(error)) from None
    if not selected:
        raise ReaderError('No source frame could be extracted at the requested time')
    frame = selected[0]
    if region:
        with Image.open(frame['path']) as image:
            x1, y1, x2, y2 = region
            cropped = image.crop((int(x1*image.width), int(y1*image.height),
                max(int(x1*image.width)+1,int(x2*image.width)), max(int(y1*image.height)+1,int(y2*image.height))))
            path = output / 'region.jpg'
            cropped.save(path, quality=95)
            frame['path'] = str(path)
    with Image.open(frame['path']) as image:
        frame.update(width=image.width, height=image.height)
    frame.update(time=stamp(frame['timestamp_seconds']), region=region, precision='source_frame',
        source_time=time, asset_sha256=hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest())
    return frame


def source_frames(reader, session, requests):
    """Extract bounded source pixels without fetching or decoding any speech."""
    if not isinstance(requests, list) or not 1 <= len(requests) <= 6:
        raise ReaderError('Source frame requests must contain 1..6 entries')
    data = reader.load(session)
    if data.get('native_only') or not data['metadata'].get('has_video', False):
        raise ReaderError('Source frames need an opened local video stream')
    from .catalog import account_scope
    scope = (data.get('authentication') or {}).get('account_marker')
    if scope != account_scope(reader.config, data['source']['canonical']):
        raise ReaderError('Source frames belong to another account scope')
    duration = data['metadata']['duration_seconds']
    checked = []
    for request in requests:
        if (not isinstance(request, dict) or 'timestamp_seconds' not in request or
                set(request)-{'timestamp_seconds', 'width', 'region'}):
            raise ReaderError('Source frames require timestamp_seconds and optional width/region')
        point, width, region = request['timestamp_seconds'], request.get('width', 1920), request.get('region')
        if type(point) not in (float, int) or not math.isfinite(point) or not 0 <= point < duration:
            raise ReaderError('Source frame timestamp_seconds must be finite and within the video duration')
        _validate_view(width, region)
        checked.append((float(point), width, region))
    directory = reader.directory(session)
    detail_root = directory / 'frame-details'
    detail_root.mkdir(parents=True, exist_ok=True)
    selected = []
    for point, width, region in checked:
        identity = digest([point, width, region, 'source-time-detail-1'])
        with FileLock(str(detail_root / (identity + '.lock')), timeout=30):
            current = reader.load(session)
            cached = next((r for r in current['reads'] if r['id'] == identity), None)
            if cached and all(Path(f['path']).is_file() for f in cached['frames']):
                for frame in cached['frames']:
                    if hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest() != frame['asset_sha256']:
                        raise ReaderError('Source frame pixels changed')
                selected.extend(cached['frames'])
                continue
            frame = _extract(current, directory / 'frames' / identity, point, width, region)
            frame['id'] = identity + ':0'
            write_json(detail_root / (identity + '.json'), {'id': identity, 'start': point, 'end': point,
                'frames': [frame], 'detail': True, 'media_identity': current.get('media_identity')})
            selected.append(frame)
    return {'session_id': session, 'source': data['source']['canonical'], 'account_scope': scope, 'frames': selected}


def inspect_frame(reader, session, frame_id, width=1920, region=None):
    _validate_view(width, region)
    directory = reader.directory(session)
    identity = digest([frame_id, width, region, 'source-detail-1'])
    detail_root = directory / 'frame-details'
    detail_root.mkdir(parents=True, exist_ok=True)
    # Source media is immutable. Distinct detail requests need no OCR/ASR lock.
    with FileLock(str(detail_root / (identity + '.lock')), timeout=30):
        data = reader.load(session)
        original = next((f for read in data['reads'] for f in read['frames'] if f['id'] == frame_id), None)
        if not original:
            raise ReaderError('Frame ID does not belong to this video session; use returned cell/frame IDs')
        cached = next((r for r in data['reads'] if r['id'] == identity), None)
        if cached and all(Path(f['path']).is_file() for f in cached['frames']):
            return {'session_id': session, 'visual': {'frames': cached['frames']}}
        time = original['timestamp_seconds']
        output = directory / 'frames' / identity
        frame = _extract(data, output, time, width, region)
        frame.update(id=identity + ':0', parent_frame_id=frame_id)
        write_json(detail_root / (identity + '.json'),
                   {'id': identity, 'start': time, 'end': time, 'frames': [frame], 'detail': True,
                    'media_identity': data.get('media_identity')})
    return {'session_id': session, 'visual': {'frames': [frame], 'complete_continuous_coverage': False}}
