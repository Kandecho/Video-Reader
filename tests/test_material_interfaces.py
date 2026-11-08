from contextlib import contextmanager, nullcontext
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from PIL import Image
from yt_dlp.extractor.bilibili import BilibiliSpaceVideoIE

from video_reader import cli, mcp_server
from video_reader.bilibili_auth import BilibiliAuth, _cookie_value
from video_reader.common import ReaderError, read_json, write_json
from video_reader.discovery import _candidate
from video_reader.mcp_content import pack
from video_reader.platform import Platform, PlatformError
from video_reader.preview import contact_sheet, native_frames, preview
from video_reader.reader import Reader
from video_reader.uploader import target, uploader_videos

URL = 'https://www.bilibili.com/video/BV0000000001?p=1'


class MaterialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        write_json(self.config, {'cache_dir': 'cache', 'agent': None, 'preview': {'directory': 'preview', 'network': {'min_gap_seconds': 0}}})
        self.reader = Reader(self.config)
        self.cookies = [{'name': 'SESSDATA', 'value': 'fixture-private-cookie', 'domain': '.bilibili.com', 'path': '/',
                         'expires': int(time.time()) + 9000, 'secure': True}]
        self.credential = {'account_marker': 'test_account', 'cookies': self.cookies}
        self.calls = []
        self.reject_page = None
        self.addCleanup(patch.stopall)
        patch.object(BilibiliSpaceVideoIE, '_wbi_key_cache', {}).start()

    def transport(self, url, form=None, **kwargs):
        path, query = urlparse(url).path, parse_qs(urlparse(url).query)
        self.calls.append((path, query, kwargs))
        if path.endswith('/nav'):
            result = {'code': 0, 'data': {'isLogin': True, 'mid': 99, 'wbi_img': {
                'img_url': 'https://i0.hdslb.com/' + 'a' * 32 + '.png', 'sub_url': 'https://i0.hdslb.com/' + 'b' * 32 + '.png'}}}
        elif path.endswith('/arc/search'):
            page = int(query['pn'][0])
            if page == self.reject_page:
                result = {'code': -352, 'message': 'fixture rejection'}
            else:
                ids = range(1, 4) if page == 1 else range(4, 6)
                result = {'code': 0, 'data': {'page': {'ps': 3, 'count': 5}, 'list': {'vlist': [
                    {'bvid': f'BV{number:010d}', 'title': f'Video {number}', 'mid': 42, 'author': 'Creator',
                     'length': '1:01', 'created': 123, 'play': 9} for number in ids]}}}
        elif path.endswith('/view'):
            result = {'code': 0, 'data': {'owner': {'mid': 42, 'name': 'Creator'}}}
        else:
            raise AssertionError(path)
        return json.dumps(result).encode()

    def platform(self, offline=False, transport=None):
        with patch('video_reader.platform.credentials', return_value=self.credential):
            return Platform(self.reader.config, offline=offline, transport=transport or self.transport)


