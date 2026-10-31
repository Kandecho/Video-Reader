"""Migration acceptance check: local evidence with HTTP disabled and no project config discovery."""
from pathlib import Path
import hashlib
import json
import os
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from video_reader.cli import doctor
from video_reader.common import write_json
from video_reader.reader import Reader

report = {"version": "0.2.0", "root": str(ROOT), "started_at": time.time(),
          "network_disabled_in_check": True, "cwd": str(Path.cwd())}
try:
    reader = Reader()
    report["capabilities"] = doctor(reader)
    assert reader.config["default_reader"] == "local"
    assert reader.config["gemini"]["enabled"] is False
    assert Path(reader.config["asr"]["model_path"]).is_relative_to(ROOT)
    assert Path(sys.executable).is_relative_to(ROOT)
    from importlib import metadata
    package_roots = {str(Path(d.locate_file("")).resolve()) for d in metadata.distributions()}
    assert all(Path(p).is_relative_to(ROOT) for p in package_roots), package_roots
    report["python_package_roots"] = sorted(package_roots)
    provenance = json.loads((ROOT / "models/faster-whisper-medium/model-provenance.json").read_text(encoding="utf-8"))
    model = ROOT / "models/faster-whisper-medium/model.bin"
    with model.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    expected_hash = next(f["sha256"] for f in provenance["files"] if f["name"] == "model.bin")
    assert actual_hash == expected_hash
    assert not model.is_symlink()
    report["model_hash_matches"] = True
    # Block every network connection for this check. FFmpeg is invoked on local files only.
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network must not be used for local reading")):
        start = time.monotonic()
        opened = reader.open(str(ROOT / "examples/synthetic-av.mp4"))
        report["open_seconds"] = round(time.monotonic()-start, 3)
        report["local_session"] = opened["session_id"]
        start = time.monotonic()
        speech = reader.transcript(opened["session_id"])
        report["speech_seconds"] = round(time.monotonic()-start, 3)
        report["speech"] = speech
        assert "confirm payment" in " ".join(s["text"].lower() for s in speech["segments"])
        focus = reader.read(opened["session_id"], timestamps=[9.3], width=1280)
        frame = focus["visual"]["frames"][0]
        with Image.open(frame["path"]) as image:
            rgb = image.convert("RGB")
            yellow_pixels = sum(1 for r, g, b in rgb.getdata() if r > 180 and g > 180 and b < 70)
        assert yellow_pixels > 10000
        assert frame["timestamp_seconds"] == 9.3
        report["focused_frame"] = frame
        report["yellow_pixel_count"] = yellow_pixels
        repeated = reader.open(str(ROOT / "examples/synthetic-av.mp4"))
        assert repeated["reused_session"]
        cached_bili = reader.open("BV1Eb411u7Fw?p=4")
        assert cached_bili["reused_session"]
        assert cached_bili["platform_metadata"]["cid"] == 122455108
        assert all(Path(f["path"]).is_relative_to(ROOT) for f in cached_bili["visual"]["frames"])
        cached_speech = reader.transcript(cached_bili["session_id"], 20, 35)
        assert cached_speech["status"] == "ready"
        report["migrated_bilibili_cache"] = {"session_id": cached_bili["session_id"], "cid": 122455108,
                                             "reused": True, "speech_segments": len(cached_speech["segments"])}
    report["status"] = "passed"
except Exception as exc:
    report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    raise
finally:
    report["finished_at"] = time.time()
    write_json(ROOT / "validation/local-migration.json", report)
    print(json.dumps(report, ensure_ascii=True, indent=2))
