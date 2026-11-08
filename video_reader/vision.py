"""Offline OCR, local text stability, and traceable speech/text reconciliation."""
from __future__ import annotations

from difflib import SequenceMatcher
import importlib
import importlib.util
from pathlib import Path
import re
import threading
import time

from PIL import Image

from .common import ReaderError, digest, read_json, stamp, write_json
from .vendor import frames as decoder
from .capability_identity import runtime_identity

REVISION = 3
FRAME_REVISION = 2
_engine = None
_engine_profile = None
_lock = threading.Lock()


def available():
    return importlib.util.find_spec('rapidocr_onnxruntime') is not None


def warmup():
    """Preload native imports on the Windows main thread without loading a model."""
    if available():
        importlib.import_module('rapidocr_onnxruntime')


def profile():
    return digest({'engine': 'rapidocr_onnxruntime', 'frame_policy': FRAME_REVISION, 'verification_policy': REVISION,
                   'runtime': runtime_identity('rapidocr-onnxruntime', assets=True),
                   'onnxruntime': runtime_identity('onnxruntime')})


def normalized(text):
    return re.sub(r'[^\w=+×÷().%-]', '', text, flags=re.UNICODE).lower()


def ocr_frame(path):
    global _engine, _engine_profile
    path = Path(path)
    identity = [path.stat().st_size, path.stat().st_mtime_ns]
    generation = profile()
    cached = path.with_suffix(f'.ocr-{generation}.json')
    if cached.is_file():
        previous = read_json(cached)
        if previous.get('revision') == FRAME_REVISION and previous.get('identity') == identity:
            return previous['lines']
    try:
        with _lock:
            if _engine is None or _engine_profile != generation:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
                _engine_profile = generation
            rows, _ = _engine(str(path))
    except Exception as exc:
        raise ReaderError(f'Local OCR failed: {type(exc).__name__}; check rapidocr-onnxruntime in this component environment') from None
    lines = [{'text': row[1], 'confidence': round(float(row[2]), 4),
              'box': [[round(float(x), 2), round(float(y), 2)] for x, y in row[0]]}
             for row in (rows or [])]
    write_json(cached, {'revision': FRAME_REVISION, 'profile': generation, 'identity': identity, 'lines': lines})
    return lines


def _bounds(line):
    xs, ys = zip(*line['box'])
    return min(xs), min(ys), max(xs), max(ys)


def _kind(line, height):
    text = normalized(line['text'])
    box = _bounds(line)
    if line['confidence'] < .8 or box[3]-box[1] < height*.025:
        return None
    if re.search(r'\d', text) and re.search(r'(?:[fpnumk]?m|[fpnumk]?s|%|[kmg]?v|倍|元|秒)$', text):
        return 'numeric'
    if '=' in text or re.fullmatch(r'[A-Za-z]', line['text']):
        return 'formula'
    return None


def _same_field(reference, lines, width, height):
    x0, y0, x1, y1 = _bounds(reference)
    candidates = []
    for line in lines:
        a, b, c, d = _bounds(line)
        if line['confidence'] < .8:
            continue
        if abs((y0+y1-b-d)/2) < height*.035 and abs(x0-a) < width*.06:
            candidates.append((abs((y0+y1-b-d)/2)+abs(x0-a), line))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def stable_runs(observations, hold_seconds=1):
    """Return runs of exactly matching tracked text, without crossing a missing field."""
    runs, run = [], []
    for obs in observations:
        if not obs['values'] or any(value is None for value in obs['values']):
            if run:
                runs.append(run)
            run = []
        elif run and obs['values'] == run[-1]['values']:
            run.append(obs)
        else:
            if run:
                runs.append(run)
            run = [obs]
    if run:
        runs.append(run)
    return [run for run in runs if run[-1]['time']-run[0]['time'] >= hold_seconds-.01]


