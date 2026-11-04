"""Read task records into a receipt/triage report, then optionally use authorized delivery."""
from pathlib import Path

from reading_tasks.queue import Queue
from reading_tasks.triage import Triage
from video_reader.common import ReaderError,digest
from video_reader.platform import Platform
from .memory import Memory
from .delivery import ENDPOINT,send_message


def build(reader,*,item_ids=None,message_id=None,limit=20):
    if item_ids is not None and (not isinstance(item_ids,list) or any(not isinstance(v,str) for v in item_ids)):
        raise ReaderError('item_ids must be a list of task IDs')
    if type(limit) is not int or not 1<=limit<=100: raise ReaderError('limit must be 1..100')
    queue=Queue.from_settings(reader.config,reader.config_path)
    triage=Triage(queue,reader)
    if item_ids is not None:
        items=[queue.show(item_id,include_material=False) for item_id in item_ids]
    else:
        items=[]; cursor=None
        while True:
            page=queue.list('all',limit=100,cursor=cursor)
            items.extend(queue.show(row['id'],include_material=False) for row in page['items'])
            cursor=page['next_cursor']
            if not cursor: break
        if message_id: items=[row for row in items if any(m['id']==message_id for m in row['messages'])]
        items=items[:limit]
    entries=[]
    for item in items:
        saved=triage.show(item['id'])
        initial=saved['status']
        result=item.get('latest_result')
        entries.append({'item_id':item['id'],'source':item['canonical'],'title':(result or {}).get('title') or item['title'] or item['canonical'].split('/')[-1].split('?')[0],
            'enqueued':True,'state':item['state'],'initial_triage':initial,'triage_stale':saved.get('stale',False),
            'type':(saved.get('assessment') or {}).get('content_type'),
            'scheme':((saved.get('assessment') or {}).get('recommendation') or {}).get('title'),
            'result':result,'revision':item['revision'],'assessment_updated':saved.get('updated_at')})
    states={'pending':'待办','paused':'暂停','done':'已完成','cancelled':'已取消','archived':'已归档'}
    routing={'suggested':'有建议','awaiting_user':'等待用户','undetermined':'待定','prepared':'待判断','unprepared':'尚未粗读'}
    text='队列汇报：'+str(len(entries))+' 项。'
    if message_id and not entries: text='本地尚未找到这条消息关联的队列任务。'
    for i,row in enumerate(entries,1):
        label=row['title'][:18]
        line=f"\n{i}. {label}：{states[row['state']]}；初分流{routing.get(row['initial_triage'],row['initial_triage'])}"
        if row['triage_stale']: line+='（旧判断）'
        if row['result']: line+='；结果已保存'
        if len(text+line)>425:
            text+='\n其余详见会话中的队列记录。'
            break
        text+=line
    key='task-report:'+digest([queue.scope,message_id,entries])
    return {'report_id':key,'library_id':queue.scope,'message_id':message_id,'enqueued':bool(entries),
            'entries':entries,'text':text,'messages_sent':0,'automatic_send':False}


def send(reader,report,*,platform=None,memory=None):
    delivery=reader.config['agent']['delivery']
    if not delivery.get('enabled'): raise ReaderError('Private delivery is not enabled')
    platform=platform or Platform(reader.config,write_endpoints=(ENDPOINT,))
    memory=memory or Memory((reader.config_path.parent/reader.config['agent']['directory']).resolve(),platform.scope)
    result=send_message(platform,memory,delivery['recipient_uid'],report['text'],[report['report_id']])
    return {**report,'delivery':result,'messages_sent':1 if result['status']=='accepted_not_receipt_verified' else 0}
