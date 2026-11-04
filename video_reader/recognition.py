"""Derived recognition quality, separate from processing and host review identity."""
import copy
from .common import digest

REVISION = 1
SUSPECT = {'suspect_decoding', 'zero_duration_alignment', 'unresolved_segment_timing', 'qwen_seam_requires_review'}


def candidate(segment):
    return bool(SUSPECT.intersection(segment.get('recognition', {}).get('flags', [])))


def unplaced(record):
    chunk = record.get('qwen_chunk') or {}
    raw = chunk.get('raw_text', '')
    from .qwen_pipeline import normalize
    if not normalize(raw) or chunk.get('text') or chunk.get('words'):
        return None
    words = chunk.get('raw_words') or []
    if words and not any(w['start'] == w['end'] for w in words):
        return None  # Valid speech confined to padding must stay outside owner.
    value = {'raw_text': raw, 'input_range': chunk.get('input'), 'owner_range': chunk.get('owner'),
             'time_status': 'unplaced', 'reason': 'missing_or_zero_duration_alignment',
             'raw_alignment': copy.deepcopy(words), 'warnings': copy.deepcopy(chunk.get('warnings', [])),
             'processed_range': [record['start'], record['end']]}
    value['candidate_id'] = digest([record.get('source'), record.get('profile'), value])
    return value


def assess(records, segments, lo, hi):
    suspects = [s for s in segments if candidate(s)]
    unresolved = [value for r in records if r['end'] > lo and r['start'] < hi
                  if (value := unplaced(r)) is not None]
    status = ('alignment_unresolved' if unresolved else 'unverified_candidates' if suspects
              else 'candidate_text' if segments else 'no_transcript_returned')
    return {'revision': REVISION, 'text_status': status, 'suspect_segments': len(suspects),
            'suspect_ranges': [[s['start'], s['end']] for s in suspects],
            'unplaced_candidates': len(unresolved), 'confirmed_absence_of_speech': False,
            'notice': 'Machine candidates are not verified speech. Empty output is not an acoustic proof of silence.'}, unresolved


def diagnostic_identity(speech):
    return digest([REVISION, [(s['start'], s['end'], s['text'], s.get('recognition'))
                              for s in speech.get('segments', [])], speech.get('unplaced_candidates', [])])
