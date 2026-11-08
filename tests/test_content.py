import copy
from pathlib import Path
from unittest.mock import patch
import unittest

from PIL import Image
from video_reader import delivery
from video_reader.common import ReaderError
from video_reader.reader import Reader
import test_foundations as foundations


class ContentTests(unittest.TestCase):
    setUp=foundations.SpeechCoverageTests.setUp
    tearDown=foundations.SpeechCoverageTests.tearDown

    def captions(self):
        self.data['metadata']['has_video']=False
        self.data['speech']=[{'source':'captions','start':0,'end':300,'status':'ready',
            'track':{'kind':'manual'},'segments':[
                {'start':1,'end':5,'text':'Super-agent 总入口'},
                {'start':118,'end':123,'text':'跨时间块完整正文，不得截断'},
                {'start':250,'end':260,'text':'后半段任务恢复'}]}]
        self.reader.save(self.data)

    def index(self,**options):
        return self.reader.content(self.sid,_delivery=False,**options)

    def test_blocks_preserve_crossing_sentences_and_middle_end_navigation(self):
        self.captions()
        index=self.index()
        self.assertEqual(len(index['blocks']),3)
        left=index['blocks'][0]['segments'][-1]
        right=index['blocks'][1]['segments'][0]
        self.assertEqual(left,right)
        self.assertEqual(left['text'],'跨时间块完整正文，不得截断')
        query=self.index(action='query',query='superagent')
        self.assertEqual(query['blocks'][0]['start'],0)
        tail=self.index(action='query',query='任务恢复')
        self.assertEqual(tail['blocks'][0]['start'],240)
        miss=self.index(action='query',query='画面中的无字幕操作')
        self.assertFalse(miss['text_match_found'])
        self.assertIn('storyboard',miss['continuation_hint'])

    def test_review_change_invalidates_old_directory_and_reuses_corrected_text(self):
        self.captions()
        before=self.index()
        prepared=self.reader.review(self.sid)
        segment=prepared['segments'][0]
        self.reader.review(self.sid,'commit',payload={'snapshot_id':prepared['snapshot_id'],'base_revision':0,
            'corrections':[{'segment_id':segment['segment_id'],'original':segment['original'],
                'corrected_text':'Super-agent 路由入口','reason':'provided source context',
                'evidence':[{'kind':'context','segment_ids':[segment['segment_id']]}]}]})
        with self.assertRaisesRegex(ReaderError,'changed'):
            self.index(index_id=before['index_id'])
        with self.assertRaisesRegex(ReaderError,'changed'):
            self.reader.content(self.sid,action='validate',index_id=before['index_id'])
        after=self.index()
        self.assertNotEqual(before['index_id'],after['index_id'])
        self.assertIn('路由入口',after['blocks'][0]['text'])
        with patch.object(self.reader,'materials',return_value={self.data['source']['canonical']:[
                {'session_id':self.sid,'media_available':True}]}):
            from_url=self.reader.content(self.data['source']['canonical'],_delivery=False)
        self.assertEqual(from_url['index_id'],after['index_id'])

    def test_long_original_text_remains_losslessly_deliverable(self):
        self.captions()
        text='原文🙂'*9000
        self.data['speech'][0]['segments'][0]['text']=text
        self.reader.save(self.data)
        index=self.index()
        result=self.reader.content(self.sid,action='material',block_ids=[index['blocks'][0]['id']])
        original=delivery.original_page(self.reader,result)
        self.assertEqual(original['blocks'][0]['segments'][0]['text'],text)
        parts=[]
        while True:
            parts.extend(result.get('material_parts',[]))
            if not result['delivery']['next_cursor']:break
            result=self.reader.continue_read(result['session_id'],result['delivery']['next_cursor'])
        self.assertEqual(delivery.restore(parts),original)

    def test_native_pixels_are_stable_and_account_bound_without_repreview(self):
        image=self.root/'preview.jpg'
        Image.new('RGB',(64,64),'blue').save(image)
        preview={'title':'native','duration_seconds':300,'part':1,'cid':7,
            'frames':[{'id':'native:0','time':30.,'path':str(image)}],
            'caption':{'kind':'automatic','language':'zh','segments':[{'start':20,'end':40,'text':'原生字幕'}]}}
        source='https://www.bilibili.com/video/BV0000000001?p=1'
        frozen=delivery.freeze_preview(self.reader,preview,None)
        with patch.object(self.reader,'preview',return_value=frozen) as native:
            first=self.reader.content(source,_delivery=False)
            asset=Path(first['blocks'][0]['frame_refs'][0]['path'])
            Image.new('RGB',(64,64),'red').save(image)
            second=self.reader.content(source,_delivery=False)
            self.assertEqual(first['index_id'],second['index_id'])
            self.assertEqual(native.call_count,1)
            with Image.open(asset) as frame:
                self.assertGreater(frame.getpixel((0,0))[2],200)
            with patch('video_reader.catalog.account_scope',return_value='other'):
                with self.assertRaisesRegex(ReaderError,'account'):
                    self.reader.content(source,action='validate',index_id=first['index_id'])
            asset.write_bytes(b'changed pixels')
            with self.assertRaisesRegex(ReaderError,'image changed'):
                self.reader.content(source,action='validate',index_id=first['index_id'])

    def test_no_caption_middle_and_end_blocks_can_be_inspected_without_asr(self):
        self.data['metadata']['has_video']=True
        self.reader.save(self.data)
        path=self.root/'source-pixels.jpg'
        Image.new('RGB',(64,64),'blue').save(path)
        def extract(media,output,points,**options):
            return ([{'index':i,'path':str(path),'timestamp_seconds':t} for i,t in enumerate(points)],{})
        with patch('video_reader.vendor.frames.extract_at_timestamps',side_effect=extract), \
                patch('video_reader.speech.decode',side_effect=AssertionError('directory must not start ASR')):
            index=self.index()
            result=self.reader.content(self.sid,action='storyboard',limit=3,index_id=index['index_id'])
        result=delivery.original_page(self.reader,result)
        self.assertEqual([f['timestamp_seconds'] for f in result['visual']['frames']],[60,180,270])
        self.assertTrue(all('no_ready_text' in b['gaps'] for b in result['blocks']))
        self.assertTrue(all('no_cached_frame_in_block' not in b['gaps'] for b in result['blocks']))

    def test_full_session_directory_rejects_changed_cached_pixels(self):
        self.captions()
        path=self.root/'cached-frame.jpg'
        Image.new('RGB',(64,64),'blue').save(path)
        self.data['reads']=[{'id':'fixture','frames':[{'id':'fixture:0','path':str(path),'timestamp_seconds':20}]}]
        self.reader.save(self.data)
        index=self.index()
        Image.new('RGB',(64,64),'red').save(path)
        with self.assertRaisesRegex(ReaderError,'image changed'):
            self.reader.content(self.sid,action='validate',index_id=index['index_id'])


if __name__=='__main__':unittest.main()
