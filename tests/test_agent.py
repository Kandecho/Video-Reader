from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from PIL import Image

from scroll_agent.agent import Agent, validate
from scroll_agent.memory import Memory
from video_reader.platform import Platform, PlatformError
from scroll_agent.schedule import in_window, next_run, validate as validate_wake
from video_reader.common import ReaderError, read_json, write_json
from video_reader.preview import preview, snapshot_positions
from video_reader.reader import Reader


URL = 'https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class AgentFixture(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.test-work'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / 'config.json'
        write_json(self.config_path, {'cache_dir': 'cache', 'preview': {'network': {'min_gap_seconds': 0}}, 'agent': {'directory': 'agent',
                   'network': {'min_gap_seconds': 0}, 'deep_read': {'enabled': False}}})
        self.reader = Reader(self.config_path)
        self.platform = Mock(scope='account_one', sender='123', csrf='not_a_real_csrf', offline=False)
        self.platform.trace = []
        self.platform.status.return_value = {}
        self.platform.request.return_value = {'code': 0, 'data': {'msg_key': 654}}
        self.agent = Agent(self.reader, platform=self.platform)
        self.material = {'url': URL, 'bvid': 'BV1E1421t7m2', 'part': 1, 'title': 'A useful video',
                         'material_level': 'preview', 'reading_status': 'previewed_not_read',
                         'caption': {'segments': [{'start': 0, 'end': 2, 'text': 'An actual point'}]},
                         'frames': [], 'gaps': []}

    def prepare(self):
        with patch('scroll_agent.agent.preview.candidates', return_value=[{'url': URL}]), \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', return_value=self.material):
            return self.agent.prepare()

    def decision(self, **extra):
        return {'decisions': [{'url': URL, 'recommend': True, 'reason': 'Specific evidence supports this topic',
                               'needs_deep_read': False, **extra}]}


class MemoryTests(AgentFixture):
    def test_mature_local_fts_chinese_recall_and_account_isolation(self):
        self.agent.memory.remember('喜欢深入解释量子计算原理', 'preference')
        self.agent.memory.remember('本轮观察到产品介绍', 'observation', URL)
        found = self.agent.memory.recall('量子计算')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['kind'], 'preference')
        other = Memory(self.agent.root, 'other_account')
        self.assertEqual(other.recall('量子计算'), [])
        self.assertEqual(self.agent.memory.context()['feedback'], [])

    def test_memory_dedup_forget_and_literal_query(self):
        first = self.agent.memory.remember('喜欢原理解释', 'feedback')
        again = self.agent.memory.remember('喜欢原理解释', 'feedback')
        self.assertEqual(first['id'], again['id'])
        self.assertFalse(again['created'])
        self.assertEqual(self.agent.memory.recall('原理')[0]['kind'], 'feedback')
        self.assertEqual(self.agent.memory.recall('" OR *'), [])
        with self.assertRaises(ReaderError):
            Memory(self.agent.root, 'other').forget(first['id'])
        self.agent.memory.forget(first['id'])
        self.assertEqual(self.agent.memory.recall(), [])

    def test_delivery_reservation_is_shared_and_account_scoped(self):
        self.assertTrue(self.agent.memory.reserve_delivery(9, [URL]))
        self.assertFalse(Memory(self.agent.root, self.agent.scope).reserve_delivery(9, [URL]))
        self.assertTrue(Memory(self.agent.root, 'other').reserve_delivery(9, [URL]))


