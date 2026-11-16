import json
from pathlib import Path
import tempfile
import unittest

from reading_tasks.catalog import Catalog
from reading_tasks.followups import Followups
from reading_tasks.queue import Queue
from reading_tasks.store import Store
from video_reader.common import ReaderError, read_json

URL='https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class FormalCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.queue=Queue(Store(self.root/'tasks','formal-library'))
        self.catalog=Catalog(self.queue)

    def item(self, description='回答原问题', task_type='回答问题'):
        return self.queue.enqueue(URL, task='原始附言', task_type=task_type,
                                  task_description=description, new_task=True)['item_id']

    def result(self, item_id):
        return self.queue.record_result(item_id, {'summary':'有明确答案','answer':{
            'question':'原问题','text':'明确答案','status':'answered'},
            'catalog':{'task_goal':'旧显示目标','task_description':'旧留存标签'}}, complete=True)

    def snapshot(self):
        return read_json(self.catalog.snapshot_path)

    def test_canonical_null_never_revives_legacy_task_or_metadata(self):
        item=self.item()
        self.result(item)
        self.catalog.build()
        self.catalog.update_metadata(item, {'task_type':None,'task_description':'  '})
        task=self.snapshot()['tasks'][0]
        self.assertIsNone(task['task_type'])
        self.assertIsNone(task['task_description'])
        self.assertIsNone(task['work'])
        self.assertEqual(task['request'],'原始附言')
        self.assertEqual(task['metadata']['task_goal'],'旧显示目标')
        self.assertEqual(task['metadata']['task_description'],'旧留存标签')
        self.catalog.build()
        self.assertIsNone(self.snapshot()['tasks'][0]['task_description'])
        self.assertEqual(self.snapshot()['types'],[])
        self.assertIn('回答问题',self.catalog.status()['task_types'])

    def test_optional_presentation_nulls_mask_old_result_values(self):
        item=self.item()
        self.queue.record_result(item, {'summary':'明确答案','answer':{
            'question':'问题','text':'答案'},'catalog':{'notes':'旧说明','format':'HTML','purposes':['学习']}},complete=True)
        self.catalog.build()
        self.catalog.update_metadata(item, {'notes':None,'format':'  ','purposes':[],'tags':None,'retention':' '})
        task=self.snapshot()['tasks'][0]
        self.assertIsNone(task['metadata']['notes'])
        self.assertIsNone(task['metadata']['format'])
        self.assertIsNone(task['metadata']['retention'])
        self.assertEqual(task['metadata']['purposes'],[])
        self.assertEqual(task['metadata']['tags'],[])
        self.assertIsNone(task['delivery']['target'])
        self.catalog.build()
        self.assertIsNone(self.snapshot()['tasks'][0]['metadata']['notes'])

    def test_source_cover_is_shared_and_explicit_clear_does_not_reuse_preview(self):
        first=self.item()
        second=self.item('另一个问题')
        image=self.root/'original-cover.jpg'
        image.write_bytes(b'local fixture cover')
        self.catalog.build({'source_metadata':{URL:{'cover_path':str(image)}},
                            'task_metadata':{first:{'preview_path':str(image)}}})
        tasks=self.snapshot()['tasks']
        self.assertEqual({task['cover_url'] for task in tasks},{image.as_uri()})
        self.assertEqual({task['id'] for task in tasks},{first,second})
        self.catalog.build({'source_metadata':{URL:{'cover_path':None}}})
        self.assertTrue(all(task['cover_url'] is None for task in self.snapshot()['tasks']))
        self.catalog.build()
        self.assertTrue(all(task['cover_url'] is None for task in self.snapshot()['tasks']))
        with self.assertRaises(ReaderError):
            self.catalog.build({'source_metadata':{URL:{'status':'done'}}})

    def test_termination_is_completed_without_inventing_reading_or_type(self):
        item=self.item('结束不可获取材料的处理',None)
        self.queue.update(item,state='done',completion_method='终止')
        self.catalog.build()
        task=self.snapshot()['tasks'][0]
        self.assertEqual(task['state'],'done')
        self.assertEqual(task['completion_method'],'终止')
        self.assertIsNone(task['task_type'])
        self.assertEqual(task['results'],[])
        self.assertEqual(self.snapshot()['stats']['total_task_states'],{'done':1})
        self.assertEqual(self.snapshot()['types'],[])

    def test_result_snapshot_is_distinct_from_current_description_and_legacy_unknown(self):
        item=self.item()
        self.result(item)
        self.catalog.build()
        self.assertTrue(self.snapshot()['tasks'][0]['result_matches_task'])
        self.queue.update(item, task_description='新的具体工作')
        self.assertFalse(self.snapshot()['tasks'][0]['result_matches_task'])
        with self.queue.store.connect() as db:
            row=db.execute('SELECT id,record FROM task_results WHERE item_id=?',(item,)).fetchone()
            record=json.loads(row['record'])
            record.pop('task_description')
            db.execute('UPDATE task_results SET record=? WHERE id=?',(json.dumps(record),row['id']))
        self.catalog.build()
        self.assertIsNone(self.snapshot()['tasks'][0]['result_matches_task'])

    def test_dispositions_do_not_become_task_types_or_completion(self):
        item=self.item('整理笔记','整理笔记')
        self.result(item)
        self.catalog.build()
        Followups(self.queue).save(item, {'description':'存入另一个位置','state':'pending'})
        snapshot=self.snapshot()
        self.assertEqual(snapshot['types'],[{'name':'整理笔记','count':1}])
        self.assertEqual(snapshot['stats']['total_task_states'],{'done':1})
        self.assertEqual(snapshot['stats']['followup_states'],{'pending':1})
        self.assertNotIn('存入另一个位置',snapshot['task_types'])


if __name__=='__main__':
    unittest.main()