def annotate_frame(frame, data, directory, config, end, allow_shift=True):
    lines = ocr_frame(frame['path'])
    original = {**frame, 'ocr': lines}
    with Image.open(frame['path']) as image:
        width, height = image.size
    tracked = [line for line in lines if _kind(line, height)]
    if not tracked:
        return {**original, 'temporal': {'status': 'not_assessed', 'reason': 'No large numeric/formula field detected'}}
    options = config.get('vision', {})
    lookahead = options.get('lookahead_seconds', 10)
    if isinstance(lookahead, bool) or not isinstance(lookahead, (int, float)) or not 1 <= lookahead <= 15:
        raise ReaderError('vision.lookahead_seconds must be between 1 and 15')
    start = frame['timestamp_seconds']
    finish = min(end, start+lookahead)
    if finish-start < 1:
        return {**original, 'temporal': {'status': 'unresolved', 'reason': 'Insufficient source interval to establish a local hold'}}
    out = directory / 'temporal' / digest([profile(), start, finish, width])
    index_path = out / 'index.json'
    if index_path.exists() and all(Path(f['path']).is_file() for f in read_json(index_path)):
        probes = read_json(index_path)
    else:
        probes = decoder.extract(data['media_path'], out, 2, resolution=width, max_frames=32,
                                 start_seconds=start, end_seconds=finish)
        write_json(index_path, probes)
    observations = []
    has_formula = any(_kind(line, height) == 'formula' for line in tracked)
    for probe in probes:
        seen = ocr_frame(probe['path'])
        matched = [_same_field(line, seen, width, height) for line in tracked]
        values = [normalized(line['text']) if line else None for line in matched]
        observations.append({'time': probe['timestamp_seconds'], 'values': values, 'path': probe['path'], 'ocr': seen})
        # Numeric counters can finish before a scene transition; formulas often
        # pause at incomplete intermediate expressions, so inspect the full window.
        runs = stable_runs(observations)
        if (not has_formula and runs and runs[-1][-1]['time'] == observations[-1]['time']
                and len({tuple(o['values']) for o in observations}) > 1):
            break
        if any(value is None for value in values):
            break  # A disappeared field is not a stable final value from another shot.
    last_seen = next((o['time'] for o in reversed(observations) if all(v is not None for v in o['values'])), None)
    runs = [run for run in stable_runs(observations) if run[-1]['time'] == last_seen
            and not any(re.search(r'[=+×÷(]$', value or '') for value in run[-1]['values'])]
    states = {tuple(o['values']) for o in observations if all(v is not None for v in o['values'])}
    changed = len(states) > 1
    status = 'changing_then_stable' if changed and runs else 'locally_stable' if runs else 'unresolved'
    temporal = {'status': status, 'observed_text_changes': changed, 'semantic_finality_established': False,
                'anchor_timestamp_seconds': start,
                'observations': [{'time': o['time'], 'values': o['values']} for o in observations],
                'scope': 'Local OCR observations only; a held frame does not prove an animation is semantically finished.'}
    if not runs:
        return {**original, 'temporal': temporal}
    selected = runs[-1][-1]
    reference = {**frame, 'path': selected['path'], 'timestamp_seconds': selected['time'],
                 'time': stamp(selected['time']), 'ocr': selected['ocr']}
    temporal['stable_observed_seconds'] = round(runs[-1][-1]['time']-runs[-1][0]['time'], 3)
    if changed and allow_shift:
        return {**reference, 'reason': 'locally_stable_text', 'anchor_frame_path': frame['path'], 'temporal': temporal}
    if changed:
        temporal['stable_reference'] = reference
    return {**original, 'temporal': temporal}


def _distance(a, b):
    return sum(max(i2-i1, j2-j1) for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes() if op != 'equal')


