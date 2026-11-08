import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from reading_tasks.queue import Queue
from reading_tasks.store import Store
from reading_tasks.api import execute
from video_reader.common import ReaderError,read_json,write_json
from video_reader.reader import Reader
from video_reader.reading_policy import READING_POLICY
from scroll_agent.inbox import configured_sender
from scroll_agent import reports
from scroll_agent.memory import Memory

URL='https://www.bilibili.com/video/BV1E1421t7m2?p=1'


class IndependentTasks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'config.json'
        write_json(self.config,{'cache_dir':'cache','agent':{'directory':'agent'}})
        self.reader=Reader(self.config)
        self.queue=Queue.from_settings(self.reader.config,self.config)

    def test_queue_needs_neither_login_scroll_memory_nor_inbox_schema(self):
        with patch('scroll_agent.memory.Memory',side_effect=AssertionError('no personal memory')), \
             patch('video_reader.platform.Platform',side_effect=AssertionError('no network')):
            item=execute(self.reader,'queue-add',URL)['item']
            self.assertEqual(execute(self.reader,'queue-show',item['id'])['state'],'pending')
            execute(self.reader,'queue-history',item['id'])
        with self.queue.store.connect() as db:
            names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('inbox_messages',names)
        self.assertNotIn('memory_fts',names)

    def test_task_library_survives_login_change_and_local_file_intake(self):
        media=self.root/'local clip.mp4';media.write_bytes(b'not decoded by intake')
        item=self.queue.enqueue(str(media))['item']
        library=self.queue.scope
        credential=Path(self.reader.config['bilibili_auth']['directory'])/'credential.json'
        write_json(credential,{'account_marker':'other-account','cookies':[]})
        self.assertEqual(Queue.from_settings(self.reader.config,self.config).show(item['id'])['canonical'],str(media))
        credential.unlink()
        again=Queue.from_settings(self.reader.config,self.config)
        self.assertEqual(again.scope,library)
        self.assertEqual(again.show(item['id'])['state'],'pending')

    def test_typed_original_notes_and_artifact_result_are_queryable(self):
        item=self.queue.enqueue(URL,'想法有意思')['item']
        with self.queue.store.connect() as db:
            self.queue.record_intent(db,item['id'],{'kind':'comment','original':'想法有意思','comment':'想法有意思','request':None})
        artifact=self.root/'notes.md';artifact.write_text('已完成指定的项目想法整理',encoding='utf-8')
        result=self.queue.record_result(item['id'],{'summary':'项目想法','artifacts':[str(artifact)],
            'task_scope':'提取项目想法','coverage':'字幕与必要画面','full_video_verified':False},complete=True)
        self.assertEqual(result['state'],'done')
        self.assertEqual(result['note']['comment'],'想法有意思')
        self.assertFalse(result['latest_result']['full_video_verified'])
        self.assertEqual(len(result['latest_result']['artifacts'][0]['sha256']),64)
        self.assertIn('result_saved',[e['kind'] for e in self.queue.history(item_id=item['id'])['events']])
        reopened=execute(Reader(self.config),'queue-show',item['id'])
        self.assertEqual(reopened['latest_result'],result['latest_result'])
        self.assertEqual(reopened['latest_result']['artifacts'][0]['path'],str(artifact.resolve()))
        self.assertEqual(reopened['completion_basis'],'explicit_task_result')
        self.assertEqual(reopened['reader_completion'],'not_inferred')
        self.assertEqual(reopened['task'],'想法有意思')

    def test_inbox_sender_is_pinned_separately_from_outbound_recipient(self):
        self.reader.config['agent']['delivery']['recipient_uid']=111
        self.assertEqual(configured_sender(self.reader),111)
        self.reader.config['agent']['delivery']['recipient_uid']=222
        self.assertEqual(configured_sender(self.reader),111)
        self.reader.config['agent']['inbox']['sender_uid']=333
        self.assertEqual(configured_sender(self.reader),333)

    def test_sender_upgrade_uses_retained_inbox_before_new_outbound_recipient(self):
        with self.queue.store.connect() as db:
            db.execute('CREATE TABLE inbox_feeds(scope TEXT,peer TEXT)')
            db.execute('INSERT INTO inbox_feeds VALUES(?,?)',('prior-account','111'))
        self.reader.config['agent']['delivery']['recipient_uid']=222
        self.assertEqual(str(configured_sender(self.reader)),'111')

    def test_report_preview_does_not_acquire_material_and_send_is_idempotent(self):
        item=self.queue.enqueue(URL,title='测试视频')['item']
        with patch.object(self.reader,'preview',side_effect=AssertionError('no reading')), \
             patch('scroll_agent.reports.Platform',side_effect=AssertionError('preview must stay local')):
            report=reports.build(self.reader,item_ids=[item['id']])
        self.assertTrue(report['enqueued']);self.assertEqual(report['messages_sent'],0)
        self.assertEqual(report['entries'][0]['initial_triage'],'unprepared')
        self.reader.config['agent']['delivery'].update(enabled=True,recipient_uid=111)
        platform=Mock(scope='account',sender='123',csrf='fixture')
        platform.request.return_value={'code':0,'data':{'msg_key':'42'}}
        memory=Memory(self.root/'personal','account')
        first=reports.send(self.reader,report,platform=platform,memory=memory)
        second=reports.send(self.reader,report,platform=platform,memory=memory)
        self.assertEqual(first['delivery']['status'],'accepted_not_receipt_verified')
        self.assertEqual(second['delivery']['status'],'duplicate_or_uncertain_not_resent')
        self.assertEqual(platform.request.call_count,1)

    def test_uncertain_report_is_not_retried_and_unknown_message_has_no_receipt_claim(self):
        item=self.queue.enqueue(URL)['item'];report=reports.build(self.reader,item_ids=[item['id']])
        self.reader.config['agent']['delivery'].update(enabled=True,recipient_uid=111)
        platform=Mock(scope='account',sender='123',csrf='fixture')
        platform.request.side_effect=OSError('connection ended')
        memory=Memory(self.root/'personal','account')
        self.assertEqual(reports.send(self.reader,report,platform=platform,memory=memory)['delivery']['status'],'uncertain')
        self.assertEqual(reports.send(self.reader,report,platform=platform,memory=memory)['delivery']['status'],'duplicate_or_uncertain_not_resent')
        self.assertFalse(reports.build(self.reader,message_id='im_unknown')['enqueued'])
        self.assertEqual(platform.request.call_count,1)

    def test_reading_policy_is_shared_by_mcp_skill_and_generated_adapters(self):
        from video_reader import mcp_server
        self.assertIn(READING_POLICY,mcp_server.mcp.instructions)
        core=Path(__file__).resolve().parents[1]
        self.assertIn(READING_POLICY,(core/'skill/SKILL.md').read_text(encoding='utf-8'))
        from tools.build_plugins import build
        # Existing plugin tests cover path portability; this checks the actual new policy.
        output=build(core)
        for host in output['hosts'].values():
            self.assertIn(READING_POLICY,(Path(host['plugin_root'])/'skills/video-read/SKILL.md').read_text(encoding='utf-8'))

    def test_json_payloads_survive_fastmcp_argument_parsing(self):
        from mcp.server.fastmcp.utilities.func_metadata import func_metadata
        from scroll_agent import mcp_server
        for fn,key,value in ((mcp_server.scroll_report,'item_ids_json',['q_example']),
                (mcp_server.scroll_triage,'assessment_json',{'content_type':'unknown'}),
                (mcp_server.scroll_round,'decisions_json',{'decisions':[]})):
            with self.subTest(field=key):
                original=json.dumps(value)
                meta=func_metadata(fn,structured_output=False)
                parsed=meta.pre_parse_json({key:original})
                self.assertEqual(meta.arg_model.model_validate(parsed).model_dump()[key],original)
