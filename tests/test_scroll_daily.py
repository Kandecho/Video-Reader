from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from test_agent import AgentFixture, URL
from scroll_agent.agent import Agent
from video_reader.common import ReaderError, write_json
from video_reader.platform import Platform
from video_reader.reader import Reader
from video_reader import mcp_server


class DailyTests(AgentFixture):
    def enable(self):
        self.agent.options['delivery']['recipient_uid'] = 999
        self.agent.options['daily']['enabled'] = True
        self.agent.options['daily']['time'] = '00:00'

    def test_before_scheduled_time_does_not_freeze_the_first_video(self):
        self.enable()
        self.agent.options['daily']['time'] = '20:00'
        before = datetime(2026, 10, 23, 11, tzinfo=timezone.utc)
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('no early feed')):
            self.assertEqual(self.agent.prepare_daily(now=before)['status'], 'before_daily_time')
        self.assertEqual(self.agent.status()['daily_runs'], [])
        self.platform.request.assert_not_called()

    def prepare_daily(self):
        rows = [{'url': URL, 'title': 'First'}, {'url': URL.replace('p=1', 'p=2'), 'title': 'Second'}]
        with patch('scroll_agent.agent.preview.candidates', return_value=rows) as discover, \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', return_value=self.material) as inspect:
            packet = self.agent.prepare_daily()
        inspect.assert_called_once_with(self.platform, URL)
        self.assertTrue(discover.call_args.kwargs['fresh'])
        return packet

    def test_first_video_ignores_preference_and_seen_filter(self):
        self.enable()
        self.agent.memory.record_video(URL, 'recommended', 'Already recommended')
        packet = self.prepare_daily()
        self.assertEqual([row['url'] for row in packet['candidates']], [URL])
        self.assertEqual(packet['selection_policy'], 'homepage_first_daily_trial')

    def test_negative_assessment_still_delivers_first_and_only_once(self):
        self.enable()
        packet = self.prepare_daily()
        result = self.agent.finish(packet['run_id'], self.decision(recommend=False), dry_run=False)
        self.assertEqual(result['selected'][0]['url'], URL)
        self.assertFalse(result['selected'][0]['recommend'])
        self.assertEqual(result['delivery']['status'], 'accepted_not_receipt_verified')
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('no second fetch')):
            again = self.agent.run(daily=True, dry_run=False, evaluator=Mock(side_effect=AssertionError('no model')))
        self.assertEqual(again['run_id'], result['run_id'])
        self.assertEqual(self.platform.request.call_count, 1)
        self.assertFalse(self.agent.options['delivery']['enabled'])
        state = self.agent.status()['daily_runs'][0]
        self.assertEqual(state['video']['url'], URL)
        self.assertEqual(state['assessment'][0]['recommend'], False)

    def test_restart_reuses_prepared_first_without_fetching(self):
        self.enable()
        packet = self.prepare_daily()
        second = Agent(self.reader, platform=self.platform)
        second.options['delivery']['recipient_uid'] = 999
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('must reuse')):
            self.assertEqual(second.prepare_daily()['run_id'], packet['run_id'])

    def test_next_day_can_deliver_same_first_video(self):
        self.enable()
        today = self.agent.daily_day()
        tomorrow = (datetime.fromisoformat(today) + timedelta(days=1)).date().isoformat()
        for day in (today, tomorrow):
            with patch.object(self.agent, 'daily_day', return_value=day):
                packet = self.prepare_daily()
                self.agent.finish(packet['run_id'], self.decision(), dry_run=False)
        self.assertEqual(self.platform.request.call_count, 2)

    def test_preview_failure_does_not_substitute_second_video(self):
        self.enable()
        with patch('scroll_agent.agent.preview.candidates', return_value=[{'url': URL, 'title': 'First'}, {'url': 'second'}]), \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', side_effect=ReaderError('Unavailable')):
            packet = self.agent.prepare_daily()
        self.assertEqual(packet['previews'][0]['url'], URL)
        self.assertEqual(packet['previews'][0]['material_level'], 'metadata_only')
        with self.assertRaises(ReaderError):
            self.agent.finish(packet['run_id'], self.decision())
        result = self.agent.finish(packet['run_id'], self.decision(recommend=False), dry_run=False)
        self.assertEqual(result['selected'][0]['url'], URL)

    def test_empty_homepage_is_visible_failure_and_sends_nothing(self):
        self.enable()
        with patch('scroll_agent.agent.preview.candidates', return_value=[]):
            result = self.agent.run(daily=True, dry_run=False)
        self.assertEqual(result['status'], 'acquisition_failed')
        self.assertTrue(result['failures'])
        self.platform.request.assert_not_called()

    def test_disabled_daily_does_not_send_even_when_finish_allows_delivery(self):
        self.agent.options['delivery']['recipient_uid'] = 999
        packet = self.prepare_daily()
        result = self.agent.finish(packet['run_id'], self.decision(), dry_run=False)
        self.assertEqual(result['delivery']['status'], 'disabled_local_archive_only')
        self.platform.request.assert_not_called()

    def test_day_boundary_is_beijing_not_utc(self):
        before = datetime(2026, 10, 23, 15, 59, tzinfo=timezone.utc)
        self.assertEqual(self.agent.daily_day(before), '2026-10-23')
        self.assertEqual(self.agent.daily_day(before + timedelta(minutes=1)), '2026-10-24')


class ReaderIndependenceTests(AgentFixture):
    def test_transport_validates_its_own_shared_budget(self):
        self.reader.config['preview']['network']['max_response_bytes'] = 1.2
        with patch('video_reader.platform.credentials', return_value={'account_marker': 'one', 'cookies': []}), \
                self.assertRaisesRegex(ReaderError, 'positive_integer'):
            Platform(self.reader.config)

    def test_reader_and_preview_ignore_invalid_scroll_business_configuration(self):
        write_json(self.config_path, {'cache_dir': 'cache', 'agent': None, 'preview': {'directory': 'preview'}})
        reader = Reader(self.config_path)
        with patch('video_reader.platform.credentials', return_value={'account_marker': 'one', 'cookies': []}):
            platform = Platform(reader.config, offline=True)
        self.assertEqual(platform.status(), {'day': None, 'count': None, 'paused': None, 'last_request': None})
        self.assertFalse((self.root / 'memory.sqlite3').exists())
        with self.assertRaisesRegex(ReaderError, 'write_not_authorized'):
            platform.request('https://api.vc.bilibili.com/web_im/v1/web_im/send_msg', form={})

    def test_general_preview_does_not_create_scroll_agent(self):
        from contextlib import nullcontext
        with patch('scroll_agent.agent.Agent', side_effect=AssertionError('Reader must not depend on Scroll')), \
                patch.object(mcp_server.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.preview.preview', return_value=self.material):
            blocks = mcp_server.video_preview(URL)
        self.assertEqual(blocks[0].type, 'text')
