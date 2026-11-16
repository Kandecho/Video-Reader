import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reading_tasks.api import execute, from_namespace
from reading_tasks.cli import parser
from reading_tasks.consume import Consumer
from reading_tasks.followups import Followups
from reading_tasks.queue import Queue, task_identity
from reading_tasks.store import Store
from video_reader.common import ReaderError, write_json
from video_reader.reader import Reader


URL = 'https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class TaskFields(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        write_json(self.config, {'cache_dir': 'cache', 'tasks': {'directory': 'tasks'}})
        self.reader = Reader(self.config)
        self.queue = Queue.from_settings(self.reader.config, self.config)

    def item(self, **kwargs):
        return self.queue.enqueue(URL, new_task=True, **kwargs)['item']

    def answer(self, item_id, **kwargs):
        return self.queue.record_result(item_id, {
            'summary': '已回答', 'answer': {'question': '具体问题', 'text': '具体回答'}, **kwargs}, complete=True)

    def test_legacy_schema_is_upgraded_once_and_cleared_description_stays_null(self):
        store = Store(self.root / 'legacy', 'legacy')
        with store.connect() as db:
            db.execute('CREATE TABLE queue_items(row_id INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,scope TEXT NOT NULL,'
                       'canonical TEXT NOT NULL,original_source TEXT NOT NULL,task TEXT NOT NULL,title TEXT NOT NULL,'
                       'state TEXT NOT NULL,priority INTEGER NOT NULL,order_at REAL NOT NULL,created REAL NOT NULL,'
                       'updated REAL NOT NULL,revision INTEGER NOT NULL)')
            db.execute('INSERT INTO queue_items VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('q_legacy', 'legacy', URL, URL, '旧正式要求', '旧标题', 'pending', 0, 1., 1., 1., 1))
            db.execute('CREATE TABLE task_annotations(scope TEXT NOT NULL,item_id TEXT NOT NULL,payload TEXT NOT NULL,'
                       'PRIMARY KEY(scope,item_id))')
            for index, (item_id, task, annotation) in enumerate((
                    ('q_comment', '这个想法不错', {'kind': 'comment', 'original': '这个想法不错'}),
                    ('q_stale', '新正式要求', {'kind': 'comment', 'original': '旧评论'})), start=2):
                db.execute('INSERT INTO queue_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (index, item_id, 'legacy', URL, URL, task, '旧标题', 'pending', 0, 1., 1., 1., 1))
                db.execute('INSERT INTO task_annotations VALUES(?,?,?)',
                           ('legacy', item_id, json.dumps(annotation, ensure_ascii=False)))
        queue = Queue(store)
        shown = queue.show('q_legacy', include_material=False)
        self.assertEqual(shown['task_description'], '旧正式要求')
        self.assertIsNone(shown['task_type'])
        self.assertIsNone(shown['completion_method'])
        self.assertEqual((shown['revision'], shown['updated']), (1, 1.))
        comment = queue.show('q_comment', include_material=False)
        self.assertIsNone(comment['task_description'])
        self.assertEqual((comment['task'], comment['state']), ('这个想法不错', 'pending'))
        self.assertEqual(queue.show('q_stale', include_material=False)['task_description'], '新正式要求')
        queue.update('q_legacy', task_description=None)
        reopened = Queue(store).show('q_legacy', include_material=False)
        self.assertIsNone(reopened['task_description'])
        self.assertEqual(reopened['task'], '旧正式要求')

    def test_create_omitted_description_initializes_from_task_but_explicit_empty_does_not(self):
        implicit = self.item(task='保留原话')
        self.assertEqual(implicit['task_description'], '保留原话')
        for value in (None, '', ' \t\n'):
            with self.subTest(value=value):
                item = self.item(task='保留原话', task_description=value, task_type=value, completion_method=value)
                self.assertIsNone(item['task_description'])
                self.assertIsNone(item['task_type'])
                self.assertIsNone(item['completion_method'])
                self.assertEqual(item['task'], '保留原话')
        typed = self.item(task_type=' 整理我的实验记录 ', task_description=' 具体工作 ')
        self.assertEqual((typed['task_type'], typed['task_description']), ('整理我的实验记录', '具体工作'))

    def test_update_omitted_fields_are_unchanged_while_null_and_blank_clear_them(self):
        item = self.item(task='原附言', task_type='回答问题', task_description='比较两种具体表现')
        untouched = self.queue.update(item['id'], priority=3)
        self.assertEqual((untouched['task_type'], untouched['task_description']), ('回答问题', '比较两种具体表现'))
        self.queue.update(item['id'], task_description='新的具体要求')
        cleared = self.queue.update(item['id'], task_type='', task_description=None)
        self.assertIsNone(cleared['task_type'])
        self.assertIsNone(cleared['task_description'])
        self.assertEqual(cleared['task'], '原附言')
        events = self.queue.history(item_id=item['id'])['events']
        update = next(event for event in events if event['kind'] == 'updated' and
                      event['details'].get('after', {}).get('task_description', 'absent') is None)
        self.assertEqual(update['details']['before']['task_description'], '新的具体要求')
        self.assertIn('task_type', update)
        self.assertIsNone(update['task_description'])

    def test_state_is_required_when_provided_and_termination_only_belongs_to_done(self):
        for state in (None, '', 'unknown'):
            with self.subTest(state=state), self.assertRaises(ReaderError):
                self.item(state=state)
        item = self.item(task_description='原片下架，结束本项', state='done', completion_method='终止')
        self.assertEqual(item['completion_method'], '终止')
        with self.assertRaises(ReaderError):
            self.queue.update(item['id'], state=None)
        with self.assertRaises(ReaderError):
            self.queue.update(item['id'], state='cancelled', completion_method='终止')
        reopened = self.queue.update(item['id'], state='pending')
        self.assertIsNone(reopened['completion_method'])
        self.assertEqual(reopened['state'], 'pending')
        self.queue.update(item['id'], completion_method=None)
        with self.assertRaises(ReaderError):
            self.queue.update(item['id'], completion_method='终止')
        cancelled = self.item(state='cancelled')
        self.assertIsNone(cancelled['completion_method'])

    def test_lengths_and_types_remain_free_text_without_fixed_type_categories(self):
        custom = '保存我的交互实验观察 📝'
        item = self.item(task_type=custom, task_description='字' * 4000)
        self.assertEqual(item['task_type'], custom)
        for fields in ({'task_type': 'x' * 201}, {'completion_method': 'x' * 201},
                       {'task_description': 'x' * 4001}, {'task_description': []}):
            with self.subTest(fields=fields), self.assertRaises(ReaderError):
                self.queue.update(item['id'], **fields)

    def test_termination_and_manual_done_do_not_claim_partial_results_completed_the_task(self):
        item = self.item(task='原片不可获取')
        partial = self.queue.record_result(item['id'], {'summary': '保留关闭记录，尚无内容结论',
            'answer': {'question': '原片是否可获取', 'text': '尚未取得', 'status': 'partial'}}, complete=False)
        terminated = self.queue.update(item['id'], state='done', completion_method='终止')
        self.assertEqual(terminated['completion_basis'], 'explicit_termination')
        self.assertEqual(terminated['reader_completion'], 'not_inferred')
        self.assertEqual(terminated['latest_result'], partial['latest_result'])
        self.assertFalse(terminated['latest_result']['task_complete'])
        manual = self.queue.update(item['id'], completion_method=None)
        self.assertEqual(manual['completion_basis'], 'manual')
        completed = self.answer(item['id'])
        self.assertEqual(completed['completion_basis'], 'explicit_task_result')

    def test_type_history_is_exact_scope_isolated_and_available_to_list_in_same_transaction(self):
        item = self.item(task_type='整理笔记')
        self.queue.update(item['id'], task_type='整理为笔记')
        self.queue.update(item['id'], task_type=None)
        other = Queue(Store(self.root / 'other', 'private-library', database=self.queue.store.path))
        other.enqueue(URL, task_type='另一库的私人类别')
        with self.queue.store.connect() as db:
            self.assertCountEqual(self.queue.task_types(db), ['整理笔记', '整理为笔记'])
        self.assertCountEqual(self.queue.list()['task_types'], ['整理笔记', '整理为笔记'])
        self.assertEqual(other.task_types(), ['另一库的私人类别'])

    def test_list_search_and_history_include_canonical_fields(self):
        item = self.item(task='原话', task_type='核查', task_description='检查论据甲', state='done', completion_method='终止')
        self.assertEqual(self.queue.list('done', query='论据甲')['items'][0]['id'], item['id'])
        match = self.queue.search('论据甲')['items'][0]
        self.assertIn('task_description', match['matched_fields'])
        self.assertEqual(match['task_type'], '核查')
        self.assertEqual(match['completion_method'], '终止')
        self.assertEqual(self.queue.history(item_id=item['id'], query='论据甲')['events'][0]['task_description'], '检查论据甲')

    def test_api_and_cli_preserve_omission_and_support_payload_null_clearing(self):
        saved = execute(self.reader, 'queue-add', URL, result={
            'task': '原话', 'task_type': '回答问题', 'task_description': '比较实际互动'})['item']
        updated = execute(self.reader, 'queue-update', saved['id'], priority=2)
        self.assertEqual(updated['task_description'], '比较实际互动')
        args = parser().parse_args(['queue-update', saved['id'], '--task-type', ''])
        self.assertFalse(hasattr(args, 'task_description'))
        cli = from_namespace(self.reader, args)
        self.assertIsNone(cli['task_type'])
        self.assertEqual(cli['task_description'], '比较实际互动')
        payload = self.root / 'clear.json'
        write_json(payload, {'task_description': None})
        cleared = execute(self.reader, 'queue-update', saved['id'], payload=str(payload))
        self.assertIsNone(cleared['task_description'])
        self.assertEqual(cleared['task'], '原话')
        write_json(payload, {'state': None})
        with self.assertRaises(ReaderError):
            execute(self.reader, 'queue-update', saved['id'], payload=str(payload))
        explicit = execute(self.reader, 'queue-add', URL, task='另一原话', task_description=None)['item']
        self.assertIsNone(explicit['task_description'])

    def test_consumer_uses_canonical_work_and_rejects_an_old_run_after_description_changes(self):
        item = self.item(task='普通附言', task_description='比较两个具体例子', task_type='回答问题')
        consumer = Consumer(self.reader)
        with patch.object(consumer, '_launch', side_effect=lambda state, wait: state):
            state = consumer.start(item['id'])
        self.assertEqual(state['request'], '比较两个具体例子')
        self.queue.update(item['id'], priority=4)
        consumer._verify_task(state)
        allowed_revision = state['task_revision']
        current = self.queue.update(item['id'], task_description='改为核查另一观点')
        with self.assertRaisesRegex(ReaderError, 'changed'):
            consumer._verify_task(state)
        self.assertEqual(state['task_revision'], allowed_revision)
        self.assertFalse(consumer.run_info(state['run_id'])['task_matches'])
        with self.assertRaisesRegex(ReaderError, 'earlier task'):
            consumer.start(item['id'], request='比较两个具体例子')
        with self.assertRaisesRegex(ReaderError, 'Task changed'):
            self.queue.record_result(item['id'], {'summary': '旧回答', 'answer': {
                'question': '旧问题', 'text': '旧内容'}}, complete=True,
                expected_revision=current['revision'], run_id=state['run_id'])
        self.assertIsNone(self.queue.show(item['id'])['latest_result'])

    def test_direct_api_explicit_null_state_is_rejected_without_applying_other_fields(self):
        before = len(self.queue.list('all')['items'])
        invalid = self.root / 'null-state.json'
        write_json(invalid, {'state': None, 'task_type': '不应更新'})
        for options in ({'state': None, 'task_type': '不应创建'},
                        {'result': {'state': None, 'task_type': '不应创建'}}, {'payload': str(invalid)}):
            with self.subTest(create_options=options), self.assertRaises(ReaderError):
                execute(self.reader, 'queue-add', URL, **options)
            self.assertEqual(len(self.queue.list('all')['items']), before)
        item = execute(self.reader, 'queue-add', URL, task_type='原类型')['item']
        for options in ({'state': None, 'task_type': '不应更新'},
                        {'result': {'state': None, 'task_type': '不应更新'}}, {'payload': str(invalid)}):
            with self.subTest(options=options), self.assertRaises(ReaderError):
                execute(self.reader, 'queue-update', item['id'], **options)
            current = self.queue.show(item['id'])
            self.assertEqual((current['state'], current['task_type'], current['revision']),
                             ('pending', '原类型', item['revision']))
        changed = execute(self.reader, 'queue-update', item['id'], task_type='新类型')
        self.assertEqual((changed['state'], changed['task_type']), ('pending', '新类型'))
        args = parser().parse_args(['queue-update', item['id'], '--task-type', 'CLI类型'])
        cli = from_namespace(self.reader, args)
        self.assertEqual((cli['state'], cli['task_type']), ('pending', 'CLI类型'))

    def test_cleared_description_never_revives_original_task_in_consumer(self):
        item = self.item(task='旧正式要求', task_description=None)
        consumer = Consumer(self.reader)
        with self.assertRaisesRegex(ReaderError, 'concrete reading request'):
            consumer.start(item['id'])
        with patch.object(consumer, '_launch', side_effect=lambda state, wait: state):
            state = consumer.start(item['id'], request='本次显式要求')
        self.assertEqual(state['request'], '本次显式要求')
        self.assertIsNone(state['task_description'])
        self.assertEqual(self.queue.show(item['id'])['task'], '旧正式要求')

    def test_result_snapshots_preserve_original_request_and_canonical_description(self):
        item = self.item(task='原附言', task_type='回答问题', task_description='具体问题甲')
        saved = self.answer(item['id'], catalog={'task_description': '旧留存注记'})
        result = saved['latest_result']
        self.assertEqual(result['task_request'], '原附言')
        self.assertEqual(result['task_description'], '具体问题甲')
        self.assertEqual(result['task_identity'], task_identity(saved))
        self.assertEqual(saved['task_description'], '具体问题甲')
        self.queue.update(item['id'], task_description='具体问题乙')
        self.assertEqual(self.queue.show(item['id'])['latest_result'], result)

    def test_explicit_legacy_task_update_initializes_work_only_when_description_is_omitted(self):
        item = self.item(task='旧要求', task_description='当前具体工作')
        updated = self.queue.update(item['id'], task='新的具体要求')
        self.assertEqual((updated['task'], updated['task_description']), ('新的具体要求', '新的具体要求'))
        cleared = self.queue.update(item['id'], task='保留原话但不作工作', task_description=None)
        self.assertEqual(cleared['task'], '保留原话但不作工作')
        self.assertIsNone(cleared['task_description'])
        explicit = self.queue.update(item['id'], task='原始附言', task_description='单独明确的实际工作')
        self.assertEqual(explicit['task_description'], '单独明确的实际工作')

    def test_comment_intent_clears_only_auto_initialized_description(self):
        item = self.item(task='想法不错')
        intent = {'kind': 'comment', 'original': '想法不错', 'comment': '想法不错', 'request': None}
        with self.queue.store.connect() as db:
            self.queue.record_intent(db, item['id'], intent)
        shown = self.queue.show(item['id'])
        self.assertIsNone(shown['task_description'])
        self.assertEqual(shown['task'], '想法不错')
        self.assertEqual(shown['note'], intent)
        self.queue.update(item['id'], task_description='保留项目入口和具体想法')
        with self.queue.store.connect() as db:
            self.queue.record_intent(db, item['id'], intent)
        self.assertEqual(self.queue.show(item['id'])['task_description'], '保留项目入口和具体想法')

    def test_followup_optional_text_is_nullable_and_omission_keeps_it(self):
        item = self.item()
        followups = Followups(self.queue)
        saved = followups.save(item['id'], {'description': '之后做笔记', 'reason': '', 'notes': None})['followup']
        self.assertIsNone(saved['reason'])
        self.assertIsNone(saved['notes'])
        followups.save(item['id'], {'id': saved['id'], 'reason': '具体理由', 'notes': '具体说明'})
        kept = followups.save(item['id'], {'id': saved['id'], 'state': 'paused'})['followup']
        self.assertEqual((kept['reason'], kept['notes']), ('具体理由', '具体说明'))
        cleared = followups.save(item['id'], {'id': saved['id'], 'reason': None, 'notes': ' \n'})['followup']
        self.assertIsNone(cleared['reason'])
        self.assertIsNone(cleared['notes'])
        with self.assertRaises(ReaderError):
            followups.save(item['id'], {'id': saved['id'], 'state': None})

    def test_legacy_scroll_mcp_can_update_priority_or_original_task_without_a_state(self):
        from scroll_agent import mcp_server
        item = self.item(task='原话', task_description='独立工作')
        with patch('scroll_agent.mcp_server.Reader', return_value=self.reader):
            result = mcp_server.scroll_queue(action='update', item_id=item['id'], priority=5)
            priority = json.loads(result[0].text)
            changed = mcp_server.scroll_queue(action='update', item_id=item['id'], task='澄清后的原始要求')
        self.assertEqual(priority['priority'], 5)
        self.assertEqual(priority['state'], 'pending')
        self.assertEqual(json.loads(changed[0].text)['task_description'], '澄清后的原始要求')


if __name__ == '__main__':
    unittest.main()
