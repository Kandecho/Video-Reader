"""A source-scoped reading layer, authored by the host agent, never by blind replacement."""
from __future__ import annotations

import copy
import difflib
import time
from pathlib import Path

from .common import ReaderError, UNTRUSTED, digest, read_json, write_json


def identity(speech):
    return {k: speech.get(k) for k in ('source', 'track', 'profile')}


def document(speech):
    source_identity = identity(speech)
    segments = [{**copy.deepcopy(s), 'segment_id': digest([source_identity, s['start'], s['end'], s['text']])}
                for s in speech.get('segments', [])]
    snapshot = speech.get('review_document_id') or digest([source_identity, [(s['segment_id'], s['text']) for s in segments]])
    return snapshot, segments


def material_id(speech):
    """Raw material identity is distinct from the durable review document."""
    return document({k: v for k, v in speech.items() if k != 'review_document_id'})[0]


def scope(speech, start, end):
    return {'start': start, 'end': end, 'material_snapshot_id': material_id(speech)}


def scoped_segments(segments, selected_scope):
    if selected_scope is None:
        return segments
    return [s for s in segments if s['end'] > selected_scope['start'] and s['start'] < selected_scope['end']]


def state(directory, snapshot, revision=None):
    path = directory / 'reviews' / (snapshot + '.json')
    saved = read_json(path) if path.is_file() else {
        'snapshot_id': snapshot, 'revision': 0, 'reviewed_segment_ids': [],
        'corrections': {}, 'terms': [], 'issues': {}, 'history': []}
    if revision is None or revision == saved['revision']:
        return saved
    if type(revision) is not int or not 0 <= revision < saved['revision']:
        raise ReaderError('Requested review revision does not exist')
    restored = {'snapshot_id': snapshot, 'revision': 0, 'reviewed_segment_ids': [],
                'corrections': {}, 'terms': [], 'issues': {}, 'history': []}
    for entry in saved['history']:
        if entry['revision'] > revision:
            break
        if entry['revision'] != restored['revision'] + 1:
            raise ReaderError('Review history is incomplete; cannot reconstruct that revision')
        payload = entry['payload']
        for term in payload.get('terms', []):
            item = {**term, 'id': digest([snapshot, term['text']])}
            restored['terms'] = [t for t in restored['terms'] if t['id'] != item['id']] + [item]
        for issue in payload.get('issues', []):
            if issue['note'].strip():
                restored['issues'][issue['segment_id']] = issue
            else:
                restored['issues'].pop(issue['segment_id'], None)
        ids = set(payload.get('reviewed_segment_ids', []))
        for change in payload.get('corrections', []):
            sid = change['segment_id']
            ids.add(sid)
            original, corrected = change['original'], change['corrected_text']
            edits = [{'start_char': a, 'end_char': b, 'original': original[a:b], 'replacement': corrected[c:d]}
                for op, a, b, c, d in difflib.SequenceMatcher(None, original, corrected, autojunk=False).get_opcodes() if op != 'equal']
            if edits:
                restored['corrections'][sid] = {**change, 'edits': edits, 'alignment': 'original_segment_times', 'updated_at': entry['at']}
            else:
                restored['corrections'].pop(sid, None)
        restored['reviewed_segment_ids'] = sorted(set(restored['reviewed_segment_ids']) | ids)
        restored['history'].append(entry)
        restored['revision'] = entry['revision']
    if restored['revision'] != revision:
        raise ReaderError('Review history is incomplete; cannot reconstruct that revision')
    return restored


def overlay(directory, full_speech, selected, view='reading', revision=None):
    if view not in ('reading', 'evidence', 'raw'):
        raise ReaderError('view must be reading, evidence or raw')
    snapshot, all_segments = document(full_speech)
    saved = state(directory, snapshot, revision)
    index = {(s['start'], s['end'], s['text']): s['segment_id'] for s in all_segments}
    result = []
    for original in selected:
        item = copy.deepcopy(original)
        sid = index.get((item['start'], item['end'], item['text']))
        correction = saved['corrections'].get(sid)
        issue = saved.get('issues', {}).get(sid)
        item.update(segment_id=sid, raw_text=item['text'], text_view=view,
                    review_status='uncertain' if issue else 'reviewed' if sid in saved['reviewed_segment_ids'] else 'pending')
        if issue:
            item['review_issue'] = issue
        if correction:
            item.update(corrected_text=correction['corrected_text'], correction=correction,
                        text=correction['corrected_text'] if view != 'raw' else item['text'])
        # Word alignment always describes raw_text, not newly inferred spellings.
        if item.get('words'):
            item['word_alignment_text'] = 'raw_text'
        if view == 'reading':
            flags = list(item.get('recognition', {}).get('flags', []))
            screen_status = item.get('screen_verification', {}).get('status')
            if screen_status and screen_status not in ('matched', 'not_corroborated', 'not_requested'):
                flags.append(screen_status)
            if issue:
                flags.append('review_uncertain')
            item = {k: item[k] for k in ('segment_id', 'start', 'end', 'text', 'review_status')}
            item.update(has_correction=bool(correction), quality_flags=flags,
                        evidence_available=bool(original.get('recognition') or original.get('screen_verification') or correction or issue))
        result.append(item)
    active_ids = {s['segment_id'] for s in all_segments}
    reviewed_ids = active_ids & set(saved['reviewed_segment_ids'])
    return result, {'snapshot_id': snapshot, 'revision': saved['revision'],
                    'reviewed_segments': len(reviewed_ids),
                    'total_segments': len(all_segments),
                    'complete': bool(full_speech.get('coverage', {}).get('complete')) and
                                len(reviewed_ids) == len(all_segments),
                    'corrected_segments': len(active_ids & saved['corrections'].keys()),
                    'unresolved_segments': len(active_ids & saved.get('issues', {}).keys()),
                    'author': 'host_agent', 'exactness_guaranteed': False}


