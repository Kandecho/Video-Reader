import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from PIL import Image
from video_reader.common import ReaderError, settings, write_json, read_json
from video_reader.platform import Platform, PlatformError
from video_reader.preview import preview, snapshot_material, validate_snapshot
from video_reader import sources, speech, qwen, delivery, review
from video_reader.reader import Reader
from video_reader.qwen_pipeline import owned_chunk
import test_foundations as foundations

BV='BV1Eb411u7Fw'


class PreviewRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=settings(self.root/'config.json')
        self.config['preview']['network']['min_gap_seconds']=0
        self.good={'index':[0,10,20,30], 'image':['https://i0.hdslb.com/sprite.jpg'],
                   'img_x_len':4,'img_y_len':1,'img_x_size':40,'img_y_size':20}
        self.bad={**self.good,'index':[]}
        body=io.BytesIO();Image.new('RGB',(160,20),'blue').save(body,format='JPEG');self.image=body.getvalue()
        self.queue=[self.good];self.calls=[]
        def transport(url,form=None,**kwargs):
            self.calls.append(url);path=urlparse(url).path
            if path.endswith('.jpg'):return self.image
            if path.endswith('/view'):data={'pages':[{'cid':1,'duration':40}],'owner':{'mid':1}}
            elif path.endswith('/v2'):data={'subtitle':{'subtitles':[]}}
            elif path.endswith('/videoshot'):data=self.queue.pop(0)
            else:raise AssertionError(path)
            return json.dumps(data if 'code' in data else {'code':0,'data':data}).encode()
        self.transport=transport
        self.credential=patch('video_reader.platform.credentials',return_value={'account_marker':'fixture','cookies':[]})
        self.credential.start();self.addCleanup(self.credential.stop)
        self.client=Platform(self.config,transport=transport)
        self.url='https://api.bilibili.com/x/player/videoshot?bvid='+BV+'&cid=1&index=1'
        self.cache=self.client.root/(hashlib.sha256(self.url.encode()).hexdigest()+'.json')

    def test_bad_cached_success_is_bypassed_and_replaced_by_valid_snapshot(self):
        write_json(self.cache,{'code':0,'data':self.bad})
        result=preview(self.client,BV,max_frames=3)
        self.assertEqual(len(result['frames']),3)
        self.assertTrue(result['visual_recovery']['invalid_cache_bypassed'])
        self.assertEqual(sum('/videoshot?' in u for u in self.calls),1)
        self.assertEqual(read_json(self.cache)['data']['index'],self.good['index'])

    def test_fresh_bad_snapshot_is_not_cached_and_recovery_is_bounded(self):
        self.queue=[self.bad,self.good]
        result=preview(self.client,BV,max_frames=3)
        self.assertEqual(result['visual_recovery']['attempts'],2)
        self.assertEqual(len(result['frames']),3)
        self.assertEqual(sum('/videoshot?' in u for u in self.calls),2)
        self.assertEqual(read_json(self.cache)['data']['index'],self.good['index'])
        self.queue=[self.bad,self.bad]
        self.cache.unlink()
        result=preview(self.client,BV,max_frames=3)
        self.assertIn('visual:snapshot_index_unavailable',result['gaps'])
        self.assertFalse(self.cache.exists())

    def test_restriction_and_offline_bad_cache_do_not_trigger_recovery(self):
        self.queue=[{'code':-412}]
        result=preview(self.client,BV)
        self.assertIn('visual:platform_code:-412',result['gaps'])
        self.assertEqual(sum('/videoshot?' in u for u in self.calls),1)
        self.assertEqual(self.client.status()['paused'],'-412')
        write_json(self.cache,{'code':0,'data':self.bad})
        offline=Platform(self.config,offline=True,transport=Mock(side_effect=AssertionError('offline network')))
        with self.assertRaisesRegex(PlatformError,'snapshot_index_unavailable'):
            snapshot_material(offline,{'bvid':BV,'cid':1,'index':1},86400)

    def test_invalid_index_or_grid_is_rejected_before_cache_acceptance(self):
        for value in ([0,'10'],[0,float('nan')],[-1,0],[],[10,0]):
            with self.subTest(value=value),self.assertRaises(PlatformError):
                validate_snapshot({**self.good,'index':value})
        with self.assertRaises(PlatformError):validate_snapshot({**self.good,'image':[]})


