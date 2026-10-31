from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from .common import ROOT, ReaderError, digest, read_json, run, stamp, write_json
from .qwen_pipeline import seam_diagnostics, stitch_chunks

SOURCE = 'local_qwen3_asr'
REVISION = 1


def profile(config, context):
    options = config['qwen']
    return digest({'engine': SOURCE, 'revision': REVISION, 'model': options['model_path'],
                   'aligner': options['aligner_path'], 'runtime': options['runtime_dir'],
                   'context': context, 'language': 'Chinese', 'chunk_seconds': 60, 'padding_seconds': 2})


def available(config):
    options = config['qwen']
    runtime = Path(options['runtime_dir'])
    return all(path.is_file() for path in (Path(options['model_path']) / 'model.safetensors',
        Path(options['aligner_path']) / 'model.safetensors', runtime / 'pyvenv.cfg')) and (runtime / 'Lib/site-packages/qwen_asr').is_dir()


def chunk_segments(chunk):
    words = chunk['words']
    selected = chunk['selected_raw_indices']
    result, first = [], 0
    for index, word in enumerate(words):
        raw_stop = selected[0] + index + 1
        text_start = 0 if selected[0] + first == 0 else words[first]['text_start']
        text_end = chunk['raw_words'][raw_stop]['text_start'] if raw_stop < len(chunk['raw_words']) else len(chunk['raw_text'])
        text = chunk['raw_text'][text_start:text_end].strip()
        duration = word['end'] - words[first]['start']
        if index + 1 < len(words) and duration < 12 and len(text) < 140 and not re.search(r'[。！？!?；;][”’"\']?$', text):
            continue
        group = words[first:index + 1]
        start, end = group[0]['start'], group[-1]['end']
        flags = ['zero_duration_alignment'] if any(item['start'] == item['end'] for item in group) else []
        if end <= start:
            start, end = chunk['owner']
            flags.append('unresolved_segment_timing')
        result.append({'start': round(start, 6), 'end': round(end, 6), 'text': text,
                       'words': [{'text': item['text'], 'start': item['start'], 'end': item['end'],
                                  'probability': None} for item in group],
                       'alignment': 'qwen_forced_alignment_estimate',
                       'recognition': {'mean_word_probability': None, 'uncertain_words': [], 'flags': flags}})
        first = index + 1
    return result


def assemble(records):
    groups = []
    for record in sorted(records, key=lambda record: record['start']):
        if not groups or abs(groups[-1][-1]['owner'][1] - record['start']) > .001:
            groups.append([])
        groups[-1].append(record['qwen_chunk'])
    segments, seams, cuts = [], [], []
    for group in groups:
        chunks, group_cuts = stitch_chunks(group)
        group_seams = seam_diagnostics(chunks)
        for chunk in chunks:
            selected = chunk_segments(chunk)
            for segment in selected:
                if any(seam['requires_review'] and segment['start'] - .5 <= seam['time'] <= segment['end'] + .5
                       for seam in group_seams):
                    segment['recognition']['flags'].append('qwen_seam_requires_review')
            segments.extend(selected)
        seams.extend(group_seams)
        cuts.extend(group_cuts)
    return segments, seams, cuts


def decode(data, lo, hi, directory, config, context, emit):
    from .relisten import stop
    if not available(config):
        raise ReaderError('Qwen requires its component-owned runtime and both local models; no automatic download or fallback')
    if hi - lo > 60.001:
        raise ReaderError('Qwen source intervals must be at most 60 seconds')
    options = config['qwen']
    timeout = options.get('timeout_seconds', 300)
    if type(timeout) not in (int, float) or not 1 <= timeout <= 600:
        raise ReaderError('Qwen timeout_seconds must be between 1 and 600')
    runtime = Path(options['runtime_dir'])
    version = next((line.partition('=')[2].strip() for line in (runtime / 'pyvenv.cfg').read_text().splitlines()
                    if line.partition('=')[0].strip() in ('version', 'version_info')), '')
    if version.split('.')[:2] != [str(sys.version_info.major), str(sys.version_info.minor)]:
        raise ReaderError('Qwen runtime must use the same Python major/minor as Video Reader')
    target = directory / 'qwen-jobs' / uuid.uuid4().hex
    target.mkdir(parents=True)
    left, right = max(0, lo - 2), min(data['metadata']['duration_seconds'], hi + 2)
    audio = target / 'input.wav'
    emit(f'Qwen decoding source interval {stamp(lo)}–{stamp(hi)}; local GPU worker')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(left), '-i', data['media_path'],
         '-t', str(right - left), '-vn', '-ac', '1', '-ar', '16000', str(audio)])
    request = {'audio': str(audio), 'start': lo, 'end': hi, 'audio_start': left,
               'options': options, 'context': context}
    write_json(target / 'request.json', request)
    bootstrap = ("import runpy,sys;sys.path[:0]=sys.argv[1:3];"
                 "sys.argv=['video_reader.qwen_worker',*sys.argv[3:]];"
                 "runpy.run_module('video_reader.qwen_worker',run_name='__main__')")
    command = [getattr(sys, '_base_executable', sys.executable), '-I', '-c', bootstrap,
               str(ROOT), str(runtime / 'Lib/site-packages'), str(target / 'request.json')]
    started, process = time.monotonic(), None
    try:
        with (target / 'worker.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            process.wait(timeout=timeout)
        if process.returncode or not (target / 'decoded.json').is_file():
            raise ReaderError(f'Qwen worker failed; inspect {target / "worker.log"}; no automatic fallback')
        chunk = read_json(target / 'decoded.json')
    except subprocess.TimeoutExpired:
        stop(process)
        raise ReaderError('Qwen worker exceeded its deadline and was terminated; completed intervals remain cached') from None
    except BaseException:
        if process:
            stop(process)
        raise
    record = {'start': lo, 'end': hi, 'source': SOURCE, 'profile': profile(config, context),
              'status': 'ready' if chunk['text'] else 'no_speech', 'qwen_chunk': chunk,
              'language': 'zh', 'language_probability': None, 'model': Path(options['model_path']).name,
              'context': context, 'segments': assemble([{'start': lo, 'qwen_chunk': chunk}])[0],
              'decoding': {'engine': 'qwen', 'revision': REVISION, 'padding_seconds': 2,
                           'word_timestamps': True, 'timestamp_class_step_seconds': .08,
                           'timing_accuracy_verified': False, 'mean_word_probability_available': False},
              'elapsed_seconds': round(time.monotonic() - started, 3), 'job_path': str(target),
              'scope': 'speech only; raw text and model-estimated timing, not native sound understanding'}
    write_json(target / 'record.json', record)
    return record
