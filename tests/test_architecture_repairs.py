from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from email.message import Message

from filelock import FileLock

import test_reader as reader_fixtures
from video_reader.common import read_json, write_json
from video_reader.platform import Platform, PlatformError
from video_reader.reader import Reader
from video_reader.sources import resolve


class ControlledShortlinks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'config.json'
        write_json(self.config,{'cache_dir':'cache','preview':{'network':{'min_gap_seconds':0}}})
        self.reader=Reader(self.config)
        self.credentials=patch('video_reader.platform.credentials',return_value={'account_marker':'fixture','cookies':[]})
        self.credentials.start(); self.addCleanup(self.credentials.stop)

    def test_identity_and_offline_preview_never_use_unbudgeted_urlopen(self):
        with patch('video_reader.sources.urlopen',side_effect=AssertionError('unexpected network')):
            self.assertTrue(resolve('https://b23.tv/AbC')['shortlink'])
            with self.assertRaisesRegex(PlatformError,'offline_cache_miss'):
                self.reader.preview('https://b23.tv/AbC',offline=True)

    def test_redirect_uses_account_budget_pause_and_offline_cache(self):
        transport=Mock(return_value=b'{"code":0,"target":"https://www.bilibili.com/video/BV1E1421t7m2?p=2"}')
        platform=Platform(self.reader.config,transport=transport)
        target=platform.resolve_shortlink('https://b23.tv/AbC')
        self.assertIn('p=2',target)
        self.assertEqual(read_json(platform.state_path)['count'],1)
        offline=Platform(self.reader.config,offline=True,transport=Mock(side_effect=AssertionError('offline')))
        self.assertEqual(offline.resolve_shortlink('https://b23.tv/AbC'),target)
        state=read_json(platform.state_path); state['paused']='412'; write_json(platform.state_path,state)
        with self.assertRaisesRegex(PlatformError,'platform_paused'):
            platform.resolve_shortlink('https://b23.tv/Other')
        self.assertEqual(transport.call_count,1)

    def test_redirect_target_is_inspected_without_following_it(self):
        platform=Platform(self.reader.config)
        headers=Message(); headers['Location']='https://evil.example/video/BV1E1421t7m2'
        platform.opener=Mock()
        platform.opener.open.side_effect=HTTPError('https://b23.tv/AbC',302,'Found',headers,None)
        with self.assertRaisesRegex(PlatformError,'untrusted_shortlink_target'):
            platform.resolve_shortlink('https://b23.tv/AbC')
        self.assertEqual(platform.opener.open.call_count,1)


class InitialAndDetailReading(unittest.TestCase):
    setUpClass=classmethod(reader_fixtures.ReaderTests.setUpClass.__func__)
    tearDownClass=classmethod(reader_fixtures.ReaderTests.tearDownClass.__func__)

    def setUp(self):
        self.reader=Reader(self.config)

    def test_initial_open_is_readable_without_deep_ocr(self):
        self.reader.config['vision']['enabled']=True
        with patch('video_reader.vision.annotate_frame',side_effect=AssertionError('deep OCR')), \
             patch('video_reader.vision._frame_at',side_effect=AssertionError('speech OCR')):
            result=self.reader.open(str(self.video))
        self.assertEqual(result['inspection']['mode'],'initial')
        self.assertTrue(result['visual']['frames'])
        self.assertTrue(result['speech']['segments'])

    def test_frame_inspection_does_not_wait_for_long_session_work_and_survives_save(self):
        result=self.reader.open(str(self.video))
        session=result['session_id']; frame=result['visual']['frames'][0]
        old=self.reader.load(session)
        lock=FileLock(str(self.reader.directory(session)/'.lock'))
        with ThreadPoolExecutor(max_workers=1) as executor:
            lock.acquire()
            try:
                future=executor.submit(self.reader.frame,session,frame['id'],1920)
                detail=future.result(timeout=4)
            finally:
                lock.release()
        self.reader.save(old)  # A long-running caller commits a pre-detail snapshot.
        loaded=self.reader.load(session)
        detail_id=detail['visual']['frames'][0]['id'].split(':')[0]
        self.assertTrue(any(r['id']==detail_id for r in loaded['reads']))
        self.assertEqual(self.reader.frame(session,frame['id'],1920)['visual']['frames'],detail['visual']['frames'])
