from contextlib import nullcontext
from io import StringIO
import inspect
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from PIL import Image

from video_reader import aligned_danmaku as dm, cli, mcp_server
from video_reader.common import ReaderError, read_json, write_json
from video_reader.reader import Reader
from video_reader.review import document
import test_foundations as foundations
from test_community import msg, num


class AlignedDanmakuTests(unittest.TestCase):
    setUp = foundations.SpeechCoverageTests.setUp
    tearDown = foundations.SpeechCoverageTests.tearDown

    def prepare(self):
        self.data['source'] = {'platform': 'bilibili', 'canonical': 'https://www.bilibili.com/video/BV0000000001?p=2', 'identity': {'part': 2}}
        self.data['authentication'] = {'account_marker': 'fixture'}
        self.data['platform_metadata'] = {'cid': 2}
        self.data['metadata'].update(has_video=True, duration_seconds=800)
        self.data['speech'] = [{'start': 0, 'end': 800, 'source': 'captions', 'status': 'ready', 'segments': [
            {'start': 359, 'end': 360, 'text': '前半句'}, {'start': 360, 'end': 362, 'text': '后半句'}]}]
        self.reader.config['page_frames'] = 1
        self.reader.save(self.data)
        self.frame = self.root / 'frame.jpg'
        Image.new('RGB', (64, 64), 'white').save(self.frame)
        self.frames = [{'path': str(self.frame), 'index': i, 'timestamp_seconds': t} for i, t in enumerate([359.5, 360.5])]
        self.platform = Mock(scope='fixture')
        self.platform.config = self.reader.config
        self.platform.json.return_value = {'aid': 99, 'pages': [{'page': 1, 'cid': 1}, {'page': 2, 'cid': 2}]}
        self.platform.request.return_value = msg(4, num(1, 360000) + num(2, 3))

    def fetch(self, platform, source, segment_index=1, **options):
        # Include boundary/out-of-range data and repeated wording with distinct IDs.
        items = ([{'id': 'a', 'time': 359.5, 'progress_ms': 359500, 'text': '同一句'},
                  {'id': 'outside', 'time': 358, 'progress_ms': 358000, 'text': '不在范围'}] if segment_index == 1 else
                 [{'id': 'b', 'time': 360, 'progress_ms': 360000, 'text': '同一句'},
                  {'id': 'end', 'time': 362, 'progress_ms': 362000, 'text': '不在范围'}])
        return {'status': 'ready', 'cid': '2', 'items': items, 'segment_complete': True}

    def read(self, **options):
        return self.reader.read(self.sid, start=359, end=362, timestamps=[359.5, 360.5],
                                temporal=False, verify=False, **options)

    def test_default_has_no_danmaku_acquisition_or_extra_field(self):
        self.prepare()
        with patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})), \
                patch('video_reader.aligned_danmaku.acquire', side_effect=AssertionError('opt-in only')):
            result = self.read()
        self.assertNotIn('danmaku', result)

    def test_range_part_time_alignment_and_continuation_freezes_audience(self):
        self.prepare()
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=self.fetch) as fetch, \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            result = self.read(include_danmaku=True)
        audience = result['danmaku']
        self.assertEqual(audience['cid'], '2')
        self.assertEqual([x['id'] for x in audience['items']], ['a', 'b'])
        self.assertEqual([x['timestamp_seconds'] for x in audience['items']], [359.5, 360])
        self.assertEqual([c.kwargs['segment_index'] for c in fetch.call_args_list], [1, 2])
        self.assertEqual(audience['coverage']['fetched_segments'], [1, 2])
        speech_ids = [x['speech_segment_ids'] for x in audience['items']]
        self.assertTrue(all(speech_ids))
        self.assertNotEqual(speech_ids[0], speech_ids[1])
        self.assertEqual(audience['items'][0]['nearest_sampled_frame']['delta_seconds'], 0)
        cursor = result['delivery']['next_cursor']
        self.assertIsNotNone(cursor)
        restarted = Reader(self.reader.config_path)
        restarted.config['page_frames'] = 1
        with patch.object(restarted, '_material_platform', side_effect=AssertionError('frozen replay is offline')):
            next_page = restarted.continue_read(self.sid, cursor)
        self.assertEqual(next_page['danmaku']['snapshot_id'], audience['snapshot_id'])
        self.assertEqual(next_page['visual']['frames'][0]['timestamp_seconds'], 360.5)
        self.assertEqual(next_page['danmaku']['items'][1]['nearest_sampled_frame']['delta_seconds'], .5)

    def test_partial_failure_preserves_material_and_core_read(self):
        self.prepare()
        def fail_second(platform, source, segment_index=1, **kwargs):
            return self.fetch(platform, source, segment_index) if segment_index == 1 else {
                'status': 'blocked', 'items': [], 'error': {'code': 'platform_paused:-412'}}
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=fail_second), \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            result = self.read(include_danmaku=True)
        self.assertTrue(result['visual']['frames'])
        self.assertTrue(result['speech']['segments'])
        self.assertEqual(result['danmaku']['status'], 'partial')
        self.assertEqual(result['danmaku']['coverage']['missing_segments'], [2])
        self.assertEqual(result['danmaku']['items'][0]['id'], 'a')

    def test_foreign_account_and_unsupported_do_not_fetch(self):
        self.prepare()
        self.platform.scope = 'other'
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=AssertionError('foreign account')):
            result = dm.acquire(self.reader, self.data, 359, 362)
        self.assertEqual(result['reason'], 'session_account_mismatch')
        self.data['source']['platform'] = 'local'
        with patch.object(self.reader, '_material_platform', side_effect=AssertionError('not Bilibili')):
            self.assertEqual(dm.acquire(self.reader, self.data, 359, 362)['status'], 'unsupported')

    def test_snapshot_range_binding_and_export_opt_in(self):
        self.prepare()
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=self.fetch), \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            result = self.read(include_danmaku=True)
        identity = result['danmaku']['snapshot_id']
        material = dm.load(self.reader, self.sid, identity)
        with self.assertRaisesRegex(ReaderError, 'different source or interval'):
            dm.attach(self.reader, {**result, 'range': {'start': 0, 'end': 10}}, self.data, {}, identity)
        with patch.object(self.reader, '_material_platform', side_effect=AssertionError('export never fetches')):
            self.reader.export(self.sid, self.root / 'default', 0)
            self.reader.export(self.sid, self.root / 'audience', 0, include_danmaku=True)
        self.assertNotIn('danmaku', read_json(self.root / 'default/evidence.json'))
        exported = read_json(self.root / 'audience/evidence.json')['danmaku'][0]
        self.assertEqual([x['text'] for x in exported['items']], ['同一句', '同一句'])
        self.assertEqual(exported['snapshot_id'], material['snapshot_id'])

    def test_cli_and_mcp_expose_same_optional_parameters(self):
        for method, argv, tool, options in [
            ('read', ['read', self.sid, '--include-danmaku'], 'video_read', {'session_id': self.sid, 'include_danmaku': True}),
            ('open', ['open', 'BV0000000001', '--include-danmaku'], 'video_open', {'source': 'BV0000000001', 'include_danmaku': True}),
            ('export', ['export', self.sid, 'destination', '--revision', '0', '--include-danmaku'], 'video_export',
             {'session_id': self.sid, 'destination': 'destination', 'revision': 0, 'include_danmaku': True})]:
            calls = []
            def record(*args, **kwargs):
                bound = inspect.signature(getattr(Reader, method)).bind(self.reader, *args, **kwargs)
                bound.apply_defaults()
                calls.append(bound.arguments)
                return {}
            def start_job(action, *, operation, parameters, wait_seconds):
                # Adapter parity is checked before the real subprocess boundary;
                # cross-process start/join/result behavior is covered in test_jobs.
                self.assertEqual(action, 'start')
                return getattr(self.reader, operation)(**parameters)
            with patch.object(cli, 'Reader', return_value=self.reader), patch.object(mcp_server, 'reader', self.reader), \
                    patch.object(self.reader, 'job', side_effect=start_job), \
                    patch.object(self.reader, method, side_effect=record), patch('sys.argv', ['reader', *argv]), \
                    patch('sys.stdout', new_callable=StringIO):
                self.assertEqual(cli.main(), 0)
                getattr(mcp_server, tool)(**options)
            self.assertEqual(calls[0], calls[1])

    def test_large_danmaku_is_losslessly_paged_with_shared_speech_and_frames(self):
        self.prepare()
        from video_reader import delivery
        long_text = '观众原文🙂' * 9000
        def fetch(platform, source, segment_index=1, **kwargs):
            return {'status': 'ready', 'cid': '2', 'segment_complete': True, 'items': [
                {'id': str(segment_index), 'time': 359.5 if segment_index == 1 else 360.5, 'text': long_text}]}
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=fetch), \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            first = self.read(include_danmaku=True)
        snapshot = read_json(self.reader.directory(self.sid) / 'deliveries' / (first['delivery']['snapshot_id'] + '.json'))
        parts = []
        for index in range(len(snapshot['pages'])):
            page = self.reader.continue_read(self.sid, first['delivery']['snapshot_id'] + ':' + str(index))
            self.assertLessEqual(len(delivery.encoded(page)), 24000)
            parts.extend(page.get('material_parts', []))
        restored = delivery.restore(parts)
        self.assertEqual(restored['danmaku']['items'][0]['text'], long_text)
        self.assertEqual(restored, snapshot['result'])

    def test_uncached_optional_failure_and_empty_export_are_explicit(self):
        self.prepare()
        with patch.object(self.reader, '_material_platform', side_effect=ReaderError('login required')), \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            result = self.read(include_danmaku=True)
        self.assertEqual(result['danmaku']['status'], 'blocked')
        self.assertFalse(result['danmaku']['coverage']['complete'])
        self.assertTrue(result['speech']['segments'])
        # Another read has no audience refs; an opt-in export must not claim an empty audience population.
        data = self.reader.load(self.sid)
        for read in data['reads']:
            read.pop('danmaku_snapshot_ids', None)
        self.reader.save(data)
        with patch.object(self.reader, '_material_platform', side_effect=AssertionError('no export acquisition')):
            self.reader.export(self.sid, self.root / 'empty-export', 0, include_danmaku=True)
        exported = read_json(self.root / 'empty-export/evidence.json')
        self.assertEqual(exported['danmaku_status'], 'not_acquired')

    def test_reordered_or_replaced_platform_part_cannot_mix_with_cached_media(self):
        self.prepare()
        self.platform.json.return_value['pages'][1]['cid'] = 999
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.community.danmaku', side_effect=AssertionError('do not fetch wrong part')):
            material = dm.acquire(self.reader, self.data, 359, 362)
        self.assertEqual(material['status'], 'blocked')
        self.assertEqual(material['reason'], 'session_part_cid_mismatch')
        self.assertEqual(material['expected_cid'], '2')
        self.assertFalse(material['items'])

    def test_closed_status_is_frozen_across_frame_pages_and_export(self):
        self.prepare()
        self.platform.request.return_value = num(1, 1)
        with patch.object(self.reader, '_material_platform', return_value=nullcontext(self.platform)), \
                patch('video_reader.vendor.frames.extract_at_timestamps', return_value=(self.frames, {})):
            first = self.read(include_danmaku=True)
        self.assertEqual(first['danmaku']['status'], 'closed')
        self.assertTrue(first['danmaku']['snapshot_id'])
        with patch.object(self.reader, '_material_platform', side_effect=AssertionError('closed snapshot must not change')):
            next_page = self.reader.continue_read(self.sid, first['delivery']['next_cursor'])
            self.reader.export(self.sid, self.root / 'closed-export', 0, include_danmaku=True)
        self.assertEqual(next_page['danmaku']['status'], 'closed')
        self.assertEqual(read_json(self.root / 'closed-export/evidence.json')['danmaku'][0]['status'], 'closed')


if __name__ == '__main__':
    unittest.main()
