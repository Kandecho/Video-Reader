"""Explicit Reader preview -> host assessment -> durable, non-executing routing."""
import json
import time

from filelock import FileLock, Timeout

from video_reader.common import ReaderError, digest
from video_reader.delivery import restore
from .queue import text_value, bounded_int
from video_reader.common import error_details

CATEGORIES = ('resource_list', 'tutorial', 'project_demo', 'creative_work', 'analysis', 'news', 'entertainment', 'unknown')
SCHEMES = {
    'resource_list': {'id': 'resource_catalog', 'title': '整理资源清单与适用场景',
                      'steps': ['保留资源名称、链接和原视频位置', '注明用途、适用场景与使用条件']},
    'tutorial': {'id': 'procedure_guide', 'title': '整理操作步骤与前置条件',
                 'steps': ['提取目标、前置条件和操作顺序', '注明关键参数、限制与容易误解的地方']},
    'project_demo': {'id': 'project_brief', 'title': '整理项目能力与复用条件',
                     'steps': ['区分演示事实、作者主张与未验证能力', '整理入口、依赖、复用方式与限制']},
    'creative_work': {'id': 'creative_notes', 'title': '记录创意、实现线索与可借鉴之处',
                       'steps': ['保留创意和实际呈现的区别', '记录实现线索、可借鉴点与待确认问题']}}


def fingerprint(item):
    return digest([item['canonical'], item['task'],
                   [{key: m.get(key) for key in ('id', 'text', 'parse_status')} for m in item.get('messages', [])]])


