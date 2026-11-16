"""Shared request accounting, pacing and evidence-based temporary protection."""
import hashlib
import json
from pathlib import Path
import math
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from filelock import FileLock

from .common import ReaderError, read_json, write_json


def request_identity(url, method='GET', data=None, headers=None):
    """Keep pagination/body/range identities; never persist URLs or credentials."""
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if parsed.hostname == 'api.bilibili.com' and parsed.path in (
            '/x/web-interface/wbi/search/type', '/x/space/wbi/arc/search'):
        query = [(key, value) for key, value in query
                 if key not in ('wts', 'w_rid') and not (parsed.path.endswith('/arc/search') and key.startswith('dm_'))]
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(query)), ''))
    if isinstance(data, bytes):
        body = hashlib.sha256(data).hexdigest()
    else:
        body = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    byte_range = next((str(value) for key, value in (headers or {}).items() if key.lower() == 'range'), '')
    return hashlib.sha256(json.dumps([method.upper(), normalized, body, byte_range], ensure_ascii=False).encode()).hexdigest()


def cooldown_details(value):
    """Read temporary protection through stored errors and acquisition wrappers."""
    if isinstance(value, BaseException):
        from .common import error_details
        value = error_details(value)
    if not isinstance(value, dict):
        return None
    for entry in [value, *value.get('chain', [])]:
        details = entry.get('details') or {}
        candidate = details.get('network_guard')
        if entry.get('code') == 'platform_request_cooldown':
            candidate = details
        if isinstance(candidate, dict):
            retry_at = candidate.get('retry_at')
            if type(retry_at) in (int, float) and math.isfinite(retry_at):
                return candidate
    return None