class UploaderTests(MaterialFixture):
    def test_source_identity_and_invalid_input(self):
        for source in ('42', 'https://space.bilibili.com/42', 'https://space.bilibili.com/42/upload/video'):
            self.assertEqual(target(source), {'uid': '42'})
        self.assertEqual(target(URL), {'bvid': 'BV0000000001'})
        with patch.object(self.reader, '_material_platform') as create:
            for source, page in (('42', 0), ('42', True), ('https://example.com/x', 1), ('', 1)):
                with self.assertRaises(ReaderError):
                    self.reader.uploader_videos(source, page)
            create.assert_not_called()

    def test_existing_extractor_uses_shared_auth_transport_and_two_pages(self):
        platform = self.platform()
        first = uploader_videos(platform, URL)
        second = uploader_videos(platform, '42', page=2)
        self.assertEqual([first['status'], second['status']], ['ready', 'ready'])
        self.assertEqual([item['bvid'] for item in first['items']], ['BV0000000001', 'BV0000000002', 'BV0000000003'])
        self.assertEqual([item['bvid'] for item in second['items']], ['BV0000000004', 'BV0000000005'])
        self.assertEqual(first['items'][0]['duration_seconds'], 61)
        self.assertEqual(first['items'][0]['uploader_id'], '42')
        self.assertEqual(first['next_page'], 2)
        self.assertIsNone(second['next_page'])
        self.assertTrue(second['page_complete'])
        self.assertFalse(second['collection_complete'])
        self.assertEqual(_cookie_value(platform.jar, 'SESSDATA'), 'fixture-private-cookie')
        self.assertNotIn('fixture-private-cookie', json.dumps(first))
        self.assertEqual(sum(path.endswith('/arc/search') for path, _, _ in self.calls), 2)
        self.assertTrue(all(kwargs.get('headers', {}).get('Origin') == 'https://space.bilibili.com'
                            for path, _, kwargs in self.calls if path.endswith('/arc/search')))

    def test_offline_page_reuses_manifest_without_loading_backend(self):
        first = uploader_videos(self.platform(), '42')
        with patch('video_reader.uploader._page', side_effect=AssertionError('offline must reuse')):
            cached = uploader_videos(self.platform(offline=True), '42')
        self.assertEqual(cached['cache'], 'hit')
        self.assertEqual(cached['items'], first['items'])

    def test_rejected_second_page_is_not_empty_success_and_keeps_first_page(self):
        platform = self.platform()
        uploader_videos(platform, '42')
        self.reject_page = 2
        failed = uploader_videos(platform, '42', 2)
        self.assertEqual(failed['status'], 'blocked')
        self.assertFalse(failed['page_complete'])
        self.assertEqual(failed['next_page'], 2)
        self.assertEqual(platform.status()['paused'], '-352')
        self.assertEqual(len(uploader_videos(self.platform(offline=True), '42')['items']), 3)
        self.assertEqual(sum(path.endswith('/arc/search') for path, _, _ in self.calls), 2)

    def test_authenticated_profile_spans_request_and_is_cleaned(self):
        events = []
        @contextmanager
        def profile(auth, options):
            events.append('enter')
            try:
                yield {}, {}, {'authenticated': True}
            finally:
                events.append('exit')
        def fetch(platform, source, page):
            self.assertEqual(events, ['enter'])
            self.assertEqual(_cookie_value(platform.jar, 'SESSDATA'), 'fixture-private-cookie')
            return {'status': 'ready'}
        with patch.object(BilibiliAuth, 'reader_profile', profile), \
                patch('video_reader.platform.credentials', return_value=self.credential), \
                patch('video_reader.uploader.uploader_videos', side_effect=fetch):
            self.reader.uploader_videos('42')
        self.assertEqual(events, ['enter', 'exit'])
        self.assertFalse((self.root / 'data/agent/memory.sqlite3').exists())

    def test_signed_page_cache_ignores_only_transport_noise(self):
        transport = Mock(return_value=b'{"code":0,"data":{"list":{}}}')
        platform = self.platform(transport=transport)
        platform.request('https://api.bilibili.com/x/space/wbi/arc/search?mid=42&pn=1&ps=30&wts=1&w_rid=a&dm_img_str=one', ttl=100)
        other = self.platform(offline=True, transport=transport)
        other.request('https://api.bilibili.com/x/space/wbi/arc/search?ps=30&pn=1&mid=42&wts=2&w_rid=b&dm_img_str=two', ttl=100)
        with self.assertRaisesRegex(PlatformError, 'offline_cache_miss'):
            other.request('https://api.bilibili.com/x/space/wbi/arc/search?ps=30&pn=2&mid=42&wts=2&w_rid=b', ttl=100)
        self.assertEqual(transport.call_count, 1)

    def test_search_projection_retains_uploader_identity(self):
        self.assertEqual(_candidate({'bvid': 'BV0000000001', 'owner': {'name': 'Creator', 'mid': 42}})['uploader_url'], 'https://space.bilibili.com/42')

    def test_partial_native_page_does_not_fetch_next_page_to_fill_gap(self):
        original = self.transport
        def short(url, form=None, **kwargs):
            data = json.loads(original(url, form, **kwargs))
            if urlparse(url).path.endswith('/arc/search'):
                data['data']['list']['vlist'].pop()
            return json.dumps(data).encode()
        result = uploader_videos(self.platform(transport=short), '42')
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['page_complete'])
        self.assertEqual(result['next_page'], 1)
        self.assertEqual(sum(path.endswith('/arc/search') for path, _, _ in self.calls), 1)

    def test_duplicate_entries_are_removed_without_changing_page_completion(self):
        original = self.transport
        def duplicate(url, form=None, **kwargs):
            data = json.loads(original(url, form, **kwargs))
            if urlparse(url).path.endswith('/arc/search'):
                rows = data['data']['list']['vlist']
                rows[1] = rows[0]
            return json.dumps(data).encode()
        result = uploader_videos(self.platform(transport=duplicate), '42')
        self.assertEqual(result['duplicates_removed'], 1)
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(result['page_complete'])
        self.assertEqual(result['next_page'], 2)


