"""Public business acquisition stays bounded across authentication modes and backends."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from video_reader.acquisition_budget import Budget
from video_reader.bilibili_auth import BilibiliAuth, cookie_value
from video_reader.catalog import account_scope
from video_reader.common import ReaderError, read_json, write_json
from video_reader.platform import Platform, PlatformError, credentials
from video_reader.reader import Reader


class PlatformBoundaryTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.test-work'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': 'cache', 'bilibili_auth': {'enabled': False},
                            'preview': {'network': {'min_gap_seconds': 0}}})
        self.reader = Reader(config)
        self.calls = []

    def transport(self, client, url, form=None, **kwargs):
        self.calls.append((url, client.scope, cookie_value(client.jar, 'SESSDATA')))
        path = urlparse(url).path
        if path.endswith('/spi'):
            data = {'b_3': 'fixture-device', 'b_4': 'fixture-device-four'}
        elif path.endswith('/nav'):
            data = {'wbi_img': {'img_url': 'https://i0.hdslb.com/' + 'a' * 32 + '.png',
                                'sub_url': 'https://i0.hdslb.com/' + 'b' * 32 + '.png'}}
        else:
            item = {'bvid': 'BV0000000001', 'title': 'Original', 'duration': 30}
            data = {'result': [item], 'numPages': 1} if '/search/' in path else {'list': [item], 'no_more': True}
        return json.dumps({'code': 0, 'data': data}).encode()

    def budget(self, scope='bilibili-anonymous'):
        return Budget({'directory': Path(self.reader.config['preview']['directory']) / scope,
                       'options': self.reader.config['preview']['network']})

    def test_public_search_signing_and_result_share_the_downloader_budget(self):
        self.reader.config['preview']['network']['daily_requests'] = 3
        with patch.object(Platform, '_transport', autospec=True, side_effect=self.transport):
            result = self.reader.search('topic')
        self.assertEqual(result['items'][0]['title'], 'Original')
        self.assertEqual(len(self.calls), 3)  # Device, signing key, business result.
        budget = self.budget()
        state = read_json(budget.path)
        self.assertEqual(state['count'], 3)
        self.assertNotIn('downloader_requests', state)
        with self.assertRaisesRegex(ReaderError, 'budget_exhausted'):
            budget.reserve()

    def test_shared_pause_and_exhaustion_prevent_all_discovery_requests(self):
        budget = self.budget()
        cases = [{'paused': 'http_429'},
                 {'day': time.strftime('%Y-%m-%d', time.gmtime()),
                  'count': self.reader.config['preview']['network']['daily_requests']}]
        with patch.object(Platform, '_transport', autospec=True, side_effect=self.transport) as network:
            for state in cases:
                write_json(budget.path, state)
                for call in (lambda: self.reader.search('topic'), self.reader.discover):
                    with self.assertRaises(PlatformError):
                        call()
            network.assert_not_called()

    def test_interval_and_response_limit_apply_to_public_discovery(self):
        self.reader.config['preview']['network']['min_gap_seconds'] = 3
        budget = self.budget()
        write_json(budget.path, {'day': time.strftime('%Y-%m-%d', time.gmtime()), 'count': 0, 'last_request': 123})
        with patch('video_reader.acquisition_budget.time.time', return_value=124), \
                patch('video_reader.acquisition_budget.time.sleep') as sleep, \
                patch.object(Platform, '_transport', autospec=True, side_effect=self.transport):
            self.reader.discover()
        sleep.assert_called_once_with(2)
        self.reader.config['preview']['network'].update(min_gap_seconds=0, max_response_bytes=4)
        with patch.object(Platform, '_transport', autospec=True, side_effect=self.transport), \
                self.assertRaisesRegex(PlatformError, 'response_too_large'):
            self.reader.discover()

    def test_discovery_preserves_anonymous_cookie_and_managed_modes(self):
        cookie = self.root / 'manual.txt'
        cookie.write_text('# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t2147483647\tSESSDATA\tuser-cookie\n', encoding='utf-8')
        with patch.object(Platform, '_transport', autospec=True, side_effect=self.transport), \
                patch('video_reader.bilibili_auth.BiliSession.request', side_effect=AssertionError('no auth network')):
            anonymous = self.reader.discover()
            self.assertIsNone(anonymous['authentication'])
            self.reader.config['platforms']['bilibili']['cookies_file'] = str(cookie)
            self.reader.discover()
            self.assertEqual(self.calls[-1][1:], ('bilibili-anonymous', 'user-cookie'))
            self.reader.config['bilibili_auth']['enabled'] = True
            auth = BilibiliAuth(self.reader.config)
            write_json(auth.path, {'schema_version': 1, 'account_marker': 'managed-one',
                                  'cookies': [{'name': 'SESSDATA', 'value': 'managed-cookie',
                                               'domain': '.bilibili.com', 'path': '/', 'expires': 2147483647}]})
            with patch.object(BilibiliAuth, '_maintain', return_value={'status': 'authenticated', 'authenticated': True, 'account_marker': 'managed-one'}):
                result = self.reader.discover()
            self.assertEqual(self.calls[-1][1:], ('managed-one', 'managed-cookie'))
            self.assertEqual(result['authentication']['account_marker'], 'managed-one')
        self.assertNotIn('cookie', json.dumps(result))

    def test_read_only_account_scope_and_filtered_snapshot_do_not_renew(self):
        self.reader.config['bilibili_auth']['enabled'] = True
        auth = BilibiliAuth(self.reader.config)
        with patch.object(BilibiliAuth, '_maintain', side_effect=AssertionError('no renewal')):
            self.assertIsNone(auth.account_scope())
            self.assertFalse(auth.directory.exists())
            record = {'schema_version': 1, 'account_marker': 'original-marker', 'refresh_token': 'private-refresh',
                      'cookies': [{'name': 'SESSDATA', 'value': 'original-cookie', 'domain': '.bilibili.com', 'path': '/'}]}
            write_json(auth.path, record)
            self.assertEqual(auth.account_scope(), 'original-marker')
            self.assertEqual(account_scope(self.reader.config, 'https://www.bilibili.com/video/BV0000000001'), 'original-marker')
            snapshot = credentials(self.reader.config)
            self.assertEqual(set(snapshot), {'account_marker', 'cookies'})
            snapshot['cookies'][0]['value'] = 'local-copy'
            self.assertEqual(read_json(auth.path), record)
            auth.path.write_text('{broken', encoding='utf-8')
            self.assertIsNone(auth.account_scope())
            self.reader.config['bilibili_auth']['enabled'] = False
            self.assertIsNone(auth.account_scope())


if __name__ == '__main__':
    unittest.main()
