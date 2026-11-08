"""Opt-in script-only intake/dispatch; understanding stays in the task host."""
import json
import time
from filelock import FileLock, Timeout
from reading_tasks.consume import Consumer
from reading_tasks.control import Controls, ControlWait
from video_reader.common import ReaderError, digest, error_details
from video_reader.resources import sample


ACTIONS=('background-status','background-config','background-pause','background-resume',
         'background-tick','background-intake','background-queue','background-retry','background-hold')


class Background:
    def __init__(self,reader,*,clock=None,probe=None,sync=None):
        self.reader=reader
        self.clock=clock or time.time
        self.control=Controls(reader,clock=self.clock)
        self.consumer=Consumer(reader)
        self.probe=probe or sample
        self.sync=sync or self._sync
        with self.control.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS task_background_runtime(scope TEXT PRIMARY KEY,last_tick REAL,last_sync REAL,last_result TEXT)')
            db.execute('INSERT OR IGNORE INTO task_background_runtime(scope) VALUES(?)',(self.control.scope,))
            columns={r['name'] for r in db.execute('PRAGMA table_info(task_background_runtime)')}
            for column,kind in (('last_intake_tick','REAL'),('last_queue_tick','REAL'),('intake_result','TEXT'),('queue_result','TEXT')):
                if column not in columns:db.execute(f'ALTER TABLE task_background_runtime ADD COLUMN {column} {kind}')
            if 'last_queue_tick' not in columns:
                db.execute('UPDATE task_background_runtime SET last_intake_tick=last_sync,last_queue_tick=last_tick WHERE scope=?',(self.control.scope,))

    def _sync(self,policy):
        from .inbox import Inbox,configured_sender
        return Inbox(self.control.queue,configured_sender(self.reader),config=self.reader.config).sync(
            max_pages=policy['sync_max_pages'],page_size=policy['sync_page_size'])

    def runtime(self):
        with self.control.store.connect() as db:
            row=db.execute('SELECT * FROM task_background_runtime WHERE scope=?',(self.control.scope,)).fetchone()
        result=dict(row)
        for key in ('last_result','intake_result','queue_result'):
            result[key]=json.loads(row[key]) if row[key] else None
        return result

    def _record(self,result,channel,*,ticked=False,synced=False):
        with self.control.store.connect() as db:
            value=json.dumps(result,ensure_ascii=False)
            db.execute(f'UPDATE task_background_runtime SET last_result=?,{channel}_result=?'+
                (f',last_tick=?,last_{channel}_tick=?' if ticked else '')+(',last_sync=?' if synced else '')+' WHERE scope=?',
                (value,value,*([self.clock(),self.clock()] if ticked else []),
                 *([self.clock()] if synced else []),self.control.scope))
        return result

    def status(self):
        slots=self.control.slots()
        retries=[]
        for slot in slots:
            slot['run']=self.consumer.status(slot['run_id']) if slot['run_id'] else None
            if slot['run'] and slot['run']['status']=='failed' and self._transient_host_failure(slot['run']) and slot['host_retries']<self.control.state()['policy']['max_host_retries']:
                retries.append({'run_id':slot['run_id'],'item_id':slot['item_id'],'retries_used':slot['host_retries'],
                    'interval_minutes':self.control.state()['policy']['queue_interval_minutes']})
        pending=self.control.queue.list('pending',limit=100)
        return {**self.control.state(),'usage':self.control.usage(),'runtime':self.runtime(),
            'active':slots,'pending_retries':retries,'pending_count':pending['counts'].get('pending',0),
            'needs_request':[{'item_id':i['id'],'title':i['title']} for i in pending['items'] if not self._request(i)],
            'needs_attention':[{'item_id':i['id'],'title':i['title']} for i in pending['items'] if self._needs_attention(i)],
            'checks_call_model':False,'reading_uses_configured_host':True,'messages_sent':0}

    def _resources(self,policy):
        usage=self.probe()
        if not usage.get('available'): raise ControlWait('resource_probe_unavailable')
        if usage['cpu_percent']>policy['max_cpu_percent']: raise ControlWait('cpu_busy')
        if usage['available_memory_mb']<policy['min_available_memory_mb']: raise ControlWait('memory_low')
        return usage

    def _request(self,item):
        detail=self.control.queue.show(item['id'],include_material=False)
        note=detail['note']
        if note.get('kind') in ('none','comment','uncertain') and not note.get('request'):
            return False
        return bool(item['task'].strip())

    def _needs_attention(self,item):
        with self.consumer.store.connect() as db:
            row=db.execute('SELECT id,status,task_identity,payload FROM task_runs WHERE scope=? AND item_id=? ORDER BY created DESC LIMIT 1',
                           (self.control.scope,item['id'])).fetchone()
            if row and row['status']=='failed' and self._transient_host_failure(json.loads(row['payload'])):
                slot=db.execute("SELECT host_retries FROM task_background_slots WHERE scope=? AND run_id=? AND status IN ('active','waiting')",(self.control.scope,row['id'])).fetchone()
                if slot and slot['host_retries']<self.control.state()['policy']['max_host_retries']:return False
        return bool(row and row['status'] in ('failed','needs_attention') and row['task_identity']==digest([item['canonical'],item['task']]))

    def _start(self,item,token):
        with self.consumer.store.connect() as db:
            prior=db.execute('SELECT task_identity FROM task_runs WHERE scope=? AND item_id=? ORDER BY created DESC LIMIT 1',
                             (self.control.scope,item['id'])).fetchone()
        changed=bool(prior and prior['task_identity']!=digest([item['canonical'],item['task']]))
        return self.consumer.start(item['id'],background_token=token,wait_seconds=0,refresh=changed)

    def _recover_reserved(self,slot):
        with self.consumer.store.connect() as db:
            rows=db.execute('SELECT id,payload FROM task_runs WHERE scope=? AND item_id=? ORDER BY created DESC',
                            (self.control.scope,slot['item_id'])).fetchall()
        for row in rows:
            state=json.loads(row['payload'])
            if state.get('background_token')==slot['token']:
                self.control.bind(slot['token'],{**state,'run_id':row['id']})
                return row['id']
        return None

    def tick(self,*,force=False):
        # Compatibility orchestration: an intake error never gates the local queue.
        intake=self.intake(force=force)
        queue=self.consume(force=force)
        return {**queue,'intake':intake}

    def intake(self,*,force=False):return self._channel('intake',force)

    def consume(self,*,force=False):return self._channel('queue',force)

    def _channel(self,channel,force):
        if type(force) is not bool: raise ReaderError('force must be boolean')
        lock=self.control.store.path.with_name(self.control.store.path.name+'.background-'+digest(self.control.scope)+'.'+channel+'.lock')
        try:
            with FileLock(str(lock),timeout=0):return self._tick(channel,force)
        except Timeout:
            return {'status':'waiting','reason':'another_tick_active','channel':channel,'messages_sent':0}

    def _tick(self,channel,force):
        synced=False;ticked=False
        try:
            policy=self.control.basic_guard(reading=False)
            last=self.runtime()['last_'+channel+'_tick']
            # Scheduler launches have subsecond jitter; minute schedules use minute boundaries.
            if not force and last is not None and int(self.clock()//60)-int(last//60)<policy[channel+'_interval_minutes']:
                return {'status':'waiting','reason':'interval_not_due','channel':channel,'messages_sent':0}
            ticked=True
            if channel=='intake':
                if not policy['sync_enabled']:raise ControlWait('intake_disabled')
                intake=self.sync(policy)
                synced=True
                ready=(intake.get('feed') or {}).get('status') in (None,'ready','partial')
                return self._record({'status':'synced' if ready else 'waiting','reason':None if ready else 'intake_unavailable',
                    'intake':intake,'channel':channel,'messages_sent':0},channel,ticked=True,synced=True)
            policy=self.control.basic_guard()
            result=self._queue(policy)
            return self._record({**result,'channel':channel},channel,ticked=True)
        except ControlWait as error:
            return self._record({'status':'waiting','reason':error.reason,'channel':channel,'messages_sent':0},channel,ticked=ticked,synced=synced)
        except (ReaderError,OSError,ValueError) as error:
            return self._record({'status':'failed','error':error_details(error),'channel':channel,'messages_sent':0},channel,ticked=ticked,synced=synced)

    @staticmethod
    def _transient_host_failure(state):
        return (state.get('error') or {}).get('category') in ('host_timeout','host_transport')

    def _queue(self,policy):
        slots=self.control.slots()
        resource=self._resources(policy)
        if slots:
            slot=slots[0]
            run_id=slot['run_id'] or self._recover_reserved(slot)
            if run_id:
                state=self.consumer.status(run_id)
                if state['status']=='completed':
                    self.control.mark(slot['token'],'completed')
                elif state['status']=='needs_attention':
                    self.control.mark(slot['token'],'failed')
                elif state['status']=='superseded':
                    self.control.mark(slot['token'],'abandoned')
                elif state['status'] in ('failed','interrupted','waiting'):
                    actual=self.consumer.load(run_id)
                    try:self.consumer._verify_task(actual)
                    except ControlWait:raise
                    except ReaderError:
                        self.control.mark(slot['token'],'abandoned')
                        return {'status':'waiting','reason':'task_changed_or_not_pending','run_id':run_id,'messages_sent':0}
                    if state['status']=='failed':
                        if self._transient_host_failure(state) and slot['host_retries']<policy['max_host_retries']:
                            finished=(state.get('job') or {}).get('finished_at')
                            if finished is None:
                                with self.consumer.store.connect() as db:
                                    finished=db.execute('SELECT updated FROM task_runs WHERE scope=? AND id=?',(self.control.scope,run_id)).fetchone()[0]
                            if int(self.clock()//60)-int(finished//60)<policy['queue_interval_minutes']:
                                return {'status':'waiting','reason':'host_retry_backoff','run':state,'messages_sent':0}
                            self.control.host_retry(slot['token'])
                            resumed=self.consumer.resume(run_id,wait_seconds=0)
                            return {'status':'retried','run':resumed,'retry':slot['host_retries']+1,'resources':resource,'messages_sent':0}
                        self.control.mark(slot['token'],'failed')
                        return {'status':'failed','reason':'host_retry_limit' if self._transient_host_failure(state) else 'inspect_run_error','run':state,'messages_sent':0}
                    if state['status']=='interrupted':self.control.interrupted_resume(slot['token'])
                    resumed=self.consumer.resume(run_id,wait_seconds=0)
                    self.control.mark(slot['token'],'active')
                    return {'status':'resumed','run':resumed,'resources':resource,'messages_sent':0}
                else:
                    return {'status':'running','run':state,'messages_sent':0}
            else:
                if self.control.foreground_job():raise ControlWait('foreground_job')
                item=self.control.queue.show(slot['item_id'],include_material=False)
                if item['state']!='pending' or not self._request(item):
                    self.control.mark(slot['token'],'abandoned')
                else:
                    started=self._start(item,slot['token'])
                    return {'status':'started','run':started,'messages_sent':0}
        if self.control.foreground_job():raise ControlWait('foreground_job')
        cursor=None; skipped=[];attention=[]
        while True:
            page=self.control.queue.list('pending',limit=100,cursor=cursor)
            for item in page['items']:
                if self._needs_attention(item):
                    attention.append(item['id']);continue
                if not self._request(item):
                    skipped.append(item['id']);continue
                token=self.control.reserve_task(item['id'])
                try:started=self._start(item,token)
                except BaseException:
                    self.control.mark(token,'abandoned');raise
                return {'status':'started','run':started,'resources':resource,
                    'skipped_without_request':skipped,'messages_sent':0}
            cursor=page['next_cursor']
            if not cursor:break
        return {'status':'idle','reason':'needs_attention' if attention else 'needs_request' if skipped else 'queue_empty',
            'skipped_without_request':skipped,'needs_attention':attention,'messages_sent':0}

    def retry(self,run_id):
        """Explicitly retry the original failed task without any Inbox operation."""
        lock=self.control.store.path.with_name(self.control.store.path.name+'.background-'+digest(self.control.scope)+'.queue.lock')
        with FileLock(str(lock),timeout=0):
            self.control.basic_guard()
            state=self.consumer.load(run_id)
            if state['status']!='failed' or not state.get('background_token'):
                raise ReaderError('Explicit background retry requires a failed background run')
            original=next((s for s in self.control.slots(active_only=False) if s['token']==state['background_token']),None)
            if not original:raise ReaderError('Original background permit is missing')
            self._resources(self.control.state()['policy'])
            self.control.host_retry(original['token'],automatic=False)
            try:
                resumed=self.consumer.resume(run_id,wait_seconds=0)
            except BaseException:
                self.control.mark(original['token'],original['status']);raise
            return {'status':'retried','run':resumed,'messages_sent':0,'intake_checked':False}


def dispatch(reader,action,parameters=None):
    parameters=parameters or {}
    if not isinstance(parameters,dict):raise ReaderError('Background parameters must be an object')
    background=Background(reader)
    if action=='background-config':return background.control.configure(parameters)
    if action=='background-pause':return background.control.pause()
    if action=='background-resume':return background.control.resume()
    if action=='background-hold':return background.control.hold(**parameters)
    if action=='background-tick':return background.tick(**parameters)
    if action=='background-intake':return background.intake(**parameters)
    if action=='background-queue':return background.consume(**parameters)
    if action=='background-retry':return background.retry(**parameters)
    if action=='background-status':return background.status()
    raise ReaderError('Unknown background action')
