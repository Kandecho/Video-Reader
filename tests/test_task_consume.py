import copy
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock,patch

from reading_tasks.consume import Consumer
from video_reader.common import ReaderError,read_json,write_json
from video_reader.reader import Reader


class TaskConsumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        config=self.root/'config.json'
        write_json(config,{'cache_dir':'cache','tasks':{'directory':'tasks'},'agent':{'directory':'agent'}})
        self.reader=Reader(config)
        self.consumer=Consumer(self.reader)
        self.item=self.consumer.queue.enqueue('BV0000000001',task='完整观点笔记',title='Super-agent 架构')['item']
        self.reader.job=Mock(return_value={'job_id':'j_'+'a'*24,'status':'queued'})
        self.index={'index_id':'ci_'+'b'*24,'binding':{'source':self.item['canonical'],'coverage':{'complete':True}},'title':'Fixture',
            'next_offset':None,'blocks':[{'id':f'b:{i}','start':i*120,'end':(i+1)*120,'text_available':True,
                'segments':[{'segment_id':f's:{i}','start':i*120+1,'end':i*120+3,'text':f'完整原文{i}'}],
                'frame_refs':[],'gaps':['no_cached_frame_in_block']} for i in range(8)]}
        def content(target,action='index',**kwargs):
            return {'valid':True} if action=='validate' else copy.deepcopy(self.index)
        self.reader.content=Mock(side_effect=content)

    def response(self,prompt,images,schema,directory,options,**kwargs):
        packet=json.loads(prompt.split('\n',1)[1])['material']
        return {'packet_id':packet['packet_id'],'observed_segment_ids':[s['segment_id'] for s in packet.get('segments',[])],
            'observed_frame_ids':[f['id'] for f in packet.get('frames',[])],
            'summary':'实际观察后的摘要','notes':'# 实际阅读笔记\n\n保留源内容与时间。',
            'uncertainties':['没有连续视觉观察'],'evidence_requests':[]}

    def test_claim_replay_result_and_registered_artifact_search(self):
        started=self.consumer.start(self.item['id'])
        same=Consumer(self.reader).start(self.item['id'])
        self.assertEqual(started['run_id'],same['run_id'])
        with patch('reading_tasks.consume.invoke',side_effect=self.response) as host:
            result=self.consumer.execute(started['run_id'])
        self.assertEqual(host.call_count,3)
        self.assertEqual(result['task']['state'],'done')
        self.assertFalse(result['task']['latest_result']['full_video_verified'])
        self.assertTrue(Path(result['artifact']).is_file())
        self.assertEqual(self.consumer.execute(started['run_id'])['status'],'completed')
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_results').fetchone()[0],1)
        found=self.consumer.queue.search('superagent')
        self.assertEqual(found['items'][0]['item_id'],self.item['id'])
        self.assertEqual(self.consumer.queue.list('all',query='superagent')['items'][0]['id'],self.item['id'])
        self.assertEqual(self.consumer.queue.search('保留源内容')['items'][0]['matched_fields'],['artifact_text'])

    def test_resume_keeps_reading_checkpoint_and_ignores_old_attempt_output(self):
        run=self.consumer.start(self.item['id'])['run_id']
        count=0
        def interrupted(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise ReaderError('host interrupted')
            return self.response(*args,**kwargs)
        with patch('reading_tasks.consume.invoke',side_effect=interrupted):
            with self.assertRaisesRegex(ReaderError,'interrupted'):self.consumer.execute(run)
        saved=self.consumer.load(run)
        self.assertEqual(saved['next_block'],4)
        abandoned=saved['attempt_id']
        write_json(self.consumer.directory(run)/'attempts'/abandoned/'response.json',{'packet_id':'late-old-result'})
        with patch('reading_tasks.consume.invoke',side_effect=self.response) as host:
            result=Consumer(self.reader).execute(run)
        self.assertEqual(host.call_count,2)
        self.assertEqual(result['status'],'completed')
        self.assertNotEqual(self.consumer.load(run)['attempt_id'],abandoned)

    def test_running_task_change_cannot_be_completed_by_old_host(self):
        run=self.consumer.start(self.item['id'])['run_id']
        def change(*args,**kwargs):
            self.consumer.queue.update(self.item['id'],state='paused')
            return self.response(*args,**kwargs)
        with patch('reading_tasks.consume.invoke',side_effect=change):
            with self.assertRaisesRegex(ReaderError,'paused'):self.consumer.execute(run)
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'],'paused')
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_results').fetchone()[0],0)

    def test_missing_host_observation_does_not_advance(self):
        run=self.consumer.start(self.item['id'])['run_id']
        def skipped(*args,**kwargs):
            response=self.response(*args,**kwargs)
            response['observed_segment_ids']=[]
            return response
        with patch('reading_tasks.consume.invoke',side_effect=skipped):
            with self.assertRaisesRegex(ReaderError,'observation IDs'):self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'],0)

    def test_stale_material_does_not_resume_or_complete(self):
        run=self.consumer.start(self.item['id'])['run_id']
        original=self.reader.content.side_effect
        def changed(target,action='index',**kwargs):
            if action=='validate':raise ReaderError('Content source/speech/review changed')
            return original(target,action,**kwargs)
        self.reader.content.side_effect=changed
        with patch('reading_tasks.consume.invoke',side_effect=AssertionError('must not read stale material')):
            with self.assertRaisesRegex(ReaderError,'changed'):self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'],0)

    def test_partial_ready_asr_must_process_the_missing_tail(self):
        self.index['binding'].update(session_id='v_'+'f'*24,coverage={'complete':False,'missing_ranges':[[120,960]]})
        original=self.reader.content.side_effect
        processed=False
        def transcript(*args,**kwargs):
            nonlocal processed
            processed=True
            return {'coverage':{'complete':True}}
        self.reader.transcript=Mock(side_effect=transcript)
        def content(*args,**kwargs):
            result=original(*args,**kwargs)
            if processed and kwargs.get('action','index')!='validate':result['binding']['coverage']={'complete':True}
            return result
        self.reader.content.side_effect=content
        run=self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke',side_effect=self.response):self.consumer.execute(run)
        self.reader.transcript.assert_called_once()

    def test_active_resume_does_not_overwrite_worker_checkpoint(self):
        run=self.consumer.start(self.item['id'])['run_id']
        state=self.consumer.load(run)
        state['next_block']=4
        state['observations']=[{'packet_id':'saved'}]
        self.consumer.save(state,'running')
        self.consumer.resume(run)
        self.assertEqual(self.consumer.load(run)['next_block'],4)
        self.assertEqual(self.consumer.load(run)['observations'],[{'packet_id':'saved'}])

    def test_superseded_run_cannot_resume_execute_or_commit(self):
        run=self.consumer.start(self.item['id'])['run_id']
        self.reader.job.return_value={'job_id':'j_'+'a'*24,'status':'failed'}
        newer=self.consumer.start(self.item['id'],refresh=True)['run_id']
        self.assertNotEqual(run,newer)
        with self.assertRaisesRegex(ReaderError,'superseded'):self.consumer.resume(run)
        with self.assertRaisesRegex(ReaderError,'superseded'):self.consumer.execute(run)

    def test_result_commit_survives_worker_loss_without_duplicate_result(self):
        run=self.consumer.start(self.item['id'])['run_id']
        commit=self.consumer.queue.record_result
        def lost(*args,**kwargs):
            commit(*args,**kwargs)
            raise ReaderError('worker lost after commit')
        with patch('reading_tasks.consume.invoke',side_effect=self.response), \
                patch.object(self.consumer.queue,'record_result',side_effect=lost):
            with self.assertRaisesRegex(ReaderError,'after commit'):self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['status'],'completed')
        self.assertEqual(self.consumer.execute(run)['status'],'completed')
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_results').fetchone()[0],1)

    def test_concurrent_start_cannot_overwrite_a_new_worker_checkpoint(self):
        entered,release=threading.Event(),threading.Event()
        def job(action,*args,**kwargs):
            if action=='start':
                run=kwargs['parameters']['run_id']
                state=self.consumer.load(run)
                state['next_block']=4
                self.consumer.save(state,'running')
                entered.set()
                release.wait(5)
            return {'job_id':'j_'+'a'*24,'status':'queued'}
        self.reader.job.side_effect=job
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.consumer.start,self.item['id'])
            try:
                self.assertTrue(entered.wait(5))
                second=pool.submit(Consumer(self.reader).start,self.item['id'])
            finally:
                release.set()
            one,two=first.result(),second.result()
        self.assertEqual(one['run_id'],two['run_id'])
        self.assertEqual(self.consumer.load(one['run_id'])['next_block'],4)
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0],1)

    def test_unresolved_critical_evidence_keeps_task_pending(self):
        run=self.consumer.start(self.item['id'])['run_id']
        def requests(*args,**kwargs):
            response=self.response(*args,**kwargs)
            response['evidence_requests']=[{'start':0,'end':10,'timestamps':[5],'reason':'关键画面未能核定'}]
            return response
        with patch('reading_tasks.consume.invoke',side_effect=requests), \
                patch.object(self.consumer,'_evidence',return_value=[]):
            with self.assertRaisesRegex(ReaderError,'unresolved'):self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'],0)
        self.assertTrue(self.consumer.load(run)['pending_evidence'])
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'],'pending')

    def test_refresh_cannot_replace_launch_before_job_id_is_recorded(self):
        entered,release=threading.Event(),threading.Event()
        def launch(action,*args,**kwargs):
            if action=='start':
                entered.set()
                release.wait(5)
            return {'job_id':'j_'+'a'*24,'status':'queued'}
        self.reader.job.side_effect=launch
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(self.consumer.start,self.item['id'])
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ReaderError,'not yet confirmed'):
                    Consumer(self.reader).start(self.item['id'],refresh=True)
            finally:release.set()
            first.result()
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0],1)


if __name__=='__main__':unittest.main()
