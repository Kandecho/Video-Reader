"""Portable evidence, explicit review revision, relative files, no runtime dump."""
import hashlib
import html
import json
from pathlib import Path
import shutil

from filelock import FileLock

from .common import ReaderError, UNTRUSTED, write_json
from . import review


def export(reader, session, destination, revision, source='auto', context=None, read_ids=None, include_danmaku=False,
           speech_profile=None):
    if not isinstance(include_danmaku, bool):
        raise ReaderError('include_danmaku must be true or false')
    if type(revision) is not int or revision < 0:
        raise ReaderError('Choose an explicit nonnegative review revision (0 retains unreviewed raw source)')
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ReaderError('Export destination must be a new folder; existing artifacts are preserved')
    directory = reader.directory(session)
    with FileLock(str(directory / '.lock'), timeout=600):
        data = reader.load(session)
        options = {'speech_profile': speech_profile} if speech_profile is not None else {}
        speech = reader._speech(data, 0, data['metadata']['duration_seconds'], source, context, **options)
        snapshot, raw = review.document(speech)
        selected_state = review.state(directory, snapshot, revision)
        if reader.config.get('vision', {}).get('enabled', True):
            from .vision import verify_segments
            raw = verify_segments(data, raw, directory, reader.config, cached_only=True)
        evidence, coverage = review.overlay(directory, speech, raw, view='evidence', revision=revision)
        reads = data['reads']
        if read_ids is not None:
            if not isinstance(read_ids, list) or any(i not in {r['id'] for r in reads} for i in read_ids):
                raise ReaderError('read_ids must identify reads in this session')
            reads = [r for r in reads if r['id'] in read_ids]
        destination.mkdir(parents=True)
        assets = destination / 'assets'
        assets.mkdir()
        copied = {}
        known_images = review._frame_paths(data, directory)
        def portable(value, field=''):
            if isinstance(value, dict):
                return {key: portable(item, key) for key, item in value.items()}
            if isinstance(value, list):
                return [portable(item, field) for item in value]
            if isinstance(value, str) and (field in ('path', 'model', 'runtime', 'file') or field.endswith(('_path', '_dir'))) and Path(value).is_absolute():
                path = Path(value)
                owned = str(path.resolve()) in known_images or path.resolve().is_relative_to(directory.resolve())
                if owned and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.wav'):
                    if not path.is_file():
                        raise ReaderError('Referenced evidence asset is missing; restore it before making a portable export')
                    if str(path) not in copied:
                        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                        name = content_hash[:24] + path.suffix.lower()
                        shutil.copyfile(path, assets / name)
                        copied[str(path)] = 'assets/' + name
                    return copied[str(path)]
                # Model/runtime/source paths describe provenance, not portable assets.
                return {'resource_name': path.name, 'bundled': False}
            return value
        canonical = data['source']['canonical'] if data['source']['platform'] != 'local' else Path(data['source']['canonical']).name
        record = portable({'schema': 1, 'session_id': session, 'title': data['title'], 'source': canonical,
            'platform': data['source']['platform'], 'metadata': data['metadata'],
            'speech_source': {k: speech.get(k) for k in ('source', 'track', 'profile', 'coverage', 'quality', 'recognition_assessment', 'unplaced_candidates')},
            'snapshot_id': snapshot, 'material_snapshot_id': review.material_id(speech), 'revision': revision, 'review': coverage,
            'segments': evidence, 'review_state': selected_state, 'reads': reads, 'source_content_policy': UNTRUSTED})
        if include_danmaku:
            from .aligned_danmaku import align, load
            identities = sorted({identity for read in reads for identity in read.get('danmaku_snapshot_ids', [])})
            record['danmaku_status'] = 'snapshots_included' if identities else 'not_acquired'
            record['danmaku'] = [align(load(reader, session, identity), evidence,
                [frame for read in reads for frame in read['frames']]) for identity in identities]
        # Relisten evidence retains its separate result and never overwrites speech.
        jobs = {e['job_id'] for change in selected_state['corrections'].values() for e in change.get('evidence', []) if e.get('kind') == 'relisten'}
        from .common import read_json
        record['relistens'] = [portable(read_json(directory / 'relistens' / job / 'result.json')) for job in sorted(jobs)]
        write_json(destination / 'evidence.json', record)
        rows = []
        for segment in record['segments']:
            rows.append(f'<article id="{html.escape(segment["segment_id"])}"><p><b>{segment["start"]:.3f}–{segment["end"]:.3f}s</b> · {html.escape(segment["review_status"])} · {html.escape(segment.get("text_status", "source_text"))}<br>{html.escape(segment["text"])}</p>' +
                (f'<details><summary>原文与修订证据</summary><pre>{html.escape(json.dumps(segment, ensure_ascii=False, indent=2))}</pre></details>' if segment.get('correction') or segment.get('screen_verification') else '') + '</article>')
        images = []
        for read in record['reads']:
            for frame in read['frames']:
                if isinstance(frame.get('path'), str):
                    images.append(f'<figure><img loading="lazy" src="{html.escape(frame["path"])}"><figcaption>{html.escape(frame["id"])} · {html.escape(str(frame.get("time", frame.get("timestamp_seconds"))))}</figcaption></figure>')
        page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Video evidence</title><style>body{max-width:1050px;margin:32px auto;padding:0 20px;font:17px/1.65 system-ui}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-bottom:1px solid #ddd}figure{margin:24px 0}</style>'
        page += f'<h1>{html.escape(data["title"])}</h1><p>Snapshot {snapshot} · revision {revision} · {html.escape(source)}</p><p>完整材料：<a href="evidence.json">evidence.json</a>。取样画面不代表连续覆盖，已交付不代表已观察，已校对不保证绝对准确。</p>'
        for candidate in record['speech_source'].get('unplaced_candidates') or []:
            rows.append('<article><b>Unplaced model candidate · timing unresolved</b><pre>' +
                        html.escape(candidate['raw_text']) + '</pre><p>This is not confirmed speech within the requested interval.</p></article>')
        audience = []
        if include_danmaku:
            audience.append('<h2>观众弹幕（可选材料，非旁白）</h2>')
            if not record['danmaku']:
                audience.append('<p>未缓存弹幕材料；导出未发起获取。</p>')
            for material in record['danmaku']:
                audience.append(f'<p>状态：{html.escape(material["status"])} · {html.escape(str(material["range"]))}</p>')
                for item in material['items']:
                    audience.append(f'<p>{item["timestamp_seconds"]:.3f}s · {html.escape(item["text"])}</p>')
        page += ''.join(rows + images + audience)
        (destination / 'index.html').write_text(page, encoding='utf-8')
    return {'status': 'exported', 'session_id': session, 'snapshot_id': snapshot, 'revision': revision,
            'destination': str(destination), 'index': str(destination / 'index.html'), 'assets': len(copied),
            'review': coverage, 'speech_coverage': speech['coverage']}