class Triage:
    def __init__(self, queue, reader):
        self.queue, self.reader, self.memory, self.scope = queue, reader, queue.memory, queue.scope
        self.root = self.memory.directory / 'triage' / self.scope
        self.root.mkdir(parents=True, exist_ok=True)
        with self.memory.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queue_triage (
                    scope TEXT NOT NULL, item_id TEXT NOT NULL, record TEXT NOT NULL,
                    PRIMARY KEY(scope,item_id));
                CREATE TABLE IF NOT EXISTS triage_events (
                    id INTEGER PRIMARY KEY, scope TEXT NOT NULL, item_id TEXT NOT NULL,
                    created REAL NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS triage_events_item ON triage_events(scope,item_id,id);
            ''')

    def _load(self, db, item_id):
        row = db.execute('SELECT record FROM queue_triage WHERE scope=? AND item_id=?', (self.scope, item_id)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, db, item_id, record, kind, details=None):
        record['updated_at'] = time.time()
        db.execute('INSERT INTO queue_triage VALUES(?,?,?) ON CONFLICT(scope,item_id) DO UPDATE SET record=excluded.record',
                   (self.scope, item_id, json.dumps(record, ensure_ascii=False)))
        db.execute('INSERT INTO triage_events(scope,item_id,created,kind,details) VALUES(?,?,?,?,?)',
                   (self.scope, item_id, time.time(), kind, json.dumps(details if details is not None else
                    {key: value for key, value in record.items() if key != 'pages'}, ensure_ascii=False)))

    def _lock(self, item_id, timeout=0):
        self.queue.show(item_id,include_material=False)  # Validate account and ID before using a filesystem name.
        return FileLock(str(self.root / (item_id + '.lock')), timeout=timeout)

    def show(self, item_id):
        item = self.queue.show(item_id,include_material=False)
        with FileLock(str(self.root / (item['id'] + '.inspect.lock')), timeout=2):
            owner = self._lock(item_id)
            try:
                owner.acquire()
            except Timeout:
                alive = True
            else:
                alive = False
            try:
                with self.memory.connect() as db:
                    record = self._load(db, item_id)
            finally:
                if not alive:
                    owner.release()
        if not record:
            return {'item_id': item_id, 'status': 'unprepared', 'queue_state': item['state'], 'executed': False}
        status = 'interrupted' if record['status'] == 'preparing' and not alive else record['status']
        return {**{key: value for key, value in record.items() if key != 'pages'}, 'status': status,
                'recorded_status': record['status'], 'worker_alive': alive,
                'stale': record['item_fingerprint'] != fingerprint(item), 'queue_state': item['state'],
                'material_pages_saved': len(record['pages']), 'executed': False, 'full_reading_completed': False}

    def _validate_page(self, page, expected=None, account=None):
        delivery = page.get('delivery', {})
        binding = delivery.get('binding', {})
        if (not isinstance(binding.get('account_scope'),str) or not binding.get('session_id', '').startswith('p_')
                or account is not None and binding['account_scope']!=account):
            raise ReaderError('Triage requires account-bound Reader preview material')
        if expected and delivery.get('snapshot_id') != expected:
            raise ReaderError('Preview snapshot changed; prepare again explicitly')

    def prepare(self, item_id, *, refresh=False):
        if type(refresh) is not bool:
            raise ReaderError('refresh must be true or false')
        try:
            with self._lock(item_id, .2):
                item = self.queue.show(item_id,include_material=False)
                if item['state'] not in ('pending', 'paused'):
                    raise ReaderError('Prepare only a pending or paused queue item')
                with self.memory.connect() as db:
                    old = self._load(db, item_id)
                reused = bool(old and old.get('pages') and old['item_fingerprint'] == fingerprint(item) and not refresh)
                if reused:
                    record = old
                else:
                    record = {'item_id': item_id, 'status': 'preparing', 'source': item['canonical'],
                              'original_task': item['task'], 'item_fingerprint': fingerprint(item),
                              'pages': [], 'assessment': None, 'started_at': time.time(), 'error': None}
                    with self.memory.connect() as db:
                        self._save(db, item_id, record, 'prepare_started')
                    try:
                        # Public, bounded material API. No full open, OCR, ASR or recommendation runner.
                        page = self.reader.preview(item['canonical'], density='light', max_frames=5, contact_sheet=True)
                        from video_reader.catalog import account_scope
                        self._validate_page(page,account=self.queue.source_scope or account_scope(self.reader.config,item['canonical']))
                        record.update(status='prepared', pages=[page],
                                      material_id=page['delivery']['binding']['session_id'],
                                      snapshot_id=page['delivery']['snapshot_id'], error=None)
                        with self.memory.connect() as db:
                            self._save(db, item_id, record, 'material_prepared')
                    except BaseException as error:
                        record.update(status='failed' if isinstance(error, Exception) else 'interrupted', error=error_details(error))
                        with self.memory.connect() as db:
                            self._save(db, item_id, record, 'prepare_failed')
                        raise
                page = record['pages'][0]
        except Timeout:
            raise ReaderError('Triage preparation is active; query its saved state') from None
        return {'triage': self.show(item_id), 'reused_material': reused, 'material': page,
                'next_cursor': page['delivery']['next_cursor'], 'host_assessment_required': record.get('assessment') is None}

    def material(self, item_id, cursor=None):
        with self._lock(item_id, .2):
            with self.memory.connect() as db:
                record = self._load(db, item_id)
            if not record or not record['pages']:
                raise ReaderError('Prepare preview material first')
            if cursor is None:
                page = record['pages'][0]
            else:
                page = self.reader.continue_read(record['material_id'], cursor)
                self._validate_page(page, record['snapshot_id'],account=record['pages'][0]['delivery']['binding']['account_scope'])
                if not any(p['delivery']['page'] == page['delivery']['page'] for p in record['pages']):
                    record['pages'].append(page)
                    with self.memory.connect() as db:
                        self._save(db, item_id, record, 'material_page_delivered', {'page': page['delivery']['page']})
        return {'triage': self.show(item_id), 'material': page, 'next_cursor': page['delivery']['next_cursor']}

    def _assembled(self, record):
        pages = sorted(record['pages'], key=lambda p:p['delivery']['page'])
        count = pages[0]['delivery'].get('pages_in_snapshot', 1)
        if [p['delivery']['page'] for p in pages] != list(range(count)) or pages[-1]['delivery']['next_cursor']:
            raise ReaderError('Read the remaining frozen preview pages before assembling their evidence')
        if not any('material_parts' in page for page in pages):
            return pages[0]
        return restore([part for page in pages for part in page.get('material_parts', [])])

    def content(self, item_id):
        """Decode the public lossless format, never inspect Reader's private cache files."""
        with self._lock(item_id, .2):
            with self.memory.connect() as db:
                record = self._load(db, item_id)
            if not record or not record['pages']:
                raise ReaderError('Prepare preview material first')
            # Reader checks original asset identities again without acquiring network material.
            self.reader.continue_read(record['material_id'], record['snapshot_id'] + ':0')
            material = self._assembled(record)
        return {'triage': self.show(item_id), 'material': material, 'evidence_page': 'assembled',
                'delivery_observation': 'delivered_not_confirmed_observed', 'next_cursor': None}

    def submit(self, item_id, payload):
        if not isinstance(payload, dict):
            raise ReaderError('Triage assessment must be an object')
        with self._lock(item_id, .2):
            item = self.queue.show(item_id,include_material=False)
            with self.memory.connect() as db:
                record = self._load(db, item_id)
            if not record or not record['pages']:
                raise ReaderError('Prepare and inspect preview evidence before submitting')
            if record['item_fingerprint'] != fingerprint(item):
                raise ReaderError('Task or linked source changed; prepare a fresh assessment')
            if payload.get('snapshot_id') != record['snapshot_id']:
                raise ReaderError('Assessment does not match the prepared material snapshot')
            category = payload.get('content_type')
            if category not in CATEGORIES:
                raise ReaderError('Unknown content_type')
            clear = payload.get('type_clear')
            if type(clear) is not bool:
                raise ReaderError('type_clear must be true or false')
            reason = text_value(payload.get('type_reason'), 'type_reason')
            if not reason:
                raise ReaderError('Give a reason for the type judgment')
            intent = payload.get('intent')
            if not isinstance(intent, dict) or intent.get('kind') not in ('none', 'comment', 'request', 'uncertain'):
                raise ReaderError('intent needs kind=none/comment/request/uncertain')
            intent_reason = text_value(intent.get('reason', ''), 'intent reason')
            original = item['task']
            if not original and intent['kind'] != 'none':
                raise ReaderError('Cannot invent a comment/request absent from the original task')
            if original and intent['kind'] == 'none':
                raise ReaderError('Classify or retain uncertainty about the original note; do not discard it')
            if original and not intent_reason:
                raise ReaderError('Explain why the note is a comment/request or uncertain')
            evidence = payload.get('evidence', [])
            if not isinstance(evidence, list) or len(evidence)>30:
                raise ReaderError('evidence must be a list of at most 30 references')
            pages = {p['delivery']['page']: p for p in record['pages']}
            if any(e.get('page') == 'assembled' for e in evidence if isinstance(e, dict)):
                pages['assembled'] = self._assembled(record)
            content_evidence = False
            for entry in evidence:
                ref = entry.get('page') if isinstance(entry, dict) else None
                if not (type(ref) is int or ref == 'assembled') or ref not in pages:
                    raise ReaderError('Evidence must refer to a delivered preview page')
                page = pages[entry['page']]
                if entry.get('kind') == 'frame':
                    frames = page.get('frames', [])
                    if entry.get('frame_id') not in [f['id'] for f in frames]:
                        raise ReaderError('Unknown frame evidence ID')
                    if not text_value(entry.get('observation', ''), 'frame observation', 1000):
                        raise ReaderError('Describe the observed visual evidence')
                    content_evidence = True
                elif entry.get('kind') == 'caption':
                    quote = text_value(entry.get('quote', ''), 'caption quote', 200)
                    texts = [s.get('text', '') for s in (page.get('caption') or {}).get('segments', [])]
                    if not quote or not any(quote in text for text in texts):
                        raise ReaderError('Caption quote is absent from the delivered caption segments')
                    content_evidence = True
                else:
                    raise ReaderError('Evidence kind must be frame or caption; a title alone is not coarse reading')
            if clear and category != 'unknown' and not content_evidence:
                raise ReaderError('A clear content type needs observed frame or caption evidence')
            suggestion_reason = text_value(payload.get('suggestion_reason', ''), 'suggestion_reason')
            uncertainties = payload.get('uncertainties', [])
            if not isinstance(uncertainties, list) or any(not isinstance(v,str) or len(v)>1000 for v in uncertainties):
                raise ReaderError('uncertainties must be a list of short text entries')
            if intent['kind'] == 'request':
                status, suggestion = 'awaiting_user', None
            elif intent['kind'] == 'uncertain' or not clear or category == 'unknown' or category not in SCHEMES:
                status, suggestion = 'undetermined', None
            else:
                if not suggestion_reason:
                    raise ReaderError('A proposed scheme needs a content-grounded reason')
                status, suggestion = 'suggested', {**SCHEMES[category], 'reason': suggestion_reason}
            assessment = {'content_type': category, 'type_clear': clear, 'type_reason': reason,
                          'intent': {'kind': intent['kind'], 'reason': intent_reason,
                                     'comment': original if intent['kind']=='comment' else None,
                                     'request': original if intent['kind']=='request' else None,
                                     'original': original},
                          'recommendation': suggestion, 'uncertainties': uncertainties,
                          'evidence': evidence, 'actor': 'host', 'full_reading_completed': False}
            record.update(status=status, assessment=assessment)
            with self.memory.connect() as db:
                self.queue.record_intent(db,item_id,assessment['intent'])
                self._save(db, item_id, record, 'assessment_saved')
        return self.show(item_id)

    def history(self, item_id, *, before=None, limit=50):
        self.queue.show(item_id,include_material=False)
        bounded_int(limit, 'limit', 1, 100)
        if before is not None:
            bounded_int(before, 'before', 1, 9223372036854775807)
        with self.memory.connect() as db:
            rows = db.execute('SELECT id,created,kind,details FROM triage_events WHERE scope=? AND item_id=? ' +
                              ('AND id<? ' if before is not None else '') + 'ORDER BY id DESC LIMIT ?',
                              (self.scope, item_id, *((before,) if before is not None else ()), limit+1)).fetchall()
        events = [{**dict(row), 'details': json.loads(row['details'])} for row in rows[:limit]]
        return {'events': events, 'next_before': events[-1]['id'] if len(rows)>limit else None}