def _frame_paths(data, directory):
    paths = set()
    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str):
                paths.add(str(Path(value['path']).resolve()))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(data.get('reads', []))
    cached = directory / 'screen-verifications.json'
    if cached.is_file():
        collect(read_json(cached))
    return paths


def _evidence(items, segments, known_paths, directory, data, terms):
    if not isinstance(items, list) or not items:
        raise ReaderError('Each correction/term requires source evidence')
    for item in items:
        if not isinstance(item, dict):
            raise ReaderError('Evidence must be an object')
        kind = item.get('kind')
        if kind == 'frame':
            path = str(Path(item.get('path', '')).resolve())
            if path not in known_paths or not Path(path).is_file():
                raise ReaderError('Frame evidence must be a returned frame from this session')
        elif kind == 'context':
            ids = item.get('segment_ids')
            if not isinstance(ids, list) or not ids or any(s not in segments for s in ids):
                raise ReaderError('Context evidence requires segment IDs from this snapshot')
        elif kind == 'title':
            if not data.get('title'):
                raise ReaderError('No source title is available')
        elif kind == 'term':
            if item.get('term_id') not in {t['id'] for t in terms}:
                raise ReaderError('Unknown source-scoped term')
        elif kind == 'relisten':
            job = item.get('job_id', '')
            if not isinstance(job, str) or len(job) != 24 or any(c not in '0123456789abcdef' for c in job):
                raise ReaderError('Invalid relisten job ID')
            path = directory / 'relistens' / job / 'result.json'
            if not path.is_file() or read_json(path).get('status') != 'completed':
                raise ReaderError('Relisten evidence requires a completed job in this session')
        else:
            raise ReaderError('Evidence kind must be frame, context, title, term or relisten')


def prepare(directory, speech, offset, limit, selected_scope=None, scope_speech=None):
    if not (scope_speech or speech).get('coverage', {}).get('complete'):
        raise ReaderError('Finish full-source transcription before preparing its review')
    snapshot, segments = document(speech)
    segments = scoped_segments(segments, selected_scope)
    saved = state(directory, snapshot)
    page, coverage = overlay(directory, speech, segments[offset:offset+limit])
    for item, original in zip(page, segments[offset:offset+limit]):
        item['original'] = original['text']
    return {'snapshot_id': snapshot, 'base_revision': saved['revision'], 'segments': page,
            **({'review_scope': selected_scope, 'scope_review': scope_coverage(directory, speech, selected_scope, scope_speech)} if selected_scope else {}),
            'source': speech.get('source'), 'track': speech.get('track'),
            'offset': offset, 'next_offset': offset+limit if offset+limit < len(segments) else None,
            'review': coverage, 'terms': saved['terms'],
            'previous_context': [{k: s[k] for k in ('segment_id', 'start', 'end', 'text')} for s in segments[max(0, offset-2):offset]],
            'following_context': [{k: s[k] for k in ('segment_id', 'start', 'end', 'text')} for s in segments[offset+limit:offset+limit+2]],
            'source_content_policy': UNTRUSTED}


def scope_coverage(directory, speech, selected_scope, scope_speech):
    snapshot, segments = document(speech)
    ids = {s['segment_id'] for s in scoped_segments(segments, selected_scope)}
    saved = state(directory, snapshot)
    reviewed = ids & set(saved['reviewed_segment_ids'])
    return {**selected_scope, 'source_processed': scope_speech['coverage']['complete'],
            'total_segments': len(ids), 'reviewed_segments': len(reviewed),
            'complete': scope_speech['coverage']['complete'] and reviewed == ids,
            'unresolved_segments': len(ids & saved.get('issues', {}).keys()),
            'exactness_guaranteed': False}