class Budget:
    def __init__(self, spec, *, error_type=ReaderError):
        self.root = Path(spec['directory'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.options = spec['options']
        self.error_type = error_type
        limit = self.options.get('daily_requests')
        if limit is not None and (type(limit) is not int or limit < 1):
            raise error_type('daily_requests_must_be_a_positive_integer_or_null')
        gap = self.options.get('min_gap_seconds', 2)
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap < 0:
            raise error_type('min_gap_seconds_must_be_finite_and_nonnegative')
        self.policy = {'failure_threshold': 3, 'repeat_threshold': 8, 'protection_window_seconds': 120,
                       'cooldown_seconds': 30, 'max_cooldown_seconds': 300}
        for key, default in self.policy.items():
            value = self.options.get(key, default)
            if type(value) is not int or value < (2 if key.endswith('threshold') else 1):
                raise error_type(key + '_must_be_a_positive_integer')
            self.policy[key] = value
        if self.policy['max_cooldown_seconds'] < self.policy['cooldown_seconds']:
            raise error_type('max_cooldown_seconds_must_not_be_less_than_cooldown_seconds')
        self.path = self.root / 'network.json'
        self.lock = FileLock(str(self.root / 'network.lock'), timeout=30)

    @staticmethod
    def _key(value):
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ReaderError('Request identity must be nonempty text')
        return value if len(value) == 64 and all(c in '0123456789abcdef' for c in value) else hashlib.sha256(value.encode()).hexdigest()

    def _state(self):
        return read_json(self.path) if self.path.exists() else {}

    @staticmethod
    def _wait(record, now, scope, key=None):
        if not record or record.get('retry_at', 0) <= now:
            return None
        return {**record, 'scope': scope, 'retry_after_seconds': round(record['retry_at'] - now, 3),
                **({'request_key': key} if key else {})}

    def _blocked(self, state, now, key=None, since=None):
        if state.get('paused'):
            return {'code': 'platform_paused:' + state['paused'], 'details': None}
        limit = self.options.get('daily_requests')
        today = time.strftime('%Y-%m-%d', time.gmtime())
        if limit is not None and state.get('day', today) == today and state.get('count', 0) >= limit:
            return {'code': 'platform_daily_budget_exhausted', 'details': None}
        guard = state.get('guard', {})
        waits = [self._wait(guard.get('cooldown'), now, 'account')]
        records = guard.get('requests', {})
        if key:
            waits.append(self._wait(records.get(key, {}).get('cooldown'), now, 'request', key))
        elif since is not None:
            waits.extend(self._wait(record.get('cooldown'), now, 'request', identity)
                         for identity, record in records.items()
                         if record.get('cooldown', {}).get('triggered_at', 0) >= since)
        active = [wait for wait in waits if wait]
        return {'code': 'platform_request_cooldown', 'details': max(active, key=lambda wait: wait['retry_at'])} if active else None

    def blocked(self, *, request_key=None, since=None):
        with self.lock:
            return self._blocked(self._state(), time.time(), self._key(request_key), since)

    def blocked_attempt(self, since):
        with self.lock:
            record = self._state().get('last_block')
            return record if record and record['at'] >= since else None

    def reserve(self, *, downloader=True, request_key=None):
        key = self._key(request_key)
        with self.lock:
            state = self._state()
            today = time.strftime('%Y-%m-%d', time.gmtime())
            if state.get('day') != today:
                state.update(day=today, count=0)
            blocked = self._blocked(state, time.time(), key)
            if blocked:
                if blocked['code'] == 'platform_request_cooldown':
                    state['last_block'] = {**blocked, 'at': time.time()}
                    write_json(self.path, state)
                error = self.error_type(blocked['code'])
                error.code, error.details = blocked['code'], blocked['details']
                raise error
            delay = self.options.get('min_gap_seconds', 2) - (time.time() - state.get('last_request', 0))
            if delay > 0:
                time.sleep(delay)
            sequence = state.get('request_sequence', 0) + 1
            state.update(count=state.get('count', 0)+1, last_request=time.time(), request_sequence=sequence)
            if downloader:
                state['downloader_requests'] = state.get('downloader_requests', 0)+1
            write_json(self.path, state)
            return {'key': key, 'sequence': sequence}

    def _cool(self, record, now, reason):
        strikes = min(record.get('strikes', 0) + 1, 10)
        delay = min(self.policy['max_cooldown_seconds'], self.policy['cooldown_seconds'] * 2 ** (strikes - 1))
        record.update(strikes=strikes, cooldown={'reason': reason, 'retry_at': now + delay, 'triggered_at': now})

    def _trim(self, guard, now):
        records = guard.setdefault('requests', {})
        retained = sorted(records.items(), key=lambda pair: max(pair[1].get('last_failure', 0), pair[1].get('last_success', 0), pair[1].get('cooldown', {}).get('retry_at', 0)), reverse=True)
        guard['requests'] = dict(retained[:128])

    def failed(self, ticket, *, transient=True):
        with self.lock:
            state, now = self._state(), time.time()
            guard = state.setdefault('guard', {})
            sequence, key = ticket['sequence'], ticket['key']
            window = self.policy['protection_window_seconds']
            if transient and sequence >= guard.get('last_success_sequence', 0):
                count = guard.get('failures', 0) if now - guard.get('last_failure', 0) <= window else 0
                guard.update(failures=count + 1, last_failure=now,
                             last_failure_sequence=max(sequence, guard.get('last_failure_sequence', 0)))
                if guard['failures'] >= self.policy['failure_threshold']:
                    self._cool(guard, now, 'transient_failures')
            elif not transient and sequence >= max(guard.get('last_failure_sequence', 0), guard.get('last_success_sequence', 0)) and not self._wait(guard.get('cooldown'), now, 'account'):
                guard['failures'] = 0
            if key:
                record = guard.setdefault('requests', {}).setdefault(key, {})
                if sequence >= record.get('last_success_sequence', 0):
                    count = record.get('failures', 0) if now - record.get('last_failure', 0) <= window else 0
                    record.update(failures=count + 1, last_failure=now,
                                  last_failure_sequence=max(sequence, record.get('last_failure_sequence', 0)))
                    if record['failures'] >= self.policy['failure_threshold']:
                        self._cool(record, now, 'repeated_request_failures')
            self._trim(guard, now)
            write_json(self.path, state)
            blocked = self._blocked(state, now, key)
            return blocked['details'] if blocked and blocked['code'] == 'platform_request_cooldown' else None

    def succeeded(self, ticket, response_digest=None):
        with self.lock:
            state, now = self._state(), time.time()
            guard = state.setdefault('guard', {})
            sequence, key = ticket['sequence'], ticket['key']
            guard['last_success_sequence'] = max(sequence, guard.get('last_success_sequence', 0))
            if sequence >= guard.get('last_failure_sequence', 0) and not self._wait(guard.get('cooldown'), now, 'account'):
                guard.update(failures=0, strikes=0)
            record = guard.setdefault('requests', {}).setdefault(key, {}) if key else None
            if record and sequence >= record.get('last_failure_sequence', 0) and not self._wait(record.get('cooldown'), now, 'request'):
                record['failures'] = 0
                if response_digest is None or record.get('response_digest') != response_digest:
                    record['strikes'] = 0
            if record is not None:
                record.update(last_success=now, last_success_sequence=max(sequence, record.get('last_success_sequence', 0)))
            if response_digest is not None and sequence >= guard.get('last_response_sequence', 0):
                guard['last_response_sequence'] = sequence
                if key:
                    recent = [event for event in guard.get('responses', [])
                              if now - event['at'] <= self.policy['protection_window_seconds']]
                    signature = hashlib.sha256((key + response_digest).encode()).hexdigest()
                    recent.append({'key': key, 'signature': signature, 'at': now})
                    guard['responses'] = recent[-max(32, self.policy['repeat_threshold'] + 4):]
                    for period in range(1, 5):
                        repetitions = max(3, math.ceil(self.policy['repeat_threshold'] / period))
                        size = period * repetitions
                        if len(recent) < size:
                            continue
                        tail = recent[-size:]
                        if [event['signature'] for event in tail] == [event['signature'] for event in tail[-period:]] * repetitions:
                            for identity in {event['key'] for event in tail}:
                                protected = guard.setdefault('requests', {}).setdefault(identity, {})
                                self._cool(protected, now, 'repeated_response_pattern')
                                if identity == key:
                                    protected['response_digest'] = response_digest
                            break
            self._trim(guard, now)
            write_json(self.path, state)

    def status(self):
        with self.lock:
            state = self._state()
            now = time.time()
            guard = state.get('guard', {})
            waits = [self._wait(guard.get('cooldown'), now, 'account')]
            waits.extend(self._wait(record.get('cooldown'), now, 'request', key)
                         for key, record in guard.get('requests', {}).items())
            active = [wait for wait in waits if wait]
            return {**{key: state.get(key) for key in ('day', 'count', 'paused', 'last_request')},
                    'daily_limit': self.options.get('daily_requests'),
                    'protection': {'active_cooldowns': active, 'consecutive_transient_failures': guard.get('failures', 0)}}

    def pause(self, reason):
        with self.lock:
            state = read_json(self.path) if self.path.exists() else {}
            state['paused'] = reason
            write_json(self.path, state)

    def reject(self, code):
        if code not in (401, 403, 412, 429):
            return
        self.pause('http_' + str(code))
