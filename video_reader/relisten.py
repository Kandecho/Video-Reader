"""Fresh local decoding in an isolated, bounded process; never replaces baseline ASR."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
import uuid

from .common import ReaderError, UNTRUSTED, read_json, write_json


def stop(process):
    if process.poll() is None:
        if os.name == 'nt':
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                if process.poll() is None:
                    process.kill()
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def execute(directory, data, config, lo, hi, context, terms, timeout_seconds, precise_words):
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 180:
        raise ReaderError('Relisten timeout_seconds must be between 1 and 180')
    if hi-lo > 60:
        raise ReaderError('Relisten accepts at most 60 seconds; split longer questions into short windows')
    if not isinstance(precise_words, bool):
        raise ReaderError('precise_words must be true or false')
    if not isinstance(terms, list) or len(terms) > 30 or any(
            not isinstance(t, str) or not 1 <= len(t) <= 100 for t in terms):
        raise ReaderError('terms must contain at most 30 short strings scoped to this source')
    job_id = uuid.uuid4().hex[:24]
    target = directory / 'relistens' / job_id
    target.mkdir(parents=True)
    request = {'data': {'metadata': data['metadata'], 'media_path': data['media_path']},
               'config': {'asr': config['asr']}, 'start': lo, 'end': hi, 'context': context,
               'terms': terms, 'precise_words': precise_words}
    write_json(target / 'request.json', request)
    result = {'job_id': job_id, 'session_id': data['id'], 'status': 'running',
              'range': {'start': lo, 'end': hi}, 'terms': terms, 'context': context,
              'cache_reused': False, 'baseline_modified': False, 'timeout_seconds': timeout_seconds,
              'precise_words': precise_words, 'started_at': time.time(),
              'source_content_policy': UNTRUSTED}
    write_json(target / 'result.json', result)
    # Windows venv launchers spawn another Python. Start the actual shared runtime
    # with this installation's own code/dependencies so timeout owns the real PID.
    bootstrap = ("import runpy,sys;sys.path[:0]=sys.argv[1:3];"
                 "sys.argv=['video_reader.relisten_worker',*sys.argv[3:]];"
                 "runpy.run_module('video_reader.relisten_worker',run_name='__main__')")
    command = [getattr(sys, '_base_executable', sys.executable), '-I', '-c', bootstrap,
               str(Path(__file__).resolve().parents[1]), sysconfig.get_path('purelib'), str(target / 'request.json')]
    began = time.monotonic()
    process = None
    try:
        with (target / 'worker.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                       start_new_session=os.name != 'nt')
            result['worker_pid'] = process.pid
            write_json(target / 'result.json', result)
            process.wait(timeout=timeout_seconds)
        if process.returncode or not (target / 'decoded.json').is_file():
            result.update(status='failed', reason='Local decoder failed; see component-owned worker.log')
        else:
            result.update(status='completed', speech=read_json(target / 'decoded.json'))
    except subprocess.TimeoutExpired:
        stop(process)
        result.update(status='timed_out', reason='Local decoder exceeded the configured deadline and was terminated')
    except BaseException as exc:
        if process:
            stop(process)
        result.update(status='interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed',
                      reason=type(exc).__name__)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            write_json(target / 'result.json', result)
            raise
    result.update(elapsed_seconds=round(time.monotonic()-began, 3), storage_path=str(target / 'result.json'))
    write_json(target / 'result.json', result)
    return result
