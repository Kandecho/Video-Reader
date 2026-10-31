"""Platform resolution and media acquisition. No LLM summarization in this layer."""
from __future__ import annotations

import http.cookiejar
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .common import ReaderError, digest, run, write_json
from .vendor.transcribe import normalize_segments, parse_vtt

BV = re.compile(r"BV[a-zA-Z0-9]{10}")


def request_json(url, cookie_path=None):
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
    if cookie_path:
        jar = http.cookiejar.MozillaCookieJar(cookie_path)
        jar.load(ignore_discard=True, ignore_expires=False)
        req = Request(url, headers=headers)
        jar.add_cookie_header(req)
    else:
        req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=25) as response:
            return json.load(response)
    except Exception as exc:
        raise ReaderError(f"Platform request failed: {type(exc).__name__}") from None


def file_identity(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ReaderError(f"File not found: {path}")
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def resolve(source, subtitle_path=None):
    source = source.strip()
    bare = re.fullmatch(r"(BV[a-zA-Z0-9]{10})(?:\?p=(\d+))?", source)
    if bare:
        source = f"https://www.bilibili.com/video/{bare[1]}?p={bare[2] or 1}"
    if source.startswith(("bilibili.com/", "www.bilibili.com/", "b23.tv/", "youtu.be/", "youtube.com/", "www.youtube.com/")):
        source = "https://" + source
    parsed = urlparse(source)
    if parsed.scheme not in ("http", "https"):
        identity = file_identity(source)
        path = Path(identity["path"])
        sidecar = Path(subtitle_path).expanduser().resolve() if subtitle_path else next(
            (p for ext in (".vtt", ".srt", ".json") if (p := path.with_suffix(ext)).is_file()), None)
        if sidecar:
            identity["subtitles"] = file_identity(sidecar)
        return {"platform": "local", "canonical": str(path), "identity": identity,
                "subtitle_path": str(sidecar) if sidecar else None, "title": path.name}
    if not parsed.hostname or parsed.username or parsed.password:
        raise ReaderError("Expected an HTTP(S) video URL without embedded credentials")
    host = parsed.hostname.lower()
    if host == "b23.tv":
        with urlopen(Request(source, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
            target = response.url
        if urlparse(target).hostname not in ("www.bilibili.com", "m.bilibili.com", "bilibili.com"):
            raise ReaderError("Bilibili short link did not resolve to bilibili.com")
        return resolve(target, subtitle_path)
    if host in ("www.bilibili.com", "m.bilibili.com", "bilibili.com"):
        match = BV.search(parsed.path)
        if not match:
            raise ReaderError("Expected a Bilibili BV video URL")
        try:
            page = int(parse_qs(parsed.query).get("p", ["1"])[0])
            if page < 1:
                raise ValueError()
        except ValueError:
            raise ReaderError("Bilibili p must be a positive integer") from None
        canonical = f"https://www.bilibili.com/video/{match[0]}?p={page}"
        result = {"platform": "bilibili", "canonical": canonical, "bvid": match[0], "page": page}
    elif host in ("youtu.be", "www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"):
        video_id = (parsed.path.strip("/") if host == "youtu.be" else
                    parsed.path.split("/")[2] if parsed.path.startswith(("/shorts/", "/live/")) else
                    parse_qs(parsed.query).get("v", [""])[0])
        if not re.fullmatch(r"[\w-]{11}", video_id):
            raise ReaderError("Expected a single YouTube video URL")
        result = {"platform": "youtube", "canonical": f"https://www.youtube.com/watch?v={video_id}", "video_id": video_id}
    else:
        result = {"platform": "generic", "canonical": source}
    result["identity"] = {"canonical": result["canonical"]}
    if subtitle_path:
        result["subtitle_path"] = str(Path(subtitle_path).expanduser().resolve())
        result["identity"]["subtitles"] = file_identity(subtitle_path)
    return result


def choose_caption(info, language="auto"):
    """Prefer requested/source language; never override it with another dubbed original."""
    target = language if language != "auto" else info.get("language")
    youtube = str(info.get("extractor_key", "")).lower().startswith("youtube")
    def matches(key):
        base = key.removesuffix("-orig")
        return target and (base == target or base.split("-")[0] == str(target).split("-")[0])
    available = []
    for kind, tracks in (("manual", info.get("subtitles")), ("automatic", info.get("automatic_captions"))):
        for key, entries in (tracks or {}).items():
            if key != "live_chat" and entries:
                available.append((kind, key))
    if target:
        matched = [a for a in available if matches(a[1])]
        if language != "auto" and not matched:
            return None
        if matched:
            available = matched
    if not available:
        return None
    kind, key = min(available, key=lambda a: (
        a[0] != "manual", not (youtube and a[1].endswith("-orig")),
        a[1].removesuffix("-orig") != target, not a[1].startswith("en"), a[1]))
    return {"kind": kind, "key": key, "language": key.removesuffix("-orig"),
            "provenance": "source-language match" if matches(key) else "language unverified"}


def bilibili_caption_kind(track):
    """AI originals can have ai_type=0; ai-* language tags still identify AI tracks."""
    return "automatic" if str(track.get("lan", "")).startswith("ai-") or track.get("ai_type") else "manual"


def ytdlp_base(profile, directory):
    prefix = str(directory.resolve()).replace("%", "%%")
    args = [sys.executable, "-I", "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-simulate",
            "--js-runtimes", "node",
            "--socket-timeout", "25", "--retries", "2", "--extractor-retries", "1",
            "-o", f"{prefix}/media.%(ext)s", "--no-cookies-from-browser"]
    if profile.get('_network_budget'):
        spec = directory / 'acquisition-budget.json'
        write_json(spec, profile['_network_budget'])
        args = [sys.executable, '-I', str(Path(__file__).with_name('downloader_worker.py')), str(spec), *args[4:]]
    if profile.get("cookies_file"):
        args += ["--cookies", profile["cookies_file"]]
    else:
        args += ["--no-cookies"]
    return args


def acquire(source, directory, profile):
    directory.mkdir(parents=True, exist_ok=True)
    warnings = []
    def platform_json(url, cookie_path=None):
        platform = profile.get('_platform')
        return platform.request(url, ttl=platform.config['preview']['material_ttl_seconds']) if platform else request_json(url, cookie_path)
    if source["platform"] == "local":
        return {"media_path": source["canonical"], "title": source["title"],
                "subtitle_path": source.get("subtitle_path"), "caption_track": None, "warnings": []}
    bili = {}
    if source["platform"] == "bilibili":
        data = platform_json("https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": source["bvid"]}), profile.get("cookies_file"))
        if data.get("code") != 0:
            raise ReaderError(f"Bilibili metadata returned code {data.get('code')}")
        video = data["data"]
        pages = video.get("pages") or []
        index = source["page"] - 1
        if index >= len(pages):
            raise ReaderError(f"Bilibili p={source['page']} is outside 1..{len(pages)}")
        part = pages[index]
        bili = {"cid": part["cid"], "part_title": part.get("part"), "part_count": len(pages), "title": video["title"]}
        owner = video.get('owner') or {}
        bili.update(uploader=owner.get('name'), uploader_id=str(owner['mid']) if owner.get('mid') else None,
                    uploader_url=f"https://space.bilibili.com/{owner['mid']}" if owner.get('mid') else None)
    base = ytdlp_base(profile, directory)
    info = json.loads(run([*base, "--skip-download", "--dump-single-json", "--", source["canonical"]], timeout=150))
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        raise ReaderError("Expected one video; choose a Bilibili part or a single video URL")
    expected_ids = {str(bili.get("cid")), f"{source.get('bvid')}_p{source.get('page')}"}
    if source.get("page") == 1:
        expected_ids.add(source.get("bvid"))
    if bili and str(info.get("id")) not in expected_ids:
        # Current yt-dlp uses BVID_pN; some versions use the selected CID.
        raise ReaderError("Bilibili part mismatch between platform metadata and yt-dlp; refusing wrong media")
    # Signed download URLs are only in this private cache, never returned to the host agent.
    info_path = directory / "download.info.json"
    write_json(info_path, info)
    record = directory / "download-path.jsonl"
    record.unlink(missing_ok=True)
    height = int(profile.get("height", 720))
    run([*base, "--load-info-json", str(info_path), "-f", f"bv*[height<={height}]+ba/b[height<={height}]/b",
         "--merge-output-format", "mp4", "--no-write-subs", "--no-write-auto-subs", "--no-write-info-json",
         "--print-to-file", "after_move:%(filepath)j", str(record).replace("%", "%%")], timeout=1800)
    lines = record.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ReaderError("Downloader did not return exactly one media file")
    media = Path(json.loads(lines[0])).resolve()
    if not media.is_relative_to(directory.resolve()) or not media.is_file() or media.stat().st_size == 0:
        raise ReaderError("Downloader returned an invalid media file")
    subtitle = source.get("subtitle_path")
    track = None
    subtitle_status = "unknown"
    if not subtitle and bili:
        try:
            player = platform_json("https://api.bilibili.com/x/player/wbi/v2?" + urlencode({"bvid": source["bvid"], "cid": bili["cid"]}), profile.get("cookies_file"))
            player_data = player.get("data") or {}
            tracks = player_data.get("subtitle", {}).get("subtitles", [])
            if player.get("code") == -101 or (player_data.get("need_login_subtitle") and not tracks):
                subtitle_status = "login_required"
                warnings.append("BILIBILI_LOGIN_REQUIRED: subtitles require login; call bilibili_login(action=start), then reopen after scanning")
            elif player.get("code") != 0:
                warnings.append(f"Bilibili subtitle API returned code {player.get('code')}")
            lang = profile.get("subtitle_language", "auto")
            if lang != "auto":
                tracks = [t for t in tracks if t.get("lan") == lang]
            if tracks:
                chosen = min(tracks, key=lambda t: (not t.get("lan", "").startswith(("zh", "ai-zh")), bilibili_caption_kind(t) == "automatic"))
                url = chosen["subtitle_url"]
                caption_data = platform_json("https:" + url if url.startswith("//") else url)
                subtitle = str(directory / "bilibili-captions.json")
                write_json(subtitle, {"segments": [{"start": s["from"], "end": s["to"], "text": s["content"]} for s in caption_data["body"]]})
                track = {"kind": bilibili_caption_kind(chosen), "language": chosen.get("lan"), "source": "bilibili", "cid": bili["cid"]}
                subtitle_status = "ready"
        except (ReaderError, KeyError, ValueError) as exc:
            warnings.append(f"Bilibili subtitles unavailable: {type(exc).__name__}")
    if not subtitle:
        track = choose_caption(info, profile.get("subtitle_language", "auto"))
        if track:
            try:
                run([*base, "--load-info-json", str(info_path), "--skip-download", "--no-write-info-json",
                     "--write-subs" if track["kind"] == "manual" else "--write-auto-subs",
                     "--sub-langs", "-all,^" + re.escape(track["key"]) + "$", "--sub-format", "vtt/best", "--convert-subs", "vtt"], timeout=150)
                path = directory / f"media.{track['key']}.vtt"
                if not path.is_file():
                    raise ReaderError("Selected caption file was not produced")
                subtitle = str(path)
            except ReaderError as exc:
                warnings.append(str(exc))
                track = None
    return {"media_path": str(media), "subtitle_path": subtitle, "caption_track": track,
            "title": bili.get("title") or info.get("title"), "platform_metadata": bili,
            "warnings": warnings, "subtitle_status": "ready" if subtitle else subtitle_status}


def load_subtitles(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return list(normalize_segments(data))
    if path.suffix.lower() in (".vtt", ".srt"):
        return parse_vtt(str(path))
    raise ReaderError("Subtitles must be VTT, SRT, or JSON with segments/start/end/text")
