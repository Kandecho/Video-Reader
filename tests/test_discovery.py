from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from video_reader.common import ReaderError, write_json
from video_reader.reader import Reader
from video_reader.discovery import _search_params, WBI_INDICES


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '.test-work'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': 'cache', 'bilibili_auth': {'enabled': False},
                            'preview': {'network': {'min_gap_seconds': 0}}})
        self.reader = Reader(config)
        signing = patch('video_reader.discovery._search_params', side_effect=lambda session, params: params)
        self.signing = signing.start()
        self.addCleanup(signing.stop)

    def item(self, bvid='BV1E1421t7m2', **extra):
        return {'bvid': bvid, 'title': 'A <em class="keyword">topic</em> &amp; B', 'author': 'Author',
                'duration': '3:12', 'pubdate': 1234, 'play': 42, **extra}

    def response(self, items, **extra):
        return {'code': 0, 'data': {'result': items, 'numPages': 3, 'numResults': 21, **extra}}

    def test_search_normalizes_metadata_and_encodes_query(self):
        with patch('video_reader.discovery.Platform.request', return_value=self.response([self.item()])) as request:
            result = self.reader.search('a & 中文', page_size=5, order='newest')
        params = parse_qs(urlparse(request.call_args.args[0]).query)
        self.assertEqual(params['keyword'], ['a & 中文'])
        self.assertEqual(params['order'], ['pubdate'])
        item = result['items'][0]
        self.assertEqual(item['title'], 'A topic & B')
        self.assertEqual(item['duration_seconds'], 192)
        self.assertEqual(item['url'], 'https://www.bilibili.com/video/BV1E1421t7m2?p=1')
        self.assertEqual(item['reading_status'], 'not_assessed')
        self.assertEqual(result['next_page'], 2)
        self.assertNotIn('cookies', str(result))

    def test_cached_duration_duplicates_and_empty_page_still_continue(self):
        write_json(self.reader.cache / ('v_' + 'a' * 24) / 'manifest.json',
                   {'source': {'platform': 'bilibili', 'bvid': 'BV1E1421t7m2', 'page': 2}})
        items = [self.item(), self.item(), self.item('BV1Xt4y1P7BH', duration='39:00'),
                 self.item('BV1TdSxByEVA', duration=None), {'bvid': 'invalid'}]
        with patch('video_reader.discovery.Platform.request', return_value=self.response(items)):
            result = self.reader.search('topic', max_duration=300)
            included = self.reader.search('topic', max_duration=300, exclude_cached=False)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['next_page'], 2)
        self.assertEqual(result['excluded'], {'cached': 1, 'duplicate': 1, 'duration': 2, 'invalid': 1})
        self.assertTrue(included['items'][0]['cached'])

    def test_popular_and_last_page(self):
        item = self.item(duration=63, owner={'name': 'Creator'}, stat={'view': 99})
        item.pop('author')
        item.pop('play')
        with patch('video_reader.discovery.Platform.request', return_value={'code': 0, 'data': {'list': [item], 'no_more': True}}) as request:
            result = self.reader.discover()
        self.assertIn('/popular?', request.call_args.args[0])
        self.assertIsNone(result['next_page'])
        self.assertEqual(result['items'][0]['uploader'], 'Creator')
        self.assertEqual(result['items'][0]['view_count'], 99)

    def test_invalid_controls_fail_before_network(self):
        options = [{'page': True}, {'page': 0}, {'page_size': 51}, {'order': 'unknown'},
                   {'min_duration': float('nan')}, {'max_duration': float('inf')},
                   {'min_duration': 10, 'max_duration': 2}, {'exclude_cached': 1}]
        with patch('video_reader.discovery.Platform.request') as request:
            for option in options:
                with self.subTest(option=option), self.assertRaises(ReaderError):
                    self.reader.search('topic', **option)
            for query in ('', ' ', 'a' * 201):
                with self.assertRaises(ReaderError):
                    self.reader.search(query)
            request.assert_not_called()

    def test_platform_errors_are_not_empty_success(self):
        for response in ({'code': -412}, {'code': 0, 'data': {'result': 'broken'}},
                         {'code': 0, 'data': {'result': [], 'numPages': None}}):
            with patch('video_reader.discovery.Platform.request', return_value=response):
                with self.assertRaises(ReaderError):
                    self.reader.search('topic')

    def test_managed_profile_covers_request_and_cleanup(self):
        events = []

        @contextmanager
        def profile(auth, options):
            events.append('enter')
            try:
                yield options, options, {'authenticated': True, 'account_marker': 'test'}
            finally:
                events.append('cleanup')

        def request(session, url):
            self.assertEqual(events, ['enter'])
            raise ReaderError('offline')

        with patch('video_reader.discovery.BilibiliAuth.reader_profile', profile), patch('video_reader.discovery.Platform.request', request):
            with self.assertRaisesRegex(ReaderError, 'offline'):
                self.reader.discover()
        self.assertEqual(events, ['enter', 'cleanup'])

    def test_real_signing_device_cookie_and_stable_signature(self):
        import hashlib
        from urllib.parse import urlencode
        from video_reader.bilibili_auth import BiliSession, _cookie_value
        session = BiliSession()
        lookup = 'abcdefghijklmnopqrstuvwxyz012345' * 2
        session.request = Mock(side_effect=[
            {'code': 0, 'data': {'b_3': 'test-device', 'b_4': 'test-device-four'}},
            {'code': 0, 'data': {'wbi_img': {'img_url': 'https://i0.hdslb.com/' + lookup[:32] + '.png',
                                           'sub_url': 'https://i0.hdslb.com/' + lookup[32:] + '.png'}}}])
        with patch('video_reader.discovery.time.time', return_value=1000):
            result = _search_params(session, {'keyword': "中!'文", 'page': 2})
        self.assertEqual(_cookie_value(session.jar, 'buvid3'), 'test-device')
        self.assertEqual(result['keyword'], '中文')
        salt = ''.join(lookup[index] for index in WBI_INDICES)
        expected = hashlib.md5((urlencode({'keyword': '中文', 'page': '2', 'wts': '1000'}) + salt).encode()).hexdigest()
        self.assertEqual(result['w_rid'], expected)


if __name__ == '__main__':
    unittest.main()
