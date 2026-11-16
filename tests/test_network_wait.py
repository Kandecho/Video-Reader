"""Network cooldowns preserve task checkpoints and the original execution permit."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from reading_tasks.consume import Consumer
from scroll_agent.background import Background
from video_reader.common import ReaderError, write_json
from video_reader.community import failure
from video_reader.platform import PlatformError
from video_reader.reader import Reader
from video_reader.sources import AcquisitionError


READY = {'available': True, 'cpu_percent': 1, 'available_memory_mb': 8192}


class NetworkWaitTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.test-work'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='network-wait-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': 'cache', 'tasks': {'directory': 'tasks'},
                            'agent': {'directory': 'agent'}})
        self.reader = Reader(config)
        self.now = datetime(2026, 11, 12, 4, tzinfo=timezone.utc).timestamp()
        clock_patch = patch('reading_tasks.control.time.time', side_effect=lambda: self.now)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        resources = patch('reading_tasks.control.sample', return_value=READY)
        resources.start()
        self.addCleanup(resources.stop)
        self.sync = Mock(return_value={'feed': {'status': 'ready'}})
        self.bg = Background(self.reader, clock=lambda: self.now, probe=lambda: READY, sync=self.sync)
        self.bg.control.configure({'enabled': True, 'sync_enabled': False, 'daily_task_limit': 3,
                                   'window_start': '00:00', 'window_end': '00:00',
                                   'max_cpu_percent': 100, 'min_available_memory_mb': 0})
        self.consumer = self.bg.consumer
        self.item = self.consumer.queue.enqueue('BV0000000001', task='整理本片内容')['item']
        self.jobs = {}
        self.starts = 0
        self.reader.job = Mock(side_effect=self._job)

    def _job(self, action, job_id=None, **kwargs):
        if action == 'start':
            self.starts += 1
            job_id = 'j_' + f'{self.starts:024x}'
            self.jobs[job_id] = 'queued'
        return {'job_id': job_id, 'status': self.jobs[job_id]}

    def _error(self, *, wrapped=False):
        details = {'reason': 'repeated_request', 'retry_at': self.now + 90,
                   'retry_after_seconds': 90, 'scope': 'account', 'request_key': 'request-key'}
        if wrapped:
            return AcquisitionError('Metadata acquisition is temporarily waiting',
                                    details={'network_guard': details})
        error = PlatformError('platform_request_cooldown')
        error.details = details
        return error

    def _waiting_run(self, *, background=False):
        started = self.bg.consume(force=True)['run'] if background else self.consumer.start(self.item['id'])
        run = started['run_id']
        with patch.object(self.consumer, '_prepare', side_effect=self._error()):
            with self.assertRaises(PlatformError):
                self.consumer.execute(run)
        self.jobs[self.consumer.load(run)['job_id']] = 'failed'
        return run

    def test_wrapped_cooldown_persists_checkpoint_and_public_wait(self):
        run = self.consumer.start(self.item['id'])['run_id']
        state = self.consumer.load(run)
        observations = [{'accepted_at': self.now - 10, 'marker': 'accepted reading'}]
        evidence = [{'start': 6, 'end': 8, 'reason': 'Read the requested detail'}]
        state.update(phase='reading', index_id='ci_fixture', next_block=4, blocks=[{} for _ in range(8)],
                     observations=copy.deepcopy(observations), pending_evidence=copy.deepcopy(evidence))
        self.consumer.save(state, 'running')
        self.reader.content = Mock(side_effect=self._error(wrapped=True))
        with self.assertRaises(AcquisitionError):
            self.consumer.execute(run)
        self.jobs[state['job_id']] = 'failed'

        restored = Consumer(self.reader)
        saved = restored.load(run)
        status = restored.status(run)
        self.assertEqual(saved['status'], 'waiting')
        self.assertEqual(saved['next_block'], 4)
        self.assertEqual(saved['observations'], observations)
        self.assertEqual(saved['pending_evidence'], evidence)
        self.assertEqual(status['status'], 'waiting')
        self.assertEqual(status['next_action'], 'wait_until_retry_at')
        self.assertEqual(status['retry_at'], self.now + 90)
        self.assertEqual(status['retry_after_seconds'], 90)
        self.assertEqual(status['network_wait']['request_key'], 'request-key')
        self.assertEqual(restored.run_info(run)['retry_at'], self.now + 90)
        self.assertEqual(restored.queue.show(self.item['id'])['state'], 'pending')

    def test_explicit_resume_does_not_start_before_retry_and_reuses_run_after(self):
        run = self._waiting_run()
        original_job = self.consumer.load(run)['job_id']
        self.reader.job.reset_mock()
        with patch('reading_tasks.consume.time.sleep') as sleep:
            result = self.consumer.resume(run)
        self.assertEqual(result['next_action'], 'wait_until_retry_at')
        self.assertEqual(self.starts, 1)
        self.assertTrue(all(call.args[0] == 'status' for call in self.reader.job.call_args_list))
        sleep.assert_not_called()

        self.now += 90
        self.assertEqual(self.consumer.status(run)['next_action'], 'resume')
        resumed = self.consumer.resume(run)
        self.assertEqual(resumed['run_id'], run)
        self.assertNotEqual(self.consumer.load(run)['job_id'], original_job)
        self.assertEqual(self.starts, 2)
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0], 1)

    def test_background_wait_and_resume_keep_permit_and_host_retry_budget(self):
        run = self._waiting_run(background=True)
        permit = self.bg.control.permit_for_run(run)
        self.reader.job.reset_mock()
        waiting = self.bg.consume(force=True)
        self.assertEqual(waiting['status'], 'waiting')
        self.assertEqual(waiting['reason'], 'platform_request_cooldown')
        self.assertEqual(waiting['retry_at'], self.now + 90)
        self.assertEqual(self.starts, 1)
        self.assertIsNone(self.bg.control.state()['paused_reason'])

        self.now += 91
        resumed = self.bg.consume(force=True)
        self.assertEqual(resumed['status'], 'resumed')
        self.assertEqual(resumed['run']['run_id'], run)
        current = self.bg.control.permit_for_run(run)
        self.assertEqual(current['token'], permit['token'])
        self.assertEqual(current['host_retries'], 0)
        self.assertEqual(current['resumes'], 0)
        self.assertEqual(self.bg.control.usage()['tasks_started'], 1)
        self.assertEqual(self.bg.control.usage()['host_attempts'], 0)
        self.assertEqual(self.starts, 2)
        self.sync.assert_not_called()

    def test_user_pause_is_not_cleared_when_network_wait_expires(self):
        run = self._waiting_run(background=True)
        self.bg.control.pause()
        self.now += 91
        self.assertEqual(self.bg.consume(force=True)['reason'], 'user_paused')
        self.assertEqual(self.bg.control.state()['paused_reason'], 'user_paused')
        self.assertEqual(self.consumer.load(run)['status'], 'waiting')
        self.assertEqual(self.starts, 1)
        self.consumer.queue.update(self.item['id'], state='paused')
        with self.assertRaisesRegex(ReaderError, 'paused'):
            self.consumer.resume(run)
        self.assertEqual(self.starts, 1)

    def test_intake_cooldown_reports_wait_without_dispatching_a_task(self):
        self.bg.control.configure({'sync_enabled': True})
        self.sync.side_effect = self._error(wrapped=True)
        result = self.bg.intake(force=True)
        self.assertEqual(result['status'], 'waiting')
        self.assertEqual(result['reason'], 'platform_request_cooldown')
        self.assertEqual(result['retry_at'], self.now + 90)
        self.assertEqual(self.bg.control.usage()['tasks_started'], 0)
        self.assertEqual(self.starts, 0)
        self.assertIsNone(self.bg.control.state()['paused_reason'])

    def test_community_wait_keeps_retry_page_separate_from_platform_pause(self):
        base = {'items': [], 'next_page': 3, 'page_complete': False}
        waiting = failure(base, self._error(wrapped=True))
        self.assertEqual(waiting['status'], 'waiting')
        self.assertEqual(waiting['next_page'], 3)
        self.assertEqual(waiting['error']['code'], 'platform_request_cooldown')
        self.assertEqual(waiting['error']['next_action'], 'wait_until_retry_at')
        self.assertEqual(waiting['error']['retry_at'], self.now + 90)
        blocked = failure(base, PlatformError('platform_http_429'))
        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['error']['next_action'], 'inspect_platform_status_do_not_auto_retry')
        self.assertNotIn('retry_at', blocked['error'])


if __name__ == '__main__':
    unittest.main()
