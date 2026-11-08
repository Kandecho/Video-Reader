"""Local speech decoding and interval coverage; never silently rewrite speech."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import threading
import time

from .common import ReaderError, digest, run, stamp
from .capability_identity import assets_identity, runtime_identity

_models = {}
_lock = threading.Lock()
REVISION = 3
SOURCE = 'local_faster_whisper'
SOURCES = ('auto', 'captions', 'asr', 'qwen')


def legacy_profile(config, context):
    options = config['asr']
    return digest({'revision': REVISION, 'model': options['model_path'], 'device': options['device'],
                   'compute_type': options['compute_type'], 'language': options.get('language'),
                   'context': context, 'word_timestamps': True, 'beam_size': 5})


def engine_identity(config):
    return {'assets': assets_identity(config['asr'].get('model_path')),
            'runtime': [runtime_identity(name) for name in ('faster-whisper', 'ctranslate2')],
            'python': list(sys.version_info[:3])}


def profile(config, context):
    return digest([legacy_profile(config, context), engine_identity(config)])


def model_key(config, generation=None):
    options = config['asr']
    return (options['model_path'], options['device'], options['compute_type'],
            digest(engine_identity(config) if generation is None else generation))


def validate_source(source):
    if source not in SOURCES:
        raise ReaderError('Speech source must be auto, captions, asr or qwen')
    return source


def backend(source):
    validate_source(source)
    if source == 'qwen':
        from . import qwen
        return qwen
    return sys.modules[__name__]


def available(config):
    model = config['asr'].get('model_path')
    return bool(model and (Path(model) / 'model.bin').is_file() and importlib.util.find_spec('faster_whisper'))


def status(config):
    from . import qwen
    model = config['asr'].get('model_path')
    return {'asr': available(config), 'qwen': qwen.available(config),
            'asr_assets': bool(model and (Path(model) / 'model.bin').is_file())}


def chunk_seconds(config):
    chunk = config['asr'].get('chunk_seconds', 120)
    if isinstance(chunk, bool) or not isinstance(chunk, (float, int)) or not 15 <= chunk <= 600:
        raise ReaderError('ASR chunk_seconds must be between 15 and 600')
    return chunk


def reading_context(data, config, context=None, source='auto', speech_profile=None):
    validate_source(source)
    value = context if context is not None else ''
    if not isinstance(value, str) or len(value) > 1000:
        raise ReaderError('Speech context must be a string of at most 1000 characters')
    if context is not None or source in ('qwen', 'captions'):
        return value
    records = [s for s in data['speech'] if s['source'] == SOURCE]
    if speech_profile is not None:
        selected = next((r for r in records if r.get('profile') == speech_profile), None)
        if selected is not None:
            return selected.get('context', '')
    def matching(text):
        identities = (profile(config, text), legacy_profile(config, text))
        return any(r.get('profile') in identities or r.get('configuration_profile') == identities[1] for r in records)
    if matching(''):
        return ''
    legacy = data.get('platform_metadata', {}).get('part_title') or data['title']
    return legacy if matching(legacy) else ''


def material(data, lo, hi, config, source='auto', context='', *, speech_profile=None, allow_historical=True):
    """Select exactly one cached generation; never splice legacy and new chunks."""
    validate_source(source)
    if speech_profile is not None and (not isinstance(speech_profile, str) or not speech_profile):
        raise ReaderError('speech_profile must identify an existing cached speech track')
    available_sources = sorted(set(r['source'] for r in data['speech']))
    profiles = list(dict.fromkeys(r['profile'] for r in data['speech'] if r.get('profile')))
    captions = [r for r in data['speech'] if r['source'] == 'captions']
    records = captions if speech_profile is None and source in ('auto', 'captions') and captions else []
    engine, wanted, historical = None, None, False
    if not records and source != 'captions':
        engine = backend(source)
        if speech_profile is not None and source == 'auto':
            selected = next((r for r in data['speech'] if r.get('profile') == speech_profile), None)
            if selected is not None:
                from . import qwen
                engine = backend('qwen' if selected['source'] == qwen.SOURCE else 'asr')
        wanted = engine.profile(config, context)
        chosen = speech_profile or wanted
        records = [r for r in data['speech'] if r['source'] == engine.SOURCE and r.get('profile') == chosen]
        if not records and speech_profile is None and allow_historical:
            legacy = engine.legacy_profile(config, context)
            historical_records = [r for r in data['speech'] if r['source'] == engine.SOURCE and
                                  (r.get('profile') == legacy or r.get('configuration_profile') == legacy)]
            if historical_records:
                chosen = historical_records[-1]['profile']
                records = [r for r in historical_records if r.get('profile') == chosen]
        historical = bool(records and chosen != wanted)
    if speech_profile is not None and not records:
        raise ReaderError('speech_profile is not a cached track for the selected source')
    missing = missing_ranges(records, lo, hi)
    coverage = {'kind': 'source_processed', 'requested_range': [lo, hi], 'complete': not missing,
                'missing_ranges': [list(r) for r in missing]}
    common = {'coverage': coverage, 'available_sources': available_sources, 'available_profiles': profiles}
    if wanted is not None:
        common.update(current_profile=wanted, profile_status='historical' if historical else 'current')
    if records:
        records = sorted(records, key=lambda r: r['start'])
        if engine is not None and hasattr(engine, 'assembled'):
            assembled = engine.assembled(records, lo, hi)
        else:
            assembled = {'segments': [s for r in records for s in r['segments']], 'metadata': {}, 'diagnostics': {}}
        segments = sorted((s for s in assembled['segments'] if s['end'] > lo and s['start'] < hi), key=lambda s: (s['start'], s['end']))
        segments = list({(s['start'], s['end'], s['text']): s for s in segments}.values())
        from .recognition import assess
        assessment, unresolved = assess(records, segments, lo, hi, diagnostics=assembled['diagnostics'])
        record = records[0]
        return {**{k: v for k, v in record.items() if k not in ('segments', 'start', 'end', 'qwen_chunk')},
                **assembled['metadata'], **common, 'start': lo, 'end': hi,
                'status': 'partial' if missing else 'alignment_unresolved' if unresolved else 'ready' if segments else 'no_speech',
                'segments': segments, 'recognition_assessment': assessment, 'unplaced_candidates': unresolved,
                'quality': {'source': 'human_declared' if (record.get('track') or {}).get('kind') == 'manual' else 'machine_generated',
                            'exactness_guaranteed': False, 'text_status': assessment['text_status']}}
    if source == 'captions':
        return {**common, 'status': 'unavailable', 'segments': [], 'reason': 'No caption track covers this interval'}
    if not data['metadata']['has_audio']:
        return {**common, 'status': 'no_audio_stream', 'segments': []}
    ready = engine.available(config)
    return {**common, 'status': 'requires_transcription' if ready else 'unavailable', 'segments': [],
            'available_tool': 'video_transcript' if ready else None,
            'reason': 'Selected local speech source needs decoding' if ready else 'Selected local speech model/runtime is unavailable; no automatic fallback'}


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
    generation = engine_identity(config)
    key = model_key(config, generation)
    try:
        with _lock:
            if key not in _models:
                from faster_whisper import WhisperModel
                for previous in list(_models):
                    if previous[:3] == key[:3] and previous != key:
                        del _models[previous]
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
    if engine_identity(config) != generation:
        raise ReaderError('Speech model/runtime changed during decoding; completed older intervals are preserved')
    if not precise_words or terms:
        decoding_profile = digest([decoding_profile, precise_words, terms])
    return {'start': lo, 'end': hi, 'source': SOURCE,
            'status': 'ready' if segments else 'no_speech', 'profile': decoding_profile,
            'configuration_profile': legacy_profile(config, context), 'engine_identity': generation,
            'language': info.language, 'language_probability': info.language_probability,
            'model': Path(options['model_path']).name, 'context': context, 'segments': segments,
            'decoding': {'revision': REVISION, 'word_timestamps': precise_words, 'beam_size': 5,
                         'padding_seconds': padding, 'terms': terms or [], 'vad_filter': precise_words,
                         'temperature_fallback': precise_words, 'max_new_tokens': None if precise_words else 256},
            'scope': 'speech only; decoding confidence is not evidence of factual correctness'}
