import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from video_reader import review, speech
from video_reader.common import ReaderError, read_json, write_json
from video_reader.reader import Reader
from video_reader.relisten import execute


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': str(self.root / 'cache'), 'vision': {'enabled': False}})
        self.reader = Reader(config)
        self.sid = 'v_' + 'a'*24
        media = self.root / 'source.mp4'
        media.write_bytes(b'fixture')
        self.frame = self.root / 'frame.jpg'
        self.frame.write_bytes(b'frame')
        self.data = {'id': self.sid, 'title': '项目创作',
                     'source': {'platform': 'generic', 'canonical': 'https://example.com', 'identity': {}},
                     'media_path': str(media), 'metadata': {'duration_seconds': 30, 'has_audio': True, 'has_video': False},
                     'reads': [{'id': 'evidence', 'frames': [{'path': str(self.frame)}]}], 'warnings': [],
                     'speech': [{'start': 0, 'end': 30, 'source': 'captions', 'status': 'ready',
                                 'track': {'kind': 'automatic'}, 'segments': [
                                     {'start': 1, 'end': 3, 'text': '那就是项目历史'},
                                     {'start': 5, 'end': 8, 'text': '今晚吃猪蹄，讨论疫情影响。'}]}]}
        self.reader.save(self.data)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, correct=True):
        prepared = self.reader.review(self.sid, limit=1)
        segment = prepared['segments'][0]
        return {'snapshot_id': prepared['snapshot_id'], 'base_revision': prepared['base_revision'],
                'reviewed_segment_ids': [segment['segment_id']],
                'corrections': [{'segment_id': segment['segment_id'], 'original': segment['original'],
                                 'corrected_text': '那就是项目意识', 'reason': '画面及项目语境一致',
                                 'evidence': [{'kind': 'frame', 'path': str(self.frame)}]}] if correct else []}

    def test_roundtrip_default_read_raw_words_and_unchanged_homophones(self):
        before = (self.reader.directory(self.sid) / 'manifest.json').read_bytes()
        result = self.reader.review(self.sid, 'commit', payload=self.payload())
        self.assertFalse(result['review']['complete'])
        later = self.reader.review(self.sid, offset=1, limit=1)
        payload = {'snapshot_id': later['snapshot_id'], 'base_revision': later['base_revision'],
                   'reviewed_segment_ids': [s['segment_id'] for s in later['segments']]}
        self.reader.review(self.sid, 'commit', payload=payload)
        text = self.reader.transcript(self.sid, verify=False)
        self.assertEqual(text['segments'][0]['text'], '那就是项目意识')
        self.assertNotIn('raw_text', text['segments'][0])
        evidence = self.reader.transcript(self.sid, view='evidence', verify=False)
        self.assertEqual(evidence['segments'][0]['raw_text'], '那就是项目历史')
        self.assertEqual(text['segments'][1]['text'], '今晚吃猪蹄，讨论疫情影响。')
        self.assertTrue(text['review']['complete'])
        self.assertEqual(evidence['segments'][0]['correction']['edits'][0]['original'], '历史')
        self.assertEqual(self.reader.transcript(self.sid, view='raw', verify=False)['segments'][0]['text'], '那就是项目历史')
        focused = self.reader.transcript(self.sid, start=1, end=4, verify=False)
        self.assertEqual(focused['segments'][0]['text'], '那就是项目意识')
        self.assertEqual((self.reader.directory(self.sid) / 'manifest.json').read_bytes(), before)
        reading = self.reader.read(self.sid, temporal=False)
        self.assertEqual(reading['speech']['segments'][0]['text'], '那就是项目意识')

    def test_stale_revision_or_snapshot_does_not_overwrite(self):
        payload = self.payload()
        self.reader.review(self.sid, 'commit', payload=payload)
        with self.assertRaisesRegex(ReaderError, 'revision'):
            self.reader.review(self.sid, 'commit', payload=payload)
        payload['snapshot_id'] = 'wrong'
        with self.assertRaisesRegex(ReaderError, 'snapshot'):
            self.reader.review(self.sid, 'commit', payload=payload)

    def test_unresolved_issue_is_visible_without_disclosing_evidence(self):
        payload = self.payload(False)
        payload['issues'] = [{'segment_id': payload['reviewed_segment_ids'][0],
                              'note': '语音与画面冲突，不能确定', 'evidence': [{'kind': 'title'}]}]
        self.reader.review(self.sid, 'commit', payload=payload)
        reading = self.reader.transcript(self.sid, verify=False)
        self.assertIn('review_uncertain', reading['segments'][0]['quality_flags'])
        self.assertNotIn('review_issue', reading['segments'][0])
        evidence = self.reader.transcript(self.sid, verify=False, view='evidence')
        self.assertEqual(evidence['segments'][0]['review_issue']['note'], '语音与画面冲突，不能确定')

    def test_compact_return_is_smaller_and_has_no_word_payload(self):
        self.data['speech'][0]['segments'][0]['words'] = [{'text': '那', 'start': 1, 'end': 1.1, 'probability': .99}]*100
        self.reader.save(self.data)
        compact = self.reader.transcript(self.sid, verify=False)
        detailed = self.reader.transcript(self.sid, verify=False, view='evidence')
        import json
        self.assertLess(len(json.dumps(compact)), len(json.dumps(detailed)) / 2)
        self.assertNotIn('words', compact['segments'][0])
        self.assertIn('words', detailed['segments'][0])

    def test_bad_original_and_foreign_frame_rejected_atomically(self):
        payload = self.payload()
        payload['corrections'][0]['original'] = 'incorrect'
        with self.assertRaisesRegex(ReaderError, 'original'):
            self.reader.review(self.sid, 'commit', payload=payload)
        payload = self.payload()
        payload['corrections'][0]['evidence'][0]['path'] = str(self.root / 'foreign.jpg')
        with self.assertRaisesRegex(ReaderError, 'this session'):
            self.reader.review(self.sid, 'commit', payload=payload)
        self.assertEqual(self.reader.review(self.sid, 'status')['review']['revision'], 0)

    def test_retraction_is_audited(self):
        self.reader.review(self.sid, 'commit', payload=self.payload())
        payload = self.payload()
        payload['corrections'][0]['corrected_text'] = '那就是项目历史'
        result = self.reader.review(self.sid, 'commit', payload=payload)
        saved = read_json(result['storage_path'])
        self.assertEqual(len(saved['history']), 2)
        self.assertFalse(saved['corrections'])

    def test_source_scoped_terms_and_asr_remain_separate(self):
        payload = self.payload()
        payload['terms'] = [{'text': '项目意识', 'evidence': [{'kind': 'frame', 'path': str(self.frame)}]}]
        result = self.reader.review(self.sid, 'commit', payload=payload)
        self.assertEqual(result['terms'][0]['text'], '项目意识')
        self.data['speech'].append({'start': 0, 'end': 30, 'source': 'local_faster_whisper',
            'profile': speech.profile(self.reader.config, self.data['title']),
            'segments': [{'start': 1, 'end': 3, 'text': '那就是项目历史',
                          'words': [{'text': '历史', 'start': 2, 'end': 3, 'probability': .9}]}]})
        self.reader.save(self.data)
        asr = self.reader.transcript(self.sid, source='asr', verify=False, view='evidence')
        self.assertEqual(asr['segments'][0]['text'], '那就是项目历史')
        self.assertEqual(asr['segments'][0]['word_alignment_text'], 'raw_text')
        self.assertFalse(asr['review']['complete'])

    def test_incomplete_coverage_and_unrelated_relisten_rejected(self):
        self.data['speech'][0]['end'] = 10
        self.reader.save(self.data)
        with self.assertRaisesRegex(ReaderError, 'full-source'):
            self.reader.review(self.sid)
        self.data['speech'][0]['end'] = 30
        self.reader.save(self.data)
        job = 'b'*24
        write_json(self.reader.directory(self.sid) / 'relistens' / job / 'result.json',
                   {'status': 'completed', 'range': {'start': 20, 'end': 25}})
        payload = self.payload()
        payload['corrections'][0]['evidence'] = [{'kind': 'relisten', 'job_id': job}]
        with self.assertRaisesRegex(ReaderError, 'overlap'):
            self.reader.review(self.sid, 'commit', payload=payload)

    def test_relisten_is_fresh_and_never_changes_manifest(self):
        before = self.reader.load(self.sid)
        def wait_for_worker(process, timeout=None):
            request_path = Path(process.request_path)
            write_json(request_path.parent / 'decoded.json', {'segments': [{'text': '项目意识'}]})
            return 0
        def start(command, **kwargs):
            return SimpleNamespace(pid=123, request_path=command[-1], returncode=0,
                                   wait=lambda timeout=None: wait_for_worker(process, timeout))
        process = None
        def factory(command, **kwargs):
            nonlocal process
            self.assertEqual(read_json(command[-1])['context'], '')
            process = start(command, **kwargs)
            return process
        with patch('video_reader.relisten.subprocess.Popen', side_effect=factory) as worker:
            first = self.reader.relisten(self.sid, 0, 10)
            second = self.reader.relisten(self.sid, 0, 10)
        self.assertEqual(worker.call_count, 2)
        self.assertNotEqual(first['job_id'], second['job_id'])
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(self.reader.load(self.sid), before)

    def test_real_process_deadline_terminates_python(self):
        original = subprocess.Popen
        processes = []
        def sleeper(command, **kwargs):
            if command[0] == 'taskkill':
                return original(command, **kwargs)
            process = original([getattr(sys, '_base_executable', sys.executable), '-I', '-c',
                                'import time;time.sleep(30)'], **kwargs)
            processes.append(process)
            return process
        with patch('video_reader.relisten.subprocess.Popen', side_effect=sleeper):
            result = self.reader.relisten(self.sid, 0, 10, timeout_seconds=1)
        self.assertEqual(result['status'], 'timed_out')
        self.assertIsNotNone(processes[0].poll())
        self.assertLess(result['elapsed_seconds'], 10)

    def test_repeated_relisten_candidate_is_explicitly_unverified(self):
        path=self.reader.directory(self.sid)/'relistens'/'result.json'
        result={'status':'completed','storage_path':str(path),
                'speech':{'segments':[{'text':'错误重复句'},{'text':'错误重复句'}]}}
        with patch('video_reader.relisten.execute',return_value=result):
            output=self.reader.relisten(self.sid,0,10)
        self.assertIn('repeated_candidate_segments',output['quality']['flags'])
        self.assertFalse(output['quality']['exactness_guaranteed'])

    def test_full_word_evidence_retained_not_just_uncertain_words(self):
        word = lambda text, start, end, prob: SimpleNamespace(word=text, start=start, end=end, probability=prob)
        segment = SimpleNamespace(words=[word('项目', 0, 1, .95), word('历史', 1, 2, .5)],
                                  start=0, end=2, text='项目历史', avg_logprob=-.1,
                                  no_speech_prob=.01, compression_ratio=1)
        class Model:
            def transcribe(self, *args, **kwargs):
                return iter([segment]), SimpleNamespace(language='zh', language_probability=.99)
        config = {'asr': {'model_path': 'fixture', 'device': 'cpu', 'compute_type': 'int8'}}
        with patch.dict(speech._models, {speech.model_key(config): Model()}), patch('video_reader.speech.run'):
            result = speech.decode({'metadata': {'duration_seconds': 10}, 'media_path': 'fixture'},
                                   0, 10, self.root, config,
                                   '', lambda s: None)
        self.assertEqual(len(result['segments'][0]['words']), 2)
        self.assertEqual(len(result['segments'][0]['recognition']['uncertain_words']), 1)

    def test_coarse_relisten_keeps_segment_timestamps_and_excludes_padding(self):
        segment = SimpleNamespace(words=None, start=0, end=10, text='完整句子', avg_logprob=-.1,
                                  no_speech_prob=.01, compression_ratio=1)
        class Model:
            def transcribe(self, *args, **kwargs):
                assert kwargs['without_timestamps'] is False
                assert kwargs['word_timestamps'] is False
                return iter([segment]), SimpleNamespace(language='zh', language_probability=.99)
        config = {'asr': {'model_path': 'fixture', 'device': 'cpu', 'compute_type': 'int8'}}
        with patch.dict(speech._models, {speech.model_key(config): Model()}), patch('video_reader.speech.run') as ffmpeg:
            result = speech.decode({'metadata': {'duration_seconds': 100}, 'media_path': 'fixture'},
                                   10,20,self.root,config,
                                   '',lambda s: None,precise_words=False)
        command=ffmpeg.call_args.args[0]
        self.assertEqual(command[command.index('-ss')+1],'10')
        self.assertEqual(command[command.index('-t')+1],'10')
        self.assertEqual(result['decoding']['padding_seconds'],0)
        self.assertEqual(result['segments'][0]['alignment'],'segment_estimate')
        self.assertEqual((result['segments'][0]['start'],result['segments'][0]['end']),(10,20))


if __name__ == '__main__':
    unittest.main()
