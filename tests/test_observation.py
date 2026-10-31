from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_reader.common import ReaderError, read_json, run, write_json
from video_reader.acquisition_budget import Budget
from video_reader.reader import Reader
from video_reader.youtube_auth import reader_profile
import test_reader as fixtures


class ObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReaderTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    setUp = fixtures.ReaderTests.setUp

    def test_adaptive_captions_retain_both_small_text_changes_and_exact_detail(self):
        result = self.reader.open(str(self.video), task='What changed in the two slides?', strategy='adaptive')
        sid = result['session_id']
        frames = list(result['visual']['frames'])
        while cursor := result['delivery']['next_cursor']:
            result = self.reader.continue_read(sid, cursor)
            frames.extend(result['visual']['frames'])
        self.assertTrue(any(f['timestamp_seconds'] < 4 for f in frames))
        self.assertTrue(any(f['timestamp_seconds'] >= 4 for f in frames))
        self.assertIn('timeline_check', {f['observation_reason'] for f in frames})
        self.assertIn('speech_cue', {f['observation_reason'] for f in frames})
        detail = self.reader.frame(sid, frames[-1]['id'], region=[.05, .35, .9, .6])
        self.assertEqual(detail['visual']['frames'][0]['parent_frame_id'], frames[-1]['id'])
        self.assertAlmostEqual(detail['visual']['frames'][0]['timestamp_seconds'], frames[-1]['timestamp_seconds'], places=1)
        with self.assertRaisesRegex(ReaderError, 'belong'):
            self.reader.frame(sid, 'other-video:0')

    def test_read_speech_cursor_retains_range_and_source(self):
        opened = self.reader.open(str(self.video))
        cursor = opened['speech']['next_cursor']
        result = self.reader.continue_read(opened['session_id'], cursor)
        self.assertEqual(result['segments'][0]['text'], '测试结束')
        self.assertEqual(result['source'], 'captions')

    def test_dense_mode_stays_optional_and_retains_last_page(self):
        sid = self.reader.open(str(self.video))['session_id']
        dense = self.reader.read(sid, strategy='dense', temporal=False, verify=False)
        self.assertEqual(dense['visual']['total_frames'], 48)
        self.assertFalse(dense['visual']['complete_continuous_coverage'])
        self.assertEqual(self.reader.read(sid)['visual']['total_frames'], 12)

    def test_local_sound_measures_quiet_without_deleting_speech(self):
        wav = self.root / 'levels.wav'
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6',
             '-af', "volume=0:enable='between(t,1,4)'", str(wav)])
        opened = self.reader.open(str(wav))
        result = self.reader.sound(opened['session_id'])
        self.assertEqual(result['status'], 'measured')
        self.assertGreaterEqual(len(result['cues']), 4)
        self.assertTrue(any(c['quiet'] for c in result['cues']))
        self.assertTrue(any(not c['quiet'] for c in result['cues']))
        self.assertFalse(result['raw_sound_understood_by_host'])


class AcquisitionTests(unittest.TestCase):
    def test_budget_and_pause_share_the_native_network_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = {'directory': temporary, 'options': {'daily_requests': 2, 'min_gap_seconds': 0}}
            budget = Budget(spec)
            budget.reserve()
            budget.reserve()
            with self.assertRaisesRegex(ReaderError, 'budget_exhausted'):
                Budget(spec).reserve()
            budget.reject(429)
            with self.assertRaisesRegex(ReaderError, 'platform_paused'):
                Budget(spec).reserve()
            self.assertEqual(read_json(root / 'network.json')['count'], 2)

    def test_cookie_download_copy_does_not_mutate_original_and_scopes_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'manual.txt'
            content = '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n'
            source.write_text(content, encoding='utf-8')
            with reader_profile({'cookies_file': str(source), 'height': 720}) as (io, cache, auth):
                copied = Path(io['cookies_file'])
                self.assertNotEqual(copied, source)
                copied.write_text('downloader changed its own jar', encoding='utf-8')
                self.assertIsNone(auth['authenticated'])
                scope = cache['cookie_scope']
            self.assertFalse(copied.exists())
            self.assertEqual(source.read_text(encoding='utf-8'), content)
            source.write_text(content.replace('fixture', 'replacement'), encoding='utf-8')
            with reader_profile({'cookies_file': str(source)}) as (_, cache, _):
                self.assertNotEqual(cache['cookie_scope'], scope)


if __name__ == '__main__':
    unittest.main()
