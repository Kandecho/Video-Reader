import copy
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from PIL import Image

from video_reader.common import ReaderError
import test_foundations as foundations


class SourceFrameTests(unittest.TestCase):
    setUp = foundations.SpeechCoverageTests.setUp
    tearDown = foundations.SpeechCoverageTests.tearDown

    def video(self):
        self.data['metadata'].update(has_video=True, width=320, height=180)
        self.reader.save(self.data)

    def extract(self, media, output, timestamps, **options):
        output.mkdir(parents=True, exist_ok=True)
        path = output / 'original.jpg'
        Image.new('RGB', (320, 180), 'blue').save(path)
        return [{'index': 0, 'path': str(path), 'timestamp_seconds': timestamps[0]}], {}

    def test_source_pixels_without_speech_are_cached_and_frame_addressable(self):
        self.video()
        original = copy.deepcopy(self.reader.load(self.sid))
        with (patch('video_reader.frame_detail.frames.extract_at_timestamps', side_effect=self.extract) as extract,
                patch.object(self.reader, '_speech', side_effect=AssertionError('no speech'))):
            first = self.reader.source_frames(self.sid, [{'timestamp_seconds': 12.5}])
            again = self.reader.source_frames(self.sid, [{'timestamp_seconds': 12.5}])
            self.assertEqual(first, again)
            self.assertEqual(extract.call_count, 1)
            source = first['frames'][0]
            self.assertEqual(source['source_time'], 12.5)
            self.assertEqual(source['asset_sha256'], hashlib.sha256(Path(source['path']).read_bytes()).hexdigest())
            detail = self.reader.frame(self.sid, source['id'], width=1920)
            self.assertEqual(detail['visual']['frames'][0]['parent_frame_id'], source['id'])
        after = self.reader.load(self.sid)
        for field in ('source', 'speech', 'authentication'):
            self.assertEqual(original.get(field), after.get(field))

    def test_crop_and_concurrent_requests_share_stable_source_identity(self):
        self.video()
        request = [{'timestamp_seconds': 10, 'region': [.25, .25, .75, .75], 'width': 1280}]
        with patch('video_reader.frame_detail.frames.extract_at_timestamps', side_effect=self.extract) as extract:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(lambda _: self.reader.source_frames(self.sid, request), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(extract.call_count, 1)
        frame = first['frames'][0]
        self.assertEqual(frame['region'], [.25, .25, .75, .75])
        self.assertEqual((frame['width'], frame['height']), (160, 90))

    def test_invalid_boundaries_and_unknown_fields_do_not_extract(self):
        self.video()
        invalid = [[], [{}], [{'timestamp_seconds': 2}] * 7, [{'timestamp_seconds': True}],
            [{'timestamp_seconds': float('nan')}], [{'timestamp_seconds': float('inf')}],
            [{'timestamp_seconds': -1}], [{'timestamp_seconds': 300}],
            [{'timestamp_seconds': '2'}], [{'timestamp_seconds': 2, 'width': 63}],
            [{'timestamp_seconds': 2, 'width': True}], [{'timestamp_seconds': 2, 'path': 'anything'}],
            [{'timestamp_seconds': 2, 'region': [0, 0, 1, True]}],
            [{'timestamp_seconds': 2, 'region': [.9, 0, .1, 1]}]]
        with patch('video_reader.frame_detail.frames.extract_at_timestamps') as extract:
            for request in invalid:
                with self.subTest(request=request), self.assertRaises(ReaderError):
                    self.reader.source_frames(self.sid, request)
            extract.assert_not_called()

    def test_changed_account_pixels_and_nonvideo_fail(self):
        self.video()
        with patch('video_reader.frame_detail.frames.extract_at_timestamps', side_effect=self.extract):
            first = self.reader.source_frames(self.sid, [{'timestamp_seconds': 10}])
        Path(first['frames'][0]['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ReaderError, 'pixels changed'):
            self.reader.source_frames(self.sid, [{'timestamp_seconds': 10}])
        with patch('video_reader.catalog.account_scope', return_value='other'):
            with self.assertRaisesRegex(ReaderError, 'another account'):
                self.reader.source_frames(self.sid, [{'timestamp_seconds': 20}])
        self.data['metadata']['has_video'] = False
        self.reader.save(self.data)
        with self.assertRaisesRegex(ReaderError, 'video stream'):
            self.reader.source_frames(self.sid, [{'timestamp_seconds': 20}])


if __name__ == '__main__':
    unittest.main()
