"""Component-owned local jobs shared by CLI/MCP; status never takes a media lock."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from filelock import FileLock, Timeout
from .common import ReaderError, digest, read_json, write_json

CURRENT = ContextVar('video_reader_job', default=None)
TERMINAL = {'completed', 'failed', 'interrupted'}
OPERATIONS = {'open', 'read', 'transcript', 'continue_read', 'content', 'consume_task'}


def execution_identity(reader):
    """Bind a request and its worker to the same effective config/account."""
    from .bilibili_auth import BilibiliAuth
    account = BilibiliAuth(reader.config).account_scope()
    return digest({'config': reader.config, 'account': account})


def report(stage=None, **details):
    job = CURRENT.get()
    if job:
        job.update(stage, **details)


@contextmanager
def resource_lock(directory, kind='session', timeout=600):
    lock = FileLock(str(directory / '.lock'), timeout=timeout)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        waiting = {'kind': kind+'_lock'}
        if kind == 'session':
            waiting['session_id'] = directory.name
        report('waiting_for_'+kind+'_lock', waiting_for=waiting,
               **({'session_id': directory.name} if kind == 'session' else {}))
        lock.acquire(timeout=timeout)
    try:
        report('checking_account' if kind == 'account' else 'reading_material', waiting_for=None,
               **({'session_id': directory.name} if kind == 'session' else {}))
        yield
    finally:
        lock.release()


session_lock = resource_lock


class Jobs:
    def __init__(self, reader):
        self.reader = reader
        self.root = reader.cache / '_jobs'
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, job_id):
        import re
        if not isinstance(job_id, str) or not re.fullmatch(r'j_[a-f0-9]{24}', job_id):
            raise ReaderError('Invalid Reader job id')
        return self.root / (job_id + '.json')

    def status(self, job_id):
        self.path(job_id)  # Validate before constructing either lock pathname.
        # Serialize observers only. Otherwise an observer probing a free owner
        # lock can be mistaken for a worker by a simultaneous status query.
        with FileLock(str(self.root / (job_id + '.status.lock')), timeout=2):
            return self._status(job_id)

    def write_state(self, job_id, value):
        self.path(job_id)
        # Windows may deny opening/replacing a file during an overlapping
        # atomic replacement. Observers and writers share this short IO lock;
        # it never guards video processing or waits for the media lock.
        with FileLock(str(self.root / (job_id + '.status.lock')), timeout=10):
            write_json(self.path(job_id), value)

    def _status(self, job_id):
        path = self.path(job_id)
        if not path.is_file():
            raise ReaderError('Reader job not found in this component cache')
        now = time.time()
        owner = FileLock(str(self.root / (job_id + '.owner.lock')))
        try:
            owner.acquire(timeout=0)
        except Timeout:
            alive = True
            value = read_json(path)
        else:
            try:
                # Snapshot while holding the free ownership lock: a delayed
                # startup cannot race this observation and look interrupted.
                value = read_json(path)
                alive = False
            finally:
                owner.release()
        # A just-enqueued worker may not have acquired its ownership lock yet.
        if value['status'] not in TERMINAL and not alive and now-value['created_at'] > 10:
            if value['status'] == 'queued':
                value = {**value, 'status': 'unknown', 'stage': 'worker_not_observed',
                         'uncertainty': 'Worker ownership has not been observed; startup may be delayed. No automatic restart.'}
            elif value['status'] not in TERMINAL:
                value = {**value, 'status': 'interrupted', 'stage': 'worker_unavailable',
                         'error': {'type': 'WorkerUnavailable', 'message': 'Worker no longer owns this job; no automatic restart.'}}
        value['worker_alive'] = None if not alive and value['status'] in ('queued', 'unknown') else alive
        value['elapsed_seconds'] = round((value.get('finished_at') or now)-value['created_at'], 3)
        value['heartbeat_age_seconds'] = round(max(0, now-value['heartbeat_at']), 3)
        value['progress_age_seconds'] = round(max(0, now-value['progress_at']), 3)
        value['stage_elapsed_seconds'] = round(max(0, (value.get('finished_at') or now)-value['stage_started_at']), 3)
        value['next_action'] = ('inspect_worker' if value['status'] == 'unknown' else
                                'result' if value['status'] == 'completed' else
                                'inspect_error' if value['status'] in TERMINAL else 'poll')
        # Parameters may contain user material and stay in the private job file.
        return {k: v for k, v in value.items() if k not in ('parameters', 'config_identity')}

    def start(self, operation, parameters, wait_seconds=1):
        if operation not in OPERATIONS or not isinstance(parameters, dict):
            raise ReaderError('Jobs support open/read/transcript/continue_read/consume_task with a parameters object')
        parameters = dict(parameters)
        if 'session_id' in parameters:
            if 'session' in parameters:
                raise ReaderError('Use session_id or session, not both')
            parameters['session'] = parameters.pop('session_id')
        method = getattr(self.reader, operation)
        try:
            bound = inspect.signature(method).bind(**parameters)
        except TypeError as exc:
            raise ReaderError(str(exc)) from None
        bound.apply_defaults()
        parameters = dict(bound.arguments)
        if parameters.get('speech_profile') is None:
            parameters.pop('speech_profile', None)
        source_identity = None
        if operation in ('read','transcript','continue_read'):
            self.reader.directory(parameters['session'])
        elif operation == 'open':
            from .sources import resolve
            resolved = resolve(parameters['source'], parameters.get('subtitles'))
            parameters['source'] = resolved['canonical']
            source_identity = resolved['identity']
        self._wait_value(wait_seconds)
        # Config and current account isolate active requests. Never persist tokens.
        identity = execution_identity(self.reader)
        key = digest({'operation': operation, 'parameters': parameters, 'config_identity': identity,
                      'source_identity': source_identity})
        with FileLock(str(self.root / '.index.lock'), timeout=10):
            index_path = self.root / 'active.json'
            active = read_json(index_path) if index_path.is_file() else {}
            previous = active.get(key)
            if previous and self.path(previous).is_file() and self.status(previous)['status'] not in TERMINAL:
                job_id = previous
                reused = True
            else:
                job_id = 'j_' + uuid.uuid4().hex[:24]
                now = time.time()
                value = {'schema_version': 1, 'job_id': job_id, 'operation': operation,
                         'parameters': parameters, 'config_identity': identity,
                         'status': 'queued', 'stage': 'starting_worker',
                         'created_at': now, 'updated_at': now, 'heartbeat_at': now,
                         'progress_at': now, 'stage_started_at': now, 'stage_seconds': {},
                         'session_id': parameters.get('session'), 'materials': {}, 'waiting_for': None}
                self.write_state(job_id, value)
                active[key] = job_id
                write_json(index_path, active)
                command = [sys.executable, '-I', str(Path(__file__).with_name('job_worker.py')),
                           str(self.reader.config_path), str(self.root), job_id]
                options = {'stdin': subprocess.DEVNULL, 'close_fds': True}
                if os.name == 'nt':
                    options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    options['start_new_session'] = True
                try:
                    with (self.root / (job_id + '.log')).open('ab') as log:
                        process = subprocess.Popen(command, stdout=log, stderr=log, **options)
                        # Reap while this host lives; the detached worker also survives host exit.
                        threading.Thread(target=process.wait, daemon=True).start()
                except OSError as exc:
                    value.update(status='failed', stage='worker_start_failed', finished_at=time.time(),
                                 error={'type': type(exc).__name__, 'message': str(exc)})
                    self.write_state(job_id, value)
                reused = False
        result = self.result(job_id, wait_seconds)
        if result.get('job'):
            result['job']['reused_running_job'] = reused
        else:
            result['reused_running_job'] = reused
        return result

    @staticmethod
    def _wait_value(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 30:
            raise ReaderError('wait_seconds must be between 0 and 30')

    def result(self, job_id, wait_seconds=0):
        self._wait_value(wait_seconds)
        until = time.monotonic()+wait_seconds
        while True:
            state = self.status(job_id)
            if state['status'] in TERMINAL or time.monotonic() >= until:
                break
            time.sleep(min(.1, max(0, until-time.monotonic())))
        if state['status'] == 'completed':
            result = read_json(self.root / (job_id + '.result.json'))
            return {**result, 'job': state}
        return state

    def list(self):
        paths = sorted(self.root.glob('j_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        paths = [p for p in paths if not p.name.endswith('.result.json')][:20]
        return {'jobs': [self.status(p.stem) for p in paths]}

    def active(self, *, exclude=None):
        """All nonterminal jobs, without the display list's twenty-item limit."""
        excluded = {exclude} if isinstance(exclude, str) else set(exclude or ())
        current = CURRENT.get()
        if current:
            excluded.add(current.job_id)
        active = []
        for path in self.root.glob('j_*.json'):
            if path.name.endswith('.result.json') or path.stem in excluded:
                continue
            if read_json(path).get('status') in TERMINAL:
                continue
            state = self.status(path.stem)
            if state['status'] not in TERMINAL:
                active.append(state)
        return active


