"""Local catalog projections over tasks and registered results; no acquisition or reading."""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import time

from filelock import FileLock
from video_reader.common import ReaderError, read_json, write_json

RETENTIONS = ('简述索引', '轻量记录', '深度提取')
METADATA_FIELDS = {'retention', 'purposes', 'reading_depth', 'format', 'tags',
                   'preview_path', 'keep', 'reason', 'title', 'notes', 'task_goal', 'task_description',
                   'primary_artifact_path'}
CORE_FIELDS = {'task_type', 'task_description', 'completion_method'}
TEMPLATE = Path(__file__).with_name('catalog_view.html')
DOCUMENT_FORMATS = {'html': 'HTML', 'htm': 'HTML', 'md': 'Markdown', 'markdown': 'Markdown',
                    'pdf': 'PDF', 'docx': 'Word', 'txt': '纯文本', 'srt': 'SRT字幕',
                    'vtt': 'WebVTT字幕'}


def delivery_formats(artifacts, answer=None):
    """Describe registered output files, independent of the desired presentation."""
    documents = list(dict.fromkeys(DOCUMENT_FORMATS[a['format']] for a in artifacts
                                   if a['format'] in DOCUMENT_FORMATS))
    formats = documents or list(dict.fromkeys(a['format'].upper() or '无扩展名文件' for a in artifacts))
    return (['直接答复'] if isinstance(answer, dict) and answer.get('text') else []) + formats


def delivery(artifacts, target, answer=None):
    formats = delivery_formats(artifacts, answer)
    target = target or None
    targets = []
    if re.search(r'html', target or '', re.I):
        targets.append('HTML')
    if re.search(r'markdown|\bmd\b', target or '', re.I):
        targets.append('Markdown')
    if '直接答复' in (target or ''):
        targets.append('直接答复')
    return {'formats': formats, 'target': target,
            'matches_target': any(item in formats for item in targets) if targets else None}


def metadata(value):
    """Only presentation annotations belong here; task truth stays in SQLite."""
    if not isinstance(value, dict) or set(value) - METADATA_FIELDS:
        raise ReaderError('Invalid catalog metadata fields')
    result = copy.deepcopy(value)
    if isinstance(result.get('retention'), str):
        result['retention'] = result['retention'].strip() or None
    if 'retention' in result and result['retention'] not in (*RETENTIONS, '', None):
        raise ReaderError('Catalog retention must be 简述索引, 轻量记录 or 深度提取')
    for key, item in result.items():
        if key in ('purposes', 'tags'):
            if item is None:
                item = []
            if (not isinstance(item, list) or len(item) > 30 or
                    any(not isinstance(s, str) or not s.strip() or len(s) > 500 for s in item)):
                raise ReaderError('Catalog purposes/tags must be short text lists')
            result[key] = list(dict.fromkeys(s.strip() for s in item))
        elif item is not None and (not isinstance(item, str) or len(item) > 4000):
            raise ReaderError('Catalog metadata values must be text')
        else:
            result[key] = item.strip() or None if isinstance(item, str) else None
    return result


def description_history(values):
    """Keep explicitly recorded wording available without assigning it to a task."""
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value.strip()))


