from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from video_reader import speech
from video_reader.common import ReaderError, read_json, write_json
from video_reader.reader import Reader


class ReadEfficiencyTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '.test-work'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': 'cache', 'vision': {'enabled': True}})
        self.reader = Reader(config)
        self.sid = 'v_' + 'c' * 24
        self.frame = self.root / 'frame.jpg'
        Image.new('RGB', (1280, 720), 'white').save(self.frame)
        media = self.root / 'source.mp4'
        media.write_bytes(b'fixture')
        self.data = {'id': self.sid, 'title': '项目创作',
            'source': {'platform': 'generic', 'canonical': 'https://example.com', 'identity': {}},
            'media_path': str(media), 'metadata': {'duration_seconds': 30, 'has_audio': True, 'has_video': False},
            'reads': [{'id': 'evidence', 'frames': [{'path': str(self.frame)}]}], 'warnings': [],
            'speech': [{'start': 0, 'end': 30, 'source': 'captions', 'status': 'ready', 'track': {'kind': 'automatic'},
                        'segments': [{'start': 1, 'end': 3, 'text': '这是平台字幕原文'}]},
                       {'start': 0, 'end': 30, 'source': 'local_faster_whisper', 'status': 'ready',
                        'profile': speech.profile(self.reader.config, '项目创作'),
                        'segments': [{'start': 1, 'end': 3, 'text': '那就是项目历史'},
                                     {'start': 6, 'end': 8, 'text': '第二句话保持原文'}]}]}
        self.reader.save(self.data)

    def review(self, count=2, uncertain=False):
        page = self.reader.review(self.sid, source='asr')
        first = page['segments'][0]
        payload = {'snapshot_id': page['snapshot_id'], 'base_revision': page['base_revision'],
            'reviewed_segment_ids': [segment['segment_id'] for segment in page['segments'][:count]],
            'corrections': [{'segment_id': first['segment_id'], 'original': first['original'],
                'corrected_text': '那就是项目意识', 'reason': '本片画面依据',
                'evidence': [{'kind': 'frame', 'path': str(self.frame)}]}]}
        if uncertain:
            payload['issues'] = [{'segment_id': first['segment_id'], 'note': '仍待核实',
                                 'evidence': [{'kind': 'frame', 'path': str(self.frame)}]}]
        self.reader.review(self.sid, 'commit', source='asr', payload=payload)

    def screen(self, data, directory, timestamp):
        text = '那就是项目意识' if timestamp < 4 else '第二句话保持原文'
        return {'path': str(self.frame), 'time': timestamp,
                'lines': [{'text': text, 'confidence': .99,
                           'box': [[100, 550], [800, 550], [800, 600], [100, 600]]}]}

    def test_read_keeps_asr_review_while_auto_still_prefers_captions(self):
        self.review()
        with patch('video_reader.vision._frame_at', side_effect=AssertionError('no new OCR')):
            result = self.reader.read(self.sid, source='asr', temporal=False)
            auto = self.reader.read(self.sid, temporal=False, verify=False)
        self.assertEqual(result['speech']['source'], 'local_faster_whisper')
        self.assertEqual(result['speech']['segments'][0]['text'], '那就是项目意识')
        self.assertTrue(result['speech']['review']['complete'])
        self.assertEqual(auto['speech']['segments'][0]['text'], '这是平台字幕原文')

    def test_reviewed_reading_skips_missing_checks_without_claiming_verified(self):
        self.review(uncertain=True)
        before = read_json(self.reader.directory(self.sid) / 'manifest.json')
        with patch('video_reader.vision._frame_at', side_effect=AssertionError('no new OCR')):
            result = self.reader.transcript(self.sid, source='asr')
        self.assertEqual(result['screen_verification']['skipped_segments'], 2)
        self.assertEqual(result['screen_verification']['computed_segments'], 0)
        self.assertIn('review_uncertain', result['segments'][0]['quality_flags'])
        self.assertNotIn('matched', result['segments'][0]['quality_flags'])
        self.assertEqual(read_json(self.reader.directory(self.sid) / 'manifest.json'), before)

    def test_pending_default_still_checks_but_only_pending_after_partial_review(self):
        self.review(count=1)
        with patch('video_reader.vision._frame_at', side_effect=self.screen) as frames:
            result = self.reader.transcript(self.sid, source='asr')
        self.assertEqual(frames.call_count, 2)
        self.assertTrue(all(call.args[2] > 6 for call in frames.call_args_list))
        self.assertEqual(result['screen_verification']['computed_segments'], 1)
        self.assertEqual(result['screen_verification']['skipped_segments'], 1)
        self.assertEqual(result['segments'][1]['review_status'], 'pending')

    def test_evidence_and_explicit_verification_compute_missing_then_reuse_raw_cache(self):
        self.review()
        with patch('video_reader.vision._frame_at', side_effect=self.screen) as frames:
            evidence = self.reader.transcript(self.sid, source='asr', view='evidence')
        self.assertEqual(frames.call_count, 4)
        first = evidence['segments'][0]
        self.assertEqual(first['raw_text'], '那就是项目历史')
        self.assertEqual(first['text'], '那就是项目意识')
        self.assertEqual(first['screen_verification']['status'], 'difference_detected')
        self.assertFalse(first['screen_verification']['cache_reused'])
        with patch('video_reader.vision._frame_at', side_effect=AssertionError('cached OCR')):
            compact = self.reader.transcript(self.sid, source='asr')
            explicit = self.reader.read(self.sid, source='asr', temporal=False, verify=True, view='evidence')
        self.assertIn('difference_detected', compact['segments'][0]['quality_flags'])
        self.assertEqual(explicit['speech']['screen_verification']['cached_segments'], 2)

    def test_verify_true_checks_reviewed_and_verify_false_disables_evidence_ocr(self):
        self.review()
        with patch('video_reader.vision._frame_at', side_effect=self.screen) as frames:
            result = self.reader.read(self.sid, source='asr', temporal=False, verify=True)
        self.assertEqual(frames.call_count, 4)
        self.assertEqual(result['speech']['screen_verification']['computed_segments'], 2)
        with patch('video_reader.vision.verify_segments', side_effect=AssertionError('disabled')):
            raw = self.reader.read(self.sid, source='asr', temporal=False, verify=False, view='raw')
        self.assertEqual(raw['speech']['segments'][0]['text'], '那就是项目历史')
        self.assertEqual(raw['speech']['screen_verification']['mode'], 'off')

    def test_exact_frames_do_not_trigger_unrelated_speech_checks_but_can_opt_in(self):
        with patch('video_reader.vision._frame_at', side_effect=AssertionError('frame request must stay cheap')):
            result = self.reader.read(self.sid, source='asr', temporal=False, timestamps=[20])
        self.assertEqual(result['speech']['screen_verification']['skipped_segments'], 2)
        self.assertEqual(result['speech']['segments'][0]['review_status'], 'pending')
        with patch('video_reader.vision._frame_at', side_effect=self.screen) as frames:
            explicit = self.reader.read(self.sid, source='asr', temporal=False, timestamps=[20], verify=True)
        self.assertEqual(frames.call_count, 4)
        self.assertEqual(explicit['speech']['screen_verification']['computed_segments'], 2)

    def test_context_selects_matching_asr_profile_without_redecoding(self):
        record = {**self.data['speech'][1], 'profile': speech.profile(self.reader.config, '另一个提示'),
                  'segments': [{'start': 1, 'end': 3, 'text': '另一个解码原文'}]}
        self.data['speech'].append(record)
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=AssertionError('read never decodes')):
            result = self.reader.read(self.sid, source='asr', context='另一个提示', temporal=False, verify=False)
        self.assertEqual(result['speech']['segments'][0]['text'], '另一个解码原文')
        self.assertFalse(result['speech']['review']['complete'])

    def test_changed_raw_snapshot_does_not_inherit_review_skip(self):
        self.review()
        self.data['speech'][1]['segments'][0]['text'] = '改变后的识别原文'
        self.reader.save(self.data)
        with patch('video_reader.vision._frame_at', side_effect=self.screen) as frames:
            result = self.reader.transcript(self.sid, source='asr')
        self.assertGreater(frames.call_count, 0)
        self.assertFalse(result['review']['complete'])
        self.assertEqual(result['screen_verification']['skipped_segments'], 0)

    def test_manual_captions_require_opt_in_and_invalid_options_fail_before_side_effects(self):
        self.data['speech'][0]['track']['kind'] = 'manual'
        self.reader.save(self.data)
        with patch('video_reader.vision._frame_at', side_effect=AssertionError('manual track')):
            result = self.reader.read(self.sid, temporal=False)
        self.assertEqual(result['speech']['screen_verification']['reason'], 'manual_captions')
        with patch.object(self.reader, 'load', side_effect=AssertionError('invalid input must fail early')):
            for options in ({'verify': 1}, {'view': 'unknown'}, {'source': 'unknown-engine'}):
                with self.subTest(options=options), self.assertRaises(ReaderError):
                    self.reader.read(self.sid, **options)
            with self.assertRaises(ReaderError):
                self.reader.transcript(self.sid, verify='false')


if __name__ == '__main__':
    unittest.main()
