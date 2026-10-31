import copy
import unittest
from unittest.mock import patch

import test_foundations
from video_reader import review, speech
from video_reader.common import ReaderError


class TaskReviewTests(unittest.TestCase):
    setUp = test_foundations.SpeechCoverageTests.setUp
    tearDown = test_foundations.SpeechCoverageTests.tearDown
    record = test_foundations.SpeechCoverageTests.record
    decode = test_foundations.SpeechCoverageTests.decode
    def prepared(self):
        self.data['speech'] = [self.record(0, 120)]
        self.reader.save(self.data)
        return self.reader.review(self.sid, source='asr', start=0, end=120)

    def payload(self, page):
        segment = page['segments'][0]
        return {'snapshot_id': page['snapshot_id'], 'base_revision': page['base_revision'],
                'review_scope': page['review_scope'],
                'reviewed_segment_ids': [segment['segment_id']],
                'corrections': [{'segment_id': segment['segment_id'], 'original': segment['original'],
                    'corrected_text': 'corrected chunk 0', 'reason': 'fixture source evidence',
                    'evidence': [{'kind': 'title'}]}]}

    def test_range_review_survives_more_asr_and_does_not_claim_full_review(self):
        page = self.prepared()
        result = self.reader.review(self.sid, 'commit', source='asr', payload=self.payload(page))
        self.assertTrue(result['scope_review']['complete'])
        self.assertFalse(result['review']['complete'])
        with patch('video_reader.speech.decode', side_effect=self.decode):
            result = self.reader.transcript(self.sid, source='asr', verify=False)
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(result['segments'][0]['text'], 'corrected chunk 0')
        self.assertEqual(result['segments'][0]['review_status'], 'reviewed')
        self.assertEqual(result['segments'][1]['review_status'], 'pending')
        self.assertFalse(result['review']['complete'])
        self.assertEqual(result['review']['snapshot_id'], page['snapshot_id'])
        self.assertEqual(self.reader.transcript(self.sid, source='asr', view='raw', verify=False)['segments'][0]['text'], 'chunk 0')
        full = self.reader.review(self.sid, source='asr')
        self.reader.review(self.sid, 'commit', source='asr', payload={
            'snapshot_id': full['snapshot_id'], 'base_revision': full['base_revision'],
            'reviewed_segment_ids': [s['segment_id'] for s in full['segments']]})
        self.assertTrue(self.reader.review(self.sid, 'status', source='asr')['review']['complete'])

    def test_scope_rejects_missing_processing_outside_edits_and_changed_material(self):
        page = self.prepared()
        with self.assertRaisesRegex(ReaderError, 'range'):
            self.reader.review(self.sid, source='asr', start=0, end=121)
        data = self.reader.load(self.sid)
        data['speech'].append(self.record(120, 240))
        self.reader.save(data)
        outside = self.reader.transcript(self.sid, source='asr', transcribe=False, verify=False)['segments'][1]
        payload = self.payload(page)
        payload['reviewed_segment_ids'].append(outside['segment_id'])
        with self.assertRaisesRegex(ReaderError, 'segment'):
            self.reader.review(self.sid, 'commit', source='asr', payload=payload)
        data['speech'][0]['segments'][0]['text'] = 'changed raw'
        self.reader.save(data)
        with self.assertRaisesRegex(ReaderError, 'material changed'):
            self.reader.review(self.sid, 'commit', source='asr', payload=self.payload(page))

    def test_review_paging_and_raw_change_cursor_protection(self):
        page = self.prepared()
        payload = self.payload(page)
        self.reader.review(self.sid, 'commit', source='asr', payload=payload)
        data = self.reader.load(self.sid)
        data['speech'].append(self.record(120, 240))
        self.reader.save(data)
        first = self.reader.transcript(self.sid, source='asr', limit=1, transcribe=False, verify=False)
        data['speech'].append(self.record(240, 300))
        self.reader.save(data)
        with self.assertRaisesRegex(ReaderError, 'Material changed'):
            self.reader.continue_read(self.sid, first['delivery']['next_cursor'])
        frozen = self.reader.continue_read(self.sid, first['delivery']['snapshot_id'] + ':0')
        self.assertEqual(frozen['segments'], first['segments'])

    def test_no_title_prompt_but_explicit_hints_and_legacy_review_preserved(self):
        with patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            self.reader.transcript(self.sid, start=0, end=20, source='asr', verify=False)
        self.assertEqual(decoder.call_args.args[5], '')
        self.data['speech'] = [self.record(0, 300, context='Subject')]
        self.reader.save(self.data)
        legacy = self.reader.review(self.sid, source='asr')
        self.reader.review(self.sid, 'commit', source='asr', payload={
            'snapshot_id': legacy['snapshot_id'], 'base_revision': 0,
            'reviewed_segment_ids': [s['segment_id'] for s in legacy['segments']]})
        with patch('video_reader.speech.decode', side_effect=AssertionError('reuse legacy')):
            reused = self.reader.transcript(self.sid, source='asr', verify=False)
        self.assertTrue(reused['review']['complete'])
        with patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            self.reader.transcript(self.sid, start=0, end=20, source='asr', context='', verify=False)
        self.assertEqual(decoder.call_args.args[5], '')
        self.assertTrue(self.reader.transcript(self.sid, source='asr', context='Subject', verify=False)['review']['complete'])
        with patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            self.reader.transcript(self.sid, start=0, end=20, source='asr', context='Explicit hint', verify=False)
        self.assertEqual(decoder.call_args.args[5], 'Explicit hint')

    def test_legacy_partial_new_decoding_does_not_inject_old_title(self):
        self.data['speech'] = [self.record(0, 120, context='Subject')]
        self.reader.save(self.data)
        with patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            self.reader.transcript(self.sid, start=120, end=140, source='asr', verify=False)
        self.assertEqual(decoder.call_args.args[5], '')
        self.assertEqual(len(self.reader.load(self.sid)['speech']), 2)
