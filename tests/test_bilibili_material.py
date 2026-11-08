"""Shared caption translation preserves source wording, identity and selection rules."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from video_reader.bilibili_material import captions
from video_reader.common import read_json
from video_reader.platform import PlatformError
from video_reader.preview import preview
from video_reader.sources import acquire, resolve


class CaptionMaterialTests(unittest.TestCase):
    def tracks(self):
        return [{'lan': 'en', 'subtitle_url': '//i0.hdslb.com/en.json'},
                {'lan': 'ai-zh', 'ai_type': 0, 'subtitle_url': '//i0.hdslb.com/ai.json'},
                {'lan': 'zh-CN', 'subtitle_url': '//i0.hdslb.com/manual.json'}]

    def test_auto_and_explicit_language_preserve_timed_source_text_and_part(self):
        raw = [{'from': 1.25, 'to': 3, 'content': '原文\n原文'},
               {'from': 3, 'to': 4, 'content': '原文\n原文'}]
        for language, selected in (('auto', 'manual.json'), ('en', 'en.json'), ('ai-zh', 'ai.json')):
            request = Mock(side_effect=[{'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}}, {'body': raw}])
            with self.subTest(language=language):
                result = captions(request, 'BV0000000001', 42, language, strict=True)
                self.assertEqual(result['status'], 'ready')
                self.assertEqual(result['segments'], [{'start': item['from'], 'end': item['to'], 'text': item['content']} for item in raw])
                self.assertEqual(result['track']['cid'], 42)
                self.assertEqual(result['track']['kind'], 'automatic' if language == 'ai-zh' else 'manual')
                self.assertEqual(parse_qs(urlparse(request.call_args_list[0].args[0]).query)['cid'], ['42'])
                self.assertTrue(request.call_args_list[1].args[0].endswith(selected))

    def test_missing_requested_language_never_substitutes_another_track(self):
        request = Mock(return_value={'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}})
        self.assertEqual(captions(request, 'BV0000000001', 42, 'ja'), {'status': 'unavailable'})
        self.assertEqual(request.call_count, 1)

    def test_login_gap_and_empty_candidate_are_not_fabricated_speech(self):
        request = Mock(return_value={'code': 0, 'data': {'need_login_subtitle': True}})
        self.assertEqual(captions(request, 'BV0000000001', 42)['status'], 'login_required')
        request = Mock(side_effect=[{'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}}, {'body': []}])
        self.assertEqual(captions(request, 'BV0000000001', 42)['segments'], [])

    def test_legacy_player_warning_does_not_discard_an_explicit_available_track(self):
        request = Mock(side_effect=[{'code': -101, 'data': {'subtitle': {'subtitles': self.tracks()}}},
                                    {'body': [{'from': 0, 'to': 1, 'content': 'available original'}]}])
        result = captions(request, 'BV0000000001', 42, 'en', strict=True)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['requires_login'])
        self.assertEqual(result['code'], -101)
        self.assertEqual(result['segments'][0]['text'], 'available original')

    def test_full_acquisition_keeps_strict_body_requirement(self):
        responses = [{'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}}, {}]
        with self.assertRaises(KeyError):
            captions(Mock(side_effect=responses), 'BV0000000001', 42, strict=True)
        preview = captions(Mock(side_effect=responses), 'BV0000000001', 42)
        self.assertEqual(preview['segments'], [])

    def test_full_download_uses_shared_explicit_track_without_changing_raw_words(self):
        parent = Path(__file__).resolve().parents[1] / '.test-work'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            directory = Path(temporary)
            info = {'code': 0, 'data': {'title': 'Source', 'pages': [{'cid': 11}, {'cid': 42}]}}
            player = {'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}}
            body = {'body': [{'from': 1, 'to': 2.5, 'content': '原文 without changes'}]}

            def run(command, **options):
                if '--dump-single-json' in command:
                    return json.dumps({'id': '42', 'title': 'Source'})
                record = Path(command[command.index('--print-to-file') + 2])
                media = directory / 'media.mp4'
                media.write_bytes(b'fixture media, decoding is outside this test')
                record.write_text(json.dumps(str(media)) + '\n', encoding='utf-8')
                return ''

            with patch('video_reader.sources.run', side_effect=run), \
                    patch('video_reader.sources.request_json', side_effect=[info, player, body]) as request:
                result = acquire(resolve('BV0000000001?p=2'), directory, {'subtitle_language': 'en'})
            self.assertTrue(request.call_args.args[0].endswith('/en.json'))
            self.assertEqual(result['caption_track'], {'language': 'en', 'kind': 'manual', 'source': 'bilibili', 'cid': 42})
            self.assertEqual(read_json(result['subtitle_path'])['segments'],
                             [{'start': 1, 'end': 2.5, 'text': '原文 without changes'}])

    def test_preview_uses_shared_track_but_keeps_its_unreviewed_material_semantics(self):
        parent = Path(__file__).resolve().parents[1] / '.test-work'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            platform = Mock(root=Path(temporary), offline=False)
            platform.config = {'preview': {'material_ttl_seconds': 600}}
            platform.json.return_value = {'title': 'Source', 'pages': [{'cid': 42, 'duration': 5}]}
            platform.request.side_effect = [
                {'code': 0, 'data': {'subtitle': {'subtitles': self.tracks()}}},
                {'body': [{'from': 1, 'to': 2.5, 'content': '原文 without changes'}]}]
            with patch('video_reader.preview.snapshot_material', side_effect=PlatformError('fixture_no_snapshot')):
                result = preview(platform, 'BV0000000001')
            self.assertEqual(result['caption']['segments'], [{'start': 1, 'end': 2.5, 'text': '原文 without changes'}])
            self.assertEqual(result['caption']['language'], 'zh-CN')
            self.assertFalse(result['caption']['proofread'])
            self.assertEqual(result['reading_status'], 'previewed_not_read')


if __name__ == '__main__':
    unittest.main()
