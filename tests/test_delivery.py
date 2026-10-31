import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from PIL import Image

from video_reader import delivery, review
from video_reader.common import ReaderError, read_json, write_json
from video_reader.reader import Reader
import test_foundations as foundations


class DeliveryTests(unittest.TestCase):
    setUp = foundations.SpeechCoverageTests.setUp
    tearDown = foundations.SpeechCoverageTests.tearDown
    record = foundations.SpeechCoverageTests.record
    decode = foundations.SpeechCoverageTests.decode

    def captions(self, segments):
        self.data['speech'] = [{'start': 0, 'end': 300, 'source': 'captions', 'status': 'ready',
                                'track': {'kind': 'manual'}, 'segments': segments}]
        self.reader.save(self.data)

    def test_long_unicode_single_segment_and_all_word_evidence_round_trip(self):
        text = '中文🙂\\\n"/路径  ' * 4000
        self.captions([{'start': 0, 'end': 300, 'text': text,
            'words': [{'word': '证据', 'start': i/10, 'end': (i+1)/10} for i in range(2500)]}])
        first = self.reader.transcript(self.sid, source='captions', view='evidence', verify=False)
        saved = read_json(self.reader.directory(self.sid) / 'deliveries' / (first['delivery']['snapshot_id'] + '.json'))
        parts, result, pages = [], first, 0
        while True:
            self.assertLessEqual(len(delivery.encoded(result)), 24000)
            parts.extend(result.get('material_parts', []))
            pages += 1
            cursor = result['delivery']['next_cursor']
            if not cursor:
                break
            # Simulate restarting the process with only the persisted cursor.
            result = Reader(self.reader.config_path).continue_read(self.sid, cursor)
        self.assertGreater(pages, 3)
        restored = delivery.restore(parts)
        self.assertEqual(restored, saved['result'])
        self.assertEqual(restored['segments'][0]['text'], text)
        self.assertEqual(len(restored['segments'][0]['words']), 2500)
        spans = [p for p in parts if p.get('pointer') == '/segments/0/text']
        self.assertTrue(all(p['segment_id'] and p['start'] == 0 and p['end'] == 300 for p in spans))

    def test_cursor_rejects_new_review_and_foreign_video(self):
        self.captions([{'start': i, 'end': i+1, 'text': str(i)} for i in range(3)])
        first = self.reader.transcript(self.sid, limit=1, verify=False)
        cursor = first['delivery']['next_cursor']
        prepared = self.reader.review(self.sid)
        self.reader.review(self.sid, 'commit', payload={'snapshot_id': prepared['snapshot_id'],
            'base_revision': 0, 'reviewed_segment_ids': [prepared['segments'][0]['segment_id']]})
        with self.assertRaisesRegex(ReaderError, 'changed'):
            self.reader.continue_read(self.sid, cursor)
        with self.assertRaisesRegex(ReaderError, 'not found'):
            self.reader.continue_read('v_' + 'b'*24, cursor)
        frozen = self.reader.continue_read(self.sid, first['delivery']['snapshot_id'] + ':0')
        self.assertEqual(frozen['review']['revision'], 0)

    def test_byte_sized_pages_keep_normal_segments_and_do_not_skip_tail(self):
        self.captions([{'start': i, 'end': i+1, 'text': '字' * 700} for i in range(50)])
        result = self.reader.transcript(self.sid, limit=50, verify=False)
        seen = []
        while True:
            self.assertNotIn('material_parts', result)
            self.assertLessEqual(len(delivery.encoded(result)), 24000)
            seen.extend(s['start'] for s in result['segments'])
            if not result['delivery']['next_cursor']:
                break
            result = self.reader.continue_read(self.sid, result['delivery']['next_cursor'])
        self.assertEqual(seen, list(range(50)))

    def test_incremental_asr_returns_ready_chunks_and_only_decodes_gaps(self):
        with patch('video_reader.speech.decode', side_effect=self.decode) as decoder:
            first = self.reader.transcript(self.sid, source='asr', max_chunks=1, verify=False)
            self.assertEqual(decoder.call_count, 1)
            self.assertEqual(first['status'], 'partial')
            self.assertEqual(len(first['segments']), 1)
            self.assertEqual(first['coverage']['missing_ranges'], [[120, 300]])
            second = self.reader.transcript(self.sid, source='asr', max_chunks=1, verify=False)
            self.assertEqual(second['coverage']['missing_ranges'], [[240, 300]])
            final = self.reader.transcript(self.sid, source='asr', max_chunks=1, verify=False)
            self.assertTrue(final['coverage']['complete'])
            self.assertEqual([call.args[1:3] for call in decoder.call_args_list], [(0, 120), (120, 240), (240, 300)])

    def test_paging_ready_material_does_not_decode_more(self):
        self.data['speech'] = [self.record(0, 120), self.record(120, 240)]
        self.reader.save(self.data)
        first = self.reader.transcript(self.sid, limit=1, source='asr', transcribe=False, verify=False)
        with patch('video_reader.speech.decode', side_effect=AssertionError('paging must not decode')):
            second = self.reader.continue_read(self.sid, first['delivery']['next_cursor'])
        self.assertEqual(len(second['segments']), 1)
        self.assertEqual(second['segments'][0]['start'], 120.1)
        self.assertFalse(second['coverage']['complete'])

    def test_old_review_export_is_relative_and_survives_move(self):
        self.captions([{'start': 1, 'end': 2, 'text': 'version won'}])
        directory = self.reader.directory(self.sid)
        frame = self.root / 'owned external frames' / 'image.jpg'
        frame.parent.mkdir()
        Image.new('RGB', (64, 64), 'blue').save(frame)
        self.data['reads'] = [{'id': 'fixture', 'start': 0, 'end': 300,
            'frames': [{'id': 'fixture:0', 'path': str(frame), 'timestamp_seconds': 1.0, 'time': '00:01.000'}]}]
        self.reader.save(self.data)
        prepared = self.reader.review(self.sid)
        segment = prepared['segments'][0]
        payload = {'snapshot_id': prepared['snapshot_id'], 'base_revision': 0,
            'corrections': [{'segment_id': segment['segment_id'], 'original': 'version won',
                'corrected_text': 'version one', 'reason': 'frame corroborates spelling',
                'evidence': [{'kind': 'frame', 'path': str(frame)}]}]}
        self.reader.review(self.sid, 'commit', payload=payload)
        payload = copy.deepcopy(payload)
        payload['base_revision'] = 1
        payload['corrections'][0]['corrected_text'] = 'version won'
        self.reader.review(self.sid, 'commit', payload=payload)
        artifact = self.root / 'export 中文'
        result = self.reader.export(self.sid, str(artifact), revision=1)
        moved = self.root / 'moved folder'
        shutil.move(str(artifact), str(moved))
        record = read_json(moved / 'evidence.json')
        self.assertEqual(record['segments'][0]['text'], 'version one')
        self.assertEqual(record['segments'][0]['raw_text'], 'version won')
        image_path = record['segments'][0]['correction']['evidence'][0]['path']
        self.assertFalse(Path(image_path).is_absolute())
        self.assertTrue((moved / image_path).is_file())
        self.assertNotIn(str(directory).replace('\\', '\\\\'), (moved / 'evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(review.state(directory, prepared['snapshot_id'])['revision'], 2)
        self.assertEqual(result['revision'], 1)


if __name__ == '__main__':
    unittest.main()