class StoryboardTests(MaterialFixture):
    def sprite(self):
        image = Image.new('RGB', (120, 60))
        colors = ['red', 'black', 'blue', 'cyan', 'white', 'green']
        for index, color in enumerate(colors):
            image.paste(color, ((index % 3) * 40, (index // 3) * 30, (index % 3 + 1) * 40, (index // 3 + 1) * 30))
        body = BytesIO()
        image.save(body, format='PNG')
        snapshot = {'index': [0, 0, 10, 20, 30, 40, 50], 'img_x_len': 3, 'img_y_len': 2, 'img_x_size': 40, 'img_y_size': 30,
                    'image': ['https://i0.hdslb.com/sprite.png']}
        return snapshot, body.getvalue()

    def preview_platform(self):
        snapshot, body = self.sprite()
        platform = self.platform()
        def data(path, params=None, **kwargs):
            if path.endswith('/view'):
                return {'title': 'Test', 'owner': {'mid': 42, 'name': 'Creator'}, 'pages': [{'cid': 1, 'duration': 51}]}
            if path.endswith('/v2'):
                return {'subtitle': {'subtitles': []}}
            return snapshot
        platform.json = Mock(side_effect=data)
        platform.request = Mock(side_effect=lambda url, **options: (
            {'code': 0, 'data': {'subtitle': {'subtitles': []}}}
            if urlparse(url).path == '/x/player/wbi/v2' else body))
        return platform

    def test_dark_and_blue_frames_keep_exact_index_time_pairing(self):
        snapshot, body = self.sprite()
        platform = self.platform()
        platform.request = Mock(return_value=body)
        frames = native_frames(platform, snapshot, 51, self.root, count=6)
        self.assertEqual([f['time'] for f in frames], [0, 10, 20, 30, 40, 50])
        with Image.open(frames[1]['path']) as image:
            self.assertLess(max(image.getpixel((20, 15))), 5)
        with Image.open(frames[2]['path']) as image:
            self.assertGreater(image.getpixel((20, 15))[2], 200)

    def test_dense_cache_does_not_replace_light_preview_and_offline_sheet_works(self):
        platform = self.preview_platform()
        dense = preview(platform, URL, density='dense', max_frames=6, make_sheet=True)
        self.assertEqual(len(dense['frames']), 6)
        self.assertEqual(dense['contact_sheet']['cells'][2]['time'], 20)
        self.assertEqual(dense['uploader_id'], '42')
        self.assertEqual(sum(block.type == 'image' for block in pack(dense)), 1)
        light = preview(platform, URL)
        self.assertEqual(light['requested_frames'], 5)
        self.assertNotIn('contact_sheet', light)
        self.assertNotEqual(Path(light['frames'][0]['path']).parent, Path(dense['frames'][0]['path']).parent)
        platform.offline = True
        platform.json = Mock(side_effect=AssertionError('offline cache'))
        repeated = preview(platform, URL, density='dense', max_frames=6, make_sheet=True)
        self.assertEqual(repeated['frames'], dense['frames'])

    def test_batch_preserves_success_and_failure_without_scroll_state(self):
        platform = self.preview_platform()
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(platform)), \
                patch('scroll_agent.agent.Agent', side_effect=AssertionError('no Scroll')):
            result = self.reader.preview_batch([URL, 'invalid'], density='dense', max_frames=6)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([row['status'] for row in result['items']], ['ready', 'failed'])
        self.assertTrue(result['items'][0]['frame_details_omitted'])
        self.assertEqual(sum(block.type == 'image' for block in pack(result)), 1)
        self.assertFalse((self.root / 'data/agent/memory.sqlite3').exists())

    def test_invalid_options_fail_before_authentication(self):
        with patch.object(self.reader, '_material_platform') as create:
            for options in ({'density': 'wrong'}, {'max_frames': 121}, {'max_frames': True}):
                with self.assertRaises(ReaderError):
                    self.reader.preview(URL, **options)
            with self.assertRaises(ReaderError):
                self.reader.preview_batch([URL] * 11)
            create.assert_not_called()

    def test_owned_source_frames_are_reused_before_native_network_preview(self):
        session = 'v_' + 'a' * 24
        media = self.root / 'cached.mp4'
        media.write_bytes(b'fixture')
        frames = []
        for index in range(2):
            path = self.root / f'cached-{index}.jpg'
            Image.new('RGB', (80, 40), 'blue').save(path)
            frames.append({'id': f'read:{index}', 'index': index, 'timestamp_seconds': index * 10, 'path': str(path)})
        self.reader.save({'id': session, 'source': {'platform': 'bilibili', 'canonical': URL, 'identity': {}},
                          'authentication': {'account_marker': 'test_account'}, 'media_path': str(media), 'title': 'Cached',
                          'metadata': {'duration_seconds': 20}, 'speech': [],
                          'reads': [{'id': 'read', 'start': 0, 'end': 20, 'frames': frames}]})
        platform = self.platform(offline=True)
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(platform)), \
                patch.object(self.reader, 'read', side_effect=AssertionError('frames already exist')), \
                patch('video_reader.preview.preview', side_effect=AssertionError('must reuse owned media')):
            result = self.reader.preview(URL, offline=True, max_frames=2, contact_sheet=True)
        self.assertEqual(result['source_session_id'], session)
        self.assertEqual(result['frame_precision'], 'source_frame')
        self.assertEqual([frame['time'] for frame in result['frames']], [0, 10])
        self.assertEqual(result['contact_sheet']['precision'], 'source_frame')


class InterfaceParityTests(MaterialFixture):
    def test_new_cli_and_mcp_route_through_same_reader_methods(self):
        for argv, tool, kwargs, method in [
            (['preview', URL, '--density', 'dense', '--max-frames', '6', '--contact-sheet', '--offline'],
             'video_preview', dict(source=URL, offline=True, density='dense', max_frames=6, contact_sheet=True), 'preview'),
            (['uploader-videos', '42', '--page', '2', '--offline'],
             'video_uploader_videos', dict(source='42', page=2, offline=True), 'uploader_videos'),
            (['preview-batch', URL, '--density', 'dense', '--no-contact-sheet'],
             'video_preview_batch', dict(sources=[URL], density='dense', contact_sheet=False), 'preview_batch')]:
            calls = []
            def record(*args, **options):
                import inspect
                bound = inspect.signature(getattr(Reader, method)).bind(self.reader, *args, **options)
                bound.apply_defaults()
                calls.append({key: value for key, value in bound.arguments.items() if key != 'self'})
                return {'status': 'ready'}
            with self.subTest(method=method), patch.object(cli, 'Reader', return_value=self.reader), \
                    patch.object(mcp_server, 'reader', self.reader), patch.object(self.reader, method, side_effect=record), \
                    patch('sys.argv', ['reader', *argv]), patch('sys.stdout', new_callable=StringIO):
                self.assertEqual(cli.main(), 0)
                getattr(mcp_server, tool)(**kwargs)
                self.assertEqual(calls[0], calls[1])

    def test_blocked_uploader_is_nonzero_cli_exit(self):
        with patch.object(cli, 'Reader', return_value=self.reader), \
                patch.object(self.reader, 'uploader_videos', return_value={'status': 'blocked', 'items': []}), \
                patch('sys.argv', ['reader', 'uploader-videos', '42']), patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(cli.main(), 1)
