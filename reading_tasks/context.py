"""Accepted evidence and scoped uncertainty history for a single task run."""
import copy

from video_reader.common import ReaderError, digest, read_json


def entries(observation, directory):
    initial = observation
    # Old runs overwrote response with the last supplement. Recover only the
    # explicitly checkpointed attempt, never arbitrary accepted files on disk.
    if observation.get('supplements') and observation.get('context_version') != 2:
        path = directory/'attempts'/observation['attempt_id']/'accepted.json'
        if not path.is_file():
            raise ReaderError('Legacy reading checkpoint is missing its original accepted response; inspect it before resuming')
        initial = {**observation,'response':read_json(path)['response']}
    result = []
    for entry in [initial,*observation.get('supplements',[])]:
        if entry.get('context_version') != 2:
            path = directory/'attempts'/entry['attempt_id']/'packet.json'
            if path.is_file():
                packet = read_json(path)
                entry = {**entry,'ranges':packet.get('ranges',[]),
                    'segment_refs':[{'id':s['segment_id'],'start':s['start'],'end':s['end']}
                        for s in packet.get('segments',[])],
                    'frame_refs':[{key:f.get(key) for key in
                        ('id','timestamp_seconds','time','asset_sha256','precision')}
                        for f in packet.get('frames',[])]}
        result.append(entry)
    return result


def records(entry):
    if 'evidence_records' in entry:
        return entry['evidence_records']
    # Legacy checkpoint notes remain lossless until a new host creates records.
    return [{'id':'ev_'+digest([entry['attempt_id'],'legacy']),
        'text':entry['response']['notes'],'segment_ids':entry.get('segment_ids',[]),
        'frame_ids':entry.get('frame_ids',[]),'ranges':entry.get('ranges',[]),
        'segment_refs':entry.get('segment_refs',[]),'frame_refs':entry.get('frame_refs',[]),'legacy_note':True}]


def issues(entry):
    return entry.get('uncertainty_issues',[{'id':'u_'+digest([entry['attempt_id'],i,text]),
        'text':text,'ranges':entry.get('ranges',[])}
        for i,text in enumerate(entry['response'].get('uncertainties',[]))])


def history(state,directory,extra=()):
    evidence, unresolved = {}, {}
    for observation in [*state['observations'],*extra]:
        for entry in entries(observation,directory):
            evidence.update((record['id'],record) for record in records(entry))
            for issue in issues(entry):
                unresolved[issue['id']] = issue
            for decision in entry.get('uncertainty_decisions',[]):
                if decision['status'] == 'retain':
                    if decision['issue_id'] in unresolved:
                        unresolved[decision['issue_id']] = {**unresolved[decision['issue_id']],
                            'text':decision['text']}
                else:
                    unresolved.pop(decision['issue_id'],None)
    return {'prior_evidence':list(evidence.values()),'uncertainty_ledger':list(unresolved.values())}


def accept(packet,response,attempt_id,kind):
    """Bind new facts and explicit uncertainty decisions to delivered evidence."""
    prior = packet.get('prior_evidence',[])
    segment_refs = {s['segment_id']:{'id':s['segment_id'],'start':s['start'],'end':s['end']}
                    for s in packet.get('segments',[])}
    frame_refs = {f['id']:{key:f.get(key) for key in
                  ('id','timestamp_seconds','time','asset_sha256','precision')}
                  for f in packet.get('frames',[])}
    for record in prior:
        segment_refs.update((ref['id'],ref) for ref in record.get('segment_refs',[]))
        frame_refs.update((ref['id'],ref) for ref in record.get('frame_refs',[]))
    allowed_segments = set(segment_refs) | {sid for record in prior for sid in record['segment_ids']}
    allowed_frames = set(frame_refs) | {fid for record in prior for fid in record['frame_ids']}
    evidence = []
    supplied = response.get('evidence_records',[])
    if not isinstance(supplied,list):
        raise ReaderError('Host evidence_records must be a list')
    for i,record in enumerate(supplied):
        if (not isinstance(record.get('text'),str) or not record['text'].strip()
                or not isinstance(record.get('segment_ids'),list) or not isinstance(record.get('frame_ids'),list)
                or not set(record['segment_ids']) <= allowed_segments or not set(record['frame_ids']) <= allowed_frames
                or not (record['segment_ids'] or record['frame_ids'])):
            raise ReaderError('Host evidence record must reference supplied or previously accepted evidence')
        evidence.append({**copy.deepcopy(record),'id':'ev_'+digest([attempt_id,i,record]),
            'ranges':packet.get('ranges',[]),
            'segment_refs':[segment_refs[s] for s in record['segment_ids'] if s in segment_refs],
            'frame_refs':[frame_refs[f] for f in record['frame_ids'] if f in frame_refs]})
    ledger = {issue['id']:issue for issue in packet.get('uncertainty_ledger',[])}
    known = {record['id'] for record in [*prior,*evidence]}
    decisions, decided = [], set()
    for raw in response.get('uncertainty_decisions',[]):
        decision = copy.deepcopy(raw)
        issue_id = decision.get('issue_id')
        if issue_id not in ledger or issue_id in decided or decision.get('status') not in ('retain','resolved'):
            raise ReaderError('Host uncertainty decision has an unknown/duplicate issue or invalid status')
        if not isinstance(decision.get('reason'),str) or not decision['reason'].strip():
            raise ReaderError('Host uncertainty decision needs a reason')
        ids = []
        for identity in decision.get('evidence_ids',[]):
            if identity.startswith('new:'):
                try:
                    index = int(identity[4:])
                    if index < 0:raise ValueError()
                    identity = evidence[index]['id']
                except (ValueError,IndexError):
                    raise ReaderError('Host uncertainty decision references an unknown new record') from None
            ids.append(identity)
        if decision['status']=='resolved' and (not ids or not set(ids) <= known):
            raise ReaderError('Resolved uncertainty needs accepted supporting evidence records')
        if decision['status']=='retain' and (not isinstance(decision.get('text'),str) or not decision['text'].strip()):
            raise ReaderError('Retained uncertainty needs task-level text')
        decision['evidence_ids'] = ids
        decisions.append(decision)
        decided.add(issue_id)
    if kind=='synthesis' and decided != set(ledger):
        raise ReaderError('Synthesis must account for every unresolved uncertainty')
    return {'context_version':2,'ranges':packet.get('ranges',[]),'evidence_records':evidence,
        'uncertainty_issues':[{'id':'u_'+digest([attempt_id,i,text]),'text':text,
            'ranges':packet.get('ranges',[])} for i,text in enumerate(response.get('uncertainties',[]))],
        'uncertainty_decisions':decisions}


def final_uncertainties(state,directory):
    final = state['final']
    if state.get('final_kind')!='synthesis':
        return list(final['response']['uncertainties'])
    unresolved = history(state,directory)['uncertainty_ledger']
    retained = {issue['id']:issue['text'] for issue in unresolved}
    for decision in final.get('uncertainty_decisions',[]):
        if decision['status']=='retain':
            retained[decision['issue_id']] = decision['text']
        else:
            retained.pop(decision['issue_id'],None)
    return list(dict.fromkeys([*retained.values(),*final['response']['uncertainties']]))