class AcquisitionRepairTests(unittest.TestCase):
    error='python.exe failed (1): ERROR: Unable to download webpage: The read operation timed out'

    def test_metadata_only_recovers_once_with_identical_command(self):
        with patch('video_reader.sources.run',side_effect=[ReaderError(self.error),'{}']) as call:
            info,diagnostics=sources.metadata_info(['same','command'],{})
        self.assertEqual(info,{})
        self.assertEqual(diagnostics['retry_count'],1)
        self.assertEqual(call.call_args_list[0],call.call_args_list[1])
        self.assertIn('timed out',diagnostics['attempts'][0]['message'])

    def test_recovery_exhaustion_is_structured_and_nontransient_is_not_retried(self):
        with patch('video_reader.sources.run',side_effect=ReaderError(self.error)) as call:
            with self.assertRaises(sources.AcquisitionError) as caught:sources.metadata_info(['command'],{})
        self.assertEqual(call.call_count,2)
        self.assertEqual(caught.exception.code,'SOURCE_METADATA_FAILED')
        self.assertEqual(len(caught.exception.details['attempts']),2)
        for message in ('HTTP Error 403','platform_daily_budget_exhausted','Unable to extract initial state'):
            with patch('video_reader.sources.run',side_effect=ReaderError(message)) as call:
                with self.assertRaises(sources.AcquisitionError):sources.metadata_info(['command'],{})
                self.assertEqual(call.call_count,1)

    def test_shared_pause_or_exhausted_budget_prevents_second_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            for state in ({'paused':'http_429'},{'count':120}):
                write_json(Path(folder)/'network.json',state)
                profile={'_network_budget':{'directory':folder,'options':{'daily_requests':120}}}
                with patch('video_reader.sources.run',side_effect=ReaderError(self.error)) as call:
                    with self.assertRaises(sources.AcquisitionError) as caught:sources.metadata_info(['command'],profile)
                self.assertEqual(call.call_count,1)
                self.assertIsNotNone(caught.exception.details['recovery_blocked_by'])

    def test_part_reordering_during_recovery_refuses_media_download(self):
        source=sources.resolve(BV)
        first={'code':0,'data':{'title':'part','pages':[{'cid':10}]}}
        changed={'code':0,'data':{'title':'part','pages':[{'cid':20}]}}
        with tempfile.TemporaryDirectory() as folder,patch('video_reader.sources.request_json',side_effect=[first,changed]),\
             patch('video_reader.sources.run',side_effect=[ReaderError(self.error),json.dumps({'id':BV+'_p1'})]) as run:
            with self.assertRaises(sources.AcquisitionError) as caught:sources.acquire(source,Path(folder),{})
            self.assertEqual(caught.exception.code,'SOURCE_PART_CHANGED')
            self.assertEqual(run.call_count,2)


