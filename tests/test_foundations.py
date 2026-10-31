from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from video_reader import speech, vision
from video_reader.common import ReaderError, write_json
from video_reader.reader import Reader


def line(text, box=None, confidence=.99):
    return {'text': text, 'confidence': confidence,
            'box': box or [[100, 550], [800, 550], [800, 600], [100, 600]]}


class SpeechCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        model = self.root / 'model'
        model.mkdir()
        (model / 'model.bin').write_bytes(b'fixture')
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': str(self.root / 'cache'), 'vision': {'enabled': False},
                            'asr': {'model_path': str(model), 'chunk_seconds': 120}})
        self.reader = Reader(config)
        media = self.root / 'source.mp4'
        media.write_bytes(b'fixture')
        self.sid = 'v_' + 'a'*24
        self.data = {'id': self.sid, 'source': {'platform': 'generic', 'canonical': 'https://example.com/test', 'identity': {}},
                     'media_path': str(media), 'title': 'Subject', 'metadata': {'duration_seconds': 300, 'has_audio': True},
                     'speech': [], 'reads': [], 'warnings': []}
        self.reader.save(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, start, end, context='', status='ready'):
        return {'start': start, 'end': end, 'source': 'local_faster_whisper', 'status': status,
                'profile': speech.profile(self.reader.config, context),
                'segments': [] if status == 'no_speech' else [{'start': start+.1, 'end': end-.1, 'text': f'chunk {start}'}]}

    def decode(self, data, start, end, directory, config, context, emit):
        return self.record(start, end, context)

    def test_force_asr_bypasses_existing_captions_and_keeps_both_sources(self):
        self.data['speech'] = [{'start': 0, 'end': 300, 'source': 'captions', 'status': 'ready',
                                'track': {'kind': 'automatic'}, 'segments': [{'start': 1, 'end': 2, 'text': 'caption'}]}]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=self.decode) as decode:
            result = self.reader.transcript(self.sid, source='asr', verify=False)
            self.assertEqual(decode.call_count, 3)
            self.assertEqual(result['source'], 'local_faster_whisper')
            self.assertTrue(result['coverage']['complete'])
            self.assertEqual(result['total_segments'], 3)
            raw_caption = self.reader.transcript(self.sid, source='captions', verify=False)
            self.assertEqual(raw_caption['segments'][0]['text'], 'caption')
        self.assertEqual(len(self.reader.load(self.sid)['speech']), 4)

    def test_interruption_commits_completed_interval_and_resumes_only_tail(self):
        with patch('video_reader.speech.decode', side_effect=[self.record(0, 120), ReaderError('interrupted')]):
            with self.assertRaisesRegex(ReaderError, 'interrupted'):
                self.reader.transcript(self.sid, source='asr', verify=False)
        pending = self.reader.transcript(self.sid, source='asr', transcribe=False, verify=False)
        self.assertFalse(pending['coverage']['complete'])
        self.assertEqual(pending['coverage']['missing_ranges'], [[120, 300]])
        with patch('video_reader.speech.decode', side_effect=self.decode) as decode:
            result = self.reader.transcript(self.sid, source='asr', verify=False)
            self.assertEqual([(c.args[1], c.args[2]) for c in decode.call_args_list], [(120, 240), (240, 300)])
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(len(self.reader.load(self.sid)['speech']), 3)

    def test_disjoint_intervals_do_not_masquerade_as_full_coverage(self):
        self.data['speech'] = [self.record(0, 100), self.record(200, 300)]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=self.decode) as decode:
            result = self.reader.transcript(self.sid, source='asr', verify=False)
            self.assertEqual((decode.call_args.args[1], decode.call_args.args[2]), (100, 200))
        self.assertEqual(result['total_segments'], 3)

    def test_subranges_and_transcript_pages_reuse_full_recognition(self):
        self.data['speech'] = [self.record(0, 120), self.record(120, 240), self.record(240, 300)]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=AssertionError('must reuse')):
            first = self.reader.transcript(self.sid, source='asr', limit=2, verify=False)
            last = self.reader.transcript(self.sid, source='asr', offset=first['next_offset'], limit=2, verify=False)
            focused = self.reader.transcript(self.sid, start=135, end=150, source='asr', verify=False)
        self.assertEqual(last['total_segments'], 3)
        self.assertIsNone(last['next_offset'])
        self.assertTrue(focused['coverage']['complete'])

    def test_silence_is_completed_processing_not_a_missing_interval(self):
        self.data['speech'] = [self.record(0, 300, status='no_speech')]
        self.reader.save(self.data)
        result = self.reader.transcript(self.sid, source='asr', verify=False)
        self.assertEqual(result['status'], 'no_speech')
        self.assertTrue(result['coverage']['complete'])

    def test_silent_first_chunk_does_not_hide_later_speech(self):
        self.data['speech'] = [self.record(0, 120, status='no_speech'), self.record(120, 300)]
        self.reader.save(self.data)
        result = self.reader.transcript(self.sid, source='asr', verify=False)
        self.assertEqual(result['status'], 'ready')

    def test_context_changes_cannot_reuse_an_incompatible_decoding(self):
        self.data['speech'] = [self.record(0, 300)]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=self.decode) as decode:
            result = self.reader.transcript(self.sid, source='asr', context='Another topic', verify=False)
        self.assertEqual(decode.call_count, 3)
        self.assertTrue(result['coverage']['complete'])

    def test_caption_request_never_silently_runs_asr(self):
        with patch('video_reader.speech.decode', side_effect=AssertionError('must not run')):
            result = self.reader.transcript(self.sid, source='captions', verify=False)
        self.assertEqual(result['status'], 'unavailable')


class VisualFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'anchor.jpg'
        Image.new('RGB', (1280, 720), 'white').save(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def annotate(self, values, shift=True, formula=False):
        records = []
        for index, value in enumerate(values):
            path = self.root / f'{index}.jpg'
            Image.new('RGB', (1280, 720), 'white').save(path)
            records.append({'index': index, 'timestamp_seconds': index*.5, 'path': str(path), 'reason': 'uniform'})
        text_by_path = {str(self.path): values[0], **{r['path']: values[i] for i, r in enumerate(records)}}
        box = [[100, 200], [500, 200], [500, 250], [100, 250]]
        def recognize(path):
            value = text_by_path[str(path)]
            return [line(value, box)] if value else []
        frame = {'index': 0, 'timestamp_seconds': 0, 'path': str(self.path), 'reason': 'uniform'}
        with patch('video_reader.vision.ocr_frame', side_effect=recognize), patch('video_reader.vision.decoder.extract', return_value=records):
            return vision.annotate_frame(frame, {'media_path': 'fixture'}, self.root,
                                         {'vision': {'lookahead_seconds': 10}}, 10, allow_shift=shift)

    def test_counter_is_replaced_by_observed_hold_not_last_changing_value(self):
        result = self.annotate(['865 nm', '558 nm', '227 nm', '1 nm', '1 nm', '1 nm'])
        self.assertEqual(result['ocr'][0]['text'], '1 nm')
        self.assertEqual(result['temporal']['status'], 'changing_then_stable')
        self.assertGreater(result['timestamp_seconds'], 0)
        self.assertFalse(result['temporal']['semantic_finality_established'])

    def test_exact_timestamp_retains_original_and_supplies_stable_reference(self):
        result = self.annotate(['865 nm', '558 nm', '227 nm', '1 nm', '1 nm', '1 nm'], shift=False)
        self.assertEqual(result['timestamp_seconds'], 0)
        self.assertEqual(result['path'], str(self.path))
        self.assertEqual(result['temporal']['stable_reference']['ocr'][0]['text'], '1 nm')

    def test_numeric_pause_before_change_does_not_select_previous_hold(self):
        result = self.annotate(['865 nm', '865 nm', '865 nm', '558 nm', '1 nm', '1 nm', '1 nm'])
        self.assertEqual(result['ocr'][0]['text'], '1 nm')

    def test_window_ending_in_change_does_not_claim_previous_hold_is_final(self):
        result = self.annotate(['F=q', 'F=q', 'F=q', 'F=qV'])
        self.assertEqual(result['temporal']['status'], 'unresolved')

    def test_formula_does_not_stop_at_intermediate_plateau(self):
        result = self.annotate(['F=', 'F=q', 'F=q', 'F=q', 'F=qV', 'F=qV', 'F=qV', 'F=qVxB', 'F=qVxB', 'F=qVxB'])
        self.assertEqual(result['ocr'][0]['text'], 'F=qVxB')

    def test_disappearing_field_is_not_a_final_stable_value(self):
        result = self.annotate(['865 nm', '558 nm', None, None, None])
        self.assertEqual(result['path'], str(self.path))
        self.assertEqual(result['temporal']['status'], 'unresolved')

    def test_similar_screen_line_can_reconcile_a_small_asr_error(self):
        candidate = vision.correction_candidate('那就是项目历史', [line('那就是，项目意识')], 720)
        self.assertIsNotNone(candidate)
        self.assertIsNone(vision.correction_candidate('那就是项目历史', [line('欢迎订阅这个频道')], 720))
        self.assertIsNone(vision.correction_candidate('那就是项目历史', [line('那就是，项目意识', confidence=.7)], 720))

    def test_visual_correction_needs_two_matching_frames_and_keeps_raw_text(self):
        segment = {'start': 20, 'end': 22, 'text': '那就是项目历史'}
        evidence = {'path': str(self.path), 'time': 21, 'lines': [line('那就是，项目意识')]}
        with patch('video_reader.vision._frame_at', return_value=evidence):
            corrected = vision.verify_segments({}, [segment], self.root, {})[0]
        self.assertEqual(corrected['raw_text'], segment['text'])
        self.assertEqual(corrected['text'], segment['text'])
        self.assertEqual(corrected['screen_candidate'], '那就是，项目意识')
        self.assertEqual(len(corrected['screen_verification']['evidence']), 2)

    def test_disagreeing_frames_cannot_overwrite_speech(self):
        segment = {'start': 20, 'end': 22, 'text': '那就是项目历史'}
        first = {'path': str(self.path), 'time': 20.8, 'lines': [line('那就是，项目意识')]}
        second = {'path': str(self.path), 'time': 21.2, 'lines': [line('这段文字已经变了')]}
        with patch('video_reader.vision._frame_at', side_effect=[first, second]):
            result = vision.verify_segments({}, [segment], self.root, {})[0]
        self.assertEqual(result['text'], segment['text'])
        self.assertNotIn('raw_text', result)
        self.assertEqual(result['screen_verification']['status'], 'unstable_or_disagreeing_screen_text')

    def test_lower_confidence_ocr_flags_difference_without_rewriting(self):
        segment = {'start': 20, 'end': 22, 'text': '那就是项目历史'}
        evidence = {'path': str(self.path), 'time': 21, 'lines': [line('那就是项目意识', confidence=.88)]}
        with patch('video_reader.vision._frame_at', return_value=evidence):
            result = vision.verify_segments({}, [segment], self.root, {})[0]
        self.assertEqual(result['text'], segment['text'])
        self.assertEqual(result['screen_verification']['status'], 'possible_screen_difference')

    def test_stable_confident_ocr_cannot_delete_an_acronym_character(self):
        segment = {'start': 20, 'end': 22, 'text': 'MBTI对人群的划分是不可能的'}
        evidence = {'path': str(self.path), 'time': 21, 'lines': [line('MBT对人群的划分是不可能的')]}
        with patch('video_reader.vision._frame_at', return_value=evidence):
            result = vision.verify_segments({}, [segment], self.root, {})[0]
        self.assertEqual(result['text'], segment['text'])
        self.assertEqual(result['screen_candidate'], evidence['lines'][0]['text'])

    def test_stable_confident_ocr_cannot_replace_correct_chinese_character(self):
        segment = {'start': 20, 'end': 22, 'text': '移情不同于日常生活中的正常情感'}
        evidence = {'path': str(self.path), 'time': 21, 'lines': [line('移情不同干日常生活中的正常情感')]}
        with patch('video_reader.vision._frame_at', return_value=evidence):
            result = vision.verify_segments({}, [segment], self.root, {})[0]
        self.assertEqual(result['text'], segment['text'])
        self.assertEqual(result['screen_verification']['status'], 'difference_detected')


if __name__ == '__main__':
    unittest.main()
