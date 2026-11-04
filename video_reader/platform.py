"""Bounded acquisition transport shared by recommendation, previews and private delivery."""
from __future__ import annotations

import hashlib
from http.cookiejar import CookieJar
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, HTTPCookieProcessor, build_opener

from filelock import FileLock

from .bilibili_auth import BilibiliAuth, USER_AGENT, _jar, _cookie_value
from .common import ReaderError, read_json, write_json

API = 'https://api.bilibili.com'
RESTRICTED = {-101, -352, -412, -799}


class PlatformError(ReaderError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def trusted(url):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        valid = (parsed.scheme == 'https' and not parsed.username and not parsed.password
                 and parsed.port in (None, 443) and any(host == name or host.endswith('.' + name)
                 for name in ('bilibili.com', 'hdslb.com')) or
                 parsed.scheme == 'https' and host == 'b23.tv' and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise PlatformError('untrusted_platform_url')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(req.full_url).hostname == 'b23.tv':
            return None  # Expose Location to the bounded transport; never follow it.
        raise PlatformError('platform_redirect_refused')


def credentials(config):
    auth = BilibiliAuth(config)
    if not auth.options['enabled']:
        raise PlatformError('managed_login_disabled')
    with auth._lock():
        record = auth._load()
    if not record:
        raise PlatformError('login_required')
    return record


class Platform:
    def __init__(self, config, *, offline=False, transport=None, write_endpoints=()):
        self.config, self.offline = config, offline
        self.write_endpoints = frozenset(write_endpoints)
        record = credentials(config)
        self.scope = record['account_marker']
        self.jar = _jar(record['cookies'])
        self.options = config['preview']['network']
        for key in ('daily_requests', 'max_response_bytes'):
            value = self.options[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PlatformError(f'{key}_must_be_a_positive_integer')
        for key, value in [('timeout_seconds', self.options['timeout_seconds']),
                           ('material_ttl_seconds', config['preview']['material_ttl_seconds']),
                           ('recommendation_ttl_seconds', config['preview']['recommendation_ttl_seconds'])]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise PlatformError(f'{key}_must_be_finite_and_positive')
        gap = self.options['min_gap_seconds']
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap < 0:
            raise PlatformError('min_gap_seconds_must_be_finite_and_nonnegative')
        self.root = Path(config['preview']['directory']) / self.scope
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / 'network.json'
        self.lock = FileLock(str(self.root / 'network.lock'), timeout=30)
        self.opener = build_opener(NoRedirect(), HTTPCookieProcessor(self.jar))
        self.transport = transport or self._transport
        self.trace = []

    def _transport(self, url, form=None, *, headers=None):
        trusted(url)
        data = urlencode(form).encode() if form is not None else None
        headers = {'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/',
                   'Origin': 'https://www.bilibili.com', 'Accept-Encoding': 'identity', **(headers or {})}
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        try:
            with self.opener.open(Request(url, data=data, headers=headers), timeout=self.options['timeout_seconds']) as response:
                return response.read(self.options['max_response_bytes'] + 1)
        except HTTPError as error:
            if urlparse(url).hostname != 'b23.tv' or error.code not in (301, 302, 303, 307, 308):
                raise
            target = error.headers.get('Location', '')
            parsed = urlparse(target)
            if (parsed.scheme != 'https' or parsed.hostname not in ('bilibili.com','www.bilibili.com','m.bilibili.com')
                    or parsed.username or parsed.password or parsed.port not in (None,443)):
                raise PlatformError('untrusted_shortlink_target') from None
            return json.dumps({'code':0,'target':target}).encode('utf-8')

    def resolve_shortlink(self, source):
        from .sources import resolve
        selected = resolve(source)
        if not selected.get('shortlink'):
            raise PlatformError('expected_shortlink')
        result = self.request(selected['canonical'], ttl=self.config['preview']['material_ttl_seconds'])
        target = result.get('target') if isinstance(result,dict) else None
        parsed = urlparse(target or '')
        if (parsed.scheme != 'https' or parsed.hostname not in ('bilibili.com','www.bilibili.com','m.bilibili.com')
                or parsed.username or parsed.password or parsed.port not in (None,443)):
            raise PlatformError('untrusted_shortlink_target')
        return target

    def request(self, url, form=None, *, ttl=0, binary=False, headers=None, validate=None):
        trusted(url)
        if form is not None and url not in self.write_endpoints:
            raise PlatformError('write_not_authorized')
        parsed = urlparse(url)
        cache_url = url
        if parsed.hostname == 'api.bilibili.com' and parsed.path in ('/x/web-interface/wbi/search/type', '/x/space/wbi/arc/search'):
            params = sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                            if key not in ('wts', 'w_rid') and not (parsed.path.endswith('/arc/search') and key.startswith('dm_')))
            cache_url = parsed._replace(query=urlencode(params)).geturl()
        key = hashlib.sha256(cache_url.encode()).hexdigest()
        cache = self.root / (key + ('.bin' if binary else '.json'))
        with self.lock:
            if form is None and ttl and cache.is_file() and (self.offline or time.time() - cache.stat().st_mtime <= ttl):
                cached = cache.read_bytes() if binary else read_json(cache)
                try:
                    if validate:
                        validate(cached)
                except PlatformError as error:
                    self.trace.append({'cache': 'invalid', 'bytes': 0, 'reason': error.code})
                    if self.offline:
                        raise
                else:
                    self.trace.append({'cache': 'hit', 'bytes': 0})
                    return cached
            if self.offline:
                raise PlatformError('offline_cache_miss')
            state = read_json(self.state_path) if self.state_path.exists() else {}
            if state.get('paused'):
                raise PlatformError('platform_paused:' + state['paused'])
            today = time.strftime('%Y-%m-%d', time.gmtime())
            if state.get('day') != today:
                state.update(day=today, count=0)
            if state.get('count', 0) >= self.options['daily_requests']:
                raise PlatformError('platform_daily_budget_exhausted')
            delay = self.options['min_gap_seconds'] - (time.time() - state.get('last_request', 0))
            if delay > 0:
                time.sleep(delay)
            state.update(count=state.get('count', 0) + 1, last_request=time.time())
            write_json(self.state_path, state)
            entry = {'cache': 'miss', 'bytes': 0, 'method': 'POST' if form is not None else 'GET'}
            self.trace.append(entry)
            try:
                body = self.transport(url, form, headers=headers) if headers is not None else self.transport(url, form)
                entry['bytes'] = len(body)
                if len(body) > self.options['max_response_bytes']:
                    raise PlatformError('platform_response_too_large')
                result = body if binary else json.loads(body)
                envelope = result
                if binary and body.lstrip().startswith(b'{'):
                    try:
                        envelope = json.loads(body)
                    except ValueError:
                        pass
                if isinstance(envelope, dict) and envelope.get('code', 0) != 0:
                    code = envelope.get('code')
                    if code in RESTRICTED:
                        state['paused'] = str(code)
                    raise PlatformError('platform_code:' + str(code))
                if validate:
                    validate(result)
                if form is None and ttl:
                    cache.write_bytes(result) if binary else write_json(cache, result)
                entry['status'] = 'ok'
                return result
            except HTTPError as error:
                if error.code in (401, 403, 412, 429):
                    state['paused'] = 'http_' + str(error.code)
                raise PlatformError('platform_http_' + str(error.code)) from None
            except (OSError, ValueError) as error:
                raise PlatformError('platform_unavailable:' + type(error).__name__) from None
            finally:
                write_json(self.state_path, state)

    def json(self, path, params=None, *, ttl=0, validate=None):
        url = API + path + ('?' + urlencode(params) if params else '')
        def envelope(value):
            if not isinstance(value, dict) or not isinstance(value.get('data'), dict):
                raise PlatformError('platform_invalid_data')
            if validate:
                validate(value['data'])
        result = self.request(url, ttl=ttl, validate=envelope)
        return result['data']

    def resume(self):
        with self.lock:
            state = read_json(self.state_path) if self.state_path.exists() else {}
            state.pop('paused', None)
            write_json(self.state_path, state)
        return {'paused': False, 'budget_reset': False}

    def status(self):
        state = read_json(self.state_path) if self.state_path.exists() else {}
        return {key: state.get(key) for key in ('day', 'count', 'paused', 'last_request')}

    @property
    def sender(self):
        return _cookie_value(self.jar, 'DedeUserID')

    @property
    def csrf(self):
        return _cookie_value(self.jar, 'bili_jct')