class RecognitionRepairTests(unittest.TestCase):
    setUp=foundations.SpeechCoverageTests.setUp
    tearDown=foundations.SpeechCoverageTests.tearDown
    record=foundations.SpeechCoverageTests.record

    def suspect_record(self):
        record=self.record(0,300)
        record['segments'][0]['recognition']={'flags':['suspect_decoding','low_word_confidence'],
          'no_speech_probability':.7382,'avg_logprob':-.6621,'mean_word_probability':.0156}
        return record

    def test_suspect_raw_text_is_preserved_and_distinct_in_reading_evidence_and_review(self):
        record=self.suspect_record();self.data['speech']=[record];self.reader.save(self.data)
        before=(self.reader.directory(self.sid)/'manifest.json').read_bytes()
        original_id=review.document(self.reader._speech(self.data,0,300,'asr'))[1][0]['segment_id']
        with patch('video_reader.speech.decode',side_effect=AssertionError('cached candidate must not decode')):
            for view in ('reading','raw','evidence'):
                result=self.reader.transcript(self.sid,source='asr',view=view,verify=False)
                segment=result['segments'][0]
                self.assertEqual(segment['text'],record['segments'][0]['text'])
                self.assertEqual(segment['segment_id'],original_id)
                self.assertEqual(segment['review_status'],'uncertain')
                self.assertEqual(segment['text_status'],'unverified_candidate')
                self.assertEqual(result['recognition_assessment']['suspect_segments'],1)
                self.assertTrue(result['coverage']['complete'])
        prepared=self.reader.review(self.sid,source='asr')
        self.reader.review(self.sid,'commit',source='asr',payload={'snapshot_id':prepared['snapshot_id'],
            'base_revision':0,'reviewed_segment_ids':[original_id]})
        reviewed=self.reader.transcript(self.sid,source='asr',verify=False)
        self.assertEqual(reviewed['segments'][0]['review_status'],'reviewed')
        self.assertEqual(reviewed['segments'][0]['text_status'],'reviewed_text')
        self.assertEqual((self.reader.directory(self.sid)/'manifest.json').read_bytes(),before)

    def test_one_low_confidence_word_alone_is_not_reclassified_as_suspect_speech(self):
        record=self.record(0,300);record['segments'][0]['recognition']={'flags':['low_word_confidence']}
        self.data['speech']=[record];self.reader.save(self.data)
        result=self.reader.transcript(self.sid,source='asr',verify=False)
        self.assertEqual(result['segments'][0]['review_status'],'pending')
        self.assertEqual(result['recognition_assessment']['suspect_segments'],0)

    def test_old_qwen_no_speech_with_unplaced_text_stays_processed_but_not_review_complete(self):
        from video_reader.qwen_pipeline import owned_chunk
        chunk=owned_chunk('候选。',[SimpleNamespace(text='候选',start_time=60,end_time=60)],
          {'index':0,'owner_start':0,'owner_end':600,'input_start':0,'input_end':620},10)
        silent=owned_chunk('',[],{'index':1,'owner_start':0,'owner_end':20,'input_start':0,'input_end':20},10,60)
        self.data['metadata']['duration_seconds']=62
        self.data['speech']=[{'source':qwen.SOURCE,'start':0,'end':60,'status':'no_speech','segments':[],
          'profile':qwen.profile(self.reader.config,''),'qwen_chunk':chunk},
          {'source':qwen.SOURCE,'start':60,'end':62,'status':'no_speech','segments':[],
           'profile':qwen.profile(self.reader.config,''),'qwen_chunk':silent}]
        self.reader.save(self.data)
        with patch('video_reader.qwen.decode',side_effect=AssertionError('do not repeat processed interval')):
            result=self.reader.transcript(self.sid,source='qwen',verify=False)
        self.assertEqual(result['status'],'alignment_unresolved')
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(result['unplaced_candidates'][0]['raw_text'],'候选。')
        self.assertEqual(result['unplaced_candidates'][0]['raw_alignment'][0]['start'],60)
        self.assertFalse(result['review']['complete'])
        prepared=self.reader.review(self.sid,source='qwen',start=0,end=30)
        self.assertFalse(prepared['scope_review']['complete'])
        clear=self.reader.review(self.sid,source='qwen',start=60,end=62)
        self.assertTrue(clear['scope_review']['complete'])
        exported=self.reader.export(self.sid,self.root/'export',0,source='qwen')
        self.assertIn('候选。',(self.root/'export/index.html').read_text(encoding='utf-8'))

    def test_valid_padding_only_alignment_does_not_become_an_unplaced_failure(self):
        from video_reader.recognition import unplaced
        chunk=owned_chunk('前文。',[SimpleNamespace(text='前文',start_time=0,end_time=1)],
          {'index':0,'owner_start':20,'owner_end':620,'input_start':0,'input_end':640},10,298)
        self.assertIsNone(unplaced({'start':300,'end':360,'qwen_chunk':chunk}))

    def test_changed_recognition_diagnostics_invalidate_new_dynamic_cursor_not_frozen_pages(self):
        record=self.record(0,300);record['segments']=[{'start':i,'end':i+1,'text':str(i)} for i in range(3)]
        self.data['speech']=[record];self.reader.save(self.data)
        first=self.reader.transcript(self.sid,source='asr',limit=1,verify=False)
        record['segments'][1]['recognition']={'flags':['suspect_decoding']};self.reader.save(self.data)
        with self.assertRaisesRegex(ReaderError,'changed'):self.reader.continue_read(self.sid,first['delivery']['next_cursor'])
        frozen=self.reader.continue_read(self.sid,first['delivery']['snapshot_id']+':0')
        self.assertEqual(frozen['segments'][0]['text'],'0')


