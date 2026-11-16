import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from reading_tasks.api import execute
from reading_tasks.consume import Consumer
from reading_tasks import metrics
from video_reader.common import ReaderError, read_json, write_json
from video_reader.reader import Reader
from video_reader.speech import profile
from video_reader.sources import resolve


class SelectedReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root/'config.json'
        write_json(config,{'cache_dir':'cache','tasks':{'directory':'tasks'},'agent':{'directory':'agent'}})
        self.reader = Reader(config)
        self.consumer = Consumer(self.reader)
        media = self.root/'source.mp4'
        media.write_bytes(b'fixture only')
        self.sid = 'v_'+'a'*24
        self.data = {'id':self.sid,'source':resolve(str(media)),'media_path':str(media),'title':'Fixture',
            'metadata':{'duration_seconds':960,'has_audio':True,'has_video':False},'reads':[],
            'speech':[{'source':'captions','start':0,'end':960,'status':'ready','track':{'kind':'manual'},
                'segments':[{'start':i*120+1,'end':i*120+4,'text':f'第{i}段完整原文'} for i in range(8)]}]}
        self.reader.save(self.data)
        self.item = self.consumer.queue.enqueue(str(media),task='解释第5段的观点')['item']
        self.reader.job = Mock(return_value={'job_id':'j_'+'a'*24,'status':'queued'})
        self.index = self.reader.content(self.sid,_delivery=False)
        self.packets = []

    def response(self,prompt,images,schema,directory,options,**kwargs):
        payload = json.loads(prompt.split('\n',1)[1])
        self.packets.append(payload)
        packet = payload['material']
        return {'packet_id':packet['packet_id'],'observed_segment_ids':[s['segment_id'] for s in packet.get('segments',[])],
            'observed_frame_ids':[f['id'] for f in packet.get('frames',[])],
            'summary':'第5段观点','notes':'# 局部笔记\n保留原句和来源时间。',
            'uncertainties':[],'evidence_requests':[],'task_satisfied':True,
            'evidence_records':[{'text':'第5段观点',
                'segment_ids':[s['segment_id'] for s in packet.get('segments',[])],
                'frame_ids':[f['id'] for f in packet.get('frames',[])]}]
                if packet.get('segments') or packet.get('frames') else [],'uncertainty_decisions':[]}

    def start(self,positions=(5,),**kwargs):
        return execute(self.reader,'run-start',self.item['id'],index_id=self.index['index_id'],
            block_ids=[self.index['blocks'][i]['id'] for i in positions],**kwargs)['run_id']

    def test_selected_content_is_lossless_and_omitted_blocks_stay_reachable(self):
        run = self.start()
        with patch.object(self.reader,'transcript',side_effect=AssertionError('no full ASR')), \
                patch('reading_tasks.consume.invoke',side_effect=self.response) as host:
            result = self.consumer.execute(run)
        self.assertEqual(host.call_count,1)
        self.assertEqual(self.packets[0]['material']['segments'],self.index['blocks'][5]['segments'])
        coverage = result['task']['latest_result']['coverage']
        self.assertEqual(coverage['reading_scope']['unselected_blocks'],7)
        self.assertEqual(coverage['reading_scope']['directory_total_blocks'],8)
        self.assertFalse(result['task']['latest_result']['full_video_verified'])
        continuation = coverage['reading_scope']['continuation']
        rest = self.reader.content(**continuation,_delivery=False)
        self.assertEqual(len(rest['blocks']),8)
        self.assertEqual(coverage['metrics']['attempt_count'],1)
        self.assertIsNone(coverage['metrics']['reported_usage']['input_tokens'])
        self.assertFalse(coverage['metrics']['usage_complete'])

    def test_full_default_keeps_all_blocks_and_synthesis(self):
        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke',side_effect=self.response) as host:
            result = self.consumer.execute(run)
        self.assertEqual(host.call_count,3)
        scope = result['task']['latest_result']['coverage']['reading_scope']
        self.assertEqual((scope['mode'],scope['planned_blocks'],scope['unselected_blocks']),('full',8,0))
        self.assertEqual(sum(len(p['material']['segments']) for p in self.packets),8)

    def test_native_auto_selection_reuses_caption_snapshot_and_pixels(self):
        from video_reader.delivery import freeze_preview
        path = self.root/'native.jpg'
        Image.new('RGB',(64,32),'blue').save(path)
        preview = {'title':'Native fixture','duration_seconds':960,'part':1,'cid':7,
            'frames':[{'id':'native:5','time':650.,'path':str(path)}],
            'caption':{'kind':'automatic','language':'zh','segments':[{'start':640,'end':650,'text':'原生字幕'}]}}
        frozen = freeze_preview(self.reader,preview,None)
        self.item = self.consumer.queue.enqueue('BV0000000001',task='解释这一段')['item']
        with patch.object(self.reader,'preview',return_value=frozen) as native:
            self.index = self.reader.content(self.item['canonical'],_delivery=False)
            self.assertEqual(self.index['binding']['speech_source'],'captions')
            run = self.start()
            with patch('reading_tasks.consume.invoke',side_effect=self.response):
                result = self.consumer.execute(run)
        self.assertEqual(native.call_count,1)
        self.assertEqual(result['task']['latest_result']['coverage']['metrics']['image_attachments'],1)
        self.assertEqual(self.packets[0]['material']['segments'][0]['text'],'原生字幕')

    def test_changed_selection_does_not_reuse_old_claim(self):
        run = self.start((5,4,5))
        self.assertEqual(run,self.start((4,5)))
        with self.assertRaisesRegex(ReaderError,'selection'):
            self.start((3,))
        for params in ({'block_ids':[]},{'index_id':self.index['index_id']},
                       {'index_id':self.index['index_id'],'block_ids':['ci_'+'b'*24+':0']}):
            with self.assertRaises(ReaderError):
                self.consumer.start(self.item['id'],**params)

    def test_stale_review_and_other_source_fail_before_host(self):
        run = self.start()
        prepared = self.reader.review(self.sid)
        segment = prepared['segments'][0]
        self.reader.review(self.sid,'commit',payload={'snapshot_id':prepared['snapshot_id'],'base_revision':0,
            'corrections':[{'segment_id':segment['segment_id'],'original':segment['original'],
                'corrected_text':'修订原文','reason':'fixture','evidence':[{'kind':'context','segment_ids':[segment['segment_id']]}]}]})
        with patch('reading_tasks.consume.invoke',side_effect=AssertionError('no stale host')):
            with self.assertRaisesRegex(ReaderError,'changed'):
                self.consumer.execute(run)
        self.index = self.reader.content(self.sid,_delivery=False)
        other = self.root/'other.mp4'
        other.write_bytes(b'another source')
        self.item = self.consumer.queue.enqueue(str(other),task='另一来源')['item']
        run = self.start()
        with patch('reading_tasks.consume.invoke',side_effect=AssertionError('no wrong-source host')):
            with self.assertRaisesRegex(ReaderError,'another source'):
                self.consumer.execute(run)

    def test_incomplete_task_stays_pending_and_boolean_is_required(self):
        run = self.start()
        def incomplete(*args,**kwargs):
            response = self.response(*args,**kwargs)
            response['task_satisfied'] = False
            response['uncertainties'] = ['需补读前文，当前块无法支持完整结论']
            return response
        with patch('reading_tasks.consume.invoke',side_effect=incomplete):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(result['task']['state'],'pending')
        self.reader.job.return_value['status'] = 'completed'
        run = self.start(refresh=True)
        def missing(*args,**kwargs):
            response = self.response(*args,**kwargs)
            response.pop('task_satisfied')
            return response
        with patch('reading_tasks.consume.invoke',side_effect=missing):
            with self.assertRaisesRegex(ReaderError,'task_satisfied'):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'],0)

    def test_partial_speech_does_not_force_unselected_tail_processing(self):
        self.data['speech'] = [{'source':'local_faster_whisper','start':0,'end':120,'status':'ready',
            'profile':profile(self.reader.config,''),
            'segments':[{'start':1,'end':5,'text':'已有局部语音原文'}]}]
        self.reader.save(self.data)
        self.index = self.reader.content(self.sid,_delivery=False)
        run = self.start((0,))
        with patch.object(self.reader,'transcript',side_effect=AssertionError('no full-tail transcription')), \
                patch('reading_tasks.consume.invoke',side_effect=self.response):
            self.consumer.execute(run)
        self.assertFalse(self.consumer.status(run)['reading_scope']['speech_coverage']['complete'])
        self.reader.job.return_value['status'] = 'completed'
        self.item = self.consumer.queue.enqueue(self.data['source']['canonical'],task='空白段',new_task=True)['item']
        run = self.start((3,))
        with patch('reading_tasks.consume.invoke',side_effect=AssertionError('no empty evidence')):
            with self.assertRaisesRegex(ReaderError,'no ready text or frames'):
                self.consumer.execute(run)

    def test_selection_paginates_with_custom_blocks_and_preserves_context(self):
        self.data['metadata']['duration_seconds'] = 1920
        self.data['speech'][0].update(end=1920,segments=[
            {'start':15*i+1,'end':15*i+4,'text':f'原段{i}'} for i in range(128)])
        self.reader.save(self.data)
        index = self.reader.content(self.sid,block_seconds=15,context='术语背景',limit=100,_delivery=False)
        ids = [f"{index['index_id']}:{i}" for i in range(128)]
        run = self.consumer.start(self.item['id'],index_id=index['index_id'],block_ids=ids)['run_id']
        state = self.consumer.load(run)
        self.consumer._prepare(state)
        self.assertEqual(len(state['blocks']),128)
        self.assertEqual(state['binding']['context'],'术语背景')
        self.assertEqual(state['binding']['block_seconds'],15)

    def test_retry_counts_failed_attempts_without_repeating_accepted_blocks(self):
        run = self.start((0,1,2,3,4))
        calls = 0
        def fail_second(*args,**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ReaderError('transport fixture')
            return self.response(*args,**kwargs)
        with patch('reading_tasks.consume.invoke',side_effect=fail_second):
            with self.assertRaisesRegex(ReaderError,'transport fixture'):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'],4)
        with patch('reading_tasks.consume.invoke',side_effect=self.response):
            result = self.consumer.execute(run)
        stats = result['task']['latest_result']['coverage']['metrics']
        self.assertEqual((stats['attempt_count'],stats['failed_attempts'],stats['repeated_packet_attempts']),(4,1,1))
        self.assertEqual(stats['accepted_response_count'],3)


class AttemptMetricsTests(unittest.TestCase):
    def test_attachment_identity_usage_and_missing_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            img = root/'image.jpg'
            Image.new('RGB',(64,32),'blue').save(img)
            packet = {'packet_id':'packet','frames':[{'id':'frame','path':str(img)}]}
            for i in range(2):
                path = root/'attempts'/str(i)
                with metrics.attempt(path,str(i),packet,'read','prompt',{}):
                    if i==0:
                        waiting = metrics.summary(root,{'created_at':0,'observations':[]})
                        self.assertIsNone(waiting['host_elapsed_seconds'])
                        self.assertEqual(waiting['unfinished_attempts'],1)
                        (path/'host.log').write_text('not-json\n[]\n'+json.dumps({'type':'turn.completed',
                            'usage':{'input_tokens':100,'cached_input_tokens':50,'output_tokens':20}})+'\n',encoding='utf-8')
            state = {'created_at':0,'finished_at':10,'observations':[]}
            result = metrics.summary(root,state)
            self.assertEqual(result['image_attachments'],2)
            self.assertEqual(result['unique_image_sha256'],1)
            self.assertEqual(result['reported_usage']['input_tokens'],100)
            self.assertFalse(result['usage_complete'])
            self.assertIsNone(result['model_context_image_occurrences'])
            record = read_json(root/'attempts/0/metrics.json')
            self.assertEqual((record['images'][0]['width'],record['images'][0]['height']),(64,32))
            self.assertIsNone(record['configured_model'])
            self.assertTrue(record['usage_complete'])
            write_json(root/'attempts/legacy/packet.json',packet)
            old = metrics.summary(root,state)
            self.assertEqual(old['unmeasured_attempts'],1)
            self.assertFalse(old['host_elapsed_complete'])


if __name__=='__main__':
    unittest.main()
