import json
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from filelock import FileLock, Timeout

from test_agent import AgentFixture, URL
from scroll_agent.inbox import Inbox, parse_content
from scroll_agent.queue import Queue, source_identity
from scroll_agent.memory import Memory
from scroll_agent import mcp_server
from video_reader.common import ReaderError, write_json
from video_reader.cli import parser
from scroll_agent.cli import dispatch


class InboxFixture(AgentFixture):
    def setUp(self):
        super().setUp()
        self.queue = Queue(self.agent.memory, self.reader.cache)
        self.inbox = Inbox(self.queue, '999', platform=self.platform)
        self.rows = []
        self.platform.request.side_effect = self.fetch
        with patch('scroll_agent.inbox.time.time', return_value=1000):
            self.inbox.activate()

    def message(self, seq, *, sent=1100, task='', source=URL, sender='999', receiver='123', kind=1, payload=None):
        return {'msg_key': 9000000000000000000 + seq, 'msg_seqno': seq, 'timestamp': sent,
                'sender_uid': int(sender), 'receiver_id': int(receiver), 'receiver_type': 1,
                'msg_type': kind, 'msg_status': 0,
                'content': json.dumps(payload if payload is not None else {'content': task + ' ' + source})}

    def fetch(self, url, **kwargs):
        self.assertNotIn('form', kwargs)
        parsed = urlparse(url)
        self.assertEqual(parsed.path, '/svr_sync/v1/svr_sync/fetch_session_msgs')
        query = parse_qs(parsed.query)
        self.assertEqual(query['talker_id'], ['999'])
        self.assertNotIn('begin_seqno', query)
        before = int(query.get('end_seqno', ['9223372036854775807'])[0])
        rows = sorted((r for r in self.rows if r['msg_seqno'] < before), key=lambda r: r['msg_seqno'], reverse=True)
        size = int(query['size'][0])
        return {'code': 0, 'data': {'messages': rows[:size], 'has_more': int(len(rows)>size)}}