def correction_candidate(raw, lines, height, min_confidence=.94):
    """Only reconcile small edits to a near-identical, high-confidence full line."""
    a = normalized(raw)
    candidates = []
    for line in lines:
        b = normalized(line['text'])
        _, y0, _, y1 = _bounds(line)
        if line['confidence'] < min_confidence or y0 < height*.35 or y1-y0 < height*.025 or min(len(a), len(b)) < 5:
            continue
        ratio = SequenceMatcher(None, a, b).ratio()
        distance = _distance(a, b)
        if min(len(a), len(b))/max(len(a), len(b)) >= .8 and ratio >= .68 and distance <= max(2, int(len(a)*.12)):
            candidates.append((ratio, line))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _frame_at(data, directory, timestamp):
    timestamp = round(timestamp, 3)
    out = directory / 'screen-verification' / digest([FRAME_REVISION, timestamp])
    path = out / 'cue_0000.jpg'
    if not path.exists():
        decoder.extract_at_timestamps(data['media_path'], out, [timestamp], resolution=1280,
                                       max_frames=1, start_seconds=0, end_seconds=data['metadata']['duration_seconds'])
    return {'path': str(path), 'time': timestamp, 'lines': ocr_frame(path)}


def verify_segments(data, segments, directory, config, *, cached_only=False, skip_reviewed=False):
    if not config.get('vision', {}).get('enabled', True):
        return [{**s, 'screen_verification': {'status': 'disabled'}} for s in segments]
    generation = profile()
    cache_path = directory / f'screen-verifications-{generation}.json'
    cache = read_json(cache_path) if cache_path.exists() else {}
    result, previous = [], time.monotonic()
    for segment in segments:
        key = digest([REVISION, segment['start'], segment['end'], segment['text']])
        reusable = key in cache and all('lines' in evidence for evidence in cache[key].get('evidence', []))
        reviewed = segment.get('review_status') in ('reviewed', 'uncertain')
        if not reusable and (cached_only or (skip_reviewed and reviewed)):
            result.append({**segment, 'screen_verification': {'status': 'not_requested',
                           'reason': 'explicit_timestamps' if cached_only else 'host_reviewed'}})
            continue
        if not reusable:
            duration = segment['end']-segment['start']
            middle = (segment['start']+segment['end'])/2
            first = _frame_at(data, directory, middle-max(0, min(.2, duration/4)))
            with Image.open(first['path']) as image:
                height = image.height
            one = correction_candidate(segment['text'], first['lines'], height, min_confidence=.85)
            check = {'status': 'not_corroborated', 'evidence': [{'time': first['time'], 'path': first['path'], 'lines': first['lines']}]}
            if one and duration >= .35:
                second = _frame_at(data, directory, middle+min(.2, duration/4))
                two = correction_candidate(segment['text'], second['lines'], height, min_confidence=.85)
                check['evidence'].append({'time': second['time'], 'path': second['path'], 'lines': second['lines']})
                if two and normalized(one['text']) == normalized(two['text']):
                    confidence = min(one['confidence'], two['confidence'])
                    status = ('matched' if normalized(one['text']) == normalized(segment['text']) else
                              'difference_detected' if confidence >= .94 else 'possible_screen_difference')
                    check.update(status=status,
                                 screen_text=one['text'], confidence=min(one['confidence'], two['confidence']),
                                 basis='Two local OCR frames agree on a near-identical full line. OCR can be wrong even when stable and confident; compare the actual images. Original speech/captions are never replaced.')
                else:
                    check['status'] = 'unstable_or_disagreeing_screen_text'
            check['ocr_profile'] = generation
            cache[key] = check
            write_json(cache_path, cache)
        check = {**cache[key], 'cache_reused': reusable}
        item = {**segment, 'screen_verification': check}
        if check['status'] in ('difference_detected', 'possible_screen_difference'):
            item.update(raw_text=segment['text'], screen_candidate=check['screen_text'])
        result.append(item)
        from .jobs import report
        report(progress={'done': len(result), 'total': len(segments), 'processed_through': segment['end']})
        if time.monotonic()-previous > 25:
            import sys
            print(f'[video-reader] Screen verification processed through {stamp(segment["end"])}', file=sys.stderr, flush=True)
            previous = time.monotonic()
    return result
