import json
import subprocess
import sys
import time
from unittest.mock import Mock, patch

from test_agent import AgentFixture, URL
from scroll_agent.agent import Agent
from scroll_agent import host, mcp_server
from scroll_agent.cli import dispatch
from scroll_agent.memory import Memory
from video_reader.common import ReaderError, read_json, write_json


class ScrollStateTests(AgentFixture):
    def run_fixture(self, evaluator=None, **kwargs):
        with patch('scroll_agent.agent.preview.candidates', return_value=[{'url': URL}]), \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', return_value=self.material):
            return self.agent.run(evaluator=evaluator or Mock(return_value=self.decision()), **kwargs)

    def test_live_executor_and_abrupt_exit_are_visible_without_blocking_query(self):
        packet = self.prepare()
        run_id = packet['run_id']
        ready = self.root / 'ready'
        code = '''
from pathlib import Path
import os,sys,time
from filelock import FileLock
from scroll_agent.memory import Memory
from scroll_agent.runtime import Runtime
root, run_id, ready = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
memory = Memory(root, 'account_one')
with FileLock(str(root/'round.lock')):
    with Runtime(memory, root/'rounds'/'account_one'/run_id, run_id).working(
            'host_assessment', completed_stage='done', completed_status='completed'):
        ready.touch()
        until = time.monotonic() + 10
        while not ready.with_suffix('.stop').exists() and time.monotonic() < until:
            time.sleep(.05)
        os._exit(23)
'''
        process = subprocess.Popen([sys.executable, '-c', code, str(self.agent.root), run_id, str(ready)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            until = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < until:
                time.sleep(.05)
            self.assertTrue(ready.exists(), 'child did not acquire round ownership')
            start = time.monotonic()
            running = self.agent.status(run_id)
            self.assertLess(time.monotonic()-start, 2)
            self.assertEqual(running['status'], 'running')
            self.assertTrue(running['runtime']['worker_alive'])
            # Windows venv python.exe can be a launcher with a distinct child PID.
            self.assertIsInstance(running['runtime']['worker_pid'], int)
            self.assertFalse(running['recovery']['available'])
            with self.assertRaisesRegex(ReaderError, 'active'):
                self.agent.recover(run_id)
            ready.with_suffix('.stop').touch()
            process.wait(timeout=5)
            interrupted = self.agent.status(run_id)
            self.assertEqual(interrupted['status'], 'interrupted')
            self.assertFalse(interrupted['runtime']['worker_alive'])
            self.assertEqual(interrupted['checkpoint']['previews_ready'], 1)
            self.assertTrue(interrupted['recovery']['available'])
            # Observation preserves the recorded snapshot and its historical stage.
            self.assertEqual(self.agent.memory.load_run(run_id)['runtime']['status'], 'running')
        finally:
            if process.poll() is None:
                ready.with_suffix('.stop').touch()
                process.wait(timeout=15)
            process.stderr.close()

    def test_prepared_is_waiting_for_host_and_never_claims_full_reading(self):
        packet = self.prepare()
        state = self.agent.status(packet['run_id'])
        self.assertEqual(state['status'], 'prepared')
        self.assertEqual(state['runtime']['stage'], 'awaiting_host')
        self.assertEqual(state['runtime']['status'], 'waiting')
        self.assertFalse(state['runtime']['worker_alive'])
        self.assertFalse(state['checkpoint']['full_reading_completed'])
        self.agent.finish(packet['run_id'], self.decision())
        state = self.agent.status(packet['run_id'])
        self.assertEqual(state['checkpoint']['host_assessed_urls'], [URL])
        self.assertFalse(state['checkpoint']['full_reading_completed'])

    def test_interrupt_after_candidate_selection_recovers_the_same_candidate(self):
        with patch('scroll_agent.agent.preview.candidates', return_value=[{'url': URL}]), \
                patch.object(self.agent, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.agent.prepare()
        run_id = self.agent.memory.recent_runs()[0]['id']
        self.assertEqual(self.agent.status(run_id)['status'], 'interrupted')
        second = Agent(self.reader, platform=self.platform)
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('must not reselect')), \
                patch.object(second, '_cached_material', return_value=None), \
                patch('scroll_agent.agent.preview.preview', return_value=self.material):
            result = second.recover(run_id, evaluator=Mock(return_value=self.decision()))
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(result['run_id'], run_id)
        self.assertEqual(result['candidates'][0]['url'], URL)
        self.platform.request.assert_not_called()

    def test_failure_cause_and_old_events_survive_archive_only_recovery(self):
        def fail(*unused):
            try:
                raise TimeoutError('workspace routing discovery timed out')
            except TimeoutError as cause:
                raise ReaderError('host failed') from cause
        with self.assertRaisesRegex(ReaderError, 'host_assessment'):
            self.run_fixture(evaluator=fail)
        run_id = self.agent.memory.recent_runs()[0]['id']
        state = self.agent.status(run_id)
        self.assertEqual(state['runtime']['stage'], 'host_assessment')
        self.assertEqual(state['error_details']['chain'][1]['type'], 'TimeoutError')
        events = state['events']
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('no fetch')), \
                patch('scroll_agent.agent.preview.preview', side_effect=AssertionError('reuse preview')):
            result = self.agent.recover(run_id, evaluator=Mock(return_value=self.decision()))
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['delivery']['status'], 'not_sent')
        self.assertEqual(self.agent.memory.run_events(run_id)[:len(events)], events)
        self.assertIn('recovery_requested', [event['kind'] for event in self.agent.status(run_id)['events']])
        self.platform.request.assert_not_called()

    def test_saved_assessment_is_reused_after_failure_before_final_archive(self):
        with patch.object(self.agent, '_finish', side_effect=OSError('disk temporarily unavailable')):
            with self.assertRaises(ReaderError):
                self.run_fixture()
        run_id = self.agent.memory.recent_runs()[0]['id']
        result = self.agent.recover(run_id, evaluator=Mock(side_effect=AssertionError('assessment already saved')))
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(result['checkpoint']['host_assessed_urls'], [URL])

    def test_daily_is_reserved_even_when_discovery_is_interrupted(self):
        self.agent.options['daily'].update(enabled=True, time='00:00')
        self.agent.options['delivery']['recipient_uid'] = 999
        with patch('scroll_agent.agent.preview.candidates', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.agent.prepare_daily()
        run_id = self.agent.memory.recent_runs()[0]['id']
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('no new daily selection')):
            self.assertEqual(self.agent.prepare_daily()['run_id'], run_id)
            with self.assertRaisesRegex(ReaderError, 'No saved candidate'):
                self.agent.recover(run_id)
        self.assertEqual(self.agent.status(run_id)['recovery']['reason'], 'no_saved_candidate')
        self.platform.request.assert_not_called()

    def test_legacy_preparing_without_day_index_is_reused_and_reported_interrupted(self):
        self.agent.options['daily'].update(enabled=True, time='00:00')
        self.agent.options['delivery']['recipient_uid'] = 999
        run_id = 'round_' + 'a' * 32
        self.agent.memory.save_run(run_id, 'preparing', {'run_id': run_id, 'trial_day': self.agent.daily_day(),
                                                        'candidates': [], 'previews': []})
        state = self.agent.status(run_id)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['recorded_status'], 'preparing')
        self.assertEqual(state['runtime']['stage'], 'legacy_stage_not_recorded')
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('must reuse legacy day')):
            self.assertEqual(self.agent.prepare_daily()['run_id'], run_id)

    def test_legacy_failed_host_gets_log_cause_without_changing_the_record(self):
        packet = self.prepare()
        packet.pop('runtime', None)
        # Use a different run so this record genuinely has no runtime schema.
        packet['run_id'] = 'round_' + 'b' * 32
        packet['error'] = 'Ephemeral host failed; see the local run log'
        self.agent.memory.save_run(packet['run_id'], 'failed', packet)
        log = self.agent.directory(packet['run_id']) / 'host' / 'host.log'
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps({'type': 'turn.failed', 'error': {'message': 'workspace routing discovery timed out'}}), encoding='utf-8')
        state = self.agent.status(packet['run_id'])
        self.assertEqual(state['error_details']['category'], 'host_transport')
        self.assertIn('workspace routing', state['error_details']['message'])
        self.assertNotIn('error_details', self.agent.memory.load_run(packet['run_id']))

    def test_interrupted_send_stays_uncertain_after_recovery_and_cannot_resend(self):
        self.agent.options['delivery'].update(enabled=True, recipient_uid=999)
        self.platform.request.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_fixture(dry_run=False)
        run_id = self.agent.memory.recent_runs()[0]['id']
        self.assertEqual(self.agent.status(run_id)['delivery']['status'], 'uncertain')
        self.assertEqual(self.platform.request.call_count, 1)
        self.agent.recover(run_id, evaluator=Mock(side_effect=AssertionError('result already saved')))
        self.assertEqual(self.agent.status(run_id)['delivery']['status'], 'uncertain')
        self.assertEqual(self.agent.deliver(run_id)['status'], 'duplicate_or_uncertain_not_resent')
        self.assertEqual(self.platform.request.call_count, 1)

    def test_memory_heartbeat_cannot_replace_a_newer_checkpoint_and_scope_is_enforced(self):
        packet = self.prepare()
        run_id = packet['run_id']
        self.agent.memory.update_runtime(run_id, {'stage': 'newer_stage'}, event='progress')
        self.agent.memory.save_run(run_id, 'prepared', packet)
        self.assertEqual(self.agent.memory.load_run(run_id)['runtime']['stage'], 'newer_stage')
        other = Memory(self.agent.root, 'other_account')
        with self.assertRaises(ReaderError):
            other.update_runtime(run_id, {'stage': 'wrong'})
        with self.assertRaises(ReaderError):
            other.run_events(run_id)

    def test_accepted_delivery_ledger_survives_an_unsaved_result_update(self):
        self.agent.options['delivery'].update(enabled=True, recipient_uid=999)
        result = self.run_fixture()
        run_id = result['run_id']
        self.agent.memory.reserve_delivery(999, [URL])
        self.agent.memory.delivery_result(999, [URL], 'accepted_not_receipt_verified')
        result['delivery'] = {'status': 'sending'}
        self.agent.memory.save_run(run_id, 'failed', result)
        state = self.agent.status(run_id)
        self.assertEqual(state['delivery']['status'], 'accepted_not_receipt_verified')
        self.assertFalse(state['delivery']['receipt_verified'])
        self.agent.recover(run_id)
        self.assertEqual(self.agent.status(run_id)['delivery']['status'], 'accepted_not_receipt_verified')
        self.platform.request.assert_not_called()

    def test_acquisition_failure_is_visible_in_single_round_query(self):
        with patch('scroll_agent.agent.preview.candidates', side_effect=ReaderError('platform unavailable')):
            result = self.agent.run(evaluator=Mock(side_effect=AssertionError('no host')))
        state = self.agent.status(result['run_id'])
        self.assertEqual(state['status'], 'acquisition_failed')
        self.assertEqual(state['failures'][0]['error_details']['message'], 'platform unavailable')
        restored = self.agent.recover(result['run_id'])
        self.assertEqual(restored['status'], 'acquisition_failed')

    def test_recovery_with_only_saved_preview_never_discovers_new_candidates(self):
        packet = self.prepare()
        packet['candidates'] = []
        self.agent.memory.save_run(packet['run_id'], 'failed', packet)
        with patch('scroll_agent.agent.preview.candidates', side_effect=AssertionError('must reuse preview source')):
            result = self.agent.recover(packet['run_id'], evaluator=Mock(return_value=self.decision()))
        self.assertEqual(result['candidates'][0]['url'], URL)

    def test_mcp_and_cli_expose_the_same_query_and_recovery_without_delivery(self):
        packet = self.prepare()
        run_id = packet['run_id']
        with patch('scroll_agent.mcp_server.Agent', return_value=self.agent), \
                patch.object(self.agent, 'status', wraps=self.agent.status) as query:
            blocks = mcp_server.scroll_round(action='status', run_id=run_id)
            query.assert_called_once_with(run_id)
        self.assertEqual(json.loads(blocks[0].text)['run_id'], run_id)
        with patch('scroll_agent.mcp_server.Agent', return_value=self.agent), self.assertRaises(ValueError):
            mcp_server.scroll_round(action='recover', run_id=run_id, dry_run=False)
        args = Mock(action='recover', value=run_id, deliver=True, offline=False)
        with patch('scroll_agent.cli.Agent', return_value=self.agent), self.assertRaises(ReaderError):
            dispatch(self.reader, args)