def commit(directory, data, speech, payload, selected_scope=None, scope_speech=None):
    if not (scope_speech or speech).get('coverage', {}).get('complete'):
        raise ReaderError('Cannot review incomplete source coverage')
    snapshot, all_segments = document(speech)
    segments = {s['segment_id']: s for s in all_segments}
    if not isinstance(payload, dict) or payload.get('snapshot_id') != snapshot:
        raise ReaderError('Review snapshot changed; prepare again')
    if selected_scope is not None and payload.get('review_scope') != selected_scope:
        raise ReaderError('Review scope material changed; prepare the same range again')
    if selected_scope is None and payload.get('review_scope') is not None:
        raise ReaderError('Commit must use the prepared review scope')
    permitted = {s['segment_id'] for s in scoped_segments(all_segments, selected_scope)}
    saved = state(directory, snapshot)
    if type(payload.get('base_revision')) is not int or payload['base_revision'] != saved['revision']:
        raise ReaderError('Review revision changed; prepare again')
    known_paths = _frame_paths(data, directory)
    terms = copy.deepcopy(saved['terms'])
    additions = payload.get('terms', [])
    if not isinstance(additions, list):
        raise ReaderError('terms must be a list')
    for term in additions:
        if not isinstance(term, dict) or not isinstance(term.get('text'), str) or not 1 <= len(term['text']) <= 100:
            raise ReaderError('A term requires 1–100 characters')
        _evidence(term.get('evidence'), segments, known_paths, directory, data, terms)
        entry = {**term, 'id': digest([snapshot, term['text']])}
        terms = [t for t in terms if t['id'] != entry['id']] + [entry]
    reviewed = payload.get('reviewed_segment_ids', [])
    if not isinstance(reviewed, list) or any(s not in permitted for s in reviewed):
        raise ReaderError('Unknown reviewed segment ID')
    changes = payload.get('corrections', [])
    if not isinstance(changes, list):
        raise ReaderError('corrections must be a list')
    issues = payload.get('issues', [])
    if not isinstance(issues, list):
        raise ReaderError('issues must be a list')
    saved.setdefault('issues', {})
    for issue in issues:
        if not isinstance(issue, dict) or issue.get('segment_id') not in permitted or not isinstance(issue.get('note'), str):
            raise ReaderError('An unresolved issue requires a known segment ID and a note')
        if issue['note'].strip():
            _evidence(issue.get('evidence'), segments, known_paths, directory, data, terms)
            saved['issues'][issue['segment_id']] = issue
        else:
            saved['issues'].pop(issue['segment_id'], None)
    ids = set()
    for change in changes:
        if not isinstance(change, dict) or change.get('segment_id') not in permitted:
            raise ReaderError('Unknown correction segment ID')
        sid = change['segment_id']
        if sid in ids:
            raise ReaderError('Duplicate correction for one segment')
        ids.add(sid)
        original = segments[sid]['text']
        corrected = change.get('corrected_text')
        if change.get('original') != original:
            raise ReaderError('Correction original must exactly match raw source text')
        if not isinstance(corrected, str) or not corrected.strip() or len(corrected) > 2*len(original)+20:
            raise ReaderError('Correction must retain the source utterance, not summarize or expand it')
        if not isinstance(change.get('reason'), str) or not change['reason'].strip():
            raise ReaderError('Correction requires a reason')
        _evidence(change.get('evidence'), segments, known_paths, directory, data, terms)
        # Relistening must actually cover this utterance, not an unrelated part.
        for item in change['evidence']:
            if item['kind'] == 'relisten':
                job = read_json(directory / 'relistens' / item['job_id'] / 'result.json')
                lo, hi = job['range']['start'], job['range']['end']
                if hi <= segments[sid]['start'] or lo >= segments[sid]['end']:
                    raise ReaderError('Relisten evidence does not overlap the corrected segment')
        edits = [{'start_char': a, 'end_char': b, 'original': original[a:b], 'replacement': corrected[c:d]}
                 for op, a, b, c, d in difflib.SequenceMatcher(None, original, corrected, autojunk=False).get_opcodes()
                 if op != 'equal']
        if edits:
            saved['corrections'][sid] = {**change, 'edits': edits, 'alignment': 'original_segment_times',
                                          'updated_at': time.time()}
        else:
            saved['corrections'].pop(sid, None)  # Explicit retraction is also audited.
    saved.update(revision=saved['revision']+1, terms=terms,
                 reviewed_segment_ids=sorted(set(saved['reviewed_segment_ids']) | set(reviewed) | ids))
    saved['history'].append({'revision': saved['revision'], 'at': time.time(), 'payload': payload})
    write_json(directory / 'reviews' / (snapshot + '.json'), saved)
    _, coverage = overlay(directory, speech, [])
    return {'status': 'committed', 'review': coverage, 'terms': terms,
            **({'review_scope': selected_scope, 'scope_review': scope_coverage(directory, speech, selected_scope, scope_speech)} if selected_scope else {}),
            'storage_path': str(directory / 'reviews' / (snapshot + '.json')),
            'source_content_policy': UNTRUSTED}
