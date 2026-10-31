from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
import time
import uuid

from filelock import FileLock

from . import sources, speech as speech_engine
from .common import ReaderError, UNTRUSTED, configuration_path, digest, read_json, settings, stamp, write_json
from .vendor import frames
from .delivery import delivered
from .jobs import Jobs, report, session_lock

def _watch_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SystemExit as exc:
        raise ReaderError(str(exc)) from None


class Reader:
    def __init__(self, config_path=None):
        self.config_path = configuration_path(config_path)
        self.config = settings(config_path)
        self.cache = Path(self.config["cache_dir"])
        self.cache.mkdir(parents=True, exist_ok=True)

    def job(self, action='status', job_id=None, operation=None, parameters=None, wait_seconds=0):
        store = Jobs(self)
        if action == 'start':
            return store.start(operation, parameters, wait_seconds)
        if action == 'list':
            return store.list()
        if action == 'status':
            return store.status(job_id)
        if action == 'result':
            return store.result(job_id, wait_seconds)
        raise ReaderError('Job action must be start, status, result or list')

    def directory(self, session):
        import re
        if not re.fullmatch(r"v_[a-f0-9]{24}", session):
            raise ReaderError("Invalid video session id")
        return self.cache / session

    def load(self, session):
        path = self.directory(session) / "manifest.json"
        if not path.is_file():
            raise ReaderError("Video session not found; open the source first")
        data = read_json(path)
        if data.get("native_only"):
            return data
        if not Path(data["media_path"]).is_file():
            raise ReaderError("Cached/source media is missing; reopen the source")
        if data.get('media_identity') and sources.file_identity(data['media_path']) != data['media_identity']:
            raise ReaderError('Cached/source media changed; restore the original or open the changed local file as a new session')
        if data["source"]["platform"] == "local":
            identity = data["source"]["identity"]
            if sources.file_identity(identity["path"]) != {k: v for k, v in identity.items() if k != "subtitles"}:
                raise ReaderError("Source file changed; reopen it to create a new video session")
        if sub := data["source"]["identity"].get("subtitles"):
            if sources.file_identity(sub["path"]) != sub:
                raise ReaderError("Subtitle file changed; reopen the source")
        return data

    def save(self, data):
        write_json(self.directory(data["id"]) / "manifest.json", data)

    def register_youtube(self, source):
        """YouTube native AV can accept a URL without a yt-dlp media download."""
        resolved = sources.resolve(source)
        if resolved["platform"] != "youtube":
            raise ReaderError("Direct native URL reading currently supports YouTube; open other sources first")
        session = "v_" + digest({"source": resolved["identity"], "native_only": True})
        directory = self.directory(session)
        directory.mkdir(parents=True, exist_ok=True)
        with session_lock(directory):
            if not (directory / "manifest.json").is_file():
                self.save({"schema_version": 1, "id": session, "source": resolved, "created_at": time.time(),
                           "native_only": True, "media_path": None, "title": resolved["canonical"],
                           "metadata": {}, "reads": [], "speech": [], "warnings": []})
        return session

    def open(self, source, subtitles=None, task=None, strategy='uniform', include_danmaku=False):
        if not isinstance(include_danmaku, bool):
            raise ReaderError('include_danmaku must be true or false')
        report('resolving_source')
        resolved = sources.resolve(source, subtitles)
        profile = self.config["platforms"].get(resolved["platform"], self.config["platforms"]["generic"])
        if resolved["platform"] == "bilibili":
            from .bilibili_auth import BilibiliAuth
            report('checking_account')
            with BilibiliAuth(self.config).reader_profile(profile) as (io_profile, cache_profile, authentication):
                return self._open(resolved, io_profile, cache_profile, authentication, task, strategy, include_danmaku)
        if resolved['platform'] == 'youtube':
            from .youtube_auth import reader_profile
            with reader_profile(profile) as (io_profile, cache_profile, authentication):
                return self._open(resolved, io_profile, cache_profile, authentication, task, strategy, include_danmaku)
        return self._open(resolved, profile, profile, task=task, strategy=strategy, include_danmaku=include_danmaku)

    def search(self, query, **options):
        from .discovery import discover
        return discover(self, query, **options)

    def continue_read(self, session, cursor):
        from .delivery import resume
        return resume(self, session, cursor)

    def frame(self, session, frame_id, width=1920, region=None):
        from .frame_detail import inspect_frame
        return inspect_frame(self, session, frame_id, width, region)

    def sound(self, session, start=0, end=None):
        from .audio import inspect_audio
        return inspect_audio(self, session, start, end)

    def export(self, session, destination, revision, source='auto', context=None, read_ids=None, include_danmaku=False):
        from .export import export
        return export(self, session, destination, revision, source, context, read_ids, include_danmaku)

    def discover(self, **options):
        from .discovery import discover
        return discover(self, **options)

    @contextmanager
    def _material_platform(self, offline=False):
        from .bilibili_auth import BilibiliAuth
        from .platform import Platform
        if not isinstance(offline, bool):
            raise ReaderError('offline must be true or false')
        if offline:
            yield Platform(self.config, offline=True)
        else:
            with BilibiliAuth(self.config).reader_profile(self.config['platforms']['bilibili']):
                yield Platform(self.config)

    def preview(self, source, offline=False, include_comments=False, density='light', max_frames=None, contact_sheet=False):
        from .preview import preview, comments, controls
        controls(density, max_frames)
        if not isinstance(include_comments, bool) or not isinstance(contact_sheet, bool):
            raise ReaderError('include_comments and contact_sheet must be true or false')
        if sources.resolve(source)['platform'] != 'bilibili':
            raise ReaderError('Light preview currently supports Bilibili BV/URL sources')
        with self._material_platform(offline) as platform:
            result = self._cached_preview(platform, source, density, max_frames, contact_sheet)
            if result is None:
                result = preview(platform, source, density=density, max_frames=max_frames, make_sheet=contact_sheet)
            if include_comments:
                result['community'] = comments(platform, result['bvid'])
            from .delivery import freeze_preview
            return freeze_preview(self, result, platform.scope)

    def preview_batch(self, sources_list, offline=False, include_comments=False, density='light', max_frames=None, contact_sheet=True):
        from .preview import preview, comments, controls
        controls(density, max_frames)
        if not isinstance(sources_list, list) or not 1 <= len(sources_list) <= 10 or any(not isinstance(s, str) for s in sources_list):
            raise ReaderError('sources must contain 1..10 video sources')
        if not isinstance(include_comments, bool) or not isinstance(contact_sheet, bool):
            raise ReaderError('include_comments and contact_sheet must be true or false')
        items = []
        with self._material_platform(offline) as platform:
            for source in sources_list:
                try:
                    item = self._cached_preview(platform, source, density, max_frames, contact_sheet)
                    if item is None:
                        item = preview(platform, source, density=density, max_frames=max_frames, make_sheet=contact_sheet)
                    if include_comments:
                        item['community'] = comments(platform, item['bvid'])
                    caption = item.get('caption')
                    item['caption'] = ({key: caption.get(key) for key in ('kind', 'language', 'proofread')} |
                                       {'segment_count': len(caption.get('segments', [])), 'segments_included': False}) if caption else None
                    item['returned_frame_count'] = len(item['frames'])
                    if item.get('contact_sheet'):
                        item['contact_sheet'] = {key: value for key, value in item['contact_sheet'].items() if key != 'cells'}
                        item['frames'] = []
                        item['frame_details_omitted'] = True
                    items.append({'status': 'ready' if item['returned_frame_count'] else 'partial', **item})
                except (ReaderError, OSError, ValueError, KeyError) as error:
                    items.append({'source': source, 'status': 'failed', 'error': {'code': getattr(error, 'code', None), 'message': str(error)}})
        successes = sum(item['status'] == 'ready' for item in items)
        result = {'material_level': 'preview_batch', 'reading_status': 'previewed_not_read', 'items': items,
                'status': 'ready' if successes == len(items) else 'partial' if successes else 'failed',
                'notice': UNTRUSTED, 'detail_hint': 'Use preview on an individual source with the same density/max_frames for full captions and frame details.'}
        from .delivery import freeze_preview
        return freeze_preview(self, result, platform.scope)

    def uploader_videos(self, source, page=1, offline=False):
        from .uploader import target, uploader_videos
        target(source)
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 1000:
            raise ReaderError('page must be an integer between 1 and 1000')
        with self._material_platform(offline) as platform:
            return uploader_videos(platform, source, page)

    def comments(self, source, page=1, page_size=20, sort='newest', root=None, offline=False):
        from .community import comments, controls
        controls(source, page, page_size, sort, root)
        with self._material_platform(offline) as platform:
            return comments(platform, source, page, page_size, sort, root)

    def danmaku(self, source, segment_index=1, offset=0, limit=100, offline=False, snapshot_id=None):
        from .community import danmaku, danmaku_controls
        danmaku_controls(source, segment_index, offset, limit, snapshot_id)
        if not isinstance(offline, bool):
            raise ReaderError('offline must be true or false')
        with self._material_platform(offline or snapshot_id is not None) as platform:
            return danmaku(platform, source, segment_index, offset, limit, snapshot_id)

    def _cached_preview(self, platform, source, density, max_frames, make_sheet):
        """Reuse owned source material without ASR/OCR or another media download."""
        from .preview import controls, contact_sheet
        resolved = sources.resolve(source)
        if resolved['platform'] != 'bilibili':
            return None
        count = controls(density, max_frames)
        for manifest in self.cache.glob('v_*/manifest.json'):
            try:
                saved = read_json(manifest)
                if (saved['source'].get('canonical') != resolved['canonical']
                        or saved.get('authentication', {}).get('account_marker') != platform.scope):
                    continue
                data = self.load(saved['id'])
            except (ReaderError, OSError, ValueError, KeyError, TypeError):
                continue
            duration = data['metadata']['duration_seconds']
            records = [record for record in data.get('reads', []) if record['start'] == 0
                       and record['end'] >= duration - .1 and len(record['frames']) >= count
                       and all(Path(frame['path']).is_file() for frame in record['frames'])]
            if records:
                record = min(records, key=lambda item: len(item['frames']))
            else:
                read = self.read(data['id'], max_frames=count, temporal=False, verify=False)
                record = next(item for item in self.load(data['id'])['reads'] if item['id'] == read['read_id'])
            available = record['frames']
            sample_count = min(count, len(available))
            chosen = [available[round(index * (len(available) - 1) / max(1, sample_count - 1))]
                      for index in range(sample_count)]
            frames = [{'id': frame['id'], 'time': frame['timestamp_seconds'], 'path': frame['path'], 'precision': 'source_frame'}
                      for frame in chosen]
            metadata = data.get('platform_metadata') or {}
            captions = next((track for track in data.get('speech', []) if track['source'] == 'captions'), None)
            result = {'bvid': resolved['bvid'], 'part': resolved['page'], 'cid': metadata.get('cid'), 'url': resolved['canonical'],
                      'title': data['title'], 'duration_seconds': duration, 'source_session_id': data['id'],
                      'uploader': metadata.get('uploader'), 'uploader_id': metadata.get('uploader_id'), 'uploader_url': metadata.get('uploader_url'),
                      'density': density, 'requested_frames': count, 'frame_precision': 'source_frame', 'frames': frames,
                      'caption': {'segments': captions['segments'], **(captions.get('track') or {}), 'proofread': False} if captions else None,
                      'gaps': [] if captions else ['no_cached_caption'], 'material_level': 'preview', 'material_origin': 'cached_media',
                      'reading_status': 'previewed_not_read', 'notice': UNTRUSTED,
                      'visual_sampling': {'requested_frames': count, 'returned_frames': len(frames), 'precision': 'source_frame',
                                          'complete_continuous_coverage': False}}
            if make_sheet:
                directory = platform.root / f"{resolved['bvid']}-p{resolved['page']}" / f'source-{count}'
                directory.mkdir(parents=True, exist_ok=True)
                result['contact_sheet'] = contact_sheet(result, directory)
            return result
        return None

    def _open(self, resolved, profile, cache_profile, authentication=None, task=None, strategy='uniform', include_danmaku=False):
        # Different part/language/resolution/auth scopes must not collide in the cache.
        identity = {"source": resolved["identity"], "profile": cache_profile, "version": 1}
        session = "v_" + digest(identity)
        directory = self.directory(session)
        directory.mkdir(parents=True, exist_ok=True)
        with session_lock(directory):
            if ((directory / "manifest.json").is_file()
                    and Path(read_json(directory / "manifest.json")["media_path"]).is_file()):
                data = self.load(session)
                reused = True
            else:
                print_progress("Preparing video source")
                if resolved['platform'] != 'local':
                    scope = (authentication or {}).get('account_marker') or resolved['platform'] + '-anonymous'
                    profile = {**profile, '_network_budget': {
                        'directory': str(Path(self.config['preview']['directory']) / scope),
                        'options': self.config['preview']['network']}}
                    if resolved['platform'] == 'bilibili' and (authentication or {}).get('account_marker'):
                        from .platform import Platform
                        profile['_platform'] = Platform(self.config)
                report('acquiring_source')
                media = sources.acquire(resolved, directory / "source", profile)
                report('probing_media')
                metadata = _watch_call(frames.get_metadata, media["media_path"])
                data = {"schema_version": 1, "id": session, "source": resolved, "created_at": time.time(),
                        **media, "metadata": metadata, 'media_identity': sources.file_identity(media['media_path']), "reads": [], "speech": []}
                if media.get("subtitle_path"):
                    try:
                        segments = sources.load_subtitles(media["subtitle_path"])
                        data["speech"].append({"start": 0, "end": metadata["duration_seconds"],
                                               "status": "ready" if segments else "no_speech",
                                               "source": "captions", "track": media.get("caption_track"), "segments": segments})
                    except (OSError, ValueError, ReaderError) as exc:
                        data["warnings"].append(f"Subtitle parsing failed: {type(exc).__name__}")
                self.save(data)
                reused = False
            if authentication is not None:
                data["authentication"] = authentication
                if data.get("subtitle_status") == "login_required":
                    data["authentication"] = {**authentication, "status": "login_required", "requires_login": True, "authenticated": False}
                self.save(data)
        report('source_ready', session_id=session, materials={'media_available': True,
               'captions_available': bool(data['speech']), 'caption_segments': sum(len(s['segments']) for s in data['speech'])})
        result = self.read(session, task=task, strategy=strategy, include_danmaku=include_danmaku)
        result["reused_session"] = reused
        result['acquisition'] = {'media_cache_reused': reused, 'download_performed': not reused and resolved['platform'] != 'local',
            'request_accounting': 'Native API and downloader urlopen calls share the account budget/pause; lower-level redirects are not separately counted'}
        return result

    def window(self, data, start=0, end=None):
        if data.get("native_only"):
            raise ReaderError("This is a native YouTube session; use cloud-ask/cloud-poll, or open the URL for local frames")
        from .common import seconds
        lo, hi = seconds(start) or 0.0, seconds(end)
        duration = data["metadata"]["duration_seconds"]
        hi = duration if hi is None else hi
        if hi <= lo or lo >= duration or hi > duration + 0.1:
            raise ReaderError(f"Requested interval is outside video duration ({duration:.3f}s)")
        return lo, min(hi, duration)

    @delivered
    def read(self, session, start=0, end=None, timestamps=None, max_frames=None, width=None, page=0, temporal=None,
             source='auto', verify=None, context=None, view='reading', strategy='uniform', task=None,
             include_danmaku=False, danmaku_snapshot_id=None):
        if not isinstance(include_danmaku, bool):
            raise ReaderError('include_danmaku must be true or false')
        if danmaku_snapshot_id is not None and not include_danmaku:
            raise ReaderError('danmaku_snapshot_id requires include_danmaku=True')
        if source not in ('auto', 'captions', 'asr', 'qwen'):
            raise ReaderError('Speech source must be auto, captions, asr or qwen')
        if view not in ('reading', 'evidence', 'raw'):
            raise ReaderError('view must be reading, evidence or raw')
        if verify is not None and not isinstance(verify, bool):
            raise ReaderError('verify must be true or false')
        if strategy not in ('uniform', 'adaptive', 'scene', 'dense'):
            raise ReaderError('strategy must be uniform, adaptive, scene or dense')
        if task is not None and (not isinstance(task, str) or len(task) > 4000):
            raise ReaderError('task must be a question or reading purpose of at most 4000 characters')
        directory = self.directory(session)
        with session_lock(directory):
            data = self.load(session)
            report(materials={'media_available': True, 'captions_available': any(s['source'] == 'captions' for s in data['speech'])})
            lo, hi = self.window(data, start, end)
            context = self._reading_context(data, context, source)
            budget = self.config["overview_frames"] if max_frames is None else max_frames
            if max_frames is None and strategy in ('adaptive', 'dense'):
                budget = 12 if strategy == 'adaptive' else 48
            width = self.config["frame_width"] if width is None else width
            if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 120:
                raise ReaderError("max_frames must be an integer between 1 and 120")
            if isinstance(width, bool) or not isinstance(width, int) or not 64 <= width <= 3840:
                raise ReaderError("width must be an integer between 64 and 3840")
            if not isinstance(page, int) or isinstance(page, bool) or page < 0:
                raise ReaderError("page must be a nonnegative integer")
            from .common import seconds
            points = sorted(set(seconds(t) for t in timestamps)) if timestamps else None
            if points and (len(points) > budget or any(t is None or t < lo or t >= hi for t in points)):
                raise ReaderError("Every requested timestamp must lie within [start,end) and fit max_frames")
            if temporal is not None and not isinstance(temporal, bool):
                raise ReaderError('temporal must be true or false')
            vision_enabled = self.config.get('vision', {}).get('enabled', True)
            ocr_available = importlib.util.find_spec('rapidocr_onnxruntime') is not None
            if temporal is True and not ocr_available:
                raise ReaderError('Temporal text checks need the optional vision extra; install it or select temporal=False')
            vision_enabled = vision_enabled and ocr_available
            temporal = vision_enabled if temporal is None else temporal
            from .vision import FRAME_REVISION as vision_revision
            parameters = {"start": lo, "end": hi, "timestamps": points, "budget": budget, "width": width,
                          'temporal': temporal, 'vision_revision': vision_revision if temporal else 0}
            if strategy != 'uniform' or task is not None:
                parameters.update(strategy=strategy, task=task)
            read_id = digest(parameters)
            previous = next((r for r in data["reads"] if r["id"] == read_id), None)
            if previous and all(Path(f["path"]).is_file() for f in previous["frames"]):
                record = previous
            else:
                selected = []
                observation = {}
                if data["metadata"]["has_video"]:
                    output = directory / "frames" / (read_id + "-" + uuid.uuid4().hex[:8])
                    report('extracting_frames')
                    if points:
                        selected, _ = _watch_call(frames.extract_at_timestamps, data["media_path"], output, points,
                                                 resolution=width, max_frames=budget, start_seconds=lo, end_seconds=hi)
                        for frame in selected:
                            frame['reason'] = 'requested_timestamp'
                    elif strategy in ('adaptive', 'scene'):
                        from .observation import extract
                        selected, observation = extract(data, output, lo, hi, budget, width, strategy,
                            self._speech(data, lo, hi, source, context))
                    elif strategy == 'dense':
                        dense_points = [lo + (hi-lo) * (i+.5) / budget for i in range(budget)]
                        selected, _ = _watch_call(frames.extract_at_timestamps, data['media_path'], output, dense_points,
                            resolution=width, max_frames=budget, start_seconds=lo, end_seconds=hi)
                    else:
                        # No perceptual deduplication: small code/text changes are evidence too.
                        selected = _watch_call(frames.extract, data["media_path"], output, budget / (hi-lo),
                                               resolution=width, max_frames=budget, start_seconds=lo, end_seconds=hi)
                    if temporal:
                        report('temporal_ocr', progress={'done': 0, 'total': len(selected)})
                        from .vision import annotate_frame
                        annotated = []
                        for f in selected:
                            annotated.append(annotate_frame(f, data, directory, self.config, hi, allow_shift=not bool(points)))
                            report(progress={'done': len(annotated), 'total': len(selected)})
                        selected = annotated
                    for frame in selected:
                        frame["time"] = stamp(frame["timestamp_seconds"])
                        frame["id"] = f"{read_id}:{frame['index']}"
                record = {"id": read_id, **parameters, "frames": selected, 'observation': observation}
                data["reads"] = [r for r in data["reads"] if r["id"] != read_id] + [record]
                self.save(data)
            report('assembling_material', materials={'frames_available': len(record['frames'])})
            page_size = self.config["page_frames"]
            count = len(record["frames"])
            if page and page * page_size >= count:
                raise ReaderError("Frame page is outside the available range")
            selected = record["frames"][page * page_size:(page+1) * page_size]
            speech = self._speech(data, lo, hi, source, context)
            speech_page_size = self.config["page_transcript_segments"]
            segments = speech.pop("segments", [])
            full = self._speech(data, 0, data['metadata']['duration_seconds'], source, context)
            speech['segments'], speech['review'], speech['screen_verification'] = self._speech_page(
                data, full, segments[:speech_page_size], directory, verify, view, cached_only=bool(points))
            speech["returned_segments"] = len(speech["segments"])
            speech["total_segments"] = len(segments)
            speech["next_offset"] = speech_page_size if len(segments) > speech_page_size else None
            result = {"session_id": session, "title": data["title"], "source": data["source"]["canonical"],
                    "platform": data["source"]["platform"], "platform_metadata": data.get("platform_metadata", {}),
                    "metadata": data["metadata"], "read_id": read_id, "range": {"start": lo, "end": hi},
                    'processing': {'frame_cache_reused': record is previous, 'speech_decode_started': False},
                    "visual": {"status": "sampled" if count else "no_video_stream", "frames": selected,
                               "page": page, "total_frames": count, "next_page": page+1 if (page+1)*page_size < count else None,
                               "strategy": "explicit_timestamps" if points else strategy,
                               "observation": record.get('observation', {}), 'task': task,
                               'task_completeness': 'host_must_assess_against_question',
                               "complete_continuous_coverage": False,
                               "constraint": "Finite hardware/context/cost budgets require sampling; increase detail for unresolved evidence."},
                    "speech": speech, "audio": {"status": "available" if data["metadata"]["has_audio"] else "no_audio_stream",
                    "raw_sound_understood_by_host": False,
                    "native_av_tool": "video_cloud_ask" if self.config["gemini"]["enabled"] else None,
                    "cloud_enabled": self.config["gemini"]["enabled"]},
                    "warnings": data["warnings"], "authentication": data.get("authentication"), "source_content_policy": UNTRUSTED}
        if include_danmaku:
            from .aligned_danmaku import attach
            result = attach(self, result, data, full, danmaku_snapshot_id)
        return result

    def _context(self, data, context=None, source='auto'):
        # A Chinese title made Whisper omit real English speech. Hints must be
        # explicit; metadata is evidence for the host, not an automatic prompt.
        value = context if context is not None else ''
        if not isinstance(value, str) or len(value) > 1000:
            raise ReaderError('Speech context must be a string of at most 1000 characters')
        return value

    def _reading_context(self, data, context=None, source='auto'):
        value = self._context(data, context, source)
        if context is not None or source in ('qwen', 'captions'):
            return value
        records = [s for s in data['speech'] if s['source'] == 'local_faster_whisper']
        if any(s.get('profile') == speech_engine.profile(self.config, '') for s in records):
            return ''
        # Preserve access to old cached transcripts/reviews. New decoding never
        # continues the old implicit title prompt; explicit context selects it.
        legacy = data.get('platform_metadata', {}).get('part_title') or data['title']
        if any(s.get('profile') == speech_engine.profile(self.config, legacy) for s in records):
            return legacy
        return ''

    def _speech(self, data, lo, hi, source='auto', context=None):
        if source not in ('auto', 'captions', 'asr', 'qwen'):
            raise ReaderError('Speech source must be auto, captions, asr or qwen')
        available = sorted(set(s['source'] for s in data['speech']))
        captions = [s for s in data['speech'] if s['source'] == 'captions']
        records = captions if source not in ('asr', 'qwen') and captions else []
        if not records and source != 'captions':
            from . import qwen
            engine = qwen if source == 'qwen' else speech_engine
            wanted = engine.profile(self.config, self._reading_context(data, context, source))
            source_name = qwen.SOURCE if source == 'qwen' else 'local_faster_whisper'
            records = [s for s in data['speech'] if s['source'] == source_name and s.get('profile') == wanted]
        missing = speech_engine.missing_ranges(records, lo, hi)
        coverage = {'kind': 'source_processed', 'requested_range': [lo, hi], 'complete': not missing,
                    'missing_ranges': [list(r) for r in missing]}
        if records:
            records = sorted(records, key=lambda r: r['start'])
            record = records[0]
            alignment = {}
            if source == 'qwen':
                assembled, seams, cuts = qwen.assemble(records)
                candidates = assembled
                alignment = {'qwen_alignment': {'timing_accuracy_verified': False,
                    'timestamp_class_step_seconds': .08,
                    'seams_requiring_review': [seam['time'] for seam in seams if seam['requires_review'] and lo <= seam['time'] <= hi],
                    'shared_pair_seams': sum(cut['method'] == 'unique_shared_pair' for cut in cuts),
                    'zero_duration_raw_units': sum(len(r['qwen_chunk']['warnings']) for r in records)}}
            else:
                candidates = [s for r in records for s in r['segments']]
            segments = sorted((s for s in candidates if s['end'] > lo and s['start'] < hi),
                              key=lambda s: (s['start'], s['end']))
            segments = list({(s['start'], s['end'], s['text']): s for s in segments}.values())
            from .review import identity
            review_document = data.get('review_documents', {}).get(digest(identity(record)))
            return {**{k: v for k, v in record.items() if k not in ('segments', 'start', 'end', 'qwen_chunk')}, **alignment,
                    **({'review_document_id': review_document} if review_document else {}),
                    'start': lo, 'end': hi, 'status': 'partial' if missing else 'ready' if segments else 'no_speech',
                    'segments': segments, 'coverage': coverage, 'available_sources': available,
                    'quality': {'source': 'human_declared' if (record.get('track') or {}).get('kind') == 'manual' else 'machine_generated',
                                'exactness_guaranteed': False}}
        if source == 'captions':
            return {'status': 'unavailable', 'segments': [], 'coverage': coverage,
                    'available_sources': available, 'reason': 'No caption track covers this interval'}
        if not data["metadata"]["has_audio"]:
            return {"status": "no_audio_stream", "segments": [], 'coverage': coverage, 'available_sources': available}
        model = self.config["asr"].get("model_path")
        ready = qwen.available(self.config) if source == 'qwen' else bool(
            model and (Path(model) / "model.bin").is_file() and importlib.util.find_spec("faster_whisper"))
        return {"status": "requires_transcription" if ready else "unavailable", "segments": [],
                'coverage': coverage, 'available_sources': available,
                "available_tool": "video_transcript" if ready else None,
                "reason": ('Selected local speech source needs decoding' if ready else
                           'Qwen needs its local runtime and both models; no fallback' if source == 'qwen' else
                           'No captions and no configured local ASR model/runtime')}

    def _speech_page(self, data, full, selected, directory, verify, view, cached_only=False):
        from .review import overlay
        selected, coverage = overlay(directory, full, selected, view='raw')
        automatic = verify is None
        enabled = self.config.get('vision', {}).get('enabled', True)
        ocr_available = importlib.util.find_spec('rapidocr_onnxruntime') is not None
        if verify is True and not ocr_available:
            raise ReaderError('Screen verification needs the optional vision extra; install it or select verify=False')
        enabled = enabled and ocr_available
        manual = (full.get('track') or {}).get('kind') == 'manual'
        summary = {'mode': 'auto' if automatic else 'on' if verify else 'off',
                   'policy': 'off' if not enabled or verify is False else
                             'cached_only' if cached_only and automatic and view != 'evidence' else
                             'pending_only' if automatic and view != 'evidence' else 'selected_page',
                   'computed_segments': 0, 'cached_segments': 0, 'skipped_segments': len(selected),
                   'reason': 'not_requested' if verify is False else 'ocr_runtime_missing' if not ocr_available else 'disabled' if not enabled else 'manual_captions' if manual else None}
        if enabled and verify is not False and (not manual or verify is True):
            from .vision import verify_segments
            report('verifying_speech', progress={'done': 0, 'total': len(selected)})
            selected = verify_segments(data, selected, directory, self.config,
                cached_only=cached_only and automatic and view != 'evidence',
                skip_reviewed=automatic and view != 'evidence')
            checks = [segment['screen_verification'] for segment in selected]
            summary.update(computed_segments=sum(check.get('cache_reused') is False for check in checks),
                           cached_segments=sum(check.get('cache_reused') is True for check in checks),
                           skipped_segments=sum(check['status'] == 'not_requested' for check in checks))
        selected, coverage = overlay(directory, full, selected, view)
        return selected, coverage, summary

    @delivered
    def transcript(self, session, start=0, end=None, offset=0, limit=60, transcribe=True,
                   source='auto', verify=None, context=None, view='reading', max_chunks=None):
        if view not in ('reading', 'evidence', 'raw'):
            raise ReaderError('view must be reading, evidence or raw')
        if verify is not None and not isinstance(verify, bool):
            raise ReaderError('verify must be true or false')
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ReaderError("offset must be >=0 and limit between 1 and 200")
        if max_chunks is not None and (type(max_chunks) is not int or not 1 <= max_chunks <= 100):
            raise ReaderError('max_chunks must be 1..100 or null for the legacy complete-range request')
        directory = self.directory(session)
        with session_lock(directory):
            data = self.load(session)
            report(materials={'media_available': True, 'captions_available': any(s['source'] == 'captions' for s in data['speech'])})
            lo, hi = self.window(data, start, end)
            requested_context = context
            context = self._reading_context(data, context, source)
            speech = self._speech(data, lo, hi, source, context)
            processed = 0
            if speech["status"] in ('requires_transcription', 'partial') and transcribe and source != 'captions':
                if requested_context is None and source != 'qwen' and context:
                    context = ''
                    speech = self._speech(data, lo, hi, source, context)
                from . import qwen
                chunk = 60 if source == 'qwen' else self.config['asr'].get('chunk_seconds', 120)
                if isinstance(chunk, bool) or not isinstance(chunk, (float, int)) or not 15 <= chunk <= 600:
                    raise ReaderError('ASR chunk_seconds must be between 15 and 600')
                for begin, finish in speech['coverage']['missing_ranges']:
                    while begin < finish - .001:
                        if max_chunks is not None and processed >= max_chunks:
                            break
                        until = min(finish, begin+chunk)
                        decoder = qwen.decode if source == 'qwen' else speech_engine.decode
                        report('transcribing', progress={'start': begin, 'end': until, 'range_end': hi})
                        record = decoder(data, begin, until, directory, self.config, context, print_progress)
                        data['speech'].append(record)
                        self.save(data)  # Completed intervals survive interruption; never claim an unfinished tail.
                        begin = until
                        processed += 1
                speech = self._speech(data, lo, hi, source, context)
            all_segments = speech.pop("segments", [])
            selected = all_segments[offset:offset+limit]
            full = self._speech(data, 0, data['metadata']['duration_seconds'], source, context)
            selected, speech['review'], speech['screen_verification'] = self._speech_page(
                data, full, selected, directory, verify, view)
            speech.update(session_id=session, requested_range={"start": lo, "end": hi}, offset=offset,
                          total_segments=len(all_segments), segments=selected,
                          next_offset=offset+limit if offset+limit < len(all_segments) else None,
                          source_content_policy=UNTRUSTED)
            speech['processing'] = {'chunks_processed_this_call': processed,
                'complete': speech['coverage']['complete'], 'remaining_ranges': speech['coverage']['missing_ranges'],
                'continue_hint': 'Repeat transcript with the same range/source/context to process remaining chunks; follow delivery cursor for already-ready text. Segment IDs identify repeated material.' if not speech['coverage']['complete'] else None}
            return speech

    @delivered
    def review(self, session, action='prepare', source='auto', offset=0, limit=60,
               payload=None, context=None, start=None, end=None):
        from . import review
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ReaderError('offset must be >=0 and limit between 1 and 200')
        directory = self.directory(session)
        with session_lock(directory):
            data = self.load(session)
            duration = data['metadata']['duration_seconds']
            supplied_scope = payload.get('review_scope') if isinstance(payload, dict) else None
            if supplied_scope is not None:
                if not isinstance(supplied_scope, dict) or not {'start', 'end', 'material_snapshot_id'} <= supplied_scope.keys():
                    raise ReaderError('review_scope must be copied from prepare')
                if start is None and end is None:
                    start, end = supplied_scope['start'], supplied_scope['end']
            local = start is not None or end is not None
            lo, hi = self.window(data, 0 if start is None else start, end)
            selected = self._speech(data, lo, hi, source, context)
            if action in ('prepare', 'commit') and not selected['coverage']['complete']:
                raise ReaderError('Finish transcription of the requested review range before preparing or committing its review' if local else 'Finish full-source transcription before preparing or committing its review')
            speech = self._speech(data, 0, duration, source, context)
            if local and action == 'prepare' and not speech.get('review_document_id'):
                # Pin the existing review document; adding other decoded intervals
                # must not orphan edits. Raw segment IDs still bind exact text/time.
                anchor, _ = review.document(speech)
                data.setdefault('review_documents', {})[digest(review.identity(speech))] = anchor
                self.save(data)
                speech['review_document_id'] = anchor
            selected_scope = review.scope(selected, lo, hi) if local else None
            if action == 'commit':
                result = review.commit(directory, data, speech, payload, selected_scope, selected)
            elif action == 'prepare':
                result = review.prepare(directory, speech, offset, limit, selected_scope, selected)
            elif action == 'status':
                _, coverage = review.overlay(directory, speech, [])
                result = {'review': coverage}
                if local:
                    result.update(review_scope=selected_scope,
                        scope_review=review.scope_coverage(directory, speech, selected_scope, selected))
            else:
                raise ReaderError('Review action must be prepare, commit or status')
            return {**result, 'session_id': session, 'title': data['title'], 'source_content_policy': UNTRUSTED}

    def relisten(self, session, start, end, terms=None, context=None, timeout_seconds=60, precise_words=False):
        from .relisten import execute
        directory = self.directory(session)
        with session_lock(directory):
            data = self.load(session)
            report(materials={'media_available': True, 'captions_available': any(s['source'] == 'captions' for s in data['speech'])})
            lo, hi = self.window(data, start, end)
            if not data['metadata']['has_audio']:
                raise ReaderError('Source has no audio stream')
            baseline_context = self._reading_context(data, context)
            # A long video title overwhelmed real 13s speech and was repeated as
            # transcript. Local rereading uses only explicitly supplied hints.
            context = self._context(data, context) if context is not None else ''
        result = execute(directory, data, self.config, lo, hi, context, [] if terms is None else terms, timeout_seconds, precise_words)
        # An observed short-window failure dropped/repeated clauses. Expose the
        # disagreement, never promote successful process completion to truth.
        from collections import Counter
        baseline = self._speech(data, lo, hi, source='asr', context=baseline_context)
        if baseline.get('status') != 'ready':
            baseline = self._speech(data, lo, hi, context=baseline_context)
        pieces = []
        for segment in baseline.get('segments', []):
            if segment.get('words'):
                pieces.extend(w['text'] for w in segment['words'] if lo <= (w['start']+w['end'])/2 < hi)
            else:
                pieces.append(segment['text'])
        baseline_text = ''.join(pieces)
        candidates = result.get('speech', {}).get('segments', [])
        text = ''.join(s['text'] for s in candidates)
        counts = Counter(s['text'].strip() for s in candidates if s['text'].strip())
        flags = []
        if any(count > 1 for count in counts.values()):
            flags.append('repeated_candidate_segments')
        if len(baseline_text) >= 20 and len(text) < .55*len(baseline_text):
            flags.append('much_shorter_than_baseline')
        if result['status'] != 'completed':
            flags.append('decode_incomplete')
        result['quality'] = {'status': 'unverified_candidate', 'flags': flags,
                             'exactness_guaranteed': False}
        result['comparison'] = {'baseline_source': baseline.get('source'), 'baseline_raw_text': baseline_text,
                                'baseline_also_fallible': True}
        write_json(Path(result['storage_path']), result)
        return result

def print_progress(message):
    import sys
    report(message=message)
    print(f"[video-reader] {message}", file=sys.stderr, flush=True)
