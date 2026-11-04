"""Real subprocess jobs and independent CLI/MCP clients; no network/model downloads."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from filelock import FileLock
from video_reader.common import ReaderError, run, write_json
from video_reader.reader import Reader
from video_reader.jobs import Jobs, Running

ROOT = Path(__file__).resolve().parents[1]


class JobTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.test-work').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='reader-jobs-',dir=ROOT/'.test-work')
        self.root = Path(self.temp.name)
        self.config = self.root/'config.json'
        write_json(self.config, {'cache_dir': 'cache', 'vision': {'enabled': False},
                                'asr': {'model_path': None}, 'bilibili_auth': {'enabled': False}})
        self.media = self.root/'fixture.mp4'
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=5',
             '-t', '2', '-threads', '1', '-pix_fmt', 'yuv420p', str(self.media)], timeout=15)
        self.media.with_suffix('.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:02.000\nRead this caption.\n',encoding='utf-8')
        self.reader=Reader(self.config)
        self.opened=self.reader.open(str(self.media))
        self.session=self.opened['session_id']
        self.store=Jobs(self.reader)

    def tearDown(self):
        # Do not remove a temporary store while its detached worker still writes.
        for path in self.store.root.glob('j_*.json'):
            if not path.name.endswith('.result.json'):
                until=time.monotonic()+15
                while self.store.status(path.stem)['status'] not in ('completed','failed','interrupted') and time.monotonic()<until:
                    time.sleep(.1)
        self.temp.cleanup()

    def cli(self, *arguments):
        result=subprocess.run([sys.executable,'-I',str(ROOT/'launch.py'),'--config',str(self.config),*arguments],
                              capture_output=True,text=True,encoding='utf-8',timeout=10)
        return result.returncode,json.loads(result.stdout)

    def wait_stage(self, job_id, stage):
        until=time.monotonic()+10
        while time.monotonic()<until:
            result=self.store.status(job_id)
            if result['stage']==stage:return result
            if result['status'] in ('failed','interrupted'):self.fail(result)
            time.sleep(.05)
        self.fail(f'job did not reach {stage}: {result}')

    def test_cli_and_mcp_attach_same_running_job_and_read_material(self):
        with FileLock(str(self.reader.directory(self.session)/'.lock')):
            code,first=self.cli('read',self.session,'--end','2','--strategy','uniform',
                                '--source','captions','--no-temporal','--no-verify','--wait','0')
            self.assertEqual(code,0)
            job_id=first['job_id']
            self.wait_stage(job_id,'waiting_for_session_lock')
            async def exercise():
                from mcp import ClientSession,StdioServerParameters
                from mcp.client.stdio import stdio_client
                params=StdioServerParameters(command=sys.executable,args=['-I',str(ROOT/'launch_mcp.py')],
                       env={**os.environ,'VIDEO_READER_CONFIG':str(self.config)})
                async with stdio_client(params) as (r,w):
                    async with ClientSession(r,w) as client:
                        await client.initialize()
                        began=time.monotonic()
                        response=await client.call_tool('video_job',{'job_id':job_id})
                        self.assertLess(time.monotonic()-began,2)
                        state=json.loads(response.content[0].text)
                        self.assertEqual(state['stage'],'waiting_for_session_lock')
                        self.assertTrue(state['worker_alive'])
                        self.assertEqual(state['waiting_for']['session_id'],self.session)
                        duplicate=await client.call_tool('video_read',{'session_id':self.session,'end':'2',
                            'strategy':'uniform','source':'captions','temporal':False,'verify':False,'wait_seconds':0})
                        joined=json.loads(duplicate.content[0].text)
                        self.assertEqual(joined['job_id'],job_id)
                        self.assertTrue(joined['reused_running_job'])
            asyncio.run(exercise())
            before=self.store.status(job_id)
            time.sleep(2.15)
            after=self.store.status(job_id)
            self.assertGreater(after['heartbeat_at'],before['heartbeat_at'])
            self.assertEqual(after['progress_at'],before['progress_at'])
        completed=self.store.result(job_id,15)
        self.assertEqual(completed['job']['status'],'completed',completed)
        self.assertEqual(completed['speech']['segments'][0]['text'],'Read this caption.')
        self.assertTrue(completed['visual']['frames'])
        self.assertGreater(completed['job']['stage_seconds']['waiting_for_session_lock'],2)
        code,other=self.cli('job','result',job_id)
        self.assertEqual(code,0)
        self.assertEqual(other['read_id'],completed['read_id'])

    def test_request_identity_and_old_result_do_not_mask_updated_material(self):
        with FileLock(str(self.reader.directory(self.session)/'.lock')):
            args={'session':self.session,'temporal':False,'verify':False,'task':'first'}
            first=self.store.start('read',args,0)
            different=self.store.start('read',{**args,'task':'second'},0)
            self.assertNotEqual(first['job_id'],different['job_id'])
        for value in (first,different):
            self.assertEqual(self.store.result(value['job_id'],15)['job']['status'],'completed')
        fresh=self.store.start('read',args,15)
        self.assertNotEqual(fresh['job']['job_id'],first['job_id'])
        self.assertTrue(fresh['processing']['frame_cache_reused'])

    def test_error_is_terminal_and_cli_exits_nonzero(self):
        result=self.store.start('read',{'session':'v_'+'a'*24},15)
        self.assertEqual(result['status'],'failed')
        self.assertIn('Video session not found',result['error']['message'])
        code,state=self.cli('job','result',result['job_id'])
        self.assertEqual(code,1)
        self.assertEqual(state['error']['type'],'ReaderError')
        self.assertIn(result['job_id'],[j['job_id'] for j in self.store.list()['jobs']])

    def test_abandoned_worker_not_reported_running_or_automatically_restarted(self):
        job_id='j_'+'b'*24;old=time.time()-30
        write_json(self.store.path(job_id),{'job_id':job_id,'status':'running','stage':'extracting_frames',
          'created_at':old,'heartbeat_at':old,'progress_at':old,'stage_started_at':old})
        state=self.store.status(job_id)
        self.assertEqual(state['status'],'interrupted')
        self.assertFalse(state['worker_alive'])
        self.assertEqual(state['next_action'],'inspect_error')

    def test_bounds_and_material_validation_precede_worker_start(self):
        for wait in (-1,31,float('nan'),True):
            with self.assertRaises(ReaderError):self.store.start('read',{'session':self.session},wait)
        with self.assertRaises(ReaderError):self.store.start('read',{'session':'../bad'},0)
        with self.assertRaises(ReaderError):self.store.start('open',{'source':str(self.media),'extra':True},0)
        self.assertEqual(self.store.list()['jobs'],[])

    def test_delayed_startup_is_unknown_instead_of_a_false_failure(self):
        job_id='j_'+'c'*24;old=time.time()-30
        write_json(self.store.path(job_id),{'job_id':job_id,'status':'queued','stage':'starting_worker',
          'created_at':old,'heartbeat_at':old,'progress_at':old,'stage_started_at':old})
        state=self.store.status(job_id)
        self.assertEqual(state['status'],'unknown')
        self.assertIsNone(state['worker_alive'])
        self.assertNotIn('error',state)
        self.assertEqual(state['next_action'],'inspect_worker')
        self.store.path(job_id).unlink()

    def test_stage_transition_clears_previous_message_and_progress(self):
        job_id='j_'+'d'*24;now=time.time()
        write_json(self.store.path(job_id),{'job_id':job_id,'status':'running','stage':'initializing',
          'created_at':now,'heartbeat_at':now,'progress_at':now,'stage_started_at':now,'stage_seconds':{},'materials':{}})
        worker=Running(self.store,job_id)
        worker.update('acquiring_source',message='Preparing video source',progress={'done':0,'total':1})
        worker.update('temporal_ocr',progress={'done':0,'total':11})
        self.assertNotIn('message',worker.value)
        self.assertEqual(worker.value['progress']['total'],11)
        worker.update('packing_delivery')
        self.assertNotIn('progress',worker.value)
        worker.update('completed',status='completed',finished_at=time.time())

    def test_concurrent_status_observers_are_not_mistaken_for_workers(self):
        from video_reader import jobs
        job_id='j_'+'e'*24;old=time.time()-30
        path=self.store.path(job_id)
        write_json(path,{'job_id':job_id,'status':'running','stage':'extracting_frames',
          'created_at':old,'heartbeat_at':old,'progress_at':old,'stage_started_at':old})
        acquired=threading.Event();release=threading.Event();results={};errors=[]
        original=jobs.read_json
        def paused_read(filename):
            if Path(filename)==path and threading.current_thread().name=='observer-a':
                acquired.set()
                if not release.wait(2):raise AssertionError('observer was not released')
            return original(filename)
        def observe(name):
            try:results[name]=self.store.status(job_id)
            except BaseException as exc:errors.append(exc)
        with patch.object(jobs,'read_json',side_effect=paused_read):
            a=threading.Thread(target=observe,args=('a',),name='observer-a')
            b=threading.Thread(target=observe,args=('b',),name='observer-b')
            a.start();self.assertTrue(acquired.wait(2));b.start()
            time.sleep(.05)
            self.assertNotIn('b',results)
            release.set();a.join(2);b.join(2)
        self.assertEqual(errors,[])
        self.assertEqual(set(results),{'a','b'})
        for state in results.values():
            self.assertEqual(state['status'],'interrupted')
            self.assertFalse(state['worker_alive'])

    def test_state_replacement_waits_for_active_status_reader(self):
        from video_reader import jobs
        job_id='j_'+'f'*24;now=time.time();path=self.store.path(job_id)
        write_json(path,{'job_id':job_id,'status':'running','stage':'initializing',
          'created_at':now,'heartbeat_at':now,'progress_at':now,'stage_started_at':now,'stage_seconds':{},'materials':{}})
        worker=Running(self.store,job_id)
        reading=threading.Event();release=threading.Event();written=threading.Event();errors=[]
        original=jobs.read_json
        def paused_read(filename):
            if Path(filename)==path and threading.current_thread().name=='state-reader':
                reading.set()
                if not release.wait(2):raise AssertionError('reader not released')
            return original(filename)
        def observe():
            try:self.store.status(job_id)
            except BaseException as exc:errors.append(exc)
        def update():
            try:worker.update('completed',status='completed',finished_at=time.time());written.set()
            except BaseException as exc:errors.append(exc)
        with patch.object(jobs,'read_json',side_effect=paused_read):
            a=threading.Thread(target=observe,name='state-reader');a.start();self.assertTrue(reading.wait(2))
            b=threading.Thread(target=update);b.start()
            try:self.assertFalse(written.wait(.1),'writer replaced a file still being read')
            finally:release.set();a.join(2);b.join(2)
        self.assertEqual(errors,[])
        self.assertTrue(written.is_set())
        self.assertEqual(self.store.status(job_id)['status'],'completed')

    def test_startup_failure_waits_for_status_io_lock_and_preserves_error(self):
        from video_reader.job_worker import fail_startup
        job_id='j_'+'a'*24;now=time.time()
        write_json(self.store.path(job_id),{'job_id':job_id,'status':'queued','stage':'starting_worker',
          'created_at':now,'heartbeat_at':now,'progress_at':now,'stage_started_at':now})
        done=threading.Event();began=threading.Event();errors=[]
        def fail():
            began.set()
            try:fail_startup(self.store.root,job_id,ValueError('config mismatch'));done.set()
            except BaseException as exc:errors.append(exc)
        with FileLock(str(self.store.root/(job_id+'.status.lock'))):
            thread=threading.Thread(target=fail);thread.start();self.assertTrue(began.wait(2))
            self.assertFalse(done.wait(.1))
        thread.join(2)
        self.assertEqual(errors,[])
        self.assertTrue(done.is_set())
        state=self.store.status(job_id)
        self.assertEqual(state['status'],'failed')
        self.assertEqual(state['error']['message'],'config mismatch')


if __name__=='__main__':unittest.main(verbosity=2)
