"""Observation candidates reuse the existing scene and exact-frame extractors."""
from pathlib import Path

from .common import ReaderError, digest, write_json
from .vendor import frames

REVISION = 1


def plan_identity(strategy, speech=None):
    """Only the actual adaptive planning input affects its generation.

    Host review, confidence and speech text are not inputs to timestamp choice.
    Scene-only plans do not depend on speech at all.
    """
    cues = [(s['start'], s['end']) for s in (speech or {}).get('segments', [])] if strategy == 'adaptive' else None
    return digest([REVISION, strategy, cues])


def spread(values, count):
    if len(values) <= count:
        return values
    return [values[round(i * (len(values) - 1) / max(1, count - 1))] for i in range(count)]


def extract(data, output, lo, hi, budget, width, strategy, speech):
    try:
        if strategy == 'scene':
            return frames.extract_scene_or_uniform(data['media_path'], output, budget / (hi-lo), budget,
                resolution=width, max_frames=budget, start_seconds=lo, end_seconds=hi, dedup=False)
        captions = speech.get('segments', [])
        # Sparse timeline anchors remain even when narration does not describe
        # a cut, black screen or text-only insert. No near-duplicate suppression.
        anchors = [lo + (hi-lo) * i / max(1, min(5, budget)) for i in range(min(5, budget))]
        candidates = frames.extract_scene_candidates(data['media_path'], output / 'candidates',
            resolution=320, max_frames=None, start_seconds=lo, end_seconds=hi)
        cuts = [f['timestamp_seconds'] for f in candidates if lo <= f['timestamp_seconds'] < hi]
        cues = [max(lo, (s['start'] + min(s['end'], hi)) / 2) for s in captions if s['end'] > lo and s['start'] < hi]
        remaining = max(0, budget - len(anchors))
        selected_cuts = spread(cuts, min(remaining, max(1, remaining // 2))) if remaining else []
        selected_cues = spread(cues, max(0, remaining-len(selected_cuts))) if remaining > len(selected_cuts) else []
        points = sorted(set(anchors + selected_cuts + selected_cues))
        if not captions and len(points) < budget:
            points = sorted(set(points + [lo + (hi-lo) * i / budget for i in range(budget)]))
            points = spread(points, budget)
        selected, _ = frames.extract_at_timestamps(data['media_path'], output, points,
            resolution=width, max_frames=budget, start_seconds=lo, end_seconds=hi)
        for frame in selected:
            frame['observation_reason'] = ('scene_change' if frame['requested_timestamp_seconds'] in selected_cuts else
                'speech_cue' if frame['requested_timestamp_seconds'] in selected_cues else 'timeline_check')
        write_json(output / 'candidates.json', {'scene_frames': candidates, 'speech_cue_times': cues})
        return selected, {'engine': 'speech_scene_timeline', 'caption_guided': bool(captions),
            'scene_candidates': len(cuts), 'speech_candidates': len(cues), 'selected_count': len(selected),
            'candidate_index': str(output / 'candidates.json'), 'deduped_count': 0,
            'coverage': 'sampled; host expands unresolved/task-relevant intervals with exact timestamps',
            'limitation': 'Scene thresholds can miss subtle text changes; timeline/caption checks do not guarantee every brief visual was observed.'}
    except SystemExit as error:
        raise ReaderError(str(error)) from None
