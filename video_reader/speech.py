"""Local speech decoding and interval coverage; never silently rewrite speech."""
from __future__ import annotations

from pathlib import Path
import threading
import time

from .common import ReaderError, digest, run, stamp

_models = {}
_lock = threading.Lock()
REVISION = 3


def profile(config, context):
    options = config['asr']
    return digest({'revision': REVISION, 'model': options['model_path'], 'device': options['device'],
                   'compute_type': options['compute_type'], 'language': options.get('language'),
                   'context': context, 'word_timestamps': True, 'beam_size': 5})


def missing_ranges(records, lo, hi):
    intervals = sorted((max(lo, r['start']), min(hi, r['end'])) for r in records
                       if r['end'] > lo and r['start'] < hi)
    result, cursor = [], lo
    for start, end in intervals:
        if start > cursor + .001:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi - .001:
        result.append((cursor, hi))
    return result


def decode(data, lo, hi, directory, config, context, emit, *, precise_words=True, terms=None):
    """Decode with two seconds of context around each owned interval.

    Word midpoints assign ownership so context words do not leak across interval
    boundaries. Raw word confidence is retained; it is not a truth probability.
    """
    options = config['asr']
    # Coarse decoding cannot assign context words to exact times, so do not feed
    # padded audio then falsely label all of it as belonging to the requested window.
    padding = 2 if precise_words else 0
    left = max(0, lo - padding)
    right = min(data['metadata']['duration_seconds'], hi + padding)
    audio = directory / 'audio' / f'{digest([left, right, REVISION])}.wav'
    audio.parent.mkdir(exist_ok=True)
    emit(f'Transcribing source interval {stamp(lo)}–{stamp(hi)} using local model')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(left), '-i', data['media_path'],
         '-t', str(right-left), '-vn', '-ac', '1', '-ar', '16000', str(audio)])
    key = (options['model_path'], options['device'], options['compute_type'])
    try:
        with _lock:
            from faster_whisper import WhisperModel
            if key not in _models:
                _models[key] = WhisperModel(options['model_path'], device=options['device'],
                                            compute_type=options['compute_type'], local_files_only=True, cpu_threads=4)
            stream, info = _models[key].transcribe(
                str(audio), language=options.get('language'), beam_size=5, vad_filter=precise_words,
                word_timestamps=precise_words, without_timestamps=False,
                temperature=(0.0, .2, .4, .6, .8, 1.0) if precise_words else 0.0,
                max_new_tokens=None if precise_words else 256,
                hallucination_silence_threshold=2 if precise_words else None,
                condition_on_previous_text=False, initial_prompt=context or None,
                hotwords=', '.join(terms) if terms else None)
            segments, previous = [], time.monotonic()
            for s in stream:
                words = [w for w in (s.words or []) if lo <= left + (w.start+w.end)/2 < hi]
                if words:
                    text = ''.join(w.word for w in words).strip()
                    start, end = max(lo, left+words[0].start), min(hi, left+words[-1].end)
                    uncertain = [{'text': w.word.strip(), 'start': round(max(lo, left+w.start), 3),
                                  'end': round(min(hi, left+w.end), 3), 'probability': round(w.probability, 4)}
                                 for w in words if w.probability < .65 and w.word.strip()]
                    probability = sum(w.probability for w in words)/len(words)
                    aligned_words = [{'text': w.word, 'start': round(max(lo, left+w.start), 3),
                                      'end': round(min(hi, left+w.end), 3),
                                      'probability': round(w.probability, 4)} for w in words]
                elif not s.words and lo <= left + (s.start+s.end)/2 < hi:
                    text, start, end = s.text.strip(), max(lo, left+s.start), min(hi, left+s.end)
                    uncertain, probability = [], None
                    aligned_words = []
                else:
                    continue
                if text and end > start:
                    flags = []
                    if uncertain:
                        flags.append('low_word_confidence')
                    if s.avg_logprob < -1 or s.no_speech_prob > .6 or s.compression_ratio > 2.4:
                        flags.append('suspect_decoding')
                    segments.append({'start': round(start, 3), 'end': round(end, 3), 'text': text,
                                     'words': aligned_words,
                                     'alignment': 'raw_words' if aligned_words else 'segment_estimate',
                                     'recognition': {'avg_logprob': round(s.avg_logprob, 4),
                                                     'no_speech_probability': round(s.no_speech_prob, 4),
                                                     'mean_word_probability': round(probability, 4) if probability is not None else None,
                                                     'uncertain_words': uncertain, 'flags': flags}})
                if time.monotonic() - previous > 25:
                    emit(f'Speech processed through source time {stamp(min(hi, left+s.end))}')
                    previous = time.monotonic()
    except Exception as exc:
        raise ReaderError(f'Local speech recognition failed: {type(exc).__name__}: {str(exc)[:250]}') from None
    decoding_profile = profile(config, context)
    if not precise_words or terms:
        decoding_profile = digest([decoding_profile, precise_words, terms])
    return {'start': lo, 'end': hi, 'source': 'local_faster_whisper',
            'status': 'ready' if segments else 'no_speech', 'profile': decoding_profile,
            'language': info.language, 'language_probability': info.language_probability,
            'model': Path(options['model_path']).name, 'context': context, 'segments': segments,
            'decoding': {'revision': REVISION, 'word_timestamps': precise_words, 'beam_size': 5,
                         'padding_seconds': padding, 'terms': terms or [], 'vad_filter': precise_words,
                         'temperature_fallback': precise_words, 'max_new_tokens': None if precise_words else 256},
            'scope': 'speech only; decoding confidence is not evidence of factual correctness'}