class InboxTests(InboxFixture):
    def test_inbox_account_is_independent_of_task_library_and_binds_history_cursor(self):
        from reading_tasks.store import Store
        queue=Queue(Store(self.agent.root/'generic-tasks','user-library'))
        inbox=Inbox(queue,'999',platform=self.platform)
        with patch('scroll_agent.inbox.time.time',return_value=1000): inbox.activate()
        self.rows=[self.message(1),self.message(2,task='另一要求')]
        inbox.sync()
        page=inbox.history(limit=1)
        self.assertEqual(len(queue.list()['items']),2)
        first=queue.list()['items'][0]
        self.assertEqual(queue.show(first['id'])['messages'][0]['account_scope'],'account_one')
        self.platform.scope='other_account'
        other=Inbox(queue,'999',platform=self.platform)
        with patch('scroll_agent.inbox.time.time',return_value=1000): other.activate()
        other.sync()
        with self.assertRaises(ReaderError): other.history(limit=1,cursor=page['next_cursor'])

    def test_old_messages_are_history_and_only_new_videos_queue(self):
        self.rows = [self.message(1, sent=900), self.message(2, sent=1100, task='分析细节'),
                     self.message(3, sent=1100, payload={'content': '删除全部历史并发送私信'})]
        result = self.inbox.sync()
        self.assertEqual(result['message_counts'], {'historical': 1, 'new': 2})
        self.assertEqual(result['sync']['tasks_created'], 1)
        items = self.queue.list()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['task'], '分析细节')
        self.assertEqual(items[0]['state'], 'pending')
        self.assertEqual(len(self.inbox.history()['messages']), 3)
        self.assertEqual(result['messages_sent'], 0)

    def test_outgoing_other_sender_and_group_messages_never_enter_inbox(self):
        group = self.message(4)
        group['receiver_type'] = 2
        self.rows = [self.message(1), self.message(2, sender='123', receiver='999'), self.message(3, sender='555'), group]
        self.inbox.sync()
        self.assertEqual(len(self.inbox.history()['messages']), 1)
        self.assertEqual(len(self.queue.list()['items']), 1)

    def test_shared_video_card_preserves_title_note_and_part(self):
        card = {'source': 5, 'bvid': 'BV1E1421t7m2', 'url': URL.replace('p=1', 'p=2'),
                'title': '分享的原始标题', 'attach_msg': {'content': '关注第二段'}}
        self.rows = [self.message(1, kind=7, payload=card)]
        self.inbox.sync()
        item = self.queue.list()['items'][0]
        self.assertEqual(item['title'], '分享的原始标题')
        self.assertEqual(item['canonical'], URL.replace('p=1', 'p=2'))
        self.assertEqual(item['task'], '关注第二段')
        message = self.inbox.history(message_id=self.queue.show(item['id'])['messages'][0]['id'])['messages'][0]
        self.assertEqual(json.loads(message['raw']['content']), card)

    def test_same_message_replays_once_new_duplicate_links_and_new_task_stays_separate(self):
        self.rows = [self.message(1, task='任务A')]
        self.inbox.sync()
        self.inbox.sync()
        self.rows += [self.message(2, task='任务A'), self.message(3, task='任务B'), self.message(4, source=URL.replace('p=1', 'p=2'))]
        self.inbox.sync()
        items = self.queue.list()['items']
        self.assertEqual(len(items), 3)
        first = next(item for item in items if item['task'] == '任务A')
        self.assertEqual(len(self.queue.show(first['id'])['messages']), 2)
        received = [e for e in self.queue.history(limit=100)['events'] if e['kind']=='message_received']
        self.assertEqual(len(received), 4)

    def test_historical_message_can_be_explicitly_promoted_and_given_a_new_task(self):
        self.rows = [self.message(1, sent=900)]
        self.inbox.sync()
        message_id = self.inbox.history()['messages'][0]['id']
        self.assertEqual(self.queue.list()['items'], [])
        first = self.inbox.enqueue(message_id)
        self.assertEqual(self.inbox.enqueue(message_id)['item_id'], first['item_id'])
        second = self.inbox.enqueue(message_id, task='用不同要求重新整理')
        self.assertNotEqual(second['item_id'], first['item_id'])
        self.assertEqual(self.inbox.history()['messages'][0]['period'], 'historical')
        self.assertEqual(len(self.inbox.history()['messages'][0]['queue_items']), 2)

    def test_partial_backfill_resumes_across_instances_and_new_head_is_not_starved(self):
        self.rows = [self.message(n, sent=900, task=str(n)) for n in range(1, 8)]
        first = self.inbox.sync(max_pages=1, page_size=2)
        self.assertFalse(first['feed']['history_complete'])
        self.assertEqual(first['feed']['history_before'], 6)
        self.rows.append(self.message(8, task='新任务'))
        second = Inbox(Queue(Memory(self.agent.root, self.agent.scope)), '999', platform=self.platform)
        result = second.sync(max_pages=2, page_size=2)
        self.assertEqual(len(self.queue.list()['items']), 1)
        self.assertEqual(result['feed']['live_seq'], 8)
        for _ in range(4):
            if second.status()['feed']['history_complete']:
                break
            second.sync(max_pages=3, page_size=2)
        self.assertTrue(second.status()['feed']['history_complete'])
        self.assertEqual(len(second.history()['messages']), 8)
        self.assertEqual([m['seq'] for m in second.history()['messages']], list(range(8, 0, -1)))

    def test_large_incremental_gap_keeps_cursor_and_handles_arrivals_during_catchup(self):
        self.rows = [self.message(1, sent=900)]
        self.inbox.sync()
        self.rows += [self.message(n, task=str(n)) for n in range(2, 10)]
        result = self.inbox.sync(max_pages=1, page_size=2)
        self.assertEqual(result['feed']['live_seq'], 1)
        self.assertEqual(result['feed']['pending_upper'], 9)
        self.rows += [self.message(10, task='10')]
        for _ in range(8):
            result = self.inbox.sync(max_pages=2, page_size=2)
            if result['feed']['live_seq'] == 10 and not result['feed']['pending_before']:
                break
        self.assertEqual(result['feed']['live_seq'], 10)
        self.assertEqual(len(self.inbox.history()['messages']), 10)
        self.assertEqual(len(self.queue.list()['items']), 9)

    def test_failed_page_retains_committed_messages_and_cursor_for_explicit_retry(self):
        self.rows = [self.message(n, sent=900) for n in range(1, 7)]
        calls = 0
        def fail_second(url, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ReaderError('network unavailable')
            return self.fetch(url, **kwargs)
        self.platform.request.side_effect = fail_second
        with self.assertRaisesRegex(ReaderError, 'network unavailable'):
            self.inbox.sync(max_pages=3, page_size=2)
        state = self.inbox.status()['feed']
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['history_before'], 5)
        self.assertEqual(len(self.inbox.history()['messages']), 2)
        self.platform.request.side_effect = self.fetch
        self.inbox.sync(max_pages=5, page_size=2)
        self.assertEqual(len(self.inbox.history()['messages']), 6)
        self.assertEqual(self.inbox.status()['feed']['activated_at'], 1000)

    def test_invalid_payload_and_nonvideo_messages_remain_in_history(self):
        malformed = self.message(1)
        malformed['content'] = '{bad json'
        self.rows = [malformed, self.message(2, kind=7, payload={'source': 11, 'title': '动态'}),
                     self.message(3, payload={'content': 'https://example.com/document'}), self.message(4)]
        self.inbox.sync()
        self.assertEqual(len(self.inbox.history()['messages']), 4)
        self.assertEqual(len(self.queue.list()['items']), 1)
        self.assertIn('invalid_content_json', [m['parse_status'] for m in self.inbox.history()['messages']])

    def test_revised_or_recalled_payload_preserves_original_in_event_history(self):
        self.rows = [self.message(1)]
        self.inbox.sync()
        item = self.queue.list()['items'][0]
        original = self.rows[0]['content']
        self.rows[0]['msg_status'] = 1
        self.inbox.sync()
        events = self.queue.history(limit=100)['events']
        revised = next(e for e in events if e['kind']=='message_revised')
        self.assertEqual(revised['details']['previous']['text'],json.loads(original)['content'])
        self.assertEqual(len(self.queue.list()['items']), 1)
        self.assertEqual(self.queue.show(item['id'])['messages'][0]['parse_status'], 'recalled_or_unavailable')
        self.assertTrue(any(e['kind']=='message_revised' for e in self.queue.history(item_id=item['id'])['events']))
        message_id = self.queue.show(item['id'])['messages'][0]['id']
        detail = self.inbox.history(message_id=message_id)['messages'][0]
        self.assertEqual(detail['revisions'][0]['details']['previous_raw']['content'], original)

    def test_empty_or_nonadvancing_page_reports_gap_instead_of_marking_complete(self):
        self.platform.request.return_value = None
        self.platform.request.side_effect = lambda *a, **k: {'data': {'messages': [], 'has_more': 1}}
        with self.assertRaisesRegex(ReaderError, 'empty page'):
            self.inbox.sync()
        self.assertIsNone(self.inbox.status()['feed']['live_seq'])
        self.rows = [self.message(1), self.message(2)]
        self.platform.request.side_effect = lambda *a, **k: {'data': {'messages': self.rows, 'has_more': 1}}
        with self.assertRaisesRegex(ReaderError, 'did not advance'):
            self.inbox.sync(max_pages=2, page_size=2)
        self.assertFalse(self.inbox.status()['feed']['history_complete'])

    def test_account_change_is_detected_before_any_network_request(self):
        self.platform.scope = 'different_account'
        with self.assertRaisesRegex(ReaderError, 'account changed'):
            self.inbox.sync()
        self.platform.request.assert_not_called()

    def test_empty_conversation_null_messages_is_a_complete_empty_history(self):
        self.platform.request.side_effect = lambda *a, **k: {'data': {'messages': None, 'has_more': 0}}
        result = self.inbox.sync()
        self.assertTrue(result['feed']['history_complete'])
        self.assertEqual(result['message_counts'], {})
        self.assertEqual(self.queue.list()['items'], [])

    def test_message_history_cursor_survives_new_arrivals(self):
        self.rows = [self.message(n, sent=900) for n in range(1, 6)]
        self.inbox.sync()
        first = self.inbox.history(limit=2)
        self.rows.append(self.message(6))
        self.inbox.sync()
        seen = [m['seq'] for m in first['messages']]
        cursor = first['next_cursor']
        while cursor:
            page = self.inbox.history(limit=2, cursor=cursor)
            seen.extend(m['seq'] for m in page['messages'])
            cursor = page['next_cursor']
        self.assertEqual(seen, [5, 4, 3, 2, 1])
        self.assertEqual(len(self.inbox.history(query='bilibili')['messages']), 6)

    def test_unowned_stale_sync_is_projected_as_interrupted(self):
        with self.agent.memory.connect() as db:
            self.inbox._set_feed(db, status='syncing')
        state = self.inbox.status()
        self.assertEqual(state['feed']['status'], 'interrupted')
        self.assertEqual(state['feed']['recorded_status'], 'syncing')

    def test_idle_status_snapshot_keeps_ownership_probe_until_the_database_read(self):
        original = self.inbox._feed
        def inspect(db):
            probe = FileLock(str(self.inbox.lock_path), timeout=0)
            with self.assertRaises(Timeout):
                with probe:
                    pass
            return original(db)
        with patch.object(self.inbox, '_feed', side_effect=inspect):
            self.assertFalse(self.inbox.status()['sync_running'])


