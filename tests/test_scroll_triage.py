from unittest.mock import Mock, patch

from test_agent import AgentFixture, URL
from scroll_agent.queue import Queue
from scroll_agent.triage import Triage
from scroll_agent.memory import Memory
from video_reader.common import ReaderError


class TriageTests(AgentFixture):
    def setUp(self):
        super().setUp()
        self.queue = Queue(self.agent.memory)
        self.item = self.queue.enqueue(URL)['item']
        self.triage = Triage(self.queue, self.reader)
        self.preview = {'title':'测试材料', 'frames':[{'id':'frame_1','time':1,'path':'fixture.jpg'}],
                        'caption':{'segments':[{'start':0,'end':2,'text':'这里介绍三个设计素材网站'}]},
                        'delivery':{'binding':{'account_scope':self.queue.scope,'session_id':'p_'+'a'*24},
                                    'snapshot_id':'b'*24,'page':0,'next_cursor':None}}
        self.reader.preview = Mock(return_value=self.preview)
        self.reader.continue_read = Mock(return_value=self.preview)
        self.addCleanup(patch.stopall)
        patch.object(self.reader,'open',side_effect=AssertionError('no full open')).start()
        patch.object(self.reader,'transcript',side_effect=AssertionError('no ASR')).start()

    def payload(self, **changes):
        return {'snapshot_id':'b'*24,'content_type':'resource_list','type_clear':True,
                'type_reason':'画面及字幕展示素材网站','intent':{'kind':'none','reason':''},
                'evidence':[{'kind':'frame','page':0,'frame_id':'frame_1','observation':'画面列出素材站点'}],
                'suggestion_reason':'资源清单便于以后按用途查找','uncertainties':[],**changes}

    def test_reader_is_material_provider_host_submits_and_no_scheme_executes(self):
        prepared = self.triage.prepare(self.item['id'])
        self.assertTrue(prepared['host_assessment_required'])
        self.assertEqual(self.triage.show(self.item['id'])['status'],'prepared')
        result = self.triage.submit(self.item['id'],self.payload())
        self.assertEqual(result['status'],'suggested')
        self.assertEqual(result['assessment']['recommendation']['id'],'resource_catalog')
        self.assertFalse(result['executed'])
        self.assertEqual(self.queue.show(self.item['id'])['state'],'pending')
        self.reader.preview.assert_called_once_with(URL,density='light',max_frames=5,contact_sheet=True)

    def test_explicit_request_is_preserved_and_takes_priority_over_a_supported_type(self):
        self.queue.update(self.item['id'],task='请判断评论里哪些是真人发言')
        self.triage.prepare(self.item['id'])
        result = self.triage.submit(self.item['id'],self.payload(intent={'kind':'request','reason':'用户明确提出判断任务'}))
        self.assertEqual(result['status'],'awaiting_user')
        self.assertEqual(result['assessment']['intent']['request'],'请判断评论里哪些是真人发言')
        self.assertIsNone(result['assessment']['recommendation'])

    def test_evaluative_comment_does_not_become_an_execution_request(self):
        self.queue.update(self.item['id'],task='这个想法有意思，纯雨声可能更好')
        self.triage.prepare(self.item['id'])
        result = self.triage.submit(self.item['id'],self.payload(content_type='creative_work',intent={'kind':'comment','reason':'这是评价，不是让组件执行'}))
        self.assertEqual(result['status'],'suggested')
        self.assertIsNone(result['assessment']['intent']['request'])
        self.assertEqual(result['assessment']['intent']['comment'],'这个想法有意思，纯雨声可能更好')

    def test_ambiguous_type_or_note_and_unsupported_category_stay_undetermined(self):
        self.triage.prepare(self.item['id'])
        for changes in ({'type_clear':False}, {'content_type':'unknown','evidence':[]}, {'content_type':'analysis'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.triage.submit(self.item['id'],self.payload(**changes))['status'],'undetermined')
        self.queue.update(self.item['id'],task='这个再看看')
        self.triage.prepare(self.item['id'])
        result=self.triage.submit(self.item['id'],self.payload(intent={'kind':'uncertain','reason':'用途不明确'}))
        self.assertEqual(result['status'],'undetermined')

    def test_no_title_only_clear_judgment_unknown_frame_or_invented_caption(self):
        self.triage.prepare(self.item['id'])
        for evidence in ([],[{'kind':'frame','page':0,'frame_id':'made_up','observation':'假证据'}],
                         [{'kind':'caption','page':0,'quote':'字幕里没有的内容'}]):
            with self.subTest(evidence=evidence), self.assertRaises(ReaderError):
                self.triage.submit(self.item['id'],self.payload(evidence=evidence))

    def test_real_caption_reference_is_accepted(self):
        self.triage.prepare(self.item['id'])
        result=self.triage.submit(self.item['id'],self.payload(evidence=[{'kind':'caption','page':0,'quote':'三个设计素材网站'}]))
        self.assertEqual(result['status'],'suggested')

    def test_cannot_discard_a_note_or_invent_request_and_snapshot_must_match(self):
        self.triage.prepare(self.item['id'])
        with self.assertRaises(ReaderError):
            self.triage.submit(self.item['id'],self.payload(intent={'kind':'request','reason':'捏造请求'}))
        with self.assertRaises(ReaderError):
            self.triage.submit(self.item['id'],self.payload(snapshot_id='wrong'))
        self.queue.update(self.item['id'],task='原始附言')
        self.triage.prepare(self.item['id'])
        with self.assertRaises(ReaderError):
            self.triage.submit(self.item['id'],self.payload())

    def test_task_changes_invalidate_assessment_but_priority_does_not(self):
        self.triage.prepare(self.item['id'])
        self.triage.submit(self.item['id'],self.payload())
        self.queue.update(self.item['id'],priority=5)
        self.assertFalse(self.triage.show(self.item['id'])['stale'])
        self.queue.update(self.item['id'],task='新增要求')
        self.assertTrue(self.triage.show(self.item['id'])['stale'])
        with self.assertRaisesRegex(ReaderError,'changed'):
            self.triage.submit(self.item['id'],self.payload())

    def test_prepared_material_reuses_after_restart_and_history_survives_resubmission(self):
        self.triage.prepare(self.item['id'])
        self.triage.submit(self.item['id'],self.payload())
        second=Triage(self.queue,self.reader)
        self.assertTrue(second.prepare(self.item['id'])['reused_material'])
        self.assertEqual(self.reader.preview.call_count,1)
        second.submit(self.item['id'],self.payload(type_clear=False))
        saved=[e for e in second.history(self.item['id'])['events'] if e['kind']=='assessment_saved']
        self.assertEqual(len(saved),2)

    def test_account_bound_material_and_account_scoped_history(self):
        self.preview['delivery']['binding']['account_scope']='other'
        with self.assertRaises(ReaderError):
            self.triage.prepare(self.item['id'])
        self.assertEqual(self.triage.show(self.item['id'])['status'],'failed')
        other=Triage(Queue(Memory(self.agent.root,'other')),self.reader)
        with self.assertRaises(ReaderError):
            other.show(self.item['id'])

    def test_continuation_uses_reader_public_frozen_cursor_and_does_not_imply_observation(self):
        self.preview['delivery']['next_cursor']='b'*24+':1'
        self.triage.prepare(self.item['id'])
        page={**self.preview,'delivery':{**self.preview['delivery'],'page':1,'next_cursor':None}}
        self.reader.continue_read=Mock(return_value=page)
        result=self.triage.material(self.item['id'],'b'*24+':1')
        self.assertEqual(result['triage']['material_pages_saved'],2)
        self.reader.continue_read.assert_called_once_with('p_'+'a'*24,'b'*24+':1')
        self.assertEqual(result['triage']['status'],'prepared')

    def test_lossless_fragmented_preview_assembles_via_public_decoder_for_frame_evidence(self):
        from video_reader.delivery import _parts
        parts=list(_parts({'frames':self.preview['frames'],'caption':self.preview['caption']}))
        cut=len(parts)//2
        first={'material_parts':parts[:cut],'delivery':{**self.preview['delivery'],'pages_in_snapshot':2,'next_cursor':'b'*24+':1'}}
        second={'material_parts':parts[cut:],'delivery':{**first['delivery'],'page':1,'next_cursor':None}}
        self.reader.preview.return_value=first
        self.triage.prepare(self.item['id'])
        with self.assertRaisesRegex(ReaderError,'remaining'):
            self.triage.content(self.item['id'])
        self.reader.continue_read.return_value=second
        self.triage.material(self.item['id'],'b'*24+':1')
        content=self.triage.content(self.item['id'])
        self.assertEqual(content['material']['frames'],self.preview['frames'])
        result=self.triage.submit(self.item['id'],self.payload(evidence=[{'kind':'frame','page':'assembled','frame_id':'frame_1','observation':'资源页面'}]))
        self.assertEqual(result['status'],'suggested')
        self.assertFalse(result['full_reading_completed'])