class RoundTests(AgentFixture):
    def test_prepare_does_not_download_and_retains_preview_status(self):
        with patch.object(self.reader, 'open', side_effect=AssertionError('must not download')):
            packet = self.prepare()
        self.assertEqual(packet['previews'][0]['reading_status'], 'previewed_not_read')
        self.assertEqual(self.agent.memory.load_run(packet['run_id'])['status'], 'prepared')
        self.assertIn(URL, self.agent.memory.excluded(24))
        self.platform.request.assert_not_called()

    def test_finish_dry_run_archives_and_separates_user_feedback(self):
        packet = self.prepare()
        result = self.agent.finish(packet['run_id'], self.decision())
        self.assertEqual(len(result['selected']), 1)
        self.assertEqual(result['delivery']['status'], 'not_sent')
        self.assertTrue((self.agent.directory(packet['run_id']) / 'archive.md').is_file())
        self.assertEqual(self.agent.memory.recall(kind='feedback'), [])
        self.assertEqual(len(self.agent.memory.recall(kind='observation')), 1)
        self.platform.request.assert_not_called()

    def test_unknown_duplicate_omitted_and_insufficient_decisions_rejected(self):
        packet = self.prepare()
        for decision in [self.decision(url='https://example.com/'), {'decisions': []},
                         {'decisions': self.decision()['decisions'] * 2}, self.decision(needs_deep_read=True)]:
            with self.subTest(decision=decision), self.assertRaises(ReaderError):
                self.agent.finish(packet['run_id'], decision)

    def test_no_material_cannot_be_recommended(self):
        self.material['caption'] = None
        packet = self.prepare()
        with self.assertRaises(ReaderError):
            self.agent.finish(packet['run_id'], self.decision())

    def test_single_private_post_and_repeated_finish_never_resends(self):
        self.agent.options['delivery'].update(enabled=True, recipient_uid=999)
        packet = self.prepare()
        result = self.agent.finish(packet['run_id'], self.decision(), dry_run=False)
        self.assertEqual(result['delivery']['status'], 'accepted_not_receipt_verified')
        self.assertFalse(result['delivery']['receipt_verified'])
        self.agent.finish(packet['run_id'], self.decision(), dry_run=False)
        self.assertEqual(self.agent.deliver(packet['run_id'])['status'], 'duplicate_or_uncertain_not_resent')
        self.assertEqual(self.platform.request.call_count, 1)
        form = self.platform.request.call_args.kwargs['form']
        self.assertEqual(form['msg[receiver_id]'], '999')
        self.assertNotIn('not_a_real_csrf', form['msg[content]'])
        self.assertIn(URL, form['msg[content]'])

    def test_timeout_is_uncertain_and_never_automatically_retried(self):
        self.agent.options['delivery'].update(enabled=True, recipient_uid=999)
        self.platform.request.side_effect = ReaderError('network timeout')
        packet = self.prepare()
        result = self.agent.finish(packet['run_id'], self.decision(), dry_run=False)
        self.assertEqual(result['delivery']['status'], 'uncertain')
        self.agent.deliver(packet['run_id'])
        self.assertEqual(self.platform.request.call_count, 1)

    def test_test_message_needs_confirmation_and_only_sends_once(self):
        self.agent.options['delivery']['recipient_uid'] = 999
        with self.assertRaises(ReaderError):
            self.agent.test_message()
        self.agent.test_message(confirm=True)
        self.agent.test_message(confirm=True)
        self.assertEqual(self.platform.request.call_count, 1)
        self.assertFalse(self.agent.options['delivery']['enabled'])

    def test_run_failures_keep_local_archive_without_delivery(self):
        with patch('scroll_agent.agent.preview.candidates', return_value=[{'url': URL}]), \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', return_value=self.material):
            with self.assertRaises(ReaderError):
                self.agent.run(evaluator=Mock(side_effect=ReaderError('host stopped')))
        run_id = self.agent.memory.recent_runs()[0]['id']
        self.assertEqual(self.agent.memory.load_run(run_id)['status'], 'failed')
        self.assertTrue((self.agent.directory(run_id) / 'archive.md').exists())
        self.platform.request.assert_not_called()

    def test_platform_failure_is_not_empty_success(self):
        with patch('scroll_agent.agent.preview.candidates', side_effect=PlatformError('platform_paused:-412')):
            result = self.agent.run(evaluator=Mock(side_effect=AssertionError('no host for no material')))
        self.assertEqual(result['status'], 'acquisition_failed')
        self.assertTrue(result['failures'])

    def test_config_disabled_by_default_and_invalid_modes_rejected(self):
        validate(self.reader.config['agent'])
        self.assertFalse(self.agent.options['wake']['enabled'])
        self.assertFalse(self.agent.options['delivery']['enabled'])
        self.agent.options['candidate_count'] = 1.2
        with self.assertRaises(ReaderError):
            validate(self.agent.options)


