from pathlib import Path
import copy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from video_reader import audio, observation, qwen, speech, vision
from video_reader.common import ReaderError, read_json, write_json
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


class CapabilityGenerationTests(unittest.TestCase):
    setUp = SpeechCoverageTests.setUp
    tearDown = SpeechCoverageTests.tearDown
    record = SpeechCoverageTests.record
    decode = SpeechCoverageTests.decode

    def test_same_path_model_replacement_changes_generation_and_keeps_old_review_readable(self):
        old = self.record(0, 300)
        old['profile'] = speech.legacy_profile(self.reader.config, '')
        old['segments'].append({'start': 200, 'end': 210, 'text': 'historical tail'})
        self.data['speech'] = [old]
        self.reader.save(self.data)
        prepared = self.reader.review(self.sid, source='asr')
        self.reader.review(self.sid, 'commit', source='asr', payload={
            'snapshot_id': prepared['snapshot_id'], 'base_revision': 0,
            'reviewed_segment_ids': [s['segment_id'] for s in prepared['segments']]})
        historical = self.reader.transcript(self.sid, source='asr', transcribe=False, verify=False, limit=1)
        self.assertEqual(historical['profile_status'], 'historical')
        self.assertEqual(historical['review']['revision'], 1)
        original = copy.deepcopy(self.reader.load(self.sid)['speech'][0])
        before = speech.profile(self.reader.config, '')
        Path(self.reader.config['asr']['model_path'], 'model.bin').write_bytes(b'replacement model')
        self.assertNotEqual(speech.profile(self.reader.config, ''), before)
        with patch('video_reader.speech.decode', side_effect=self.decode):
            current = self.reader.transcript(self.sid, source='asr', verify=False)
        self.assertNotEqual(current['profile'], old['profile'])
        self.assertEqual(self.reader.load(self.sid)['speech'][0], original)
        with patch('video_reader.speech.decode', side_effect=AssertionError('historical track cannot decode')):
            selected = self.reader.transcript(self.sid, source='asr', speech_profile=old['profile'], verify=False)
            review = self.reader.review(self.sid, source='asr', speech_profile=old['profile'])
        self.assertEqual(selected['review']['snapshot_id'], prepared['snapshot_id'])
        self.assertEqual(selected['review']['revision'], 1)
        self.assertEqual(review['snapshot_id'], prepared['snapshot_id'])
        self.assertIn(old['profile'], current['available_profiles'])
        exported = self.reader.export(self.sid, self.root / 'historical-export', 1,
            source='asr', speech_profile=old['profile'])
        archive = read_json(Path(exported['destination']) / 'evidence.json')
        self.assertEqual(archive['snapshot_id'], prepared['snapshot_id'])
        self.assertEqual(archive['revision'], 1)
        self.assertEqual(archive['speech_source']['profile'], old['profile'])

    def test_in_process_model_pool_reloads_same_path_generation(self):
        model = SimpleNamespace(transcribe=lambda *args, **kwargs:
            (iter([]), SimpleNamespace(language='zh', language_probability=.99)))
        factory = unittest.mock.Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=factory)}), \
             patch.dict(speech._models, {}, clear=True), patch('video_reader.speech.run'):
            first = speech.decode(self.data, 0, 10, self.root, self.reader.config, '', lambda text: None)
            Path(self.reader.config['asr']['model_path'], 'model.bin').write_bytes(b'replaced in process')
            second = speech.decode(self.data, 0, 10, self.root, self.reader.config, '', lambda text: None)
            self.assertEqual(len(speech._models), 1)
        self.assertEqual(factory.call_count, 2)
        self.assertNotEqual(first['profile'], second['profile'])

    def test_explicit_profile_is_read_only_even_when_coverage_is_partial(self):
        old = self.record(0, 120)
        self.data['speech'] = [old]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=AssertionError('must not decode')):
            result = self.reader.transcript(self.sid, source='asr', speech_profile=old['profile'], verify=False)
        self.assertFalse(result['coverage']['complete'])
        with self.assertRaisesRegex(ReaderError, 'cached track'):
            self.reader.transcript(self.sid, source='asr', speech_profile='unknown', verify=False)

    def test_normalized_diagnostics_preserve_preexisting_cursor_identity(self):
        from video_reader.recognition import diagnostic_identity
        speech = {'segments': [{'start': 1, 'end': 2, 'text': 'original',
            'recognition': {'flags': ['qwen_seam_requires_review']}}]}
        before = diagnostic_identity(speech)
        speech['segments'][0]['recognition']['requires_review'] = True
        self.assertEqual(diagnostic_identity(speech), before)
        speech['segments'][0]['recognition']['flags'].append('suspect_decoding')
        self.assertNotEqual(diagnostic_identity(speech), before)

    def test_runtime_and_qwen_assets_change_generation_without_model_loading(self):
        with patch('video_reader.speech.runtime_identity', return_value='runtime-a'):
            old = speech.profile(self.reader.config, '')
        with patch('video_reader.speech.runtime_identity', return_value='runtime-b'):
            self.assertNotEqual(speech.profile(self.reader.config, ''), old)
        options = copy.deepcopy(self.reader.config)
        for field in ('model_path', 'aligner_path'):
            path = self.root / field
            path.mkdir()
            (path / 'model.safetensors').write_bytes(b'first')
            options['qwen'][field] = str(path)
        runtime = self.root / 'qwen-runtime'
        runtime.mkdir()
        (runtime / 'pyvenv.cfg').write_text('version = 3.11.0', encoding='utf-8')
        options['qwen']['runtime_dir'] = str(runtime)
        first = qwen.profile(options, '')
        Path(options['qwen']['model_path'], 'model.safetensors').write_bytes(b'replacement')
        second = qwen.profile(options, '')
        self.assertNotEqual(first, second)
        (runtime / 'pyvenv.cfg').write_text('version = 3.11.1', encoding='utf-8')
        self.assertNotEqual(qwen.profile(options, ''), second)

    def test_audio_cache_derives_pagination_from_each_request(self):
        self.data['metadata']['duration_seconds'] = 1200
        self.reader.save(self.data)
        output = 'pts_time:0\nlavfi.astats.Overall.RMS_level=-20\nlavfi.astats.Overall.Peak_level=-10'
        with patch('video_reader.audio.run', side_effect=['16000', output, '16000', output]) as run_audio:
            short = self.reader.sound(self.sid, 0, 600)
            long = self.reader.sound(self.sid, 0, 1200)
            self.assertIsNone(short['next_start'])
            self.assertEqual(long['next_start'], 600)
            long_first = self.reader.sound(self.sid, 1, 1200)
            short_after = self.reader.sound(self.sid, 1, 601)
            self.assertEqual(long_first['next_start'], 601)
            self.assertIsNone(short_after['next_start'])
        self.assertEqual(run_audio.call_count, 4)
        cached = list((self.reader.directory(self.sid) / 'audio-cues').glob('*.json'))
        self.assertTrue(all('next_start' not in read_json(path) for path in cached))

    def test_adaptive_cache_tracks_cue_times_and_policy_but_not_host_review(self):
        self.data['metadata']['has_video'] = True
        self.reader.save(self.data)
        frame = self.root / 'frame.jpg'
        Image.new('RGB', (640, 360), 'white').save(frame)
        def extract(*args):
            return [{'path': str(frame), 'index': 0, 'timestamp_seconds': 1}], {'engine': 'fixture'}
        with patch('video_reader.observation.extract', side_effect=extract) as adaptive:
            first = self.reader.read(self.sid, strategy='adaptive', temporal=False, verify=False)
            self.data['speech'] = [{'source': 'captions', 'start': 0, 'end': 300, 'status': 'ready',
                'segments': [{'start': 10, 'end': 20, 'text': 'new raw cues'}]}]
            self.reader.save(self.data)
            second = self.reader.read(self.sid, strategy='adaptive', temporal=False, verify=False)
            self.assertNotEqual(first['read_id'], second['read_id'])
            prepared = self.reader.review(self.sid)
            self.reader.review(self.sid, 'commit', payload={'snapshot_id': prepared['snapshot_id'],
                'base_revision': 0, 'reviewed_segment_ids': [s['segment_id'] for s in prepared['segments']]})
            third = self.reader.read(self.sid, strategy='adaptive', temporal=False, verify=False)
            self.assertEqual(second['read_id'], third['read_id'])
            self.assertEqual(adaptive.call_count, 2)
            with patch('video_reader.observation.REVISION', observation.REVISION + 1):
                changed = self.reader.read(self.sid, strategy='adaptive', temporal=False, verify=False)
            self.assertNotEqual(third['read_id'], changed['read_id'])
        with patch('video_reader.reader.frames.extract', return_value=[{'path': str(frame), 'index': 0, 'timestamp_seconds': 1}]) as uniform:
            first = self.reader.read(self.sid, temporal=False, verify=False)
            state = self.reader.load(self.sid)
            state['speech'][0]['segments'][0]['start'] = 12
            self.reader.save(state)
            second = self.reader.read(self.sid, temporal=False, verify=False)
        self.assertEqual(first['read_id'], second['read_id'])
        self.assertEqual(uniform.call_count, 1)

    def test_ocr_generations_isolate_raw_and_verification_caches_and_keep_old_files(self):
        frame = self.root / 'frame.jpg'
        Image.new('RGB', (1280, 720), 'white').save(frame)
        box = [[100, 550], [800, 550], [800, 600], [100, 600]]
        backend = SimpleNamespace(RapidOCR=lambda **kwargs: lambda path: ([[box, 'original text', .99]], None))
        with patch.dict(sys.modules, {'rapidocr_onnxruntime': backend}), patch.object(vision, '_engine', None), patch.object(vision, '_engine_profile', None):
            with patch.object(vision, 'profile', return_value='generation-a'):
                vision.ocr_frame(frame)
            with patch.object(vision, 'profile', return_value='generation-b'):
                vision.ocr_frame(frame)
        self.assertTrue(frame.with_suffix('.ocr-generation-a.json').is_file())
        self.assertTrue(frame.with_suffix('.ocr-generation-b.json').is_file())
        directory = self.reader.directory(self.sid)
        segment = {'start': 1, 'end': 3, 'text': 'original text'}
        sample = {'path': str(frame), 'time': 2, 'lines': [line('original text', box)]}
        self.reader.config['vision']['enabled'] = True
        with patch.object(vision, '_frame_at', return_value=sample) as inspect:
            with patch.object(vision, 'profile', return_value='generation-a'):
                old = vision.verify_segments(self.data, [segment], directory, self.reader.config)[0]
            with patch.object(vision, 'profile', return_value='generation-b'):
                new = vision.verify_segments(self.data, [segment], directory, self.reader.config)[0]
        self.assertFalse(old['screen_verification']['cache_reused'])
        self.assertFalse(new['screen_verification']['cache_reused'])
        self.assertEqual(inspect.call_count, 4)
        self.assertTrue((directory / 'screen-verifications-generation-a.json').is_file())
        self.assertTrue((directory / 'screen-verifications-generation-b.json').is_file())
        self.data['metadata']['has_video'] = True
        self.reader.save(self.data)
        selected = [{'path': str(frame), 'index': 0, 'timestamp_seconds': 1}]
        with patch.object(vision, 'available', return_value=True), patch.object(vision, 'annotate_frame', side_effect=lambda f, *args, **kwargs: f), \
             patch('video_reader.reader.frames.extract', side_effect=lambda *args, **kwargs: copy.deepcopy(selected)) as extract:
            with patch.object(vision, 'profile', return_value='generation-a'):
                first = self.reader.read(self.sid, temporal=True, verify=False)
            with patch.object(vision, 'profile', return_value='generation-b'):
                second = self.reader.read(self.sid, temporal=True, verify=False)
        self.assertNotEqual(first['read_id'], second['read_id'])
        self.assertEqual(extract.call_count, 2)
        self.assertEqual(len(self.reader.load(self.sid)['reads']), 2)


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
