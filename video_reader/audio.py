"""Measured sound cues only: levels, quiet intervals and abrupt level changes."""
import math
import re

from .common import ReaderError, digest, read_json, run, write_json


def inspect_audio(reader, session, start=0, end=None):
    data = reader.load(session)
    lo, hi = reader.window(data, start, end)
    requested_end = hi
    if hi - lo > 600:
        hi = lo + 600
    if not data['metadata'].get('has_audio'):
        return {'session_id': session, 'status': 'no_audio_stream', 'cues': []}
    path = reader.directory(session) / 'audio-cues' / (digest([lo, hi, 2]) + '.json')
    if path.is_file():
        # The measurement window can serve both a short request and the first
        # page of a longer one. Continuation belongs to this request, not cache.
        return {**read_json(path), 'next_start': hi if hi < requested_end else None}
    sample_rate = int(run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate',
                           '-of', 'default=noprint_wrappers=1:nokey=1', data['media_path']]).strip())
    result = run(['ffmpeg', '-hide_banner', '-nostdin', '-ss', str(lo), '-t', str(hi-lo), '-i', data['media_path'],
        '-vn', '-af', f'asetnsamples=n={sample_rate}:p=0,astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level+Peak_level,ametadata=print:file=-',
        '-f', 'null', '-'], timeout=180)
    cues, current = [], None
    for line in result.splitlines():
        if match := re.search(r'pts_time:([0-9.]+)', line):
            current = {'start': lo + float(match[1]), 'end': min(hi, lo + float(match[1]) + 1)}
            cues.append(current)
        elif current is not None and '=' in line:
            key, value = line.rsplit('=', 1)
            if key.endswith(('RMS_level', 'Peak_level')):
                number = float(value)
                current['rms_db' if key.endswith('RMS_level') else 'peak_db'] = number if math.isfinite(number) else None
    for index, cue in enumerate(cues):
        cue['quiet'] = cue.get('rms_db') is None or cue['rms_db'] < -45
        previous = cues[index-1].get('rms_db') if index else None
        cue['abrupt_level_change'] = previous is not None and cue.get('rms_db') is not None and abs(cue['rms_db']-previous) >= 10
        previous_peak = cues[index-1].get('peak_db') if index else None
        cue['peak_rise'] = previous_peak is not None and cue.get('peak_db') is not None and cue['peak_db']-previous_peak >= 10
    output = {'session_id': session, 'status': 'measured', 'range': {'start': lo, 'end': hi}, 'cues': cues,
        'measurement': 'native sample rate, one-second windows; dBFS RMS and peak; quiet threshold -45 dBFS; change threshold 10 dB; short events may need finer inspection',
        'semantics': 'No music/emotion/event recognition. Quiet does not prove absence of meaningful speech. No speech is removed.',
        'raw_sound_understood_by_host': False}
    write_json(path, output)
    return {**output, 'next_start': hi if hi < requested_end else None}
