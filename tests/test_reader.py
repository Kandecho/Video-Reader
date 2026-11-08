from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from video_reader.common import ReaderError, run, write_json
from video_reader.reader import Reader
from video_reader.sources import acquire, choose_caption, resolve


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("Building short video fixture...", flush=True)
        temp_root = Path(__file__).resolve().parents[1] / ".test-work"
        temp_root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="video-reader-test-", dir=temp_root)
        cls.root = Path(cls.temp.name)
        cls.config = cls.root / "config.json"
        write_json(cls.config, {"cache_dir": str(cls.root / "cache"), "overview_frames": 12,
                               "page_frames": 5, "page_transcript_segments": 2,
                               "asr": {"model_path": None}, 'vision': {'enabled': False}})
        cls.video = cls.root / "text-change.mp4"
        font_path = Path("C:/Windows/Fonts/arial.ttf")
        font = ImageFont.truetype(str(font_path), 64) if font_path.exists() else ImageFont.load_default(size=64)
        for i, text in enumerate(("Deploy checklist step 3", "Confirm payment")):
            image = Image.new("RGB", (1280, 720), "white")
            ImageDraw.Draw(image).text((100, 300), text, font=font, fill="black")
            image.save(cls.root / f"slide-{i}.png")
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", "4", "-i", str(cls.root / "slide-0.png"),
             "-loop", "1", "-t", "4", "-i", str(cls.root / "slide-1.png"), "-filter_complex",
             "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]", "-map", "[v]", "-r", "20",
             "-t", "8", "-threads", "2", "-preset", "ultrafast", str(cls.video)], timeout=30)
        cls.video.with_suffix(".vtt").write_text("WEBVTT\n\n00:00.000 --> 00:03.900\n部署清单\n\n00:04.000 --> 00:06.000\n确认付款\n\n00:06.000 --> 00:08.000\n测试结束\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.reader = Reader(self.config)

    def test_01_source_canonicalization_and_part_identity(self):
        first = resolve("BV1Eb411u7Fw")
        second = resolve("www.bilibili.com/video/BV1Eb411u7Fw?p=2&spm_id_from=x")
        self.assertEqual(first["page"], 1)
        self.assertNotEqual(first["identity"], second["identity"])
        self.assertEqual(second["canonical"], "https://www.bilibili.com/video/BV1Eb411u7Fw?p=2")
        self.assertEqual(resolve("https://youtu.be/jNQXAC9IVRw?t=3")["canonical"],
                         resolve("https://youtube.com/shorts/jNQXAC9IVRw")["canonical"])
        with self.assertRaises(ReaderError):
            resolve("BV1Eb411u7Fw?p=0")

    def test_02_original_caption_language_regression(self):
        info = {"extractor_key": "Youtube", "language": "en-US", "automatic_captions":
                {"ar-orig": [{}], "en-orig": [{}], "en": [{}]}}
        self.assertEqual(choose_caption(info)["key"], "en-orig")
        self.assertIsNone(choose_caption(info, "zh"))

    def test_02b_bilibili_ai_original_with_zero_ai_type(self):
        from video_reader.sources import bilibili_caption_kind
        self.assertEqual(bilibili_caption_kind({"lan": "ai-zh", "ai_type": 0, "ai_status": 2}), "automatic")
        self.assertEqual(bilibili_caption_kind({"lan": "ai-en", "ai_type": 0, "ai_status": 2}), "automatic")
        self.assertEqual(bilibili_caption_kind({"lan": "zh-CN", "ai_type": 0, "ai_status": 0}), "manual")
        self.assertEqual(bilibili_caption_kind({"lan": "en-US", "ai_type": 0}), "manual")

    def test_03_parts_do_not_silently_fall_back(self):
        source = resolve("BV1Eb411u7Fw?p=2")
        metadata = {"code": 0, "data": {"title": "Parts", "pages": [{"cid": 111}, {"cid": 222}]}}
        with patch("video_reader.sources.request_json", return_value=metadata), patch("video_reader.sources.run", return_value='{"id":"111"}'):
            with self.assertRaisesRegex(ReaderError, "mismatch"):
                acquire(source, self.root / "wrong-part", {})
        with patch("video_reader.sources.request_json", return_value=metadata):
            with self.assertRaisesRegex(ReaderError, "outside"):
                acquire(resolve("BV1Eb411u7Fw?p=3"), self.root / "out-of-range", {})

    def test_04_actual_images_text_changes_pagination_and_captions(self):
        first = self.reader.open(str(self.video))
        sid = first["session_id"]
        self.assertEqual(first["visual"]["total_frames"], 12)
        self.assertEqual(first["speech"]["status"], "ready")
        self.assertEqual(first["speech"]["total_segments"], 3)
        self.assertEqual(first["speech"]["next_offset"], 2)
        all_frames = []
        page = 0
        while True:
            result = self.reader.read(sid, page=page)
            all_frames += result["visual"]["frames"]
            if result["visual"]["next_page"] is None:
                break
            page += 1
        self.assertEqual(len(all_frames), 12)  # incomplete last page preserved
        self.assertEqual(len(self.reader.read(sid, page=2)["visual"]["frames"]), 2)
        self.assertTrue(any(f["timestamp_seconds"] < 4 for f in all_frames))
        self.assertTrue(any(f["timestamp_seconds"] >= 4 for f in all_frames))
        hashes = {Image.open(f["path"]).crop((90, 280, 1050, 420)).tobytes() for f in all_frames}
        self.assertGreater(len(hashes), 1)  # second slide was not removed as near-duplicate
        before = [f["path"] for f in all_frames]
        repeated = self.reader.open(str(self.video))
        self.assertTrue(repeated["reused_session"])
        self.assertEqual(repeated["session_id"], sid)
        self.assertEqual(repeated["visual"]["frames"][0]["path"], before[0])
        tail = self.reader.transcript(sid, offset=2)
        self.assertEqual(tail["segments"][0]["text"], "测试结束")
        self.assertIsNone(tail["next_offset"])
        focused = self.reader.read(sid, start=4, end=6, timestamps=[4.25], width=1920)
        frame = focused["visual"]["frames"][0]
        self.assertAlmostEqual(frame["timestamp_seconds"], 4.25, places=2)
        self.assertEqual(frame["requested_timestamp_seconds"], 4.25)

    def test_05_stale_sources_and_invalid_controls(self):
        source = self.root / "mutable.mp4"
        shutil.copyfile(self.video, source)
        opened = self.reader.open(str(source))
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        with self.assertRaisesRegex(ReaderError, "changed"):
            self.reader.read(opened["session_id"])
        self.assertNotEqual(self.reader.open(str(source))["session_id"], opened["session_id"])
        sid = self.reader.open(str(self.video))["session_id"]
        for kwargs in ({"start": "nan"}, {"end": 999}, {"max_frames": 0}, {"timestamps": [8]}, {"page": 100}):
            with self.assertRaises(ReaderError):
                self.reader.read(sid, **kwargs)

    def test_05b_native_youtube_registration_needs_no_download(self):
        with patch("video_reader.sources.acquire", side_effect=AssertionError("must not download")):
            session = self.reader.register_youtube("https://youtu.be/jNQXAC9IVRw")
            self.assertEqual(self.reader.register_youtube("https://www.youtube.com/watch?v=jNQXAC9IVRw"), session)
            self.assertTrue(self.reader.load(session)["native_only"])
            with self.assertRaisesRegex(ReaderError, "native YouTube"):
                self.reader.read(session)

    def test_06_mcp_real_protocol_and_native_images(self):
        async def exercise():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            env = {**os.environ, "VIDEO_READER_CONFIG": str(self.config), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            params = StdioServerParameters(command=sys.executable, args=["-m", "video_reader.mcp_server"], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {"video_open", "video_read", "video_transcript", "video_review", "video_relisten", "bilibili_login", "video_search", "video_discover", "video_preview", "video_uploader_videos", "video_preview_batch", "video_continue", "video_frame", "video_sound", "video_export", "video_youtube_status", "video_comments", "video_danmaku", "video_job", "video_tasks", "video_content"})
                    read_schema = next(tool.inputSchema for tool in tools.tools if tool.name == 'video_read')
                    self.assertTrue({'source', 'context', 'view', 'verify'} <= set(read_schema['properties']))
                    review_schema = next(tool.inputSchema for tool in tools.tools if tool.name == 'video_review')
                    self.assertTrue({'start', 'end'} <= set(review_schema['properties']))
                    invalid_search = await client.call_tool('video_search', {'query': '', 'page': 1})
                    self.assertTrue(invalid_search.isError)
                    invalid_discovery = await client.call_tool('video_discover', {'page': 0})
                    self.assertTrue(invalid_discovery.isError)
                    login = await client.call_tool("bilibili_login", {"action": "status"})
                    self.assertFalse(login.isError)
                    self.assertFalse(json.loads(login.content[0].text)["authenticated"])
                    async def material_tool(name, parameters):
                        result = await client.call_tool(name, parameters)
                        for _ in range(15):
                            if result.isError:
                                return result
                            value = json.loads(result.content[0].text)
                            if 'job_id' not in value:
                                return result
                            if value['status'] in ('failed', 'interrupted'):
                                self.fail(value)
                            result = await client.call_tool('video_job', {'action': 'result',
                                'job_id': value['job_id'], 'wait_seconds': 2})
                        self.fail('Reader job did not finish in 30 seconds')
                    opened = await material_tool("video_open", {"source": str(self.video)})
                    self.assertFalse(opened.isError)
                    self.assertEqual(sum(c.type == "image" for c in opened.content), 5)
                    data = json.loads(opened.content[0].text)
                    prepared = await client.call_tool('video_review', {'session_id': data['session_id'], 'limit': 2})
                    review = json.loads(prepared.content[0].text)
                    committed = await client.call_tool('video_review', {'session_id': data['session_id'], 'action': 'commit',
                        'payload': {'snapshot_id': review['snapshot_id'], 'base_revision': review['base_revision'],
                                    'reviewed_segment_ids': [s['segment_id'] for s in review['segments']]}})
                    self.assertFalse(committed.isError)
                    local = await client.call_tool('video_review', {'session_id': data['session_id'], 'start': '0', 'end': '2'})
                    self.assertFalse(local.isError, local.content)
                    local_page = json.loads(local.content[0].text)
                    self.assertTrue(local_page['scope_review']['source_processed'])
                    scoped_commit = await client.call_tool('video_review', {'session_id': data['session_id'], 'action': 'commit',
                        'payload': {'snapshot_id': local_page['snapshot_id'], 'base_revision': local_page['base_revision'],
                                    'review_scope': local_page['review_scope'],
                                    'reviewed_segment_ids': [s['segment_id'] for s in local_page['segments']]}})
                    self.assertFalse(scoped_commit.isError)
                    self.assertTrue(json.loads(scoped_commit.content[0].text)['scope_review']['complete'])
                    directory = await material_tool('video_content', {'target':data['session_id'],'source':'captions'})
                    self.assertFalse(directory.isError,directory.content)
                    index = json.loads(directory.content[0].text)
                    self.assertTrue(index['index_id'].startswith('ci_'))
                    self.assertTrue(index['blocks'])
                    self.assertEqual(index['binding']['review_revision'],local_page['base_revision']+1)
                    raw_read = await material_tool('video_read', {'session_id': data['session_id'],
                        'source': 'captions', 'view': 'raw', 'verify': False, 'temporal': False})
                    self.assertFalse(raw_read.isError)
                    raw_speech = json.loads(raw_read.content[0].text)['speech']
                    self.assertEqual(raw_speech['source'], 'captions')
                    self.assertEqual(raw_speech['segments'][0]['text_view'], 'raw')
                    self.assertEqual(raw_speech['screen_verification']['mode'], 'off')
                    asr_read = await material_tool('video_read', {'session_id': data['session_id'],
                        'source': 'asr', 'verify': False, 'temporal': False})
                    self.assertFalse(asr_read.isError)
                    self.assertEqual(json.loads(asr_read.content[0].text)['speech']['segments'], [])
                    evidence = await material_tool('video_transcript', {'session_id': data['session_id'], 'view': 'evidence'})
                    self.assertIn('raw_text', json.loads(evidence.content[0].text)['segments'][0])
                    result = await material_tool("video_read", {"session_id": data["session_id"], "page": 2, "strategy": "uniform"})
                    self.assertEqual(sum(c.type == "image" for c in result.content), 2)
                    invalid = await material_tool("video_read", {"session_id": "../invalid"})
                    self.assertTrue(invalid.isError)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main(verbosity=2)
