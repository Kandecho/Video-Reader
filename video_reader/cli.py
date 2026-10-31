from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import ReaderError
from .reader import Reader


def parser():
    p = argparse.ArgumentParser(description="Read video as source material for an agent; JSON output")
    p.add_argument("--config")
    sub = p.add_subparsers(dest="command", required=True)
    agent = sub.add_parser('agent', help='Run, inspect or configure the lightweight video agent')
    agent.add_argument('action', choices=('status', 'config', 'candidates', 'preview', 'prepare', 'finish',
                                         'run', 'deliver', 'test-message', 'memory', 'forget', 'tick', 'watch', 'resume',
                                         'batch-start', 'batch-next', 'batch-status', 'batch-retry'))
    agent.add_argument('value', nargs='?', default='')
    agent.add_argument('--query', default='')
    agent.add_argument('--payload', help='UTF-8 JSON settings or host decisions, never executable code')
    agent.add_argument('--offline', action='store_true')
    agent.add_argument('--deliver', action='store_true', help='Allow configured private delivery, otherwise archive only')
    agent.add_argument('--confirm', action='store_true', help='Explicit approval for the first test message')
    agent.add_argument('--kind', choices=('preference', 'feedback', 'observation'), default='observation')
    agent.add_argument('--source', default='')
    agent.add_argument('--poll-seconds', type=float, default=30)
    agent.add_argument('--cursor')
    agent.add_argument('--index', type=int)
    for name in ('search', 'discover'):
        discovery = sub.add_parser(name, help='Find Bilibili video candidates without downloading')
        if name == 'search':
            discovery.add_argument('query')
            discovery.add_argument('--order', choices=('relevance', 'views', 'newest'), default='relevance')
        discovery.add_argument('--page', type=int, default=1)
        discovery.add_argument('--page-size', type=int, default=10)
        discovery.add_argument('--min-duration', type=float, default=0)
        discovery.add_argument('--max-duration', type=float)
        discovery.add_argument('--include-cached', action='store_false', dest='exclude_cached')
    op = sub.add_parser("open", help="Open URL/BV/local file and return the first page of evidence")
    op.add_argument("source")
    op.add_argument("--subtitles")
    op.add_argument('--task', help='The user question or reading purpose; host judges sufficient evidence')
    op.add_argument('--strategy', choices=('adaptive', 'uniform', 'scene', 'dense'), default='adaptive')
    op.add_argument('--include-danmaku', action='store_true')
    uploader = sub.add_parser('uploader-videos', help='List one page of uploader works with component login; UID, space URL or BV')
    uploader.add_argument('source')
    uploader.add_argument('--page', type=int, default=1)
    uploader.add_argument('--offline', action='store_true')
    comments = sub.add_parser('comments', help='Read a Bilibili comment page, or replies with --root ID')
    comments.add_argument('source')
    comments.add_argument('--page', type=int, default=1)
    comments.add_argument('--page-size', type=int, default=20)
    comments.add_argument('--sort', choices=('newest', 'likes', 'replies'), default='newest')
    comments.add_argument('--root')
    comments.add_argument('--offline', action='store_true')
    dm = sub.add_parser('danmaku', help='Read current Bilibili danmaku, one part/segment and bounded text page')
    dm.add_argument('source')
    dm.add_argument('--segment-index', type=int, default=1)
    dm.add_argument('--offset', type=int, default=0)
    dm.add_argument('--limit', type=int, default=100)
    dm.add_argument('--snapshot-id')
    dm.add_argument('--offline', action='store_true')
    for name in ('preview', 'preview-batch'):
        preview = sub.add_parser(name, help='Native snapshots and captions without downloading full media')
        preview.add_argument('sources' if name == 'preview-batch' else 'source', nargs='+' if name == 'preview-batch' else None)
        preview.add_argument('--offline', action='store_true')
        preview.add_argument('--include-comments', action='store_true')
        preview.add_argument('--density', choices=('light', 'dense'), default='light')
        preview.add_argument('--max-frames', type=int)
        preview.add_argument('--contact-sheet', action=argparse.BooleanOptionalAction, default=name == 'preview-batch')
    read = sub.add_parser("read", help="Read timestamped frames and available speech in a video interval")
    read.add_argument("session")
    read.add_argument('--include-danmaku', action='store_true')
    read.add_argument('--danmaku-snapshot-id')
    read.add_argument("--start", default="0")
    read.add_argument("--end")
    read.add_argument("--timestamps", help="Comma-separated source times")
    read.add_argument("--max-frames", type=int)
    read.add_argument("--width", type=int)
    read.add_argument("--page", type=int, default=0)
    read.add_argument('--temporal', action=argparse.BooleanOptionalAction, default=None)
    read.add_argument('--source', choices=('auto', 'captions', 'asr', 'qwen'), default='auto')
    read.add_argument('--verify', action=argparse.BooleanOptionalAction, default=None)
    read.add_argument('--context')
    read.add_argument('--view', choices=('reading', 'evidence', 'raw'), default='reading')
    read.add_argument('--task')
    read.add_argument('--strategy', choices=('adaptive', 'uniform', 'scene', 'dense'), default='adaptive')
    tr = sub.add_parser("transcript", help="Read captions or transcribe local audio, with source timestamps")
    tr.add_argument("session")
    tr.add_argument("--start", default="0")
    tr.add_argument("--end")
    tr.add_argument("--offset", type=int, default=0)
    tr.add_argument("--limit", type=int, default=60)
    tr.add_argument("--no-transcribe", action="store_true")
    tr.add_argument('--source', choices=('auto', 'captions', 'asr', 'qwen'), default='auto')
    tr.add_argument('--verify', action=argparse.BooleanOptionalAction, default=None)
    tr.add_argument('--context')
    tr.add_argument('--view', choices=('reading', 'evidence', 'raw'), default='reading')
    tr.add_argument('--max-chunks', type=int, default=1, help='Decode this many missing chunks then return ready material')
    tr.add_argument('--complete-range', action='store_const', const=None, dest='max_chunks', help='Legacy blocking decode of the entire requested range')
    continuation = sub.add_parser('continue', help='Resume exactly the material named by a persistent cursor')
    continuation.add_argument('session')
    continuation.add_argument('cursor')
    detail = sub.add_parser('frame', help='Expand a returned frame ID using original media pixels')
    detail.add_argument('session')
    detail.add_argument('frame_id')
    detail.add_argument('--width', type=int, default=1920)
    detail.add_argument('--region', nargs=4, type=float, help='Normalized left top right bottom')
    sound = sub.add_parser('sound', help='Measure local levels and quiet/change cues; no semantic sound claims')
    sound.add_argument('session')
    sound.add_argument('--start', default='0')
    sound.add_argument('--end')
    output = sub.add_parser('export', help='Export a selected review revision and portable relative evidence assets')
    output.add_argument('session')
    output.add_argument('destination')
    output.add_argument('--include-danmaku', action='store_true')
    output.add_argument('--revision', type=int, required=True)
    output.add_argument('--source', choices=('auto', 'captions', 'asr', 'qwen'), default='auto')
    output.add_argument('--context')
    output.add_argument('--read-id', action='append', dest='read_ids')
    sub.add_parser('youtube-status', help='Check explicitly configured manual cookies without modifying them')
    review = sub.add_parser('review', help='Prepare/commit host-agent proofreading with source evidence')
    review.add_argument('action', choices=('prepare', 'commit', 'status'))
    review.add_argument('session')
    review.add_argument('--source', choices=('auto', 'captions', 'asr', 'qwen'), default='auto')
    review.add_argument('--offset', type=int, default=0)
    review.add_argument('--limit', type=int, default=60)
    review.add_argument('--context')
    review.add_argument('--start', help='Review only this completed task range; default is the whole source')
    review.add_argument('--end')
    review.add_argument('--payload', help='UTF-8 JSON file for commit; never executed')
    listen = sub.add_parser('relisten', help='Fresh bounded local decoding, saved separately from the baseline')
    listen.add_argument('session')
    listen.add_argument('--start', required=True)
    listen.add_argument('--end', required=True)
    listen.add_argument('--term', action='append', default=[])
    listen.add_argument('--context')
    listen.add_argument('--timeout', type=float, default=60, dest='timeout_seconds')
    listen.add_argument('--precise-words', action='store_true')
    ask = sub.add_parser("cloud-ask", help="Explicitly ask the configured Gemini model about video including sound")
    ask.add_argument("session")
    ask.add_argument("question")
    for name in ("cloud-poll", "cloud-close"):
        sub.add_parser(name).add_argument("session")
    sub.add_parser("doctor", help="Report capabilities without exposing credentials")
    login = sub.add_parser("login", help="Manage this component's independent Bilibili login")
    login.add_argument("action", choices=("start", "poll", "status", "refresh", "logout"))
    login.add_argument("login_id", nargs="?")
    login.add_argument("--wait", type=int, default=0, dest="wait_seconds")
    job = sub.add_parser('job', help='Shared Reader jobs: query without waiting for the media lock')
    job.add_argument('action', choices=('start', 'status', 'result', 'list'))
    job.add_argument('job_id', nargs='?')
    job.add_argument('--operation', choices=('open', 'read', 'transcript'))
    job.add_argument('--payload', help='JSON parameters file for start; material data, never executable code')
    job.add_argument('--wait', type=float, default=0, dest='wait_seconds')
    for command_parser in (op, read, tr):
        command_parser.add_argument('--wait', type=float, default=1, dest='wait_seconds', help='Wait 0..30 seconds, then return shared job state')
    return p


