"""Durable opt-in background permits; manual reading remains independent."""
from datetime import datetime, timedelta, timezone
import json
import re
import time
import uuid

from video_reader.common import ReaderError
from video_reader.resources import sample
from .queue import Queue


DEFAULTS = {
    'enabled': False, 'sync_enabled': True, 'read_enabled': True,
    'window_start': '09:00', 'window_end': '23:00', 'timezone_offset_minutes': 480,
    'intake_interval_minutes': 60, 'queue_interval_minutes': 5,
    'max_host_retries': 2, 'daily_task_limit': 0, 'daily_host_call_limit': 60,
    'per_run_host_call_limit': 20, 'max_interrupted_resumes': 2,
    'max_cpu_percent': 85, 'min_available_memory_mb': 2048,
    'sync_max_pages': 3, 'sync_page_size': 50,
}


class ControlWait(ReaderError):
    code = 'BACKGROUND_WAIT'

    def __init__(self, reason):
        self.reason = reason
        self.details = {'reason':reason}
        super().__init__('Background task waiting: '+reason)


def local_time(policy, now):
    return datetime.fromtimestamp(now, timezone(timedelta(minutes=policy['timezone_offset_minutes'])))


def in_window(policy, now):
    current = local_time(policy, now).strftime('%H:%M')
    start, end = policy['window_start'], policy['window_end']
    return start <= current < end if start < end else current >= start or current < end if start > end else True


