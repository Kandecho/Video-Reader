"""Downloader request accounting shares the native API account's pause/budget."""
from pathlib import Path
import math
import time
from filelock import FileLock

from .common import ReaderError, read_json, write_json


class Budget:
    def __init__(self, spec, *, error_type=ReaderError):
        self.root = Path(spec['directory'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.options = spec['options']
        self.error_type = error_type
        limit = self.options['daily_requests']
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise error_type('daily_requests_must_be_a_positive_integer')
        gap = self.options['min_gap_seconds']
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap < 0:
            raise error_type('min_gap_seconds_must_be_finite_and_nonnegative')
        self.path = self.root / 'network.json'
        self.lock = FileLock(str(self.root / 'network.lock'), timeout=30)

    def reserve(self, *, downloader=True):
        with self.lock:
            state = read_json(self.path) if self.path.exists() else {}
            if state.get('paused'):
                raise self.error_type('platform_paused:' + state['paused'])
            today = time.strftime('%Y-%m-%d', time.gmtime())
            if state.get('day') != today:
                state.update(day=today, count=0)
            if state.get('count', 0) >= self.options['daily_requests']:
                raise self.error_type('platform_daily_budget_exhausted')
            delay = self.options['min_gap_seconds'] - (time.time() - state.get('last_request', 0))
            if delay > 0:
                time.sleep(delay)
            state.update(count=state.get('count', 0)+1, last_request=time.time())
            if downloader:
                state['downloader_requests'] = state.get('downloader_requests', 0)+1
            write_json(self.path, state)

    def pause(self, reason):
        with self.lock:
            state = read_json(self.path) if self.path.exists() else {}
            state['paused'] = reason
            write_json(self.path, state)

    def reject(self, code):
        if code not in (401, 403, 412, 429):
            return
        self.pause('http_' + str(code))
