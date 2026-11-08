"""Derived recognition quality, separate from processing and host review identity."""
import copy
from .common import digest

REVISION = 1
SUSPECT = {'suspect_decoding', 'zero_duration_alignment', 'unresolved_segment_timing'}


def candidate(segment):
    recognition = segment.get('recognition', {})
    return bool(recognition.get('requires_review') or SUSPECT.intersection(recognition.get('flags', [])))


def assess(records, segments, lo, hi, *, diagnostics=None):
    diagnostics = diagnostics or {}
    suspects = [s for s in segments if candidate(s)]
    unresolved = copy.deepcopy(diagnostics.get('unplaced_candidates', []))
    status = ('alignment_unresolved' if unresolved else 'unverified_candidates' if suspects
              else 'candidate_text' if segments else 'no_transcript_returned')
    generation = copy.deepcopy(diagnostics.get('generation_warnings', []))
    return {'revision': REVISION, 'text_status': status, 'suspect_segments': len(suspects),
            'generation_warnings': generation,
            'suspect_ranges': [[s['start'], s['end']] for s in suspects],
            'unplaced_candidates': len(unresolved), 'confirmed_absence_of_speech': False,
            'notice': 'Machine candidates are not verified speech. Empty output is not an acoustic proof of silence.'}, unresolved


def diagnostic_identity(speech):
    # requires_review is a normalized projection of the preserved raw flags.
    # Adding the projection must not invalidate pre-boundary-fix continuations.
    def identity(segment):
        value = segment.get('recognition')
        return {k: v for k, v in value.items() if k != 'requires_review'} if value is not None else None
    return digest([REVISION, [(s['start'], s['end'], s['text'], identity(s))
                              for s in speech.get('segments', [])], speech.get('unplaced_candidates', [])])
