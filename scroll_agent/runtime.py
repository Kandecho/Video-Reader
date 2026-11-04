"""Round ownership and durable progress, independent of Reader/media locks."""
from contextlib import contextmanager
import os
import threading
import time
import uuid

from filelock import FileLock, Timeout


from video_reader.common import error_details


class Runtime:
    def __init__(self, memory, directory, run_id):
        self.memory, self.directory, self.run_id = memory, directory, run_id
        self.stop = threading.Event()

    def update(self, stage=None, **fields):
        now = time.time()
        if stage:
            previous = self.memory.load_run(self.run_id).get('runtime', {})
            fields.update(stage=stage, progress_at=now)
            fields.setdefault('waiting_for', None)
            if stage != previous.get('stage'):
                fields['stage_started_at'] = now
        return self.memory.update_runtime(self.run_id, {**fields, 'updated_at': now, 'heartbeat_at': now},
                                          event='progress' if stage else 'execution')

    def _heartbeat(self):
        while not self.stop.wait(2):
            self.memory.update_runtime(self.run_id, {'heartbeat_at': time.time()})

    @contextmanager
    def working(self, stage, *, completed_stage, completed_status):
        with FileLock(str(self.directory / '.owner.lock'), timeout=10):
            self.update(stage, status='running', worker_pid=os.getpid(), owner_id=uuid.uuid4().hex,
                        started_at=time.time(), finished_at=None, error=None, host_pid=None,
                        schema_version=1, history_available=True)
            thread = threading.Thread(target=self._heartbeat, daemon=True)
            thread.start()
            try:
                yield self
            except BaseException as error:
                self.update(status='failed' if isinstance(error, Exception) else 'interrupted',
                            error=error_details(error), finished_at=time.time(), waiting_for=None)
                raise
            else:
                self.update(completed_stage, status=completed_status, finished_at=time.time())
            finally:
                self.stop.set()
                thread.join(3)


def inspect_runtime(memory, directory, run_id, global_lock):
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / '.inspect.lock'), timeout=2):
        return _inspect_runtime(memory, directory, run_id, global_lock)


def _inspect_runtime(memory, directory, run_id, global_lock):
    """Read-only projection: a heartbeat alone never proves an executor is alive."""
    owner = FileLock(str(directory / '.owner.lock'), timeout=0)
    try:
        owner.acquire()
    except Timeout:
        alive = True
        result = memory.load_run(run_id)
    else:
        try:
            alive = False
            result = memory.load_run(run_id)
        finally:
            owner.release()
    runtime = dict(result.get('runtime', {}))
    if not runtime:
        runtime = {'stage': 'legacy_stage_not_recorded', 'status': 'unknown', 'worker_alive': None,
                   'progress_at': result['created_at'], 'history_available': False}
        if result['status'] == 'preparing':
            # Old workers only held the installation-wide round lock.
            probe = FileLock(global_lock.lock_file, timeout=0)
            try:
                probe.acquire()
            except Timeout:
                pass
            else:
                probe.release()
                runtime.update(status='interrupted', worker_alive=False,
                               waiting_for='explicit_recovery_or_inspection')
        elif result['status'] == 'prepared':
            runtime.update(status='waiting', stage='awaiting_host', worker_alive=False)
        elif result['status'] in ('finished', 'failed', 'acquisition_failed', 'interrupted'):
            runtime.update(status='completed' if result['status'] == 'finished' else result['status'], worker_alive=False)
    else:
        runtime['worker_alive'] = alive
        if runtime['status'] == 'running' and not alive:
            runtime.update(status='interrupted', waiting_for='explicit_recovery_or_inspection',
                           interruption='Executor no longer owns the round; no automatic restart.')
        for field in ('heartbeat_at', 'progress_at'):
            if runtime.get(field) is not None:
                runtime[field.replace('_at', '_age_seconds')] = round(max(0, time.time()-runtime[field]), 3)
    return result, runtime