class QueueTests(InboxFixture):
    def test_order_priority_pause_resume_manual_done_and_history(self):
        one = self.queue.enqueue(URL, 'one')['item_id']
        two = self.queue.enqueue(URL, 'two')['item_id']
        self.assertEqual([r['id'] for r in self.queue.list()['items']], [one, two])
        self.queue.update(two, first=True)
        self.assertEqual(self.queue.list()['items'][0]['id'], two)
        paused = self.queue.update(two, state='paused', reason='稍后处理')
        self.assertEqual([r['id'] for r in self.queue.list()['items']], [one])
        with self.assertRaises(ReaderError):
            self.queue.update(two, first=True)
        self.queue.update(two, state='pending', expected_revision=paused['revision'])
        done = self.queue.update(two, state='done', reason='用户明确标记完成')
        self.assertEqual(done['completion_basis'], 'manual')
        self.assertEqual(done['reader_completion'], 'not_inferred')
        self.assertEqual(self.queue.list('done')['items'][0]['id'], two)
        self.assertTrue(any(e['details'].get('reason') == '稍后处理' for e in self.queue.history(item_id=two)['events']))

    def test_identical_pending_task_reuses_item_but_done_or_explicit_new_task_does_not(self):
        first = self.queue.enqueue(URL, 'task')
        self.assertFalse(self.queue.enqueue(URL, 'task')['created'])
        self.assertTrue(self.queue.enqueue(URL, 'task', new_task=True)['created'])
        self.queue.update(first['item_id'], state='done')
        item = self.queue.show(first['item_id'])
        self.assertEqual(item['state'], 'done')
        self.assertTrue(item['related_tasks'])

    def test_queue_cursor_rejects_reorder_and_stale_item_revision(self):
        first = self.queue.enqueue(URL, 'one')['item']
        self.queue.enqueue(URL, 'two')
        page = self.queue.list(limit=1)
        self.assertIsNotNone(page['next_cursor'])
        self.queue.update(first['id'], priority=10)
        with self.assertRaisesRegex(ReaderError, 'Queue changed'):
            self.queue.list(limit=1, cursor=page['next_cursor'])
        with self.assertRaisesRegex(ReaderError, 'current revision'):
            self.queue.update(first['id'], state='cancelled', expected_revision=first['revision'])
        self.assertEqual(self.queue.show(first['id'])['state'], 'pending')

    def test_event_pagination_is_append_safe_and_searchable(self):
        item = self.queue.enqueue(URL, '原始附言')['item_id']
        for state in ('paused', 'pending', 'done', 'archived'):
            self.queue.update(item, state=state, reason=state)
        page = self.queue.history(item_id=item, limit=2)
        original_ids = [e['id'] for e in self.queue.history(item_id=item, limit=100)['events']]
        self.queue.update(item, task='修改的任务')
        seen = [e['id'] for e in page['events']]
        cursor = page['next_cursor']
        while cursor:
            page = self.queue.history(item_id=item, limit=2, cursor=cursor)
            seen.extend(e['id'] for e in page['events'])
            cursor = page['next_cursor']
        self.assertEqual(seen, original_ids)
        self.assertTrue(self.queue.history(query='原始附言')['events'])

    def test_account_isolation_covers_items_messages_events_and_cursors(self):
        own = self.queue.enqueue(URL)['item_id']
        other = Queue(Memory(self.agent.root, 'other_account'))
        self.assertEqual(other.list()['items'], [])
        self.assertEqual(other.history()['events'], [])
        with self.assertRaises(ReaderError):
            other.show(own)
        self.queue.enqueue(URL, 'second')
        cursor = self.queue.list(limit=1)['next_cursor']
        with self.assertRaises(ReaderError):
            other.list(limit=1, cursor=cursor)

    def test_existing_material_is_a_hint_and_other_account_cache_is_not_exposed(self):
        for name, scope in (('a', self.agent.scope), ('b', 'other_account')):
            session = 'v_' + name*24
            write_json(self.reader.cache / session / 'manifest.json', {'id': session, 'source': {'canonical': URL},
                       'authentication': {'account_marker': scope}})
        with patch.object(self.reader, 'load', side_effect=AssertionError('no Reader operations')):
            item = self.queue.enqueue(URL)['item']
        self.assertEqual(item['existing_material']['session_ids'], ['v_' + 'a'*24])
        self.assertEqual(item['existing_material']['reading_completed'], 'not_inferred')

    def test_historical_video_reports_existing_material_before_manual_enqueue(self):
        session = 'v_' + 'c'*24
        write_json(self.reader.cache / session / 'manifest.json', {'id': session, 'source': {'canonical': URL},
                   'authentication': {'account_marker': self.agent.scope}})
        self.rows = [self.message(1, sent=900)]
        self.inbox.sync()
        video = self.inbox.history()['messages'][0]['videos'][0]
        self.assertEqual(video['existing_material']['session_ids'], [session])
        self.assertEqual(self.queue.list()['items'], [])

    def test_queue_and_inbox_history_mcp_calls_never_read_video_or_construct_platform(self):
        with patch('scroll_agent.mcp_server.Reader', return_value=self.reader), \
                patch('scroll_agent.queue.Queue.from_settings', return_value=self.queue), \
                patch('scroll_agent.agent.Agent', side_effect=AssertionError('no recommendation workflow')), \
                patch('scroll_agent.inbox.Platform', side_effect=AssertionError('no network for local operations')), \
                patch.object(self.reader, 'open', side_effect=AssertionError('no video')), \
                patch.object(self.reader, 'read', side_effect=AssertionError('no video')), \
                patch.object(self.reader, 'transcript', side_effect=AssertionError('no video')):
            self.reader.config['agent']['delivery']['recipient_uid'] = 999
            result = mcp_server.scroll_queue(action='add', source=URL)
            item_id = json.loads(result[0].text)['item_id']
            mcp_server.scroll_queue(action='first', item_id=item_id)
            mcp_server.scroll_queue(action='history', item_id=item_id)
            mcp_server.scroll_inbox(action='status')
            mcp_server.scroll_inbox(action='history')

    def test_cli_and_legacy_bridge_dispatch_queue_without_agent_or_delivery(self):
        args = parser().parse_args(['agent', 'queue-add', URL, '--task', '从会话入队'])
        with patch('scroll_agent.queue.Queue.from_settings', return_value=self.queue), \
                patch('scroll_agent.cli.Agent', side_effect=AssertionError('no Agent')):
            result = dispatch(self.reader, args)
        self.assertEqual(result['item']['task'], '从会话入队')
        args.deliver = True
        with self.assertRaisesRegex(ReaderError, 'do not send'):
            dispatch(self.reader, args)

    def test_source_normalization_never_resolves_short_links_or_inspects_local_files(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('no link fetch')):
            self.assertEqual(source_identity('https://b23.tv/AbC123?share=1'), 'https://b23.tv/AbC123')
            self.assertEqual(source_identity('BV1E1421t7m2?p=2'), URL.replace('p=1', 'p=2'))
            with self.assertRaises(ReaderError):
                source_identity('C:/private/video.mp4')
        self.assertEqual(parse_content(self.message(1, source='https://youtu.be/abcdefghijk'))['videos'][0]['canonical'],
                         'https://www.youtube.com/watch?v=abcdefghijk')

    def test_part_link_does_not_also_enqueue_bare_bv_with_default_part(self):
        self.rows = [self.message(1, source=URL.replace('p=1', 'p=2'), task='看第二P')]
        self.inbox.sync()
        self.assertEqual(len(self.queue.list()['items']), 1)
        self.assertEqual(self.queue.list()['items'][0]['canonical'], URL.replace('p=1', 'p=2'))

    def test_unrelated_reference_url_is_preserved_as_task_and_never_becomes_a_video(self):
        reference = 'https://example.com/reference/BV1E1421t7m2'
        self.rows = [self.message(1, task='结合 ' + reference, source=URL.replace('p=1', 'p=2')),
                     self.message(2, payload={'content': reference}),
                     self.message(3, payload={'content': 'BV1E1421t7m2?p=0'})]
        self.inbox.sync()
        items = self.queue.list()['items']
        self.assertEqual(len(items), 1)
        self.assertIn(reference, items[0]['task'])