class Running:
    def __init__(self, store, job_id):
        self.store, self.job_id = store, job_id
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.value = read_json(store.path(job_id))

    def update(self, stage=None, **details):
        with self.lock:
            now = time.time()
            if stage and stage != self.value['stage']:
                old = self.value['stage']
                durations = self.value['stage_seconds']
                durations[old] = round(durations.get(old, 0)+now-self.value['stage_started_at'], 3)
                self.value['stage_started_at'] = now
                self.value['stage'] = stage
                self.value.pop('message', None)
                self.value.pop('progress', None)
            materials = details.pop('materials', None)
            if materials:
                self.value['materials'].update(materials)
            self.value.update(details, updated_at=now, heartbeat_at=now, progress_at=now)
            self.store.write_state(self.job_id, self.value)

    def heartbeat(self):
        while not self.stop.wait(2):
            with self.lock:
                self.value.update(heartbeat_at=time.time(), updated_at=time.time())
                self.store.write_state(self.job_id, self.value)

    def run(self):
        owner = FileLock(str(self.store.root / (self.job_id + '.owner.lock')))
        with owner:
            token = CURRENT.set(self)
            thread = threading.Thread(target=self.heartbeat, daemon=True)
            try:
                if self.value.get('config_identity') != execution_identity(self.store.reader):
                    raise ReaderError('Job execution configuration/account changed; reload the caller and start an explicit new request')
                self.update('initializing', status='running', worker_pid=os.getpid())
                thread.start()
                result = getattr(self.store.reader, self.value['operation'])(**self.value['parameters'])
                self.update('saving_result')
                write_json(self.store.root / (self.job_id + '.result.json'), result)
                self.update('completed', status='completed', finished_at=time.time(), waiting_for=None)
            except BaseException as exc:
                self.update('failed', status='failed', finished_at=time.time(), waiting_for=None,
                            error={'type': type(exc).__name__, 'code': getattr(exc, 'code', None),
                                   'message': str(exc), 'details': getattr(exc, 'details', None)})
            finally:
                self.stop.set()
                if thread.is_alive():
                    thread.join(3)
                CURRENT.reset(token)