class Catalog:
    def __init__(self, queue):
        self.queue = queue
        root = getattr(queue.store, 'directory', None) or getattr(queue.store, 'root', None)
        if root is None:
            raise ReaderError('Task store has no local directory')
        self.directory = Path(root) / 'catalog'
        self.index_path = self.directory / 'index.html'
        self.snapshot_path = self.directory / 'catalog.json'
        self.metadata_path = self.directory / 'metadata.json'
        self.marker = self.directory / 'enabled.json'
        self.error_path = self.directory / 'refresh-error.json'

    def _lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.directory / '.build.lock'), timeout=30)

    def enabled(self):
        return self.marker.is_file() and read_json(self.marker).get('scope') == self.queue.scope

    def _saved(self):
        value = read_json(self.metadata_path) if self.metadata_path.is_file() else {}
        if value.get('scope', self.queue.scope) != self.queue.scope:
            raise ReaderError('Catalog belongs to another task library')
        return {'scope': self.queue.scope, 'task_metadata': {
                    item_id: metadata(note) for item_id, note in value.get('task_metadata', {}).items()},
                'source_metadata': value.get('source_metadata', {}),
                'metadata_updated': value.get('metadata_updated', {}), 'views': value.get('views', []),
                'task_goal_tasks': value.get('task_goal_tasks', {}),
                'task_description_tasks': value.get('task_description_tasks', {}),
                'description_history': description_history([
                    *value.get('description_history', []),
                    *(note.get('task_description') for note in value.get('task_metadata', {}).values())])}

    def _options(self, saved, options, task_ids):
        if options is None:
            return saved
        if not isinstance(options, dict) or set(options) - {'task_metadata', 'source_metadata', 'views'}:
            raise ReaderError('Catalog build accepts task_metadata, source_metadata and views only')
        annotations = options.get('task_metadata', {})
        if not isinstance(annotations, dict) or any(item not in task_ids for item in annotations):
            raise ReaderError('Catalog metadata needs tasks in this library')
        for item_id, value in annotations.items():
            saved['task_metadata'][item_id] = {**saved['task_metadata'].get(item_id, {}), **metadata(value)}
            saved['metadata_updated'].setdefault(item_id, {}).update({key: time.time() for key in value})
            for field in ('task_goal', 'task_description'):
                if field in value:
                    saved[field + '_tasks'][item_id] = task_ids[item_id]
        if 'views' in options:
            views = options['views']
            if not isinstance(views, list) or len(views) > 100:
                raise ReaderError('Catalog views must be a list')
            by_id = {view['id']: view for view in saved['views']}
            for view in views:
                if (not isinstance(view, dict) or set(view) != {'id', 'label', 'task_ids'} or
                        not isinstance(view['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', view['id']) or
                        not isinstance(view['label'], str) or not 1 <= len(view['label']) <= 200 or
                        not isinstance(view['task_ids'], list) or
                        any(not isinstance(t, str) or t not in task_ids for t in view['task_ids'])):
                    raise ReaderError('Catalog views need id, label and existing task_ids')
                by_id[view['id']] = {**view, 'task_ids': list(dict.fromkeys(view['task_ids']))}
            saved['views'] = list(by_id.values())
        return saved

    def _source_options(self, saved, options, sources):
        annotations = (options or {}).get('source_metadata', {})
        if not isinstance(annotations, dict) or any(source not in sources for source in annotations):
            raise ReaderError('Source metadata needs sources in this task library')
        for source, value in annotations.items():
            if not isinstance(value, dict) or set(value) - {'cover_path'}:
                raise ReaderError('Source metadata accepts cover_path only')
            normalized = {}
            if 'cover_path' in value:
                normalized['cover_path'] = metadata({'preview_path': value['cover_path']})['preview_path']
            saved['source_metadata'][source] = {**saved['source_metadata'].get(source, {}), **normalized}
        return saved

    def _cover(self, source, saved):
        path = saved['source_metadata'].get(source, {}).get('cover_path')
        if not path:
            return None
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp', '.avif', '.gif') or not target.is_file():
            return None
        return target.as_uri()

    def _records(self):
        with self.queue.store.connect() as db:
            db.execute('BEGIN')
            tasks = [dict(row) for row in db.execute('SELECT * FROM queue_items WHERE scope=? ORDER BY row_id',
                                                    (self.queue.scope,))]
            results = [dict(row) for row in db.execute('SELECT * FROM task_results WHERE scope=? ORDER BY id',
                                                      (self.queue.scope,))]
            origins = db.execute('SELECT item_id,payload FROM queue_origins WHERE scope=? ORDER BY seq',
                                 (self.queue.scope,)).fetchall()
            annotations = {row['item_id']: json.loads(row['payload']) for row in db.execute(
                'SELECT item_id,payload FROM task_annotations WHERE scope=?', (self.queue.scope,))}
            from .followups import Followups
            followups = Followups(self.queue)
            by_followup = {}
            for record in followups._records(db):
                by_followup.setdefault(record['item_id'], []).append(record)
            followup_history = followups._history(db)
            followup_history += [task.get('task_description') for task in tasks]
            for row in db.execute("SELECT details FROM queue_events WHERE scope=? "
                                  "AND kind IN ('updated','enqueued','task_contract_migrated') ORDER BY id",
                                  (self.queue.scope,)):
                event = json.loads(row['details'])
                followup_history.append(event.get('task_description'))
                for side in ('before', 'after'):
                    value = event.get(side)
                    if isinstance(value, dict):
                        followup_history.append(value.get('task_description'))
            task_types = self.queue.task_types(db)
        messages = {}
        for row in origins:
            origin = json.loads(row['payload'])
            messages.setdefault(row['item_id'], []).append({key: origin[key] for key in
                ('id', 'text', 'seq', 'sent_at', 'msg_type', 'parse_status', 'provider') if key in origin})
        for task in tasks:
            note = annotations.get(task['id'], {})
            if not note or note.get('original') != task['task']:
                note = {'kind': 'unclassified', 'original': task['task'], 'comment': None, 'request': None}
            task['note'] = note
            task['messages'] = messages.get(task['id'], [])
            task['followups'] = by_followup.get(task['id'], [])
        return tasks, results, followup_history, task_types

    def _url(self, path):
        try:
            relative = Path(os.path.relpath(path, self.directory)).as_posix()
            from urllib.parse import quote
            return quote(relative, safe='/')
        except ValueError:  # An artifact may legitimately live on another Windows drive.
            return path.as_uri()

    def _artifact(self, record, checks):
        path = Path(record['path']).expanduser().resolve()
        key = (str(path), record.get('sha256'))
        if key not in checks:
            exists, valid = path.is_file(), None
            try:
                if exists and record.get('sha256'):
                    valid = hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
            except OSError:
                exists, valid = False, None
            checks[key] = (exists, valid)
        exists, valid = checks[key]
        return {'path': str(path), 'url': self._url(path), 'exists': exists,
                'hash_valid': valid, 'name': path.name, 'format': path.suffix.lstrip('.').lower()}

    def _preview(self, source, annotation, results):
        candidates = [annotation.get('preview_path')]
        cache = self.queue.cache_dir
        if cache:
            for result in reversed(results):
                coverage = result.get('coverage')
                coverage = coverage if isinstance(coverage, dict) else {}
                binding = result.get('material_binding')
                binding = binding if isinstance(binding, dict) else {}
                session = coverage.get('session_id') or binding.get('session_id')
                if isinstance(session, str) and re.fullmatch(r'v_[a-f0-9]{24}', session):
                    manifest = cache / session / 'manifest.json'
                    if manifest.is_file():
                        data = read_json(manifest)
                        if data.get('source', {}).get('canonical') == source:
                            candidates += [f.get('path') for read in data.get('reads', []) for f in read.get('frames', [])]
                index = coverage.get('index_id') or result.get('index_id')
                if isinstance(index, str) and re.fullmatch(r'ci_[a-f0-9]{24}', index):
                    path = cache / 'content' / (index + '.json')
                    if path.is_file():
                        data = read_json(path)
                        if data.get('binding', {}).get('source') == source:
                            candidates += [f.get('path') for f in data.get('frame_assets', [])]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            path = Path(candidate)
            kind = mimetypes.guess_type(path.name)[0]
            if (kind in ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif') and
                    path.is_file() and path.stat().st_size <= 5 * 1024 * 1024):
                return 'data:' + kind + ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
        return ''

    def _project(self, tasks, records, saved, followup_history=(), task_types=()):
        by_task = {}
        descriptions = [*saved['description_history'],
                        *(note.get('task_description') for note in saved['task_metadata'].values()),
                        *followup_history]
        for row in records:
            result = json.loads(row['record'])
            if isinstance(result.get('catalog'), dict):
                descriptions.append(result['catalog'].get('task_description'))
            by_task.setdefault(row['item_id'], []).append({**result, 'id': row['id'], 'created_at': row['created']})
        grouped, checks, followup_checks, all_tasks = {}, {}, {}, []
        for task in tasks:
            results = by_task.get(task['id'], [])
            annotation, annotation_times = {}, {}
            for result in results:
                if isinstance(result.get('catalog'), dict):
                    result_metadata = metadata(result['catalog'])
                    if result.get('task_request') != task['task']:
                        result_metadata.pop('task_goal', None)
                        result_metadata.pop('task_description', None)
                    annotation.update(result_metadata)
                    annotation_times.update({key: result['created_at'] for key in result_metadata})
            for key, value in saved['task_metadata'].get(task['id'], {}).items():
                if key in ('task_goal', 'task_description') and saved[key + '_tasks'].get(task['id']) != task['task']:
                    continue
                if saved['metadata_updated'].get(task['id'], {}).get(key, 0) >= annotation_times.get(key, 0):
                    annotation[key] = value
            projected = []
            for result in results:
                artifacts = [self._artifact(a, checks) for a in result.get('artifacts', [])]
                projected.append({**result, 'complete': bool(result.get('task_complete', False)),
                    'artifacts': artifacts, 'delivery_formats': delivery_formats(artifacts, result.get('answer'))})
            latest = projected[-1] if projected else {}
            source = task['canonical']
            item = {'id': task['id'], 'title': task['title'], 'request': task['task'], 'state': task['state'],
                    'task_type': task.get('task_type'), 'task_description': task.get('task_description'),
                    'completion_method': task.get('completion_method'),
                    'source': source,
                    'source_title': annotation.get('title') or task['title'] or source,
                    'preview_url': '',
                    'cover_url': self._cover(source, saved),
                    'primary_artifact_path': None,
                    'created_at': task['created'], 'updated_at': task['updated'], 'metadata': annotation,
                    'note': task['note'], 'messages': task['messages'],
                    'followups': [{**record, 'artifacts': [self._artifact(artifact, followup_checks)
                                   for artifact in record.get('artifacts', [])]}
                                  for record in task.get('followups', [])],
                    'delivery': delivery(latest.get('artifacts', []), annotation.get('format', ''),
                                         latest.get('answer')),
                    'results': list(reversed(projected))}
            item['work'] = task.get('task_description')
            preferred = annotation.get('primary_artifact_path')
            if preferred:
                preferred = str(Path(preferred).expanduser().resolve())
                if any(artifact['path'] == preferred for result in projected for artifact in result['artifacts']):
                    item['primary_artifact_path'] = preferred
            item['result_matches_task'] = (latest.get('task_description') == task.get('task_description')
                                           if 'task_description' in latest else None)
            all_tasks.append(item)
            if not results:
                item['preview_url'] = self._preview(source, annotation, [])
                continue
            video = grouped.setdefault(source, {'source': source, 'title': '', '_metadata_title': False,
                                               'preview_url': '', 'tasks': []})
            video['tasks'].append(item)
            if annotation.get('title'):
                video['title'], video['_metadata_title'] = annotation['title'], True
            elif task['title'] and not video['_metadata_title']:
                video['title'] = task['title']
            if not video['preview_url']:
                video['preview_url'] = self._preview(source, annotation, results)
        videos = list(grouped.values())
        for video in videos:
            video.pop('_metadata_title')
            video['title'] = video['title'] or video['source']
            video['retentions'] = sorted({t['metadata'].get('retention') for t in video['tasks'] if t['metadata'].get('retention')})
            video['purposes'] = sorted({p for t in video['tasks'] for p in t['metadata'].get('purposes', [])})
            video['states'] = sorted({t['state'] for t in video['tasks']})
            video['updated_at'] = max(max([t['updated_at']] + [r['created_at'] for r in t['results']]) for t in video['tasks'])
        for item in all_tasks:
            video = grouped.get(item['source'])
            if video:
                item['source_title'] = video['title']
                item['preview_url'] = item['preview_url'] or video['preview_url']
        videos.sort(key=lambda v: (-v['updated_at'], v['source']))
        all_tasks.sort(key=lambda t: (-max([t['updated_at']] + [r['created_at'] for r in t['results']]), t['id']))
        projected_tasks = [t for v in videos for t in v['tasks']]
        all_followups = [record for task in all_tasks for record in task['followups']]
        from collections import Counter
        stats = {'videos': len(videos), 'tasks': len(projected_tasks), 'results': len(records),
                 'artifacts': len(checks), 'task_states': dict(Counter(t['state'] for t in projected_tasks)),
                 'total_tasks': len(all_tasks), 'without_results': len(all_tasks) - len(projected_tasks),
                 'total_task_states': dict(Counter(t['state'] for t in all_tasks)),
                 'missing_artifacts': sum(not c[0] for c in checks.values()),
                 'changed_artifacts': sum(c[1] is False for c in checks.values()),
                 'followups': len(all_followups),
                 'followup_states': dict(Counter(record['state'] for record in all_followups)),
                 'followup_artifacts': len(followup_checks),
                 'missing_followup_artifacts': sum(not c[0] for c in followup_checks.values()),
                 'changed_followup_artifacts': sum(c[1] is False for c in followup_checks.values()),
                 'excluded_without_results': len(tasks) - len(projected_tasks)}
        type_counts = Counter(task['task_type'] for task in all_tasks if task.get('task_type'))
        return {'schema_version': 2, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'library': self.queue.scope, 'stats': stats, 'views': saved['views'], 'videos': videos,
                'tasks': all_tasks, 'description_history': description_history(descriptions),
                'types': [{'name': name, 'count': count} for name, count in type_counts.most_common()],
                'task_types': list(task_types)}

    def _write_html(self, snapshot):
        template = TEMPLATE.read_text(encoding='utf-8')
        if template.count('__CATALOG_DATA__') != 1:
            raise ReaderError('Catalog template needs one data placeholder')
        data = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace(chr(0x2028), '\\u2028').replace(chr(0x2029), '\\u2029')
        # Preview hosts authorize and rewrite local links before page scripts run.
        # Keep the original relative hrefs in static HTML; the dynamic task list
        # reuses the resulting DOM hrefs instead of inventing file: navigation.
        files = {}
        for task in snapshot['tasks']:
            for record in [*task.get('results', []), *task.get('followups', [])]:
                for artifact in record.get('artifacts', []):
                    if artifact.get('exists') is not False:
                        files.setdefault(artifact['path'], artifact)
        links = ''.join(
            '<a data-artifact-path="' + html.escape(path, quote=True) + '" href="' +
            html.escape(artifact['url'], quote=True) + '">' +
            html.escape(artifact['name']) + '</a>\n'
            for path, artifact in files.items())
        output = template.replace('__CATALOG_DATA__', data).replace('__CATALOG_FILE_LINKS__', links)
        fd, temporary = tempfile.mkstemp(prefix='.catalog-', suffix='.html', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(output)
            os.replace(temporary, self.index_path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def build(self, options=None):
        with self._lock():
            tasks, records, followup_history, task_types = self._records()
            saved = self._options(self._saved(), options, {t['id']: t['task'] for t in tasks})
            saved = self._source_options(saved, options, {task['canonical'] for task in tasks})
            snapshot = self._project(tasks, records, saved, followup_history, task_types)
            saved['description_history'] = snapshot['description_history']
            # Write the usable view before enabling automatic refresh.
            self._write_html(snapshot)
            write_json(self.snapshot_path, snapshot)
            write_json(self.metadata_path, saved)
            write_json(self.marker, {'scope': self.queue.scope})
            self.error_path.unlink(missing_ok=True)
        return {'status': 'ready', 'index_path': str(self.index_path), 'snapshot_path': str(self.snapshot_path),
                'generated_at': snapshot['generated_at'], 'stats': snapshot['stats']}

    def update_metadata(self, item_id, payload):
        with self.queue.store.connect() as db:
            self.queue._item(db, item_id)
        if not isinstance(payload, dict):
            raise ReaderError('Catalog update needs a metadata object')
        core = {key: value for key, value in payload.items() if key in CORE_FIELDS}
        presentation = {key: value for key, value in payload.items() if key not in CORE_FIELDS}
        normalized = metadata(presentation)
        if core:
            self.queue.update(item_id, **core)
        return self.build({'task_metadata': {item_id: normalized}})

    def status(self):
        snapshot = read_json(self.snapshot_path) if self.snapshot_path.is_file() else None
        return {'status': 'needs_refresh' if self.error_path.is_file() else 'ready' if self.enabled() else 'not_built',
                'enabled': self.enabled(), 'index_path': str(self.index_path), 'snapshot_path': str(self.snapshot_path),
                'generated_at': snapshot.get('generated_at') if snapshot else None,
                'stats': snapshot.get('stats') if snapshot else None,
                'description_history': snapshot.get('description_history', []) if snapshot else [],
                'schema_version': snapshot.get('schema_version') if snapshot else None,
                'task_types': self.queue.task_types(),
                'refresh_error': read_json(self.error_path) if self.error_path.is_file() else None}

    def refresh_if_enabled(self):
        if not self.enabled():
            return None
        try:
            return self.build()
        except Exception as error:
            detail = {'status': 'failed', 'error': str(error), 'at': time.time(), 'index_path': str(self.index_path)}
            try:
                write_json(self.error_path, detail)
            except OSError:
                pass
            return detail


def refresh(queue):
    """A derived-view failure cannot undo an already committed task result."""
    try:
        return Catalog(queue).refresh_if_enabled()
    except Exception as error:
        return {'status': 'failed', 'error': str(error)}
