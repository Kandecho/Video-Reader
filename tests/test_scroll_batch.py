from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_reader as fixtures
import test_foundations as foundations
from scroll_agent.batch import Batch
from video_reader.common import ReaderError
from video_reader.delivery import original_page
from video_reader.reader import Reader
from video_reader.platform import PlatformError


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReaderTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.reader = Reader(self.config)
        self.auth = patch('scroll_agent.batch.credentials', return_value={'account_marker': 'fixture'})
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.batch = Batch(self.reader, offline=True)
        self.sid = self.reader.open(str(self.video))['session_id']

    def drain(self, batch_id, first=None, maximum=100):
        result = first or self.batch.next(batch_id)
        responses = []
        for _ in range(maximum):
            if 'next_ack_cursor' not in result:
                return responses, result
            responses.append(result)
            result = Batch(Reader(self.config), offline=True).next(batch_id, result['next_ack_cursor'])
        self.fail('Batch did not reach a terminal status')

    def test_restart_replays_unacknowledged_page_and_lost_next_response(self):
        started = self.batch.start([self.sid], task='Read the two slides')
        batch_id = started['batch_id']
        first = self.batch.next(batch_id)
        replay = Batch(Reader(self.config), offline=True).next(batch_id)
        self.assertEqual(replay, first)
        second = self.batch.next(batch_id, first['next_ack_cursor'])
        replay_second = Batch(Reader(self.config), offline=True).next(batch_id, first['next_ack_cursor'])
        self.assertEqual(replay_second, second)
        with self.assertRaisesRegex(ReaderError, 'match'):
            self.batch.next(batch_id, 'batch_' + 'f'*32 + ':1')
        _, final = self.drain(batch_id, second)
        self.assertTrue(final['all_material_delivered'])
        self.assertEqual(final['host_observation'], 'not_inferred')
        self.assertFalse(final['scheduler_changed'])
        self.assertEqual(final['messages_sent'], 0)

    def test_failure_isolation_then_retry_only_failed_item(self):
        started = self.batch.start([self.sid, self.sid, self.sid])
        batch_id = started['batch_id']
        original = self.batch._material
        failed = False
        def one_failure(state, item):
            nonlocal failed
            if item is state['items'][1] and item['phase'] == 'speech' and not failed:
                failed = True
                raise ReaderError('fixture decode interruption')
            return original(state, item)
        # Use the same Batch object while injecting one material failure.
        with patch.object(self.batch, '_material', side_effect=one_failure):
            result = self.batch.next(batch_id)
            for _ in range(100):
                if 'next_ack_cursor' not in result:
                    break
                result = self.batch.next(batch_id, result['next_ack_cursor'])
        self.assertEqual([item['status'] for item in result['items']], ['delivered','failed','delivered'])
        self.assertTrue(result['processing_finished'])
        self.assertFalse(result['all_material_delivered'])
        self.assertEqual(result['batch_status'], 'partial')
        self.batch.retry(batch_id, 1)
        responses, final = self.drain(batch_id)
        self.assertTrue(final['all_material_delivered'])
        self.assertEqual({page['item_index'] for page in responses}, {1})

    def test_multiple_video_source_ids_and_empty_audio_stay_distinct(self):
        other = self.root / 'second source.mp4'
        shutil.copyfile(self.video, other)
        other.with_suffix('.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:08.000\nSecond video only\n', encoding='utf-8')
        second = self.reader.open(str(other))['session_id']
        batch_id = self.batch.start([self.sid, second])['batch_id']
        responses, final = self.drain(batch_id)
        for page in responses:
            self.assertEqual(page['session_id'], [self.sid, second][page['item_index']])
            self.assertEqual(page['material']['delivery']['binding']['session_id'], page['session_id'])
        self.assertTrue(final['all_material_delivered'])

    def test_invalid_item_and_foreign_account_do_not_affect_valid_item(self):
        batch_id = self.batch.start([str(self.root / 'missing.mp4'), self.sid])['batch_id']
        _, final = self.drain(batch_id)
        self.assertEqual([item['status'] for item in final['items']], ['failed', 'delivered'])
        with patch('scroll_agent.batch.credentials', return_value={'account_marker': 'other'}):
            with self.assertRaisesRegex(ReaderError, 'account scope'):
                Batch(self.reader).status(batch_id)

    def test_local_batch_requires_no_platform_login_but_keeps_account_queues_separate(self):
        with patch('scroll_agent.batch.credentials', side_effect=PlatformError('login_required')):
            batch = Batch(self.reader, offline=True)
            batch_id = batch.start([self.sid])['batch_id']
            _, final = self.drain(batch_id, batch.next(batch_id))
            self.assertTrue(final['all_material_delivered'])
            self.assertEqual(final['account_scope'], 'anonymous')
        with self.assertRaisesRegex(ReaderError, 'account scope'):
            self.batch.status(batch_id)


class IncrementalBatchTests(unittest.TestCase):
    setUp = foundations.SpeechCoverageTests.setUp
    tearDown = foundations.SpeechCoverageTests.tearDown
    record = foundations.SpeechCoverageTests.record
    decode = foundations.SpeechCoverageTests.decode

    def test_decode_one_chunk_per_step_and_deliver_only_matching_new_prefix(self):
        self.data['metadata']['has_video'] = False
        self.reader.save(self.data)
        with patch('scroll_agent.batch.credentials', return_value={'account_marker':'fixture'}), \
             patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            batch = Batch(self.reader, offline=True)
            batch_id = batch.start([self.sid], source='asr')['batch_id']
            result = batch.next(batch_id)
            texts = []
            for _ in range(20):
                if 'next_ack_cursor' not in result:
                    break
                if 'material' in result:
                    material = original_page(self.reader, result['material'])
                    texts.extend(s['text'] for s in material.get('segments', []))
                before = decoder.call_count
                result = batch.next(batch_id, result['next_ack_cursor'])
                self.assertLessEqual(decoder.call_count-before, 1)
            self.assertTrue(result['all_material_delivered'])
            self.assertEqual(texts, ['chunk 0.0', 'chunk 120.0', 'chunk 240.0'])
            self.assertEqual(decoder.call_count, 3)


if __name__ == '__main__':
    unittest.main()
