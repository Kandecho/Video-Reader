from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reading_tasks.api import ACTIONS, execute
from reading_tasks.queue import Queue
from video_reader.common import ReaderError, write_json
from video_reader.reader import Reader


class FollowupsAPI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'config.json'
        write_json(self.config,{'cache_dir':'cache','tasks':{'directory':'tasks'}})
        self.reader=Reader(self.config)
        self.queue=Queue.from_settings(self.reader.config,self.config)
        self.item=self.queue.enqueue('BV1E1421t7m2',task='原任务要求')['item']

    def test_result_and_payload_updates_share_followups_without_changing_the_task(self):
        self.assertIn('followup-save',ACTIONS)
        self.assertIn('followup-list',ACTIONS)
        original=self.queue.show(self.item['id'],include_material=False)
        saved=execute(self.reader,'followup-save',self.item['id'],result={
            'description':'保存至casebook，保留这个具体交互的上下文','state':'pending',
            'notes':'有新增认识时再收录'})
        followup=saved['followup']
        self.assertTrue(saved['created'])
        self.assertEqual(followup['state'],'pending')
        payload=self.root/'followup.json'
        write_json(payload,{'id':followup['id'],'expected_revision':followup['revision'],
                            'state':'done','reason':'无新增认识，不另存入知识库'})
        updated=execute(self.reader,'followup-save',self.item['id'],payload=str(payload))
        self.assertFalse(updated['created'])
        self.assertEqual(updated['followup']['id'],followup['id'])
        self.assertEqual(updated['followup']['state'],'done')
        self.assertEqual(updated['followup']['artifacts'],[])
        shown=self.queue.show(self.item['id'],include_material=False)
        for key in ('task','state','updated','revision','latest_result'):
            self.assertEqual(shown[key],original[key])
        listed=execute(self.reader,'followup-list',self.item['id'])
        self.assertEqual([entry['id'] for entry in listed['followups']],[followup['id']])
        self.assertEqual(listed['description_history'],[followup['description']])

    def test_list_without_task_id_returns_all_records_and_task_list_is_scoped(self):
        other=self.queue.enqueue('BV1E1421t7m2',task='另一个原任务',new_task=True)['item']
        first=execute(self.reader,'followup-save',self.item['id'],result={
            'description':'仅留下本地收藏入口','state':'done'})['followup']
        second=execute(self.reader,'followup-save',other['id'],result={
            'description':'下一次整理为操作笔记','state':'pending'})['followup']
        self.assertEqual({record['id'] for record in execute(self.reader,'followup-list')['followups']},
                         {first['id'],second['id']})
        scoped=execute(self.reader,'followup-list',other['id'])
        self.assertEqual([record['id'] for record in scoped['followups']],[second['id']])

    def test_missing_or_empty_payload_cannot_create_an_implicit_followup(self):
        for payload in (None,{},[]):
            with self.subTest(payload=payload),self.assertRaises(ReaderError):
                execute(self.reader,'followup-save',self.item['id'],result=payload)
        self.assertEqual(execute(self.reader,'followup-list')['followups'],[])

    def test_followup_commands_do_not_acquire_material_or_use_scroll_memory(self):
        with patch.object(self.reader,'open',side_effect=AssertionError('no reading')), \
             patch('video_reader.platform.Platform',side_effect=AssertionError('no network')), \
             patch('scroll_agent.memory.Memory',side_effect=AssertionError('no personal memory')):
            saved=execute(self.reader,'followup-save',self.item['id'],result={
                'description':'无新增认识，不另存入知识库','state':'done'})
            listed=execute(self.reader,'followup-list',self.item['id'])
        self.assertEqual(listed['followups'][0]['id'],saved['followup']['id'])
        self.assertEqual(self.queue.show(self.item['id'])['state'],'pending')


if __name__=='__main__':
    unittest.main()