def doctor(reader):
    import importlib.util
    from pathlib import Path
    import shutil
    from . import qwen
    return {"python": sys.version.split()[0], "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
            "python_executable": sys.executable, "python_base": sys.base_prefix,
            "yt_dlp_module": str(importlib.util.find_spec("yt_dlp").origin) if importlib.util.find_spec("yt_dlp") else None,
            "node": shutil.which("node"), "default_reader": reader.config["default_reader"],
            "mcp": bool(importlib.util.find_spec("mcp")), "faster_whisper": bool(importlib.util.find_spec("faster_whisper")),
            "local_ocr": bool(importlib.util.find_spec("rapidocr_onnxruntime")),
            "temporal_text_checks": reader.config.get('vision', {}).get('enabled', True) and bool(importlib.util.find_spec('rapidocr_onnxruntime')),
            "local_model_present": bool(reader.config["asr"].get("model_path") and (Path(reader.config["asr"]["model_path"]) / "model.bin").is_file()),
            "local_model_path": reader.config["asr"].get("model_path"),
            "qwen_assets_present": qwen.available(reader.config),
            "qwen_selection": "Explicit source=qwen, Chinese GPU ASR; availability does not probe CUDA",
            "gemini_enabled": reader.config["gemini"]["enabled"],
            "gemini_key_present": bool(__import__("os").environ.get(reader.config["gemini"]["api_key_env"])),
            "cache_dir": str(reader.cache)}


