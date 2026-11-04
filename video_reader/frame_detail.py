"""Resolve an existing frame ID in its own session, then inspect original pixels."""
from pathlib import Path
import math
from filelock import FileLock
from PIL import Image

from .common import ReaderError, digest, stamp, write_json
from .vendor import frames


def inspect_frame(reader, session, frame_id, width=1920, region=None):
    if type(width) is not int or not 64 <= width <= 3840:
        raise ReaderError('width must be 64..3840')
    if region is not None and (not isinstance(region, list) or len(region) != 4 or
        any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in region) or
        not region[0] < region[2] or not region[1] < region[3]):
        raise ReaderError('region must be normalized [left,top,right,bottom] within 0..1')
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
                cropped = image.crop((int(x1*image.width), int(y1*image.height), max(int(x1*image.width)+1,int(x2*image.width)), max(int(y1*image.height)+1,int(y2*image.height))))
                path = output / 'region.jpg'
                cropped.save(path, quality=95)
                frame['path'] = str(path)
        frame.update(id=identity + ':0', time=stamp(frame['timestamp_seconds']), parent_frame_id=frame_id,
                     region=region, precision='source_frame', source_time=time)
        write_json(detail_root / (identity + '.json'),
                   {'id': identity, 'start': time, 'end': time, 'frames': [frame], 'detail': True,
                    'media_identity': data.get('media_identity')})
    return {'session_id': session, 'visual': {'frames': [frame], 'complete_continuous_coverage': False}}
