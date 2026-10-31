import copy
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from video_reader import qwen, speech
from video_reader.cli import parser
from video_reader.common import ReaderError, write_json
from video_reader.qwen_pipeline import owned_chunk
from video_reader.reader import Reader


def fixture_chunk(start=0, end=60, silent=False):
    items = [] if silent else [SimpleNamespace(text='甲', start_time=1, end_time=1.5),
                              SimpleNamespace(text='乙', start_time=2, end_time=2.5)]
    return owned_chunk('' if silent else '甲。乙。', items,
        {'index': 0, 'owner_start': 0, 'owner_end': round((end-start)*10),
         'input_start': 0, 'input_end': round((end-start)*10)}, 10, start)


class QwenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        runtime = self.root / 'runtime'
        runtime.mkdir()
        (runtime / 'pyvenv.cfg').write_text(f'version = {sys.version_info.major}.{sys.version_info.minor}.0')
        write_json(config, {'cache_dir': str(self.root / 'cache'), 'vision': {'enabled': False},
                           'qwen': {'runtime_dir': str(runtime), 'timeout_seconds': 1}})
        self.reader = Reader(config)
        self.sid = 'v_' + 'f'*24
        (self.root / 'source.mp4').write_bytes(b'fixture')
        self.data = {'id': self.sid, 'title': 'Do not inject this title into Qwen',
                     'source': {'platform': 'generic', 'canonical': 'https://example.com', 'identity': {}},
                     'media_path': str(self.root / 'source.mp4'),
                     'metadata': {'duration_seconds': 130, 'has_audio': True, 'has_video': False},
                     'reads': [], 'warnings': [], 'speech': [
                         {'source': 'captions', 'start': 0, 'end': 130, 'status': 'ready',
                          'track': {'kind': 'manual'}, 'segments': [{'start': 1, 'end': 3, 'text': 'caption'}]},
                         {'source': 'local_faster_whisper', 'start': 0, 'end': 130, 'status': 'ready',
                          'profile': speech.profile(self.reader.config, 'Do not inject this title into Qwen'),
                          'segments': [{'start': 1, 'end': 3, 'text': 'whisper'}]}]}
        self.reader.save(self.data)

    def tearDown(self):
        self.temp.cleanup()

    def decode(self, data, start, end, directory, config, context, emit):
        chunk = fixture_chunk(start, end)
        return {'source': qwen.SOURCE, 'profile': qwen.profile(config, context), 'context': context,
                'start': start, 'end': end, 'status': 'ready', 'qwen_chunk': chunk,
                'segments': qwen.assemble([{'start': start, 'qwen_chunk': chunk}])[0]}

    def load_qwen(self):
        with patch('video_reader.qwen.available', return_value=True), patch('video_reader.qwen.decode', side_effect=self.decode):
            return self.reader.transcript(self.sid, source='qwen', verify=False)

    def test_explicit_source_keeps_defaults_and_original_records(self):
        before = copy.deepcopy(self.data['speech'])
        result = self.load_qwen()
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(result['source'], qwen.SOURCE)
        self.assertEqual(result['context'], '')
        self.assertNotIn('qwen_chunk', result)
        self.assertNotIn('words', result['segments'][0])
        self.assertEqual(self.reader.load(self.sid)['speech'][:2], before)
        self.assertEqual(self.reader.transcript(self.sid)['source'], 'captions')
        self.assertEqual(self.reader.transcript(self.sid, source='asr')['segments'][0]['text'], 'whisper')

    def test_checkpoint_resumes_only_missing_intervals(self):
        def interrupted(*args):
            if args[1] >= 60:
                raise ReaderError('interrupted fixture')
            return self.decode(*args)
        with patch('video_reader.qwen.available', return_value=True), patch('video_reader.qwen.decode', side_effect=interrupted):
            with self.assertRaisesRegex(ReaderError, 'interrupted'):
                self.reader.transcript(self.sid, source='qwen', verify=False)
        records = self.reader.load(self.sid)['speech']
        self.assertEqual([(item['start'], item['end']) for item in records[2:]], [(0, 60)])
        with patch('video_reader.qwen.available', return_value=True), patch('video_reader.qwen.decode', side_effect=self.decode) as decoder:
            self.assertTrue(self.reader.transcript(self.sid, source='qwen', verify=False)['coverage']['complete'])
        self.assertEqual([(call.args[1], call.args[2]) for call in decoder.call_args_list], [(60, 120), (120, 130)])

    def test_review_isolated_from_whisper_captions_and_raw_words(self):
        self.load_qwen()
        prepared = self.reader.review(self.sid, source='qwen', limit=1)
        segment = prepared['segments'][0]
        payload = {'snapshot_id': prepared['snapshot_id'], 'base_revision': prepared['base_revision'],
                   'reviewed_segment_ids': [segment['segment_id']],
                   'corrections': [{'segment_id': segment['segment_id'], 'original': segment['original'],
                                    'corrected_text': '丙。', 'reason': 'fixture context',
                                    'evidence': [{'kind': 'context', 'segment_ids': [segment['segment_id']]}]}]}
        self.reader.review(self.sid, 'commit', source='qwen', payload=payload)
        result = self.reader.transcript(self.sid, source='qwen', verify=False, view='evidence')
        self.assertEqual(result['segments'][0]['text'], '丙。')
        self.assertEqual(result['segments'][0]['raw_text'], '甲。')
        self.assertEqual(result['segments'][0]['words'][0]['text'], '甲')
        self.assertIsNone(result['segments'][0]['words'][0]['probability'])
        self.assertEqual(self.reader.transcript(self.sid, source='asr')['review']['reviewed_segments'], 0)
        self.assertEqual(self.reader.transcript(self.sid)['review']['reviewed_segments'], 0)

    def test_cached_read_and_context_are_source_consistent(self):
        result = self.load_qwen()
        with patch('video_reader.qwen.decode') as decoder:
            read = self.reader.read(self.sid, source='qwen', temporal=False)
        decoder.assert_not_called()
        self.assertEqual(read['speech']['source'], qwen.SOURCE)
        self.assertEqual(read['speech']['review']['snapshot_id'], result['review']['snapshot_id'])
        self.assertFalse(self.reader.transcript(self.sid, source='qwen', context='explicit hint', transcribe=False)['coverage']['complete'])

    def test_unavailable_qwen_does_not_reuse_other_engines(self):
        with patch('video_reader.qwen.available', return_value=False), patch('video_reader.speech.decode') as decoder:
            result = self.reader.transcript(self.sid, source='qwen', verify=False)
        decoder.assert_not_called()
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['coverage']['complete'])

    def test_cli_accepts_explicit_qwen_on_all_three_commands(self):
        for command in ('read', 'transcript', 'review'):
            arguments = [command, 'prepare', self.sid] if command == 'review' else [command, self.sid]
            self.assertEqual(parser().parse_args([*arguments, '--source', 'qwen']).source, 'qwen')

    def test_punctuation_survives_sentence_segmentation(self):
        chunk = fixture_chunk()
        segments, seams, cuts = qwen.assemble([{'start': 0, 'qwen_chunk': chunk}])
        self.assertEqual([segment['text'] for segment in segments], ['甲。', '乙。'])
        self.assertEqual((seams, cuts), ([], []))

    def test_unprocessed_gaps_are_not_stitched(self):
        records = [{'start': start, 'qwen_chunk': fixture_chunk(start, start+60)} for start in (0, 120)]
        segments, seams, cuts = qwen.assemble(records)
        self.assertEqual(len(segments), 4)
        self.assertEqual((seams, cuts), ([], []))

    def test_zero_duration_text_and_native_timing_are_retained(self):
        chunk = fixture_chunk()
        chunk['raw_words'][0]['end'] = chunk['raw_words'][0]['start']
        segments, _, _ = qwen.assemble([{'start': 0, 'qwen_chunk': chunk}])
        self.assertEqual(segments[0]['text'], '甲。')
        self.assertEqual(segments[0]['words'][0]['start'], segments[0]['words'][0]['end'])
        self.assertIn('unresolved_segment_timing', segments[0]['recognition']['flags'])

    def test_silence_retains_processed_coverage_without_text(self):
        chunk = fixture_chunk(silent=True)
        self.data['metadata']['duration_seconds'] = 60
        self.data['speech'].append({'source': qwen.SOURCE, 'start': 0, 'end': 60, 'status': 'no_speech',
                                   'profile': qwen.profile(self.reader.config, ''), 'qwen_chunk': chunk, 'segments': []})
        self.reader.save(self.data)
        result = self.reader.transcript(self.sid, source='qwen', verify=False)
        self.assertEqual(result['status'], 'no_speech')
        self.assertTrue(result['coverage']['complete'])

    def test_deadline_stops_owned_worker_without_fallback(self):
        process = SimpleNamespace(wait=lambda timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired('fixture', timeout)))
        with patch('video_reader.qwen.available', return_value=True), patch('video_reader.qwen.run'), \
             patch('video_reader.qwen.subprocess.Popen', return_value=process), patch('video_reader.relisten.stop') as stop:
            with self.assertRaisesRegex(ReaderError, 'deadline'):
                qwen.decode(self.data, 0, 60, self.reader.directory(self.sid), self.reader.config, '', lambda value: None)
        stop.assert_called_once_with(process)


if __name__ == '__main__':
    unittest.main()
