"""Local attempt measurements. Attachments and CLI usage are not model request traces."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

from PIL import Image

from video_reader.common import read_json, write_json


TOKEN_FIELDS = ('input_tokens','cached_input_tokens','output_tokens')


def reported_usage(path):
    turns = []
    if Path(path).is_file():
        with Path(path).open(encoding='utf-8',errors='replace') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event,dict) or event.get('type') != 'turn.completed':
                    continue
                usage = event.get('usage')
                usage = usage if isinstance(usage,dict) else {}
                turns.append({key:usage.get(key) if type(usage.get(key)) is int and usage[key]>=0 else None
                              for key in TOKEN_FIELDS})
    return {'reported_turns':len(turns),'reported_usage':{
        key:sum(t[key] for t in turns if t[key] is not None) if any(t[key] is not None for t in turns) else None
        for key in TOKEN_FIELDS},
        'usage_complete':bool(turns) and all(t[key] is not None for t in turns for key in TOKEN_FIELDS)}


@contextmanager
def attempt(directory,attempt_id,packet,kind,prompt,options):
    frames = []
    for frame in packet.get('frames',[]):
        path = Path(frame['path'])
        with Image.open(path) as img:
            width,height = img.size
        frames.append({'id':frame['id'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'width':width,'height':height,'bytes':path.stat().st_size})
    record = {'attempt_id':attempt_id,'packet_id':packet['packet_id'],'kind':kind,
        'started_at':time.time(),'status':'started','elapsed_seconds':None,
        'prompt_characters':len(prompt),'prompt_bytes':len(prompt.encode('utf-8')),
        'configured_model':options.get('model'),'images':frames,
        'model_request_count':None,'model_context_image_occurrences':None,
        'reported_usage':{key:None for key in TOKEN_FIELDS},'usage_complete':False,'reported_turns':0}
    path = Path(directory)/'metrics.json'
    write_json(path,record)
    started = time.monotonic()
    try:
        yield
    except BaseException as error:
        record.update(status='failed',error_type=type(error).__name__)
        raise
    else:
        record['status'] = 'returned'
    finally:
        record.update(elapsed_seconds=time.monotonic()-started,**reported_usage(Path(directory)/'host.log'))
        write_json(path,record)


def summary(directory,state):
    records = [read_json(path) for path in sorted(Path(directory).glob('attempts/*/metrics.json'))]
    unmeasured = sum(not (path.parent/'metrics.json').is_file()
                     for path in Path(directory).glob('attempts/*/packet.json'))
    counts = {}
    for record in records:
        counts[record['packet_id']] = counts.get(record['packet_id'],0)+1
    observations = state.get('observations',[])
    accepted = [o for entry in observations for o in [entry,*entry.get('supplements',[])]]
    if state.get('final_kind')=='synthesis' and state.get('final'):
        accepted.append(state['final'])
    accepted_times = [o['accepted_at'] for o in accepted if o.get('accepted_at') is not None]
    images = [f for record in records for f in record['images']]
    elapsed = [r['elapsed_seconds'] for r in records if r['elapsed_seconds'] is not None]
    return {'scope':'local_host_attempts_not_model_request_trace',
        'attempt_count':len(records),'returned_attempts':sum(r['status']=='returned' for r in records),
        'unmeasured_attempts':unmeasured,
        'failed_attempts':sum(r['status']=='failed' for r in records),
        'unfinished_attempts':sum(r['status']=='started' for r in records),
        'accepted_response_count':len(accepted),
        'repeated_packet_attempts':sum(n-1 for n in counts.values()),
        'host_elapsed_seconds':sum(elapsed) if elapsed else None,
        'host_elapsed_complete':bool(records) and not unmeasured and all(r['elapsed_seconds'] is not None for r in records),
        'preparation_elapsed_seconds':state.get('preparation_elapsed_seconds'),
        'run_elapsed_seconds':max(0,state.get('finished_at',time.time())-state['created_at']),
        'first_accepted_packet_seconds':max(0,min(accepted_times)-state['created_at']) if accepted_times else None,
        'first_usable_answer_seconds':None,
        'prompt_bytes':sum(r['prompt_bytes'] for r in records),
        'image_attachments':len(images),'unique_image_sha256':len({f['sha256'] for f in images}),
        'image_attachment_bytes':sum(f['bytes'] for f in images),
        'reported_usage':{key:sum(r['reported_usage'][key] for r in records if r['reported_usage'][key] is not None)
            if any(r['reported_usage'][key] is not None for r in records) else None for key in TOKEN_FIELDS},
        'usage_complete':bool(records) and not unmeasured and all(r['usage_complete'] and r['status']=='returned' for r in records),
        'model_request_count':None,'model_context_image_occurrences':None,
        'attempt_records':str(Path(directory)/'attempts')}