class PlatformTests(AgentFixture):
    def client(self, transport, offline=False):
        with patch('video_reader.platform.credentials', return_value={'account_marker': 'one', 'cookies': []}):
            return Platform(self.reader.config, transport=transport, offline=offline)

    def test_cache_budget_across_instances_and_offline_zero_requests(self):
        transport = Mock(return_value=b'{"code":0,"data":{"value":1}}')
        first = self.client(transport)
        first.json('/test', ttl=100)
        second = self.client(transport, offline=True)
        self.assertEqual(second.json('/test', ttl=100)['value'], 1)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(first.status()['count'], 1)
        with self.assertRaisesRegex(PlatformError, 'offline_cache_miss'):
            second.json('/other', ttl=100)

    def test_restriction_persists_cache_still_usable_and_no_retry(self):
        transport = Mock(side_effect=[b'{"code":0,"data":{"value":1}}', b'{"code":-412}'])
        client = self.client(transport)
        client.json('/cached', ttl=100)
        with self.assertRaises(PlatformError):
            client.json('/rejected')
        client.json('/cached', ttl=100)
        with self.assertRaisesRegex(PlatformError, 'platform_paused'):
            self.client(transport).json('/not_cached')
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(client.status()['count'], 2)
        client.resume()
        self.assertEqual(client.status()['count'], 2)

    def test_signed_search_cache_ignores_only_volatile_signature(self):
        transport = Mock(return_value=b'{"code":0,"data":{"result":[]}}')
        self.client(transport).request('https://api.bilibili.com/x/web-interface/wbi/search/type?keyword=topic&wts=1&w_rid=old', ttl=100)
        offline = self.client(transport, offline=True)
        offline.request('https://api.bilibili.com/x/web-interface/wbi/search/type?w_rid=new&wts=2&keyword=topic', ttl=100)
        with self.assertRaisesRegex(PlatformError, 'offline_cache_miss'):
            offline.request('https://api.bilibili.com/x/web-interface/wbi/search/type?keyword=different&wts=2&w_rid=new', ttl=100)
        self.assertEqual(transport.call_count, 1)

    def test_http429_and_response_size_and_untrusted_destination(self):
        transport = Mock(side_effect=HTTPError('https://api.bilibili.com/', 429, '', {}, None))
        client = self.client(transport)
        with self.assertRaises(PlatformError):
            client.json('/test')
        self.assertEqual(client.status()['paused'], 'http_429')
        with self.assertRaisesRegex(PlatformError, 'untrusted'):
            client.request('https://bilibili.com.attacker.example/')
        with self.assertRaisesRegex(PlatformError, 'write_not_authorized'):
            client.request('https://api.bilibili.com/x/reply', form={})

    def test_native_snapshot_placeholder_and_part_identity(self):
        snapshot = {'index': [0, 0, 10, 20], 'img_x_len': 3, 'img_y_len': 1}
        selected = snapshot_positions(snapshot, [0, 10, 25])
        self.assertEqual([row['column'] for row in selected], [0, 1, 2])

    def test_preview_preserves_part_and_empty_caption_not_silence(self):
        platform = self.client(Mock())
        platform.json = Mock(side_effect=[{'title': 'video', 'pages': [{'cid': 1, 'duration': 10}, {'cid': 2, 'duration': 20}]},
                                         {'subtitle': {'subtitles': []}}, {}])
        with patch('video_reader.preview.native_frames', return_value=[]):
            result = preview(platform, URL.replace('p=1', 'p=2'))
        self.assertEqual(result['part'], 2)
        self.assertEqual(result['cid'], 2)
        self.assertIn('no_platform_caption', result['gaps'])
        self.assertNotIn('no_speech', result['gaps'])
        self.assertEqual(platform.json.call_args_list[1].args[1]['cid'], 2)


class ScheduleTests(AgentFixture):
    def wake(self, **extra):
        return {**self.agent.options['wake'], 'enabled': True, 'mode': 'fixed', 'interval_seconds': 60,
                'timezone': 'UTC', **extra}

    def test_disabled_fixed_and_range_are_parameters(self):
        start = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
        self.assertIsNone(next_run(start, self.agent.options['wake']))
        self.assertEqual(next_run(start, self.wake()), start + timedelta(seconds=60))
        ranged = self.wake(mode='range', min_seconds=120, max_seconds=300)
        self.assertEqual(next_run(start, ranged, uniform=lambda lower, upper: upper), start + timedelta(seconds=300))
        with self.assertRaises(ReaderError):
            validate_wake(self.wake(mode='range', min_seconds=300, max_seconds=120))

    def test_windows_and_overnight_timezone(self):
        wake = self.wake(timezone='+08:00', windows=[{'start': '22:00', 'end': '02:00'}])
        start = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)
        self.assertFalse(in_window(start, wake))
        self.assertEqual(next_run(start, wake), datetime(2026, 10, 22, 14, tzinfo=timezone.utc))
        self.assertTrue(in_window(datetime(2026, 10, 22, 17, tzinfo=timezone.utc), wake))

    def test_tick_is_opt_in_and_runs_once_without_catch_up(self):
        self.assertEqual(self.agent.tick()['status'], 'disabled')
        self.agent.options['wake'] = self.wake()
        start = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
        self.assertEqual(self.agent.tick(now=start)['status'], 'scheduled')
        self.assertEqual(self.agent.tick(now=start)['status'], 'waiting')
        with patch.object(self.agent, 'run', return_value={'status': 'finished', 'run_id': 'fixture'}) as execute:
            self.assertEqual(self.agent.tick(now=start + timedelta(hours=4), evaluator=Mock())['status'], 'finished')
            self.assertEqual(self.agent.tick(now=start + timedelta(hours=4), evaluator=Mock())['status'], 'waiting')
        self.assertEqual(execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()