class HostDiagnosticTests(AgentFixture):
    def test_retry_preserves_prior_log_and_decision(self):
        directory = self.root / 'round'
        write_json(directory / 'host' / 'decision.json', {'decisions': ['old']})
        log = directory / 'host' / 'host.log'
        log.write_text('original failure evidence', encoding='utf-8')
        process = Mock(returncode=0)
        process.communicate.side_effect = lambda *args, **kwargs: write_json(directory / 'host' / 'decision.json', {'decisions': []})
        with patch('scroll_agent.host.resolve_executable', return_value=sys.executable), \
                patch('video_reader.processes.identity', return_value=None), \
                patch('scroll_agent.host.model_options', return_value=[]), \
                patch('scroll_agent.host.subprocess.Popen', return_value=process):
            self.assertEqual(host.decide({'previews': []}, directory, self.agent.options['host']), {'decisions': []})
        history = list((directory / 'host' / 'history').iterdir())
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0] / 'host.log').read_text(encoding='utf-8'), 'original failure evidence')
        self.assertEqual(read_json(history[0] / 'decision.json'), {'decisions': ['old']})

    def test_json_error_tail_is_reported_without_unrelated_prompt_fields(self):
        log = self.root / 'host.log'
        log.write_text('\n'.join([json.dumps({'type': 'prompt', 'secret': 'private prompt text'}),
                                  json.dumps({'type': 'error', 'message': 'Reconnecting...'}),
                                  json.dumps({'type': 'turn.failed', 'error': {'message': 'workspace routing discovery timed out'}})]), encoding='utf-8')
        error = host.HostError('Ephemeral host failed', log, returncode=1)
        self.assertEqual(error.category, 'host_transport')
        self.assertIn('workspace routing discovery timed out', str(error))
        self.assertNotIn('private prompt text', json.dumps(error.details))
        self.assertEqual(error.details['returncode'], 1)