def main():
    from .vendor.runtime import configure_stdio
    configure_stdio()
    args = parser().parse_args()
    reader = Reader(args.config)
    try:
        if args.command == 'agent':
            from scroll_agent.cli import dispatch
            result = dispatch(reader, args)
        elif args.command in ('search', 'discover'):
            options = {key: getattr(args, key) for key in ('page', 'page_size', 'min_duration', 'max_duration', 'exclude_cached')}
            result = (reader.search(args.query, order=args.order, **options) if args.command == 'search'
                      else reader.discover(**options))
        elif args.command == "login":
            from .bilibili_auth import login_action
            result = login_action(reader.config, args.action, args.login_id, args.wait_seconds)
        elif args.command in ('open', 'read', 'transcript'):
            options = vars(args).copy()
            operation = options.pop('command')
            options.pop('config')
            wait_seconds = options.pop('wait_seconds')
            if operation == 'read' and options.get('timestamps'):
                options['timestamps'] = options['timestamps'].split(',')
            if operation == 'transcript':
                options['transcribe'] = not options.pop('no_transcribe')
            result = reader.job('start', operation=operation, parameters=options, wait_seconds=wait_seconds)
        elif args.command == 'job':
            payload = json.loads(Path(args.payload).read_text(encoding='utf-8-sig')) if args.payload else None
            result = reader.job(args.action, args.job_id, args.operation, payload, args.wait_seconds)
        elif args.command == 'continue':
            result = reader.continue_read(args.session, args.cursor)
        elif args.command == 'frame':
            result = reader.frame(args.session, args.frame_id, args.width, args.region)
        elif args.command == 'sound':
            result = reader.sound(args.session, args.start, args.end)
        elif args.command == 'export':
            result = reader.export(args.session, args.destination, args.revision, args.source, args.context, args.read_ids, args.include_danmaku)
        elif args.command == 'youtube-status':
            from .youtube_auth import status
            result = status(reader.config['platforms']['youtube'])
        elif args.command == 'uploader-videos':
            result = reader.uploader_videos(args.source, args.page, args.offline)
        elif args.command == 'comments':
            result = reader.comments(args.source, args.page, args.page_size, args.sort, args.root, args.offline)
        elif args.command == 'danmaku':
            result = reader.danmaku(args.source, args.segment_index, args.offset, args.limit, args.offline, args.snapshot_id)
        elif args.command in ('preview', 'preview-batch'):
            options = {key: getattr(args, key) for key in ('offline', 'include_comments', 'density', 'max_frames', 'contact_sheet')}
            result = (reader.preview(args.source, **options) if args.command == 'preview'
                      else reader.preview_batch(args.sources, **options))
        elif args.command == 'review':
            from .common import read_json
            result = reader.review(args.session, args.action, source=args.source, offset=args.offset,
                                   limit=args.limit, context=args.context, start=args.start, end=args.end,
                                   payload=read_json(args.payload) if args.payload else None)
        elif args.command == 'relisten':
            result = reader.relisten(args.session, args.start, args.end, terms=args.term,
                                     context=args.context, timeout_seconds=args.timeout_seconds,
                                     precise_words=args.precise_words)
        elif args.command.startswith("cloud-"):
            from .cloud import Cloud
            cloud = Cloud(reader)
            method = args.command.removeprefix("cloud-")
            result = getattr(cloud, method)(args.session, args.question) if method == "ask" else getattr(cloud, method)(args.session)
        else:
            result = doctor(reader)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if result.get('status') in ('failed', 'interrupted'):
            return 1
        return 1 if args.command in ('uploader-videos', 'preview-batch', 'comments', 'danmaku') and result.get('status') not in ('ready', 'closed') else 0
    except (ReaderError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__, "code": getattr(exc, "code", None)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
