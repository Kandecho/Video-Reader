"""Offline acceptance checks for shared pacing, temporary protection and real pauses."""
import hashlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrllibRequest

from yt_dlp.networking import Request as DownloaderRequest

from video_reader.acquisition_budget import Budget, cooldown_details, request_identity
from video_reader.common import ReaderError, read_json, settings, write_json
from video_reader.platform import Platform, PlatformError
from video_reader import sources


ROOT = Path(__file__).resolve().parents[1]
REAL_GMTIME = time.gmtime


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def completed_digests(calls):
    return [call.kwargs.get('response_digest', call.args[2] if len(call.args) > 2 else None)
            for call in calls
            if call.kwargs.get('response_digest', call.args[2] if len(call.args) > 2 else None) is not None]


class Clock:
    def __init__(self, value=1794410000):
        self.value = value

    def advance(self, seconds):
        self.value += seconds


class Response(io.BytesIO):
    status = 200

    def read(self, amt=None):
        return super().read(-1 if amt is None else amt)


class DownloaderHTTPError(Exception):
    def __init__(self, status):
        super().__init__(str(status))
        self.status = status


class NetworkGuardTests(unittest.TestCase):
    def test_configured_larger_repeat_threshold_remains_effective(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = Budget({'directory': directory, 'options': {
                'daily_requests': None, 'min_gap_seconds': 0, 'repeat_threshold': 40}})
            key = request_identity('https://api.bilibili.com/x/view?bvid=larger-threshold')
            for _ in range(40):
                budget.succeeded(budget.reserve(request_key=key), digest('same-complete-response'))
            with self.assertRaisesRegex(ReaderError, 'platform_request_cooldown'):
                budget.reserve(request_key=key)

    def setUp(self):
        work = ROOT / '.test-work'
        work.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='network-guard-', dir=work)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = settings(self.root / 'config.json')
        self.config['preview']['directory'] = str(self.root / 'preview')
        self.options = self.config['preview']['network']
        self.options.update(daily_requests=None, min_gap_seconds=0)
        self.spec = {'directory': str(self.root / 'preview' / 'one'), 'options': self.options}
        self.clock = Clock()
        patches = [
            patch('video_reader.acquisition_budget.time.time', side_effect=lambda: self.clock.value),
            patch('video_reader.acquisition_budget.time.sleep', side_effect=self.clock.advance),
            patch('video_reader.acquisition_budget.time.gmtime',
                  side_effect=lambda value=None: REAL_GMTIME(self.clock.value if value is None else value)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.budget = Budget(self.spec)

    def client(self, transport, *, offline=False):
        with patch('video_reader.platform.credentials', return_value={'account_marker': 'one', 'cookies': []}):
            return Platform(self.config, transport=transport, offline=offline)

    def fail_transiently(self, key, count=3):
        for _ in range(count):
            self.budget.failed(self.budget.reserve(downloader=False, request_key=key), transient=True)

    def assert_cooldown(self, key=None):
        blocked = self.budget.blocked(request_key=key)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked['code'], 'platform_request_cooldown')
        self.assertGreater(blocked['details']['retry_at'], self.clock.value)
        return blocked['details']

    def repeat_cycle(self, keys, bodies):
        for index in range(32):
            key = keys[index % len(keys)]
            try:
                ticket = self.budget.reserve(downloader=False, request_key=key)
            except ReaderError as error:
                self.assertIsNotNone(cooldown_details(error))
                return
            self.budget.succeeded(ticket, response_digest=digest(bodies[index % len(bodies)]))
            if self.budget.blocked(request_key=key):
                return
        self.fail('Repeated successful responses never entered temporary protection')

    def test_successful_queue_can_pass_120_and_legacy_count_is_only_telemetry(self):
        write_json(self.budget.path, {'day': time.strftime('%Y-%m-%d', time.gmtime()),
                                     'count': 120, 'last_request': 0})
        for index in range(160):
            key = request_identity(f'https://api.bilibili.com/x/web-interface/view?bvid=BV{index:010d}')
            self.budget.succeeded(self.budget.reserve(request_key=key), response_digest=digest(str(index)))
        state = read_json(self.budget.path)
        self.assertEqual(state['count'], 280)
        self.assertIsNone(self.budget.blocked())
        self.assertIsNone(self.budget.status()['daily_limit'])
        self.assertIn('protection', self.budget.status())

    def test_identity_ignores_signing_noise_but_keeps_source_page_cursor_range_and_body(self):
        first = 'https://api.bilibili.com/x/space/wbi/arc/search?mid=42&pn=1&wts=1&w_rid=old&dm_img_str=a'
        same = 'https://api.bilibili.com/x/space/wbi/arc/search?dm_img_str=b&w_rid=new&wts=2&pn=1&mid=42'
        self.assertEqual(request_identity(first), request_identity(same))
        self.assertNotEqual(request_identity(first), request_identity(same.replace('pn=1', 'pn=2')))
        self.assertNotEqual(request_identity(first), request_identity(same.replace('mid=42', 'mid=43')))
        self.assertNotEqual(request_identity('https://api.bilibili.com/x?a=1&cursor=first'),
                            request_identity('https://api.bilibili.com/x?a=1&cursor=second'))
        url = 'https://cdn.bilibili.com/video.mp4'
        self.assertNotEqual(request_identity(url, headers={'Range': 'bytes=0-1023'}),
                            request_identity(url, headers={'Range': 'bytes=1024-2047'}))
        self.assertEqual(request_identity(url, headers={'Range': 'bytes=0-1023'}),
                         request_identity(url, headers={'range': 'bytes=0-1023'}))
        self.assertNotEqual(request_identity(url, method='POST', data=b'cursor=first'),
                            request_identity(url, method='POST', data=b'cursor=second'))
        self.assertNotEqual(request_identity(url), request_identity(url, method='POST'))

    def test_same_response_loop_cools_only_its_request_and_new_video_can_progress(self):
        key = request_identity('https://api.bilibili.com/x/web-interface/view?bvid=BV0000000001')
        self.repeat_cycle([key], ['unchanged body'])
        details = self.assert_cooldown(key)
        other = request_identity('https://api.bilibili.com/x/web-interface/view?bvid=BV0000000002')
        self.assertIsNone(self.budget.blocked(request_key=other))
        self.budget.succeeded(self.budget.reserve(request_key=other), response_digest=digest('new video'))
        self.assertEqual(self.assert_cooldown(key)['retry_at'], details['retry_at'])

    def test_abc_success_loop_protects_the_whole_cycle_but_not_a_new_page(self):
        keys = [request_identity(f'https://api.bilibili.com/x/reply?pn={page}') for page in (1, 2, 3)]
        self.repeat_cycle(keys, ['page A', 'page B', 'page C'])
        for key in keys:
            self.assert_cooldown(key)
        new_page = request_identity('https://api.bilibili.com/x/reply?pn=4')
        self.assertIsNone(self.budget.blocked(request_key=new_page))
        self.budget.succeeded(self.budget.reserve(request_key=new_page), response_digest=digest('page D'))

    def test_same_request_with_changing_complete_results_keeps_progressing(self):
        key = request_identity('https://api.bilibili.com/x/live/status')
        for index in range(40):
            self.budget.succeeded(self.budget.reserve(downloader=False, request_key=key),
                                  response_digest=digest(f'changed complete response {index}'))
        self.assertIsNone(self.budget.blocked(request_key=key))

    def test_two_and_four_request_success_cycles_are_bounded(self):
        for length in (2, 4):
            with self.subTest(period=length):
                self.budget = Budget({**self.spec, 'directory': str(self.root / f'cycle-{length}')})
                keys = [request_identity(f'https://api.bilibili.com/x/reply?pn={page}')
                        for page in range(1, length + 1)]
                self.repeat_cycle(keys, [f'page {page}' for page in range(length)])
                for key in keys:
                    self.assert_cooldown(key)

    def test_transient_failure_cooldown_is_shared_fails_fast_and_allows_expired_probe(self):
        key = request_identity('https://api.bilibili.com/x/reply?pn=1')
        self.fail_transiently(key)
        details = self.assert_cooldown(key)
        other = Budget(self.spec)
        count = read_json(other.path)['count']
        with self.assertRaises(ReaderError) as caught:
            other.reserve(request_key=request_identity('https://api.bilibili.com/x/other'))
        self.assertEqual(cooldown_details(caught.exception)['retry_at'], details['retry_at'])
        self.assertEqual(read_json(other.path)['count'], count)
        self.clock.value = details['retry_at'] + .01
        other.succeeded(other.reserve(request_key=key), response_digest=digest('recovered'))
        self.assertIsNone(other.blocked(request_key=key))
        for _ in range(2):
            other.failed(other.reserve(request_key=key), transient=True)
        self.assertIsNone(other.blocked(request_key=key))

    def test_missing_video_failure_is_local_and_does_not_suspend_other_videos(self):
        missing = request_identity('https://api.bilibili.com/x/web-interface/view?bvid=missing')
        for _ in range(3):
            self.budget.failed(self.budget.reserve(request_key=missing), transient=False)
        valid = request_identity('https://api.bilibili.com/x/web-interface/view?bvid=valid')
        self.assertIsNone(self.budget.blocked(request_key=valid))
        self.budget.succeeded(self.budget.reserve(request_key=valid), response_digest=digest('valid video'))
        self.assertFalse(self.budget.status().get('paused'))

    def test_late_success_does_not_erase_newer_failures_or_active_cooldown(self):
        old = self.budget.reserve(request_key=digest('old request'))
        key = digest('new failing request')
        self.fail_transiently(key, count=2)
        self.budget.succeeded(old, response_digest=digest('late response'))
        self.fail_transiently(key, count=1)
        details = self.assert_cooldown(key)
        self.budget.succeeded(old, response_digest=digest('another late response'))
        self.assertEqual(self.assert_cooldown(key)['retry_at'], details['retry_at'])

    def test_late_failures_do_not_cancel_more_recent_successful_progress(self):
        key = digest('concurrent requests for the same source')
        older = [self.budget.reserve(request_key=key) for _ in range(3)]
        newest = self.budget.reserve(request_key=key)
        self.budget.succeeded(newest, response_digest=digest('newer complete response'))
        for ticket in older:
            self.budget.failed(ticket, transient=True)
        self.assertIsNone(self.budget.blocked(request_key=key))
        self.assertIsNone(self.budget.blocked(request_key=digest('another video')))

    def test_optional_daily_cap_preflight_expires_at_the_same_utc_boundary_as_reservation(self):
        self.options['daily_requests'] = 2
        for _ in range(2):
            self.budget.reserve()
        self.assertEqual(self.budget.blocked()['code'], 'platform_daily_budget_exhausted')
        self.clock.advance(86400)
        self.assertIsNone(Budget(self.spec).blocked())
        self.budget.reserve()
        self.assertEqual(read_json(self.budget.path)['count'], 1)

    def test_utc_day_rollover_does_not_clear_cooldown_or_real_platform_pause(self):
        self.clock.value = datetime(2026, 11, 11, 23, 59, 50, tzinfo=timezone.utc).timestamp()
        key = digest('failure at midnight')
        self.fail_transiently(key)
        details = self.assert_cooldown(key)
        self.clock.advance(15)
        self.assertEqual(self.assert_cooldown(key)['retry_at'], details['retry_at'])
        self.budget.reject(429)
        self.clock.advance(86400)
        with self.assertRaisesRegex(ReaderError, 'platform_paused'):
            Budget(self.spec).reserve(request_key=digest('next day'))

    def test_cooldown_details_survive_stored_errors_and_metadata_wrapping(self):
        key = digest('errors')
        self.fail_transiently(key)
        with self.assertRaises(ReaderError) as caught:
            self.budget.reserve(request_key=key)
        error = caught.exception
        detail = cooldown_details(error)
        self.assertIsNotNone(detail)
        stored = {'type': type(error).__name__, 'code': getattr(error, 'code', None),
                  'message': str(error), 'details': getattr(error, 'details', None)}
        self.assertEqual(cooldown_details(stored), detail)
        self.assertEqual(cooldown_details({'code': 'SOURCE_METADATA_FAILED',
                                          'details': {'network_guard': detail}}), detail)
        self.assertIsNone(cooldown_details(ReaderError('platform_code:-404')))

    def test_metadata_error_preserves_request_cooldown_that_started_before_the_command(self):
        key = request_identity('https://api.bilibili.com/x/repeating')
        self.repeat_cycle([key], ['no new result'])
        wait = self.assert_cooldown(key)
        self.clock.advance(1)
        with patch('video_reader.sources.run', side_effect=ReaderError('platform_request_cooldown')) as run:
            with self.assertRaises(ReaderError) as caught:
                sources.metadata_info(['fixture-command'], {'_network_budget': self.spec})
        self.assertEqual(run.call_count, 1)
        self.assertIsNotNone(cooldown_details(caught.exception))
        self.assertEqual(cooldown_details(caught.exception)['retry_at'], wait['retry_at'])

    def test_media_download_error_retains_shared_request_cooldown_details(self):
        key = request_identity('https://cdn.bilibili.com/video.mp4')
        self.repeat_cycle([key], ['unchanged response'])
        wait = self.assert_cooldown(key)
        self.clock.advance(1)
        source = sources.resolve('BV1Eb411u7Fw')
        envelope = {'code': 0, 'data': {'title': 'fixture', 'pages': [{'cid': 10}]}}
        directory = self.root / 'download'
        with patch('video_reader.sources.request_json', return_value=envelope), \
                patch('video_reader.sources.run', side_effect=[json.dumps({'id': 'BV1Eb411u7Fw_p1'}),
                                                              ReaderError('platform_request_cooldown')]) as run:
            with self.assertRaises(ReaderError) as caught:
                sources.acquire(source, directory, {'_network_budget': self.spec})
        self.assertEqual(run.call_count, 2)
        self.assertIsNotNone(cooldown_details(caught.exception))
        self.assertEqual(cooldown_details(caught.exception)['retry_at'], wait['retry_at'])

    def acquisition_run(self, directory, info, subtitle_failure=None):
        def run(command, **kwargs):
            if '--dump-single-json' in command:
                return json.dumps(info)
            if '--print-to-file' in command:
                media = directory / 'media.mp4'
                media.write_bytes(b'fixture media; this test does not decode video')
                record = Path(command[command.index('--print-to-file') + 2])
                record.write_text(json.dumps(str(media.resolve())) + '\n', encoding='utf-8')
                return ''
            if '--write-subs' in command or '--write-auto-subs' in command:
                if subtitle_failure:
                    return subtitle_failure()
            raise AssertionError('Unexpected downloader command in offline acquisition fixture')
        return run

    def test_native_caption_cooldown_propagates_but_ordinary_unavailability_stays_optional(self):
        source = sources.resolve('BV1Eb411u7Fw')
        envelope = {'code': 0, 'data': {'title': 'fixture', 'pages': [{'cid': 10}]}}
        info = {'id': 'BV1Eb411u7Fw_p1'}
        for protected in (False, True):
            with self.subTest(protected=protected):
                directory = self.root / f'native-captions-{protected}'
                def caption_failure(*args, **kwargs):
                    if protected:
                        key = digest('native caption failure')
                        self.fail_transiently(key)
                        self.budget.reserve(request_key=key)
                    raise ReaderError('ordinary unavailable caption fixture')
                with patch('video_reader.sources.request_json', return_value=envelope), \
                        patch('video_reader.sources.run', side_effect=self.acquisition_run(directory, info)), \
                        patch('video_reader.sources.bilibili_captions', side_effect=caption_failure):
                    if protected:
                        with self.assertRaises(ReaderError) as caught:
                            sources.acquire(source, directory, {'_network_budget': self.spec})
                        self.assertIsNotNone(cooldown_details(caught.exception))
                    else:
                        result = sources.acquire(source, directory, {'_network_budget': self.spec})
                        self.assertIsNone(result['subtitle_path'])
                        self.assertIsNone(result['caption_track'])
                        self.assertTrue(any('subtitles unavailable' in warning for warning in result['warnings']))

    def test_downloader_caption_cooldown_propagates_instead_of_becoming_no_subtitles(self):
        source = sources.resolve('BV1Eb411u7Fw')
        envelope = {'code': 0, 'data': {'title': 'fixture', 'pages': [{'cid': 10}]}}
        info = {'id': 'BV1Eb411u7Fw_p1', 'language': 'en',
                'subtitles': {'en': [{'ext': 'vtt', 'url': 'https://fixture.invalid/captions.vtt'}]}}
        for protected in (False, True):
            with self.subTest(protected=protected):
                directory = self.root / f'downloader-captions-{protected}'
                def subtitle_failure():
                    if protected:
                        key = digest('downloader caption failure')
                        self.fail_transiently(key)
                        self.budget.reserve(request_key=key)
                    raise ReaderError('ordinary unavailable downloader caption fixture')
                with patch('video_reader.sources.request_json', return_value=envelope), \
                        patch('video_reader.sources.run', side_effect=self.acquisition_run(directory, info, subtitle_failure)), \
                        patch('video_reader.sources.bilibili_captions', return_value={'status': 'unavailable'}):
                    if protected:
                        with self.assertRaises(ReaderError) as caught:
                            sources.acquire(source, directory, {'_network_budget': self.spec})
                        self.assertIsNotNone(cooldown_details(caught.exception))
                    else:
                        result = sources.acquire(source, directory, {'_network_budget': self.spec})
                        self.assertIsNone(result['subtitle_path'])
                        self.assertIsNone(result['caption_track'])
                        self.assertTrue(any('ordinary unavailable downloader caption' in warning
                                            for warning in result['warnings']))

    def test_downloader_block_details_survive_worker_exit_after_the_deadline(self):
        for operation in ('metadata', 'media'):
            with self.subTest(operation=operation):
                spec = {**self.spec, 'directory': str(self.root / f'expired-worker-{operation}')}
                budget = Budget(spec)
                key = digest('worker request that failed before its deadline')
                for _ in range(3):
                    budget.failed(budget.reserve(request_key=key), transient=True)
                deadline = budget.blocked(request_key=key)['details']['retry_at']
                def exited_worker(*args, **kwargs):
                    with self.assertRaises(ReaderError):
                        budget.reserve(request_key=key)
                    self.clock.value = deadline + .01
                    raise ReaderError('python.exe failed (1): ERROR: platform_request_cooldown')
                with patch('video_reader.sources.run', side_effect=exited_worker) as run:
                    with self.assertRaises(ReaderError) as caught:
                        if operation == 'metadata':
                            sources.metadata_info(['fixture-command'], {'_network_budget': spec})
                        else:
                            sources.network_run(['fixture-command'], {'_network_budget': spec}, timeout=150)
                self.assertEqual(run.call_count, 1)
                detail = cooldown_details(caught.exception)
                self.assertIsNotNone(detail)
                self.assertEqual(detail['retry_at'], deadline)
                self.assertLessEqual(detail['retry_at'], self.clock.value)
                self.assertIsNone(budget.blocked(request_key=key))

    def test_platform_reports_transient_failures_and_preserves_cached_reads_during_wait(self):
        transport = Mock(return_value=b'{"code":0,"data":{"value":1}}')
        client = self.client(transport)
        client.json('/cached', ttl=100)
        transport.side_effect = URLError('fixture transport failure')
        for _ in range(3):
            with self.assertRaises(PlatformError):
                client.json('/failing')
        called = transport.call_count
        with self.assertRaises(PlatformError) as caught:
            client.json('/new')
        self.assertIsNotNone(cooldown_details(caught.exception))
        self.assertEqual(transport.call_count, called)
        self.assertEqual(client.json('/cached', ttl=100)['value'], 1)
        self.assertEqual(transport.call_count, called)

    def test_platform_http503_and_timeout_errors_enter_shared_temporary_protection(self):
        errors = [HTTPError('https://api.bilibili.com/', 503, 'unavailable', {}, None),
                  TimeoutError('fixture timeout')]
        for index, error in enumerate(errors):
            with self.subTest(error=type(error).__name__):
                self.config['preview']['directory'] = str(self.root / f'transient-{index}')
                transport = Mock(side_effect=error)
                client = self.client(transport)
                for _ in range(3):
                    with self.assertRaises(PlatformError):
                        client.json('/failing')
                calls = transport.call_count
                with self.assertRaises(PlatformError) as caught:
                    self.client(transport).json('/different')
                self.assertIsNotNone(cooldown_details(caught.exception))
                self.assertEqual(transport.call_count, calls)
                self.assertFalse(client.status().get('paused'))

    def test_platform_404_stays_local_and_another_video_is_still_available(self):
        for index, failure in enumerate((json.dumps({'code': -404}).encode(),
                                        HTTPError('https://api.bilibili.com/', 404, 'missing', {}, None))):
            with self.subTest(failure=type(failure).__name__):
                self.config['preview']['directory'] = str(self.root / f'missing-{index}')
                transport = Mock(side_effect=[failure, failure, failure,
                                              b'{"code":0,"data":{"title":"available"}}'])
                client = self.client(transport)
                for _ in range(3):
                    with self.assertRaises(PlatformError):
                        client.json('/view', {'bvid': 'missing'})
                self.assertEqual(client.json('/view', {'bvid': 'available'})['title'], 'available')
                self.assertFalse(client.status().get('paused'))

    def test_real_platform_restrictions_persist_and_success_cannot_clear_them(self):
        for code in (401, 403, 412, 429):
            with self.subTest(http=code):
                spec = {**self.spec, 'directory': str(self.root / f'http-{code}')}
                budget = Budget(spec)
                old = budget.reserve(request_key=digest('already in flight'))
                budget.reject(code)
                budget.succeeded(old, response_digest=digest('late success'))
                self.clock.advance(1000)
                with self.assertRaisesRegex(ReaderError, 'platform_paused'):
                    Budget(spec).reserve()
        for code in (-101, -352, -412, -799):
            with self.subTest(api=code):
                self.config['preview']['directory'] = str(self.root / f'api-{abs(code)}')
                transport = Mock(side_effect=[b'{"code":0,"data":{"value":1}}',
                                              json.dumps({'code': code}).encode()])
                client = self.client(transport)
                client.json('/cached', ttl=100)
                with self.assertRaisesRegex(PlatformError, f'platform_code:{code}'):
                    client.json('/restricted')
                self.assertEqual(client.json('/cached', ttl=100)['value'], 1)
                with self.assertRaisesRegex(PlatformError, 'platform_paused'):
                    self.client(transport).json('/new')
                self.assertEqual(transport.call_count, 2)

    def test_network_state_retains_hashes_without_url_body_or_credentials(self):
        secret = 'private-fixture-token-123'
        url = 'https://api.bilibili.com/x/protected?token=' + secret
        transport = Mock(return_value=json.dumps({'code': 0, 'data': {'value': secret}}).encode())
        client = self.client(transport)
        client.request(url, headers={'Authorization': 'Bearer ' + secret})
        state = client.budget.path.read_text(encoding='utf-8')
        self.assertNotIn(secret, state)
        self.assertNotIn('https://', state)
        self.assertNotIn('Bearer', state)

    def run_downloader(self, action, use):
        from video_reader.downloader_worker import main
        spec_path = self.root / 'worker-budget.json'
        write_json(spec_path, self.spec)
        module = types.ModuleType('yt_dlp')
        class FakeDL:
            def urlopen(self, request):
                return action(request)
        module.YoutubeDL = FakeDL
        module.main = lambda argv: use(module.YoutubeDL())
        exceptions = types.ModuleType('yt_dlp.networking.exceptions')
        exceptions.HTTPError = DownloaderHTTPError
        with patch.dict(sys.modules, {'yt_dlp': module, 'yt_dlp.networking.exceptions': exceptions}), \
                patch.object(sys, 'argv', ['downloader_worker.py', str(spec_path)]):
            return main()

    def test_downloader_transport_failures_share_native_account_cooldown(self):
        def fail(request):
            raise URLError('offline decoder fixture')
        def use(client):
            for _ in range(3):
                try:
                    client.urlopen('https://cdn.bilibili.com/video.mp4')
                except Exception:
                    pass
        self.run_downloader(fail, use)
        self.assert_cooldown(digest('a different native request'))

    def test_downloader_open_is_not_progress_until_response_bytes_are_read(self):
        original = Budget.succeeded
        with patch.object(Budget, 'succeeded', autospec=True, side_effect=original) as success:
            def use(client):
                response = client.urlopen('https://cdn.bilibili.com/video.mp4')
                self.assertEqual(success.call_count, 0)
                self.assertEqual(response.read(), b'actual bytes')
                self.assertGreaterEqual(success.call_count, 1)
            self.run_downloader(lambda request: Response(b'actual bytes'), use)

    def test_downloader_accepts_string_urllib_and_ytdlp_request_objects(self):
        requests = ['https://cdn.bilibili.com/first.mp4',
                    UrllibRequest('https://cdn.bilibili.com/second.mp4', headers={'Range': 'bytes=0-9'}),
                    DownloaderRequest('https://cdn.bilibili.com/third.mp4', data=b'fixture=1')]
        action = Mock(side_effect=lambda request: Response(b'payload'))
        def use(client):
            for request in requests:
                self.assertEqual(client.urlopen(request).read(), b'payload')
        self.run_downloader(action, use)
        self.assertEqual([call.args[0] for call in action.call_args_list], requests)
        self.assertEqual(read_json(self.budget.path)['count'], 3)

    def test_downloader_read_zero_is_neither_progress_nor_failure(self):
        from video_reader.downloader_worker import observe_response
        ticket = self.budget.reserve(request_key=digest('read zero'))
        response = Response(b'payload')
        original_success, original_failure = Budget.succeeded, Budget.failed
        with patch.object(Budget, 'succeeded', autospec=True, side_effect=original_success) as success, \
                patch.object(Budget, 'failed', autospec=True, side_effect=original_failure) as failure:
            observed = observe_response(response, self.budget, ticket)
            self.assertIs(observed, response)
            self.assertEqual(observed.read(0), b'')
            self.assertEqual(observed.read(amt=0), b'')
            success.assert_not_called()
            failure.assert_not_called()
            self.assertEqual(observed.read(1), b'p')
            self.assertEqual(success.call_count, 1)
            self.assertEqual(observed.read(), b'ayload')
            self.assertEqual(observed.read(), b'')
            self.assertEqual(completed_digests(success.call_args_list), [digest('payload')])
            failure.assert_not_called()

    def test_many_stream_reads_and_repeated_eof_are_one_request_and_one_complete_response(self):
        from video_reader.downloader_worker import observe_response
        key = request_identity('https://cdn.bilibili.com/large.mp4')
        ticket = self.budget.reserve(request_key=key)
        original = Budget.succeeded
        with patch.object(Budget, 'succeeded', autospec=True, side_effect=original) as success:
            response = observe_response(Response(b'x' * 40), self.budget, ticket)
            for _ in range(40):
                self.assertEqual(response.read(1), b'x')
            self.assertEqual(completed_digests(success.call_args_list), [])
            for _ in range(12):
                self.assertEqual(response.read(1), b'')
            self.assertEqual(completed_digests(success.call_args_list), [digest('x' * 40)])
        self.assertEqual(read_json(self.budget.path)['count'], 1)
        self.assertIsNone(self.budget.blocked(request_key=key))

    def test_known_content_length_reports_full_digest_without_an_extra_eof_read(self):
        from video_reader.downloader_worker import observe_response
        key = request_identity('https://cdn.bilibili.com/known-length.mp4')
        response = Response(b'abcde')
        response.headers = {'Content-Length': '5'}
        original = Budget.succeeded
        with patch.object(Budget, 'succeeded', autospec=True, side_effect=original) as success:
            observed = observe_response(response, self.budget, self.budget.reserve(request_key=key))
            self.assertEqual(observed.read(2), b'ab')
            self.assertEqual(completed_digests(success.call_args_list), [])
            self.assertEqual(observed.read(3), b'cde')
            self.assertEqual(completed_digests(success.call_args_list), [digest('abcde')])
            self.assertEqual(observed.read(), b'')
            self.assertEqual(completed_digests(success.call_args_list), [digest('abcde')])

    def test_downloader_repeating_complete_body_enters_request_cooldown(self):
        url = 'https://cdn.bilibili.com/repeated.mp4'
        key = request_identity(url)
        def use(client):
            for _ in range(32):
                try:
                    self.assertEqual(client.urlopen(url).read(), b'unchanged complete body')
                except ReaderError as error:
                    self.assertIsNotNone(cooldown_details(error))
                    break
                if self.budget.blocked(request_key=key):
                    break
            self.assert_cooldown(key)
            self.assertEqual(client.urlopen(url + '?new-video=1').read(), b'unchanged complete body')
        self.run_downloader(lambda request: Response(b'unchanged complete body'), use)

    def test_downloader_different_byte_ranges_keep_progressing_even_with_equal_bytes(self):
        url = 'https://cdn.bilibili.com/chunked.mp4'
        def use(client):
            for index in range(20):
                request = UrllibRequest(url, headers={'Range': f'bytes={index * 4}-{index * 4 + 3}'})
                response = client.urlopen(request)
                self.assertEqual(response.read(2), b'da')
                self.assertEqual(response.read(), b'ta')
                self.assertIsNone(self.budget.blocked(request_key=request_identity(url, headers=request.headers)))
        self.run_downloader(lambda request: Response(b'data'), use)
        self.assertEqual(read_json(self.budget.path)['count'], 20)

    def test_downloader_read_failure_is_reported_once_and_shared_with_native_requests(self):
        from video_reader.downloader_worker import observe_response
        class FailingResponse:
            def __init__(self):
                self.reads = 0
            def read(self):
                self.reads += 1
                if self.reads == 1:
                    return b'first bytes'
                raise TimeoutError('fixture read interrupted')
        ticket = self.budget.reserve(request_key=digest('interrupted stream'))
        original = Budget.failed
        with patch.object(Budget, 'failed', autospec=True, side_effect=original) as failure:
            response = observe_response(FailingResponse(), self.budget, ticket)
            self.assertEqual(response.read(), b'first bytes')
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    response.read()
            self.assertEqual(failure.call_count, 1)
        self.fail_transiently(digest('following request'), count=2)
        self.assert_cooldown(digest('native request'))

    def test_downloader_http429_sets_the_same_durable_pause_as_native_requests(self):
        def reject(request):
            raise DownloaderHTTPError(429)
        def use(client):
            with self.assertRaises(DownloaderHTTPError):
                client.urlopen('https://cdn.bilibili.com/video.mp4')
        self.run_downloader(reject, use)
        native = self.client(Mock(side_effect=AssertionError('paused account must not access transport')))
        with self.assertRaisesRegex(PlatformError, 'platform_paused'):
            native.json('/new')
        self.assertEqual(native.status()['paused'], 'http_429')


class SharedProcessAccountingTests(unittest.TestCase):
    def budget(self, directory):
        return Budget({'directory': directory, 'options': {'daily_requests': None, 'min_gap_seconds': 0}})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows reader handles can deny atomic file replacement')
    def test_transient_reader_handle_retries_same_commit_without_double_counting(self):
        with tempfile.TemporaryDirectory() as temporary:
            budget = self.budget(temporary)
            budget.reserve()
            held = budget.path.open('rb')
            release = None
            failures = []
            replace = os.replace
            def commit(source, target):
                nonlocal release
                self.assertTrue(budget.lock.is_locked)
                try:
                    return replace(source, target)
                except PermissionError as error:
                    failures.append(getattr(error, 'winerror', None))
                    if release is None:
                        release = threading.Timer(.02, held.close)
                        release.start()
                    raise
            try:
                with patch('video_reader.common.os.replace', side_effect=commit) as commits, \
                        patch('video_reader.acquisition_budget.write_json', wraps=write_json) as writes:
                    ticket = budget.reserve()
            finally:
                held.close()
                if release is not None:
                    release.join(timeout=1)
            self.assertTrue(failures)
            self.assertTrue(all(code in (5, 32) for code in failures))
            self.assertGreater(commits.call_count, 1)
            self.assertEqual(len({call.args[0] for call in commits.call_args_list}), 1)
            writes.assert_called_once()
            self.assertEqual(ticket['sequence'], 2)
            self.assertEqual(read_json(budget.path)['count'], 2)
            self.assertEqual(list(Path(temporary).glob('.write-*.json')), [])

    def test_independent_processes_share_count_without_a_default_daily_cap(self):
        work = ROOT / '.test-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='network-process-', dir=work) as temporary:
            spec = {'directory': temporary, 'options': {'daily_requests': None, 'min_gap_seconds': 0}}
            code = '''import hashlib,json,sys
sys.path.insert(0,sys.argv[1])
from video_reader.acquisition_budget import Budget,request_identity
budget=Budget(json.loads(sys.argv[2]))
for index in range(80):
    value=sys.argv[3]+str(index)
    key=request_identity('https://api.bilibili.com/x/view?bvid='+value)
    budget.succeeded(budget.reserve(request_key=key),response_digest=hashlib.sha256(value.encode()).hexdigest())
'''
            children = [subprocess.Popen([sys.executable, '-I', '-c', code, str(ROOT), json.dumps(spec), name],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                        for name in ('first-', 'second-')]
            try:
                for child in children:
                    stdout, stderr = child.communicate(timeout=30)
                    self.assertEqual(child.returncode, 0, (stdout + stderr).decode('utf-8', errors='replace'))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=10)
            self.assertEqual(read_json(Path(temporary) / 'network.json')['count'], 160)


if __name__ == '__main__':
    unittest.main()