def validate(policy):
    for key in ('enabled', 'sync_enabled', 'read_enabled'):
        if type(policy[key]) is not bool: raise ReaderError(key+' must be boolean')
    for key in ('window_start', 'window_end'):
        if not isinstance(policy[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', policy[key]):
            raise ReaderError(key+' must be HH:MM')
    ranges = {'timezone_offset_minutes': (-840, 840), 'intake_interval_minutes': (1, 1440),
        'queue_interval_minutes': (1, 1440), 'max_host_retries': (0, 10),
        'daily_task_limit': (0, 100), 'daily_host_call_limit': (0, 1000),
        'per_run_host_call_limit': (1, 200), 'max_interrupted_resumes': (0, 10),
        'max_cpu_percent': (1, 100), 'min_available_memory_mb': (0, 1048576),
        'sync_max_pages': (1, 10), 'sync_page_size': (1, 100)}
    for key, (lo, hi) in ranges.items():
        if type(policy[key]) is not int or not lo <= policy[key] <= hi:
            raise ReaderError(f'{key} must be an integer in {lo}..{hi}')


class Controls:
    def __init__(self, reader, *, clock=None):
        self.reader = reader
        self.queue = Queue.from_settings(reader.config, reader.config_path)
        self.store, self.scope = self.queue.store, self.queue.scope
        self.clock = clock or time.time
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS task_background_control(
                    scope TEXT PRIMARY KEY,policy TEXT NOT NULL,paused_reason TEXT,hold_until REAL NOT NULL DEFAULT 0,
                    epoch INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS task_background_slots(
                    token TEXT PRIMARY KEY,scope TEXT NOT NULL,item_id TEXT NOT NULL,run_id TEXT,
                    day TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,resumes INTEGER NOT NULL DEFAULT 0,
                    host_retries INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS task_background_attempts(
                    id INTEGER PRIMARY KEY,scope TEXT NOT NULL,token TEXT NOT NULL,day TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS task_background_events(
                    id INTEGER PRIMARY KEY,scope TEXT NOT NULL,created REAL NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
            ''')
            if 'epoch' not in {r['name'] for r in db.execute('PRAGMA table_info(task_background_control)')}:
                db.execute('ALTER TABLE task_background_control ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0')
            if 'host_retries' not in {r['name'] for r in db.execute('PRAGMA table_info(task_background_slots)')}:
                db.execute('ALTER TABLE task_background_slots ADD COLUMN host_retries INTEGER NOT NULL DEFAULT 0')
            db.execute('INSERT OR IGNORE INTO task_background_control(scope,policy) VALUES(?,?)',
                       (self.scope,json.dumps(DEFAULTS)))
            row=db.execute('SELECT policy FROM task_background_control WHERE scope=?',(self.scope,)).fetchone()
            saved=json.loads(row['policy'])
            legacy=saved.pop('interval_minutes',None)
            if legacy is not None:
                saved.setdefault('intake_interval_minutes',legacy)
                saved.setdefault('queue_interval_minutes',legacy)
            migrated={**DEFAULTS,**saved}
            if migrated!=json.loads(row['policy']):
                db.execute('UPDATE task_background_control SET policy=? WHERE scope=?',(json.dumps(migrated),self.scope))

    def _event(self, db, kind, **payload):
        db.execute('INSERT INTO task_background_events(scope,created,kind,payload) VALUES(?,?,?,?)',
                   (self.scope,self.clock(),kind,json.dumps(payload,ensure_ascii=False)))

    def state(self):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM task_background_control WHERE scope=?',(self.scope,)).fetchone()
        return {'policy':json.loads(row['policy']), 'paused_reason':row['paused_reason'], 'hold_until':row['hold_until'],'epoch':row['epoch']}

    def configure(self, changes):
        if not isinstance(changes,dict) or set(changes)-(DEFAULTS.keys()|{'interval_minutes'}):
            raise ReaderError('Unknown background policy fields')
        changes=dict(changes)
        if 'interval_minutes' in changes:
            if {'intake_interval_minutes','queue_interval_minutes'} & changes.keys():
                raise ReaderError('Use the legacy interval alias or separate intervals, not both')
            legacy=changes.pop('interval_minutes')
            changes.update(intake_interval_minutes=legacy,queue_interval_minutes=legacy)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = json.loads(db.execute('SELECT policy FROM task_background_control WHERE scope=?',(self.scope,)).fetchone()[0])
            policy = {**old,**changes}
            validate(policy)
            invalidates=(old['enabled'] and not policy['enabled']) or (old['read_enabled'] and not policy['read_enabled'])
            db.execute('UPDATE task_background_control SET policy=?,epoch=epoch+? WHERE scope=?',(json.dumps(policy),int(invalidates),self.scope))
            self._event(db,'policy_changed',changes=changes)
        return self.state()

    def pause(self, reason='user_paused'):
        with self.store.connect() as db:
            db.execute('UPDATE task_background_control SET paused_reason=?,epoch=epoch+1 WHERE scope=?',(reason,self.scope))
            self._event(db,'paused',reason=reason)
        return self.state()

    def resume(self):
        with self.store.connect() as db:
            db.execute('UPDATE task_background_control SET paused_reason=NULL WHERE scope=?',(self.scope,))
            self._event(db,'resumed')
        return self.state()

    def hold(self, minutes):
        if type(minutes) is not int or not 0 <= minutes <= 1440: raise ReaderError('Hold minutes must be 0..1440')
        with self.store.connect() as db:
            db.execute('UPDATE task_background_control SET hold_until=?,epoch=epoch+? WHERE scope=?',
                       (self.clock()+minutes*60 if minutes else 0,int(minutes>0),self.scope))
            self._event(db,'foreground_hold',minutes=minutes)
        return self.state()

    def usage(self):
        day = local_time(self.state()['policy'],self.clock()).date().isoformat()
        with self.store.connect() as db:
            tasks=db.execute('SELECT count(*) FROM task_background_slots WHERE scope=? AND day=?',(self.scope,day)).fetchone()[0]
            calls=db.execute('SELECT count(*) FROM task_background_attempts WHERE scope=? AND day=?',(self.scope,day)).fetchone()[0]
        return {'day':day,'tasks_started':tasks,'host_attempts':calls,'provider_remaining_quota':'unknown',
                'allowance_source':'explicit_local_limits','attempts_are_not_billed_tokens':True}

    def basic_guard(self, *, reading=True):
        state=self.state(); p=state['policy']
        if not p['enabled']: raise ControlWait('disabled')
        if state['paused_reason'] and (reading or state['paused_reason']!='model_quota'):
            raise ControlWait(state['paused_reason'])
        if not in_window(p,self.clock()): raise ControlWait('outside_window')
        if reading and not p['read_enabled']: raise ControlWait('reading_disabled')
        if reading and state['hold_until'] > self.clock(): raise ControlWait('foreground_hold')
        return p

    def foreground_job(self, own_job=None):
        jobs = self.reader.active_jobs(exclude=[own_job] if own_job else [])
        return jobs[0]['job_id'] if jobs else None

    def reserve_task(self,item_id):
        p=self.basic_guard()
        day=local_time(p,self.clock()).date().isoformat()
        token='bg_'+uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute("SELECT token FROM task_background_slots WHERE scope=? AND status IN ('reserved','active','waiting')",(self.scope,)).fetchone()
            if active: raise ControlWait('background_run_active')
            count=db.execute('SELECT count(*) FROM task_background_slots WHERE scope=? AND day=?',(self.scope,day)).fetchone()[0]
            if not p['daily_task_limit'] or count>=p['daily_task_limit']: raise ControlWait('daily_task_limit')
            db.execute('INSERT INTO task_background_slots(token,scope,item_id,day,status,created) VALUES(?,?,?,?,?,?)',
                       (token,self.scope,item_id,day,'reserved',self.clock()))
            self._event(db,'task_reserved',token=token,item_id=item_id)
        return token

    def bind(self,token,state):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM task_background_slots WHERE token=? AND scope=?',(token,self.scope)).fetchone()
            if not row or row['item_id']!=state['item_id'] or row['run_id'] not in (None,state['run_id']):
                raise ReaderError('Background permit does not belong to this task/run')
            if state.get('permit_token',state.get('background_token'))!=token:
                raise ReaderError('Task run has a different execution permit')
            day=row['day']
            if row['run_id'] is None:
                policy=json.loads(db.execute('SELECT policy FROM task_background_control WHERE scope=?',(self.scope,)).fetchone()[0])
                today=local_time(policy,self.clock()).date().isoformat()
                if today!=day:
                    count=db.execute('SELECT count(*) FROM task_background_slots WHERE scope=? AND day=?',(self.scope,today)).fetchone()[0]
                    if not policy['daily_task_limit'] or count>=policy['daily_task_limit']:raise ControlWait('daily_task_limit')
                    day=today
            db.execute("UPDATE task_background_slots SET run_id=?,day=?,status='active' WHERE token=?",(state['run_id'],day,token))

    def guard(self,state,*,reserve_host=False,check_resources=True,expected_epoch=None):
        p=self.basic_guard()
        if expected_epoch is not None and self.state()['epoch']!=expected_epoch:
            raise ControlWait('control_changed_during_host')
        token=state.get('background_token')
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM task_background_slots WHERE scope=? AND token=?',(self.scope,token)).fetchone()
        if not row or row['run_id']!=state['run_id'] or row['status'] not in ('active','waiting'):
            raise ReaderError('Background permit is missing or no longer active')
        if self.foreground_job(state.get('job_id')): raise ControlWait('foreground_job')
        if check_resources:
            resource=sample()
            if not resource.get('available'):raise ControlWait('resource_probe_unavailable')
            if resource['cpu_percent']>p['max_cpu_percent']:raise ControlWait('cpu_busy')
            if resource['available_memory_mb']<p['min_available_memory_mb']:raise ControlWait('memory_low')
        if reserve_host:
            day=local_time(p,self.clock()).date().isoformat()
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                daily=db.execute('SELECT count(*) FROM task_background_attempts WHERE scope=? AND day=?',(self.scope,day)).fetchone()[0]
                run=db.execute('SELECT count(*) FROM task_background_attempts WHERE scope=? AND token=?',(self.scope,token)).fetchone()[0]
                if not p['daily_host_call_limit'] or daily>=p['daily_host_call_limit']: raise ControlWait('daily_host_call_limit')
                if run>=p['per_run_host_call_limit']: raise ControlWait('run_host_call_limit')
                db.execute('INSERT INTO task_background_attempts(scope,token,day,created) VALUES(?,?,?,?)',
                           (self.scope,token,day,self.clock()))
                self._event(db,'host_attempt_reserved',token=token)

    def slots(self,active_only=True):
        with self.store.connect() as db:
            rows=db.execute('SELECT * FROM task_background_slots WHERE scope=?'+
                (" AND status IN ('reserved','active','waiting')" if active_only else '')+' ORDER BY created', (self.scope,)).fetchall()
        return [dict(r) for r in rows]

    def permit_for_run(self, run_id, *, active_only=True):
        return next((slot for slot in self.slots(active_only) if slot['run_id']==run_id),None)

    def mark(self,token,status):
        if status not in ('active','waiting','completed','failed','abandoned'): raise ReaderError('Invalid permit state')
        with self.store.connect() as db:
            db.execute('UPDATE task_background_slots SET status=? WHERE scope=? AND token=?',(status,self.scope,token))
            self._event(db,'permit_state',token=token,status=status)

    def interrupted_resume(self,token):
        p=self.state()['policy']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT resumes FROM task_background_slots WHERE scope=? AND token=?',(self.scope,token)).fetchone()
            if not row or row[0]>=p['max_interrupted_resumes']: raise ControlWait('interrupted_resume_limit')
            db.execute('UPDATE task_background_slots SET resumes=resumes+1 WHERE scope=? AND token=?',(self.scope,token))
            self._event(db,'interrupted_resume',token=token)

    def host_retry(self,token,*,automatic=True):
        p=self.basic_guard()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM task_background_slots WHERE scope=? AND token=?',(self.scope,token)).fetchone()
            if not row:raise ReaderError('Original background permit is missing')
            if automatic and row['host_retries']>=p['max_host_retries']:raise ControlWait('host_retry_limit')
            other=db.execute("SELECT token FROM task_background_slots WHERE scope=? AND token!=? AND status IN ('reserved','active','waiting')",(self.scope,token)).fetchone()
            if other:raise ControlWait('background_run_active')
            db.execute("UPDATE task_background_slots SET host_retries=host_retries+?,status='active' WHERE token=?",(int(automatic),token))
            self._event(db,'host_retry' if automatic else 'explicit_host_retry',token=token)
