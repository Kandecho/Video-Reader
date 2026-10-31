import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_reader.cloud import Cloud
from video_reader.common import write_json
from video_reader.reader import Reader


class CloudStateTests(unittest.TestCase):
    def test_background_id_and_video_context_survive_restart(self):
        root = Path(__file__).resolve().parents[1] / ".test-work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            config = Path(directory) / "config.json"
            write_json(config, {"cache_dir": str(Path(directory) / "cache"), "gemini": {"enabled": True}})
            reader = Reader(config)
            with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
                cloud = Cloud(reader)
                with patch.object(cloud, "_request", return_value={"id": "first", "status": "in_progress"}) as request:
                    first = cloud.ask("https://youtu.be/jNQXAC9IVRw", "What is visible?")
                    self.assertEqual(first["next_tool"], "video_cloud_poll")
                    self.assertEqual(request.call_args.args[2]["input"][0]["uri"], "https://www.youtube.com/watch?v=jNQXAC9IVRw")
                restarted = Cloud(Reader(config))
                with patch.object(restarted, "_request", return_value={"id": "first", "status": "completed", "steps": [
                        {"type": "model_output", "content": [{"type": "text", "text": "At 00:01, an elephant."}]}]}) as request:
                    result = restarted.poll(first["session_id"])
                    self.assertTrue(request.call_args.args[1].endswith("/first"))
                    self.assertIn("elephant", result["answer"])
                with patch.object(restarted, "_request", return_value={"id": "second", "status": "in_progress"}) as request:
                    restarted.ask(first["session_id"], "What did he say?")
                    payload = request.call_args.args[2]
                    self.assertEqual(payload["previous_interaction_id"], "first")
                    self.assertEqual([p["type"] for p in payload["input"]], ["text"])

    def test_cloud_disabled_even_if_a_key_exists(self):
        root = Path(__file__).resolve().parents[1] / ".test-work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            config = Path(directory) / "config.json"
            write_json(config, {"cache_dir": str(Path(directory) / "cache")})
            with patch.dict("os.environ", {"GEMINI_API_KEY": "must-not-be-used"}):
                from video_reader.common import ReaderError
                with self.assertRaisesRegex(ReaderError, "Gemini is disabled"):
                    Cloud(Reader(config))


if __name__ == "__main__":
    unittest.main()
