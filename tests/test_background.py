import copy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock,patch

from reading_tasks.consume import Consumer
from reading_tasks.control import Controls,ControlWait
from scroll_agent.background import Background,dispatch
from video_reader.common import ReaderError,write_json
from video_reader.host_runtime import HostError
from video_reader.jobs import Jobs
from video_reader.reader import Reader


READY={'available':True,'cpu_percent':1,'available_memory_mb':8192}


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[1]/'.test-work'
        parent.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='background-test-',dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        config=self.root/'config.json'
        write_json(config,{'cache_dir':'cache','tasks':{'directory':'tasks'},'agent':{'directory':'agent'}})
        self.reader=Reader(config)
        self.now=datetime(2026,11,6,12,tzinfo=timezone(timedelta(hours=8))).timestamp()
        self.clock=lambda:self.now
        # Consumer creates its own Controls; keep its default clock on the same
        # simulated day rather than letting real midnight change permit counts.
        clock_patch=patch('reading_tasks.control.time.time',side_effect=self.clock)
        clock_patch.start();self.addCleanup(clock_patch.stop)
        self.sync=Mock(return_value={'feed':{'status':'ready'}})
        self.bg=Background(self.reader,clock=self.clock,probe=lambda:READY,sync=self.sync)
        self.bg.control.configure({'enabled':True,'sync_enabled':False,'daily_task_limit':3,
            'window_start':'00:00','window_end':'00:00','max_cpu_percent':100,'min_available_memory_mb':0})
        self.reader.job=Mock(return_value={'job_id':'j_'+'a'*24,'status':'queued'})
        self.resource_patch=patch('reading_tasks.control.sample',return_value=READY)
        self.resource_patch.start();self.addCleanup(self.resource_patch.stop)
        self.item=self.bg.control.queue.enqueue('BV0000000001',task='整理视频观点',title='First')['item']

    def test_repeated_and_concurrent_ticks_claim_once(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.bg.tick(force=True),range(2)))
        self.assertEqual(sum(r['status']=='started' for r in results),1)
        self.assertEqual(self.bg.tick(force=True)['status'],'running')
        self.assertEqual(len(self.bg.control.slots()),1)
        self.assertEqual(sum(call.args[0]=='start' for call in self.reader.job.call_args_list),1)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)
        self.assertEqual(self.bg.control.usage()['host_attempts'],0)

    def test_empty_requests_wait_and_priority_is_respected(self):
        self.bg.control.queue.update(self.item['id'],task='')
        self.assertEqual(self.bg.tick(force=True)['reason'],'needs_request')
        self.reader.job.assert_not_called()
        second=self.bg.control.queue.enqueue('BV0000000002',task='检查关键论据')['item']
        self.bg.control.queue.update(second['id'],priority=10)
        result=self.bg.tick(force=True)
        self.assertEqual(result['run']['item_id'],second['id'])
        self.assertEqual(self.bg.status()['needs_request'][0]['item_id'],self.item['id'])

    def test_disabled_pause_window_and_hold_do_not_start_work(self):
        self.bg.control.configure({'enabled':False,'sync_enabled':True})
        self.assertEqual(self.bg.tick(force=True)['reason'],'disabled')
        self.bg.control.configure({'enabled':True})
        self.bg.control.pause()
        self.assertEqual(self.bg.tick(force=True)['reason'],'user_paused')
        self.sync.assert_not_called()
        self.bg.control.resume()
        self.bg.control.configure({'window_start':'13:00','window_end':'14:00'})
        self.assertEqual(self.bg.tick(force=True)['reason'],'outside_window')
        self.sync.assert_not_called()
        self.bg.control.configure({'window_start':'00:00','window_end':'00:00'})
        self.bg.control.hold(60)
        self.assertEqual(self.bg.tick(force=True)['reason'],'foreground_hold')
        self.reader.job.assert_not_called()

    def test_busy_or_unknown_resources_wait(self):
        self.bg.probe=lambda:{'available':False}
        self.assertEqual(self.bg.tick(force=True)['reason'],'resource_probe_unavailable')
        self.bg.control.configure({'max_cpu_percent':85,'min_available_memory_mb':2048})
        self.bg.probe=lambda:{**READY,'cpu_percent':99}
        self.assertEqual(self.bg.tick(force=True)['reason'],'cpu_busy')
        self.bg.probe=lambda:{**READY,'available_memory_mb':100}
        self.assertEqual(self.bg.tick(force=True)['reason'],'memory_low')
        self.reader.job.assert_not_called()

    def test_foreground_job_prevents_background_claim(self):
        jobs=Jobs(self.reader);job_id='j_'+'f'*24
        write_json(jobs.path(job_id),{'job_id':job_id,'status':'queued','created_at':self.now,
            'heartbeat_at':self.now,'progress_at':self.now,'stage_started_at':self.now,'stage':'starting'})
        self.assertEqual(self.bg.tick(force=True)['reason'],'foreground_job')
        self.assertEqual(self.bg.control.usage()['tasks_started'],0)
        self.reader.job.assert_not_called()

    def test_daily_cap_and_day_rollover(self):
        for n in range(3):
            token=self.bg.control.reserve_task(self.item['id'])
            self.bg.control.mark(token,'completed')
        self.assertEqual(self.bg.tick(force=True)['reason'],'daily_task_limit')
        self.now+=86400
        self.assertTrue(self.bg.control.reserve_task(self.item['id']).startswith('bg_'))
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_host_attempt_is_reserved_before_call_and_never_refunded(self):
        result=self.bg.tick(force=True)
        state=self.bg.consumer.load(result['run']['run_id'])
        self.bg.control.configure({'daily_host_call_limit':1})
        self.bg.control.guard(state,reserve_host=True)
        with self.assertRaisesRegex(ControlWait,'daily_host_call_limit'):
            self.bg.control.guard(state,reserve_host=True)
        self.assertEqual(self.bg.control.usage()['host_attempts'],1)
        self.assertEqual(self.bg.control.usage()['provider_remaining_quota'],'unknown')

    def test_interrupted_run_resumes_same_claim_and_is_bounded(self):
        first=self.bg.tick(force=True)['run']['run_id']
        self.reader.job.return_value={'job_id':'j_'+'b'*24,'status':'interrupted'}
        self.assertEqual(self.bg.tick(force=True)['status'],'resumed')
        self.assertEqual(self.bg.tick(force=True)['status'],'resumed')
        self.assertEqual(self.bg.tick(force=True)['reason'],'interrupted_resume_limit')
        self.assertEqual(self.bg.control.slots()[0]['run_id'],first)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_blank_permit_after_process_loss_reuses_reservation(self):
        token=self.bg.control.reserve_task(self.item['id'])
        result=self.bg.tick(force=True)
        self.assertEqual(result['status'],'started')
        self.assertEqual(self.bg.consumer.load(result['run']['run_id'])['background_token'],token)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_lost_permit_link_recovers_the_original_run_and_its_checkpoint(self):
        run=self.bg.tick(force=True)['run']['run_id']
        state=self.bg.consumer.load(run)
        state.update(next_block=4,phase='reading')
        self.bg.consumer.save(state,'running')
        token=self.bg.control.slots()[0]['token']
        # Simulate the lost association only; the originally bound run survives.
        with self.bg.control.store.connect() as db:
            db.execute("UPDATE task_background_slots SET run_id=NULL,status='reserved' WHERE token=?",(token,))
        self.reader.job.reset_mock()
        result=self.bg.consume(force=True)
        self.assertEqual(result['status'],'running')
        self.assertEqual(result['run']['run_id'],run)
        self.assertEqual(self.bg.control.permit_for_run(run)['token'],token)
        self.assertEqual(self.bg.consumer.load(run)['next_block'],4)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)
        self.assertTrue(self.reader.job.call_args_list)
        self.assertTrue(all(call.args[0]=='status' for call in self.reader.job.call_args_list))

    def test_failed_model_quota_latches_pause_without_auto_clear(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=HostError('usage limit reached',self.root/'missing.log')):
            with self.assertRaises(HostError):self.bg.consumer.execute(run)
        self.assertEqual(self.bg.control.state()['paused_reason'],'model_quota')
        self.assertEqual(self.bg.tick(force=True)['reason'],'model_quota')
        token=self.bg.control.slots()[0]['token']
        self.bg.control.resume()
        self.assertEqual(self.bg.tick(force=True)['status'],'resumed')
        self.assertEqual(self.bg.control.slots()[0]['token'],token)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_failed_task_is_not_reclaimed_with_new_permits(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=ReaderError('fixture failure')):
            with self.assertRaises(ReaderError):self.bg.consumer.execute(run)
        self.reader.job.return_value={'job_id':'j_'+'a'*24,'status':'failed'}
        self.assertEqual(self.bg.tick(force=True)['reason'],'inspect_run_error')
        self.assertEqual(self.bg.tick(force=True)['reason'],'needs_attention')
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_comment_is_not_promoted_to_a_request(self):
        q=self.bg.control.queue
        with q.store.connect() as db:
            q.record_intent(db,self.item['id'],{'original':self.item['task'],'kind':'comment',
                'comment':self.item['task'],'request':None})
        self.assertEqual(self.bg.tick(force=True)['reason'],'needs_request')
        self.reader.job.assert_not_called()

    def test_current_worker_is_not_mistaken_for_foreground_during_resume(self):
        from video_reader.jobs import CURRENT
        jobs=Jobs(self.reader);new='j_'+'e'*24
        write_json(jobs.path(new),{'job_id':new,'status':'queued','created_at':self.now,
            'heartbeat_at':self.now,'progress_at':self.now,'stage_started_at':self.now,'stage':'starting'})
        token=CURRENT.set(Mock(job_id=new))
        try:self.assertIsNone(self.bg.control.foreground_job('j_'+'d'*24))
        finally:CURRENT.reset(token)

    def test_platform_failure_is_not_model_quota(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=ReaderError('Platform HTTP 429')):
            with self.assertRaises(ReaderError):self.bg.consumer.execute(run)
        self.assertIsNone(self.bg.control.state()['paused_reason'])

    def _response(self,prompt,*args,**kwargs):
        material=json.loads(prompt.split('\n',1)[1])['material']
        return {'packet_id':material['packet_id'],'observed_segment_ids':[s['segment_id'] for s in material['segments']],
            'observed_frame_ids':[],'summary':'Fixture only','notes':'# Controlled fixture result',
            'uncertainties':[],'evidence_requests':[],'task_satisfied':True}

    def _ready_run(self):
        run=self.bg.tick(force=True)['run']['run_id']
        index={'index_id':'ci_fixture','binding':{'coverage':{'complete':True}},'title':'Fixture','next_offset':None,
            'blocks':[{'id':'b1','start':0,'end':8,'segments':[{'segment_id':'s1','start':0,'end':8,'text':'fixture'}],
                       'frame_refs':[],'gaps':[]}]}
        self.reader.content=Mock(side_effect=lambda target,action='index',**kw:{'valid':True} if action=='validate' else copy.deepcopy(index))
        return run

    def test_pause_at_commit_preserves_checkpoint_and_resume_needs_no_new_host(self):
        run=self._ready_run()
        original=self.bg.consumer.queue.record_result
        def paused(*args,**kwargs):
            self.bg.control.pause()
            return original(*args,**kwargs)
        with patch('reading_tasks.consume.invoke',side_effect=self._response),patch.object(self.bg.consumer.queue,'record_result',side_effect=paused):
            with self.assertRaises(ControlWait):self.bg.consumer.execute(run)
        self.assertEqual(self.bg.consumer.load(run)['next_block'],1)
        self.assertEqual(self.bg.control.queue.show(self.item['id'])['state'],'pending')
        self.bg.control.resume()
        with patch('reading_tasks.consume.invoke') as host:
            result=self.bg.consumer.execute(run)
        host.assert_not_called()
        self.assertEqual(result['status'],'completed')

    def test_pause_then_resume_during_host_rejects_the_late_response(self):
        run=self._ready_run()
        def transient_pause(*args,**kwargs):
            response=self._response(*args,**kwargs)
            self.bg.control.pause();self.bg.control.resume()
            return response
        with patch('reading_tasks.consume.invoke',side_effect=transient_pause):
            with self.assertRaisesRegex(ControlWait,'control_changed_during_host'):
                self.bg.consumer.execute(run)
        self.assertEqual(self.bg.consumer.load(run)['next_block'],0)
        self.assertEqual(self.bg.control.queue.show(self.item['id'])['state'],'pending')

    def test_external_verification_gap_saves_draft_without_completing_task(self):
        run=self._ready_run()
        def incomplete(*args,**kwargs):
            return {**self._response(*args,**kwargs),'task_satisfied':False,'uncertainties':['External source not checked']}
        with patch('reading_tasks.consume.invoke',side_effect=incomplete):
            result=self.bg.consumer.execute(run)
        self.assertEqual(result['status'],'needs_attention')
        item=self.bg.control.queue.show(self.item['id'])
        self.assertEqual(item['state'],'pending')
        self.assertFalse(item['latest_result']['task_complete'])
        self.assertTrue(Path(result['artifact']).is_file())
        self.assertEqual(self.bg.tick(force=True)['reason'],'needs_attention')
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_pause_at_checkpoint_does_not_resave_rejected_progress_in_error_path(self):
        run=self._ready_run()
        original=self.bg.consumer.save
        def paused(state,status=None,**kwargs):
            if kwargs.get('checkpoint_epoch') is not None:
                self.bg.control.pause();self.bg.control.resume()
            return original(state,status,**kwargs)
        with patch('reading_tasks.consume.invoke',side_effect=self._response),patch.object(self.bg.consumer,'save',side_effect=paused):
            with self.assertRaisesRegex(ControlWait,'control_changed_during_host'):
                self.bg.consumer.execute(run)
        saved=self.bg.consumer.load(run)
        self.assertEqual(saved['next_block'],0)
        self.assertEqual(saved['observations'],[])
        self.assertEqual(saved['status'],'waiting')
        with patch('reading_tasks.consume.invoke',side_effect=self._response):
            self.assertEqual(self.bg.consumer.execute(run)['status'],'completed')

    def test_manual_run_ignores_background_pause(self):
        self.bg.control.pause()
        run=Consumer(self.reader).start(self.item['id'])
        self.assertNotIn('background_token',self.bg.consumer.load(run['run_id']))

    def test_status_and_mcp_do_not_invoke_model_or_sync(self):
        with patch('reading_tasks.consume.invoke') as host:
            self.assertFalse(dispatch(self.reader,'background-status')['checks_call_model'])
            from scroll_agent import mcp_server
            with patch.object(mcp_server,'Reader',return_value=self.reader):
                self.assertIn('checks_call_model',mcp_server.scroll_background()[0].text)
        host.assert_not_called();self.sync.assert_not_called()

    def test_policy_rejects_invalid_limits_and_interval_is_effective(self):
        with self.assertRaises(ReaderError):self.bg.control.configure({'daily_task_limit':True})
        self.bg.tick(force=True)
        self.assertEqual(self.bg.tick()['reason'],'interval_not_due')

    def test_intake_and_queue_have_independent_actions_and_clocks(self):
        self.bg.control.configure({'sync_enabled':True,'intake_interval_minutes':60,'queue_interval_minutes':5})
        self.assertEqual(self.bg.intake()['status'],'synced')
        self.reader.job.assert_not_called()
        first_intake=self.bg.runtime()['last_intake_tick']
        self.assertIsNone(self.bg.runtime()['last_queue_tick'])
        self.assertEqual(self.bg.consume()['status'],'started')
        self.now+=5*60
        self.assertEqual(self.bg.intake()['reason'],'interval_not_due')
        self.assertEqual(self.bg.consume()['status'],'running')
        self.assertEqual(self.bg.runtime()['last_intake_tick'],first_intake)
        self.assertEqual(self.sync.call_count,1)

    def test_intake_failure_does_not_gate_compatibility_tick_or_queue(self):
        self.bg.control.configure({'sync_enabled':True})
        self.sync.side_effect=ReaderError('Inbox unavailable')
        result=self.bg.tick(force=True)
        self.assertEqual(result['status'],'started')
        self.assertEqual(result['intake']['status'],'failed')
        self.sync.reset_mock()
        self.assertEqual(self.bg.consume(force=True)['status'],'running')
        self.sync.assert_not_called()

    def test_model_quota_pause_does_not_stop_script_only_intake(self):
        self.bg.control.configure({'sync_enabled':True})
        self.bg.control.pause('model_quota')
        self.assertEqual(self.bg.intake(force=True)['status'],'synced')
        self.assertEqual(self.bg.consume(force=True)['reason'],'model_quota')
        self.reader.job.assert_not_called()

    def test_schedule_boundary_jitter_does_not_skip_an_hour(self):
        self.bg.control.configure({'sync_enabled':True,'intake_interval_minutes':60})
        self.now+=.8
        self.assertEqual(self.bg.intake()['status'],'synced')
        self.now+=3599.4
        self.assertEqual(self.bg.intake()['status'],'synced')
        self.assertEqual(self.sync.call_count,2)

    def test_legacy_interval_migrates_without_resetting_other_limits(self):
        with self.bg.control.store.connect() as db:
            raw=self.bg.control.state()['policy']
            raw.pop('intake_interval_minutes');raw.pop('queue_interval_minutes');raw.pop('max_host_retries')
            raw['interval_minutes']=37
            db.execute('UPDATE task_background_control SET policy=? WHERE scope=?',(json.dumps(raw),self.bg.control.scope))
        migrated=Controls(self.reader).state()['policy']
        self.assertEqual(migrated['intake_interval_minutes'],37)
        self.assertEqual(migrated['queue_interval_minutes'],37)
        self.assertEqual(migrated['daily_task_limit'],3)
        self.bg.control.configure({'intake_interval_minutes':60})
        self.assertEqual(self.bg.control.state()['policy']['queue_interval_minutes'],37)
        with self.assertRaises(ReaderError):self.bg.control.configure({'interval_minutes':60,'queue_interval_minutes':5})

    def test_transient_host_retry_is_short_bounded_and_reuses_original_permit(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=HostError('Connection attempt timed out',self.root/'missing.log',timeout=True)):
            with self.assertRaises(HostError):self.bg.consumer.execute(run)
        self.reader.job.return_value={'job_id':'j_'+'a'*24,'status':'failed','finished_at':self.now}
        token=self.bg.control.slots()[0]['token']
        self.assertEqual(self.bg.consume(force=True)['reason'],'host_retry_backoff')
        self.assertEqual(self.bg.status()['pending_retries'][0]['run_id'],run)
        self.bg.control.configure({'sync_enabled':True,'queue_interval_minutes':5})
        self.sync.side_effect=ReaderError('Inbox unavailable')
        for number in (1,2):
            self.now+=5*60
            result=self.bg.consume(force=True)
            self.assertEqual(result['status'],'retried')
            self.assertEqual(result['run']['run_id'],run)
            self.assertEqual(result['retry'],number)
        self.assertEqual(self.bg.consume(force=True)['reason'],'host_retry_limit')
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)
        self.assertEqual(self.bg.control.slots(active_only=False)[0]['token'],token)
        self.sync.assert_not_called()

    def test_explicit_failed_retry_never_checks_inbox(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=ReaderError('fixture failure')):
            with self.assertRaises(ReaderError):self.bg.consumer.execute(run)
        self.reader.job.return_value={'job_id':'j_'+'a'*24,'status':'failed'}
        self.assertEqual(self.bg.consume(force=True)['reason'],'inspect_run_error')
        result=self.bg.retry(run)
        self.assertEqual(result['status'],'retried')
        self.assertEqual(result['run']['run_id'],run)
        self.assertFalse(result['intake_checked'])
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)
        self.assertEqual(self.bg.control.slots()[0]['host_retries'],0)
        self.sync.assert_not_called()

    def test_explicit_retry_after_auto_limit_is_allowed_without_resetting_auto_count(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=HostError('Timed out',self.root/'missing.log',timeout=True)):
            with self.assertRaises(HostError):self.bg.consumer.execute(run)
        self.reader.job.return_value={'job_id':'j_'+'a'*24,'status':'failed','finished_at':self.now-3600}
        token=self.bg.control.slots()[0]['token']
        self.bg.control.host_retry(token);self.bg.control.host_retry(token)
        self.assertEqual(self.bg.consume(force=True)['reason'],'host_retry_limit')
        self.assertEqual(self.bg.retry(run)['status'],'retried')
        self.assertEqual(self.bg.control.slots()[0]['host_retries'],2)
        self.assertEqual(self.bg.control.usage()['tasks_started'],1)

    def test_foreground_hold_blocks_explicit_retry_without_consuming_auto_retries(self):
        run=self._ready_run()
        with patch('reading_tasks.consume.invoke',side_effect=ReaderError('Fixture failure')):
            with self.assertRaises(ReaderError):self.bg.consumer.execute(run)
        self.bg.control.hold(60)
        with self.assertRaises(ControlWait):self.bg.retry(run)
        self.assertEqual(self.bg.control.slots()[0]['host_retries'],0)