class ReadingProjectionTests(unittest.TestCase):
    setUp=foundations.SpeechCoverageTests.setUp
    tearDown=foundations.SpeechCoverageTests.tearDown

    def fixture(self):
        image=self.root/'frame.jpg';Image.new('RGB',(96,96),'blue').save(image)
        return {'session_id':self.sid,'visual':{'frames':[{'id':'f0','path':str(image),'timestamp_seconds':1,'time':'00:01',
            'temporal':{'lines':['very large OCR']*5000}}],'next_page':1,'total_frames':2},
            'speech':{'segments':[{'segment_id':str(i),'start':i,'end':i+1,'text':'readable sentence','review_status':'pending'} for i in range(3)],
                      'total_segments':10,'next_offset':3,'next_cursor':'speech:next'}}

    def test_first_page_contains_text_and_original_image_and_all_evidence_round_trips(self):
        result=self.fixture();pages=delivery.pages(result,12000,1000000,reading=True)
        first=pages[0]
        self.assertEqual(len(first['visual']['frames']),1)
        self.assertEqual(len(first['speech']['segments']),3)
        self.assertEqual(first['speech']['next_offset'],3)
        self.assertEqual(first['visual']['next_page'],1)
        self.assertEqual(delivery.restore([part for page in pages for part in page.get('material_parts',[])]),result)
        self.assertNotIn('temporal',first['visual']['frames'][0])
        self.assertTrue(first['visual']['frames'][0]['temporal_evidence_available'])

    def test_partial_projection_does_not_expose_offsets_that_skip_undelivered_segments(self):
        result=self.fixture();result['speech']['segments'][0]['text']='x'*20000
        first=delivery.pages(result,12000,1000000,reading=True)[0]
        self.assertEqual(first['speech']['segments'],[])
        self.assertNotIn('next_offset',first['speech'])
        self.assertNotIn('next_cursor',first['speech'])
        self.assertEqual(first['speech']['remaining_in_snapshot'],3)
        self.assertLessEqual(len(delivery.encoded(first)),12000)

    def test_original_pixels_over_projection_budget_are_explicitly_deferred(self):
        result=self.fixture();first=delivery.pages(result,12000,1,reading=True)[0]
        self.assertEqual(first['visual']['frames'],[])
        self.assertNotIn('next_page',first['visual'])
        self.assertEqual(first['visual']['remaining_in_snapshot'],1)

    def test_final_counters_do_not_discard_an_image_projection_at_text_boundary(self):
        result=self.fixture()
        result['speech']['segments']=result['speech']['segments'][:1]
        # Exercise the narrow boundary where the utterance fits before the
        # final counters, but the finished page must defer it as a whole.
        for length in range(11000,11800,20):
            result['speech']['segments'][0]['text']='x'*length
            first=delivery.pages(result,12000,1000000,reading=True)[0]
            self.assertIn('reading_projection',first)
            self.assertEqual(len(first['visual']['frames']),1)
            self.assertLessEqual(len(delivery.encoded(first)),12000)


if __name__=='__main__':unittest.main(verbosity=2)
