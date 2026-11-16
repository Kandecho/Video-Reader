import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reading_tasks.catalog import Catalog
from reading_tasks.followups import Followups
from reading_tasks.queue import Queue
from reading_tasks.store import Store
from video_reader.common import ReaderError, read_json


URL = 'https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = Queue(Store(self.root / 'tasks', 'library'))
        self.followups = Followups(self.queue)
        self.catalog = Catalog(self.queue)
        template = self.root / 'template.html'
        template.write_text('<script type="application/json">__CATALOG_DATA__</script>', encoding='utf-8')
        patcher = patch('reading_tasks.catalog.TEMPLATE', template)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.item = self.queue.enqueue(URL, task='回答原来的问题')['item_id']

    def artifact(self, name, text='原始内容'):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def result(self, item_id=None):
        item_id = item_id or self.item
        path = self.artifact(item_id + '.md', '已经回答原来的问题')
        self.queue.record_result(item_id, {'summary': '原问题已经回答', 'artifacts': [str(path)]}, complete=True)
        with self.queue.store.connect() as db:
            return db.execute('SELECT max(id) FROM task_results WHERE item_id=?', (item_id,)).fetchone()[0]

    def test_pending_to_done_is_independent_of_task_state_results_and_original_description(self):
        result_id = self.result()
        self.catalog.build({'task_metadata': {self.item: {'task_description': '仅回答当前问题'}}})
        original = self.queue.show(self.item, include_material=False)
        created = self.followups.save(self.item, {'description': '以后把交互细节收进知识库',
                                                'source_result_id': result_id})
        record = created['followup']
        self.assertTrue(created['created'])
        self.assertEqual((record['state'], record['revision']), ('pending', 1))
        path = self.artifact('knowledge-entry.html', '<p>具体想法和上下文</p>')
        done = self.followups.save(self.item, {'id': record['id'], 'expected_revision': 1,
                                             'state': 'done', 'reason': '已登记至本地知识库',
                                             'notes': '保留原始案例上下文', 'artifacts': [str(path)]})
        self.assertFalse(done['created'])
        saved = done['followup']
        self.assertEqual((saved['state'], saved['revision']), ('done', 2))
        self.assertEqual(saved['created_at'], record['created_at'])
        self.assertEqual(saved['source_result_id'], result_id)
        self.assertEqual(saved['artifacts'], [{'path': str(path.resolve()),
                                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}])
        shown = self.queue.show(self.item, include_material=False)
        for key in ('state', 'task', 'updated', 'revision', 'latest_result'):
            self.assertEqual(shown[key], original[key])
        self.assertEqual(shown['followups'], [saved])
        task = read_json(self.catalog.snapshot_path)['tasks'][0]
        self.assertEqual(task['metadata']['task_description'], '仅回答当前问题')
        self.assertEqual(task['followups'][0]['state'], 'done')
        self.assertTrue(task['followups'][0]['artifacts'][0]['hash_valid'])

    def test_done_decision_without_files_does_not_complete_or_create_a_task_result(self):
        self.catalog.build()
        saved = self.followups.save(self.item, {'description': '无新增认识，不另存入知识库',
                                               'state': 'done', 'reason': '原成果已经足够'})['followup']
        self.assertEqual(saved['artifacts'], [])
        shown = self.queue.show(self.item)
        self.assertEqual(shown['state'], 'pending')
        self.assertIsNone(shown['latest_result'])
        snapshot = read_json(self.catalog.snapshot_path)
        self.assertEqual(snapshot['videos'], [])
        self.assertEqual(snapshot['stats']['results'], 0)
        self.assertEqual(snapshot['stats']['followup_states'], {'done': 1})
        self.assertEqual(snapshot['tasks'][0]['followups'][0]['description'], saved['description'])

    def test_source_result_must_belong_to_the_same_task_and_library(self):
        other = self.queue.enqueue(URL, task='另一个问题', new_task=True)['item_id']
        other_result = self.result(other)
        with self.assertRaisesRegex(ReaderError, 'does not belong'):
            self.followups.save(self.item, {'description': '收录这条观点', 'source_result_id': other_result})
        self.assertEqual(self.followups.list(self.item)['followups'], [])
        own_result = self.result()
        saved = self.followups.save(self.item, {'description': '保留这个案例',
                                               'source_result_id': own_result})['followup']
        with self.assertRaisesRegex(ReaderError, 'does not belong'):
            self.followups.save(self.item, {'id': saved['id'], 'source_result_id': other_result})
        self.assertEqual(self.followups.list(self.item)['followups'][0]['source_result_id'], own_result)

    def test_artifact_changes_and_missing_files_are_projected_without_changing_old_result_counts(self):
        self.result()
        changed = self.artifact('changed.md')
        missing = self.artifact('missing.md')
        saved = self.followups.save(self.item, {'description': '保存这两个本地条目',
                                               'artifacts': [str(changed), str(missing)]})['followup']
        changed.write_text('后续更改', encoding='utf-8')
        missing.unlink()
        self.catalog.build()
        snapshot = read_json(self.catalog.snapshot_path)
        self.assertEqual(snapshot['stats']['artifacts'], 1)
        self.assertEqual(snapshot['stats']['changed_artifacts'], 0)
        self.assertEqual(snapshot['stats']['missing_artifacts'], 0)
        self.assertEqual(snapshot['stats']['followup_artifacts'], 2)
        self.assertEqual(snapshot['stats']['changed_followup_artifacts'], 1)
        self.assertEqual(snapshot['stats']['missing_followup_artifacts'], 1)
        artifacts = snapshot['tasks'][0]['followups'][0]['artifacts']
        self.assertEqual({(a['exists'], a['hash_valid']) for a in artifacts}, {(True, False), (False, None)})
        revised = self.followups.save(self.item, {'id': saved['id'], 'notes': '保留原登记路径以便核对'})['followup']
        self.assertEqual(revised['artifacts'], saved['artifacts'])
        with self.assertRaisesRegex(ReaderError, 'artifact not found'):
            self.followups.save(self.item, {'description': '不存在的文件', 'artifacts': [str(missing)]})

    def test_revision_prevents_overwrite_and_events_preserve_before_and_after_wording(self):
        first = '保存至casebook，保留交互想法'
        second = '保存到casebook，保留交互想法'
        saved = self.followups.save(self.item, {'description': first})['followup']
        updated = self.followups.save(self.item, {'id': saved['id'], 'expected_revision': 1,
                                                 'description': second, 'state': 'paused'})['followup']
        with self.assertRaisesRegex(ReaderError, 'revision changed'):
            self.followups.save(self.item, {'id': saved['id'], 'expected_revision': 1, 'state': 'done'})
        listed = self.followups.list(self.item)
        self.assertEqual(listed['followups'], [updated])
        self.assertCountEqual(listed['description_history'], [first, second])
        with self.queue.store.connect() as db:
            events = [(row['kind'], json.loads(row['details'])) for row in db.execute(
                "SELECT kind,details FROM queue_events WHERE scope=? AND item_id=? AND kind LIKE 'followup_%' ORDER BY id",
                (self.queue.scope, self.item))]
        self.assertEqual([kind for kind, _ in events], ['followup_added', 'followup_updated'])
        self.assertEqual(events[1][1]['before']['description'], first)
        self.assertEqual(events[1][1]['after']['description'], second)
        self.catalog.build()
        history = read_json(self.catalog.snapshot_path)['description_history']
        self.assertTrue({first, second} <= set(history))
        self.assertEqual(len(history), len(set(history)))
        self.assertTrue(all(isinstance(value, str) and value.strip() for value in history))
        self.assertNotIn('task_description', read_json(self.catalog.snapshot_path)['tasks'][0]['metadata'])

    def test_scope_and_task_ids_cannot_expose_or_update_other_followups(self):
        saved = self.followups.save(self.item, {'description': '第一资料库的记录'})['followup']
        other_queue = Queue(Store(self.root / 'other', 'other-library', database=self.queue.store.path))
        other = Followups(other_queue)
        own = other_queue.enqueue(URL, task='另一资料库任务')['item_id']
        self.assertEqual(other.list(), {'followups': [], 'description_history': []})
        with self.assertRaises(ReaderError):
            other.list(self.item)
        with self.assertRaises(ReaderError):
            other.save(own, {'id': saved['id'], 'state': 'done'})
        with self.assertRaises(ReaderError):
            self.followups.save(own, {'description': '错库'})
        other.save(own, {'description': '另一资料库独立表达', 'state': 'done'})
        self.assertEqual(self.followups.list()['description_history'], ['第一资料库的记录'])

    def test_refresh_failure_preserves_the_committed_followup_and_event(self):
        self.catalog.build()
        with patch.object(Catalog, '_write_html', side_effect=RuntimeError('renderer unavailable')):
            saved = self.followups.save(self.item, {'description': '之后再做的独立要求'})
        self.assertEqual(saved['catalog_refresh']['status'], 'failed')
        self.assertEqual(self.queue.show(self.item)['followups'][0]['id'], saved['followup']['id'])
        self.assertEqual(self.catalog.status()['status'], 'needs_refresh')
        self.assertIn('followup_added', [event['kind'] for event in self.queue.history(item_id=self.item)['events']])
        self.catalog.build()
        self.assertEqual(self.catalog.status()['status'], 'ready')
        self.assertEqual(read_json(self.catalog.snapshot_path)['tasks'][0]['followups'][0]['id'], saved['followup']['id'])

    def test_description_is_free_text_but_empty_and_invalid_records_are_rejected(self):
        custom = '比较两种交互后再决定：先记在我的实验日记里 📝'
        saved = self.followups.save(self.item, {'description': custom, 'state': 'archived'})['followup']
        self.assertEqual(saved['description'], custom)
        for payload in ({}, {'description': ''}, {'description': ['整理']},
                        {'description': 'x' * 4001}, {'description': '整理', 'state': 'unknown'},
                        {'description': '整理', 'expected_revision': 1},
                        {'description': '整理', 'source_result_id': True}):
            with self.subTest(payload=payload), self.assertRaises(ReaderError):
                self.followups.save(self.item, payload)
        self.assertEqual(len(self.followups.list()['followups']), 1)


if __name__ == '__main__':
    unittest.main()
