"""One task command contract used by CLI and both MCP adapters."""
from video_reader.common import ReaderError, read_json
from .queue import Queue

ACTIONS=('queue-list','queue-show','queue-add','queue-update','queue-first','queue-history','queue-result',
         'triage-prepare','triage-material','triage-content','triage-submit','triage-show','triage-history',
         'batch-start','batch-next','batch-status','batch-retry')


def execute(reader,action,value='',**options):
    if action not in ACTIONS: raise ReaderError('Unknown task action')
    defaults={'state':None,'query':'','limit':20,'cursor':None,'task':None,'title':'','new_task':False,
        'priority':None,'reason':'','revision':None,'payload':None,'refresh':False,'index':None,
        'offline':False,'complete':False,'assessment':None,'result':None,'sources':None,'source':'auto'}
    if set(options)-set(defaults): raise ReaderError('Unknown task parameters: '+','.join(sorted(set(options)-set(defaults))))
    p={**defaults,**options}
    if action.startswith('batch-'):
        from .batch import Batch
        batch=Batch(reader,offline=p['offline'])
        if action=='batch-start':
            payload=read_json(p['payload']) if p['payload'] else {'sources':p['sources'],'task':p['task'] or '', 'source':p['source']}
            return batch.start(**payload)
        if action=='batch-next': return batch.next(value,p['cursor'])
        if action=='batch-retry': return batch.retry(value,p['index'])
        return batch.status(value)
    queue=Queue.from_settings(reader.config,reader.config_path)
    if action=='queue-list': return queue.list(p['state'] or 'pending',query=p['query'],limit=p['limit'],cursor=p['cursor'])
    if action=='queue-show': return queue.show(value)
    if action=='queue-add': return queue.enqueue(value,p['task'] or '',p['title'],new_task=p['new_task'])
    if action=='queue-history': return queue.history(item_id=value or None,query=p['query'],limit=p['limit'],cursor=p['cursor'])
    if action=='queue-first': return queue.update(value,first=True,reason=p['reason'],expected_revision=p['revision'])
    if action=='queue-update':
        changes=read_json(p['payload']) if p['payload'] else {'state':p['state'],'priority':p['priority'],
            'task':p['task'],'reason':p['reason'],'expected_revision':p['revision']}
        if not isinstance(changes,dict) or set(changes)-{'state','priority','task','reason','expected_revision'}:
            raise ReaderError('Invalid queue update fields')
        return queue.update(value,**changes)
    if action=='queue-result':
        result=read_json(p['payload']) if p['payload'] else p['result']
        return queue.record_result(value,result,complete=p['complete'])
    from .triage import Triage
    triage=Triage(queue,reader)
    if action=='triage-prepare':
        if p['offline']: raise ReaderError('Prepare requires online preview; use triage-content for saved material')
        return triage.prepare(value,refresh=p['refresh'])
    if action=='triage-material': return triage.material(value,p['cursor'])
    if action=='triage-content': return triage.content(value)
    if action=='triage-show': return triage.show(value)
    if action=='triage-history': return triage.history(value,before=p['index'],limit=p['limit'])
    assessment=read_json(p['payload']) if p['payload'] else p['assessment']
    return triage.submit(value,assessment)


def from_namespace(reader,args):
    keys=('state','query','limit','cursor','task','title','new_task','priority','reason','revision','payload',
          'refresh','index','offline','complete')
    if getattr(args,'deliver',False): raise ReaderError('Task operations do not send messages')
    return execute(reader,args.action,args.value,**{k:getattr(args,k) for k in keys if hasattr(args,k)})
