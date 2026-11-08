"""Local account-scoped tasks and audit history; never acquires video material."""
import base64
import json
from pathlib import Path
import re
import time
import uuid

from video_reader.common import ReaderError, digest, read_json
from .store import Store

STATES = ('pending', 'paused', 'done', 'cancelled', 'archived')


def bounded_int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReaderError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def text_value(value, name, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ReaderError(f'{name} must be text of at most {maximum} characters')
    return value.strip()


def source_identity(value, *, allow_local=False):
    """Normalize known video URLs without resolving short links or reading local files."""
    from urllib.parse import parse_qs, urlparse
    value = text_value(value, 'source', 4000)
    bare = re.fullmatch(r'(BV[A-Za-z0-9]{10})(?:\?p=([1-9][0-9]*))?', value)
    if bare:
        return f'https://www.bilibili.com/video/{bare[1]}?p={bare[2] or 1}'
    if value.startswith(('www.bilibili.com/', 'bilibili.com/', 'b23.tv/', 'youtu.be/', 'www.youtube.com/', 'youtube.com/')):
        value = 'https://' + value
    parsed = urlparse(value)
    if allow_local and parsed.scheme not in ('http','https'):
        path=Path(value).expanduser().resolve()
        if not path.is_file():
            raise ReaderError('Local video file not found')
        return str(path)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ReaderError('Queue source must be a video URL or BV; local files are not inspected')
    host = parsed.hostname.lower()
    if host in ('www.bilibili.com', 'bilibili.com', 'm.bilibili.com'):
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10}|av[1-9][0-9]*)/?', parsed.path)
        if not match:
            raise ReaderError('Expected a Bilibili video URL')
        page = parse_qs(parsed.query).get('p', ['1'])[0]
        if not re.fullmatch(r'[1-9][0-9]*', page):
            raise ReaderError('Bilibili part must be positive')
        return f'https://www.bilibili.com/video/{match[1]}?p={int(page)}'
    if host == 'b23.tv' and re.fullmatch(r'/[A-Za-z0-9]+/?', parsed.path):
        return 'https://b23.tv/' + parsed.path.strip('/')
    if host in ('youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        video = (parsed.path.strip('/') if host == 'youtu.be' else
                 parsed.path.split('/')[2] if parsed.path.startswith(('/shorts/', '/live/')) else
                 parse_qs(parsed.query).get('v', [''])[0])
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
            return 'https://www.youtube.com/watch?v=' + video
        raise ReaderError('Expected a single YouTube video URL')
    if allow_local:
        return value
    raise ReaderError('Unsupported video link; retain the message for manual selection')


class Queue:
    def __init__(self, memory, cache_dir=None, *, material_lookup=None):
        self.memory, self.store, self.scope = memory, memory, memory.scope
        self.source_scope = memory.scope if type(memory) is not Store else None
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.material_lookup = material_lookup
        with memory.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS queue_items (
                    row_id INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, scope TEXT NOT NULL,
                    canonical TEXT NOT NULL, original_source TEXT NOT NULL, task TEXT NOT NULL,
                    title TEXT NOT NULL, state TEXT NOT NULL, priority INTEGER NOT NULL,
                    order_at REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, revision INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_order ON queue_items(scope,state,priority,order_at,row_id);
                CREATE INDEX IF NOT EXISTS queue_source ON queue_items(scope,canonical);
                CREATE TABLE IF NOT EXISTS queue_links (
                    scope TEXT NOT NULL, item_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    PRIMARY KEY(scope,item_id,message_id));
                CREATE TABLE IF NOT EXISTS queue_events (
                    id INTEGER PRIMARY KEY, scope TEXT NOT NULL, item_id TEXT, message_id TEXT,
                    created REAL NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, details TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_events_lookup ON queue_events(scope,item_id,id);
                CREATE TABLE IF NOT EXISTS queue_meta (scope TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS queue_origins (
                    scope TEXT NOT NULL,item_id TEXT NOT NULL,message_id TEXT NOT NULL,text TEXT NOT NULL,
                    seq INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(scope,item_id,message_id));
                CREATE TABLE IF NOT EXISTS task_annotations (
                    scope TEXT NOT NULL,item_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(scope,item_id));
                CREATE TABLE IF NOT EXISTS task_results (
                    id INTEGER PRIMARY KEY,scope TEXT NOT NULL,item_id TEXT NOT NULL,created REAL NOT NULL,record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_migrations(id TEXT PRIMARY KEY);
            ''')
            db.execute('INSERT OR IGNORE INTO queue_meta VALUES(?,0)', (self.scope,))
            from .legacy import import_origins
            import_origins(db,self.scope)

    @classmethod
    def from_settings(cls, config, config_path):
        from video_reader.reader import Reader
        reader=Reader(config_path)
        return cls(Store.from_settings(config,config_path),config['cache_dir'],material_lookup=reader.materials)

    def _event(self, db, kind, *, item_id=None, message_id=None, actor='conversation', **details):
        db.execute('INSERT INTO queue_events(scope,item_id,message_id,created,kind,actor,details) VALUES(?,?,?,?,?,?,?)',
                   (self.scope, item_id, message_id, time.time(), kind, actor, json.dumps(details, ensure_ascii=False)))

    def _bump(self, db):
        db.execute('UPDATE queue_meta SET revision=revision+1 WHERE scope=?', (self.scope,))

    def encode_cursor(self,*args,**kwargs):
        return self._cursor(*args,**kwargs)

    def decode_cursor(self,*args,**kwargs):
        return self._parse_cursor(*args,**kwargs)

    def describe_sources(self,items):
        return self._decorate(items)

    def _item(self, db, item_id):
        row = db.execute('SELECT * FROM queue_items WHERE scope=? AND id=?', (self.scope, item_id)).fetchone()
        if not row:
            raise ReaderError('Queue item not found in the current account')
        return dict(row)

    def _enqueue(self, db, source, task='', title='', *, message_id=None, order_at=None, new_task=False, actor='conversation'):
        canonical = source_identity(source,allow_local=True)
        task, title = text_value(task, 'task'), text_value(title, 'title', 1000)
        existing = None
        if message_id:
            existing = db.execute('SELECT q.* FROM queue_items q JOIN queue_links l ON l.item_id=q.id AND l.scope=q.scope '
                                  'WHERE q.scope=? AND l.message_id=? AND q.canonical=? AND q.task=? ORDER BY q.row_id LIMIT 1',
                                  (self.scope, message_id, canonical, task)).fetchone()
            if existing is None and actor=='inbox':
                # Sync replays the source message, not the user's later task
                # edits. Reuse its original link even after manual completion.
                existing = db.execute('SELECT q.* FROM queue_items q JOIN queue_links l ON l.item_id=q.id AND l.scope=q.scope '
                    'WHERE q.scope=? AND l.message_id=? AND q.canonical=? ORDER BY q.row_id LIMIT 1',
                    (self.scope,message_id,canonical)).fetchone()
        if existing is None and not new_task:
            existing = db.execute("SELECT * FROM queue_items WHERE scope=? AND canonical=? AND task=? "
                                  "AND state IN ('pending','paused') ORDER BY row_id LIMIT 1",
                                  (self.scope, canonical, task)).fetchone()
        now = time.time()
        created = existing is None
        if created:
            item_id = 'q_' + uuid.uuid4().hex
            db.execute('INSERT INTO queue_items(id,scope,canonical,original_source,task,title,state,priority,order_at,created,updated,revision) '
                       "VALUES(?,?,?,?,?,?,'pending',0,?,?,?,1)",
                       (item_id, self.scope, canonical, source, task, title, order_at if order_at is not None else now, now, now))
            self._event(db, 'enqueued', item_id=item_id, message_id=message_id, actor=actor,
                        source=source, canonical=canonical, task=task, title=title)
            self._bump(db)
        else:
            item_id = existing['id']
        if message_id:
            link = db.execute('INSERT OR IGNORE INTO queue_links VALUES(?,?,?)', (self.scope, item_id, message_id))
            if link.rowcount:
                self._event(db, 'message_linked' if created else 'duplicate_submission', item_id=item_id,
                            message_id=message_id, actor=actor)
                self._bump(db)
        elif not created:
            self._event(db, 'duplicate_submission', item_id=item_id, actor=actor)
        return {'item_id': item_id, 'created': created, 'duplicate': not created}

    def enqueue(self, source, task='', title='', *, new_task=False):
        if type(new_task) is not bool:
            raise ReaderError('new_task must be true or false')
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = self._enqueue(db, source, task, title, new_task=new_task)
        return {**result, 'item': self.show(result['item_id']), 'video_reading_started': False}

    def show(self, item_id, *, include_material=True):
        with self.memory.connect() as db:
            item = self._item(db, item_id)
            rows = db.execute('SELECT payload FROM queue_origins WHERE scope=? AND item_id=? ORDER BY seq', (self.scope,item_id)).fetchall()
            annotation=db.execute('SELECT payload FROM task_annotations WHERE scope=? AND item_id=?',(self.scope,item_id)).fetchone()
            latest=db.execute('SELECT record FROM task_results WHERE scope=? AND item_id=? ORDER BY id DESC LIMIT 1',(self.scope,item_id)).fetchone()
        note=json.loads(annotation[0]) if annotation else {'kind':'unclassified','original':item['task'],'comment':None,'request':None}
        if note.get('original')!=item['task']:
            note={'kind':'unclassified','original':item['task'],'comment':None,'request':None}
        return {**(self._decorate([item])[0] if include_material else item), 'messages': [json.loads(row[0]) for row in rows], 'note':note,
                'latest_result':json.loads(latest[0]) if latest else None,
                'completion_basis': ('explicit_task_result' if latest else 'manual') if item['state'] == 'done' else None,
                'reader_completion': 'not_inferred'}

    def enqueue_in_transaction(self,db,*args,**kwargs):
        return self._enqueue(db,*args,**kwargs)

    def link_origin(self,db,item_id,origin):
        self._item(db,item_id)
        data=dict(origin)
        message_id=text_value(data.get('id'),'origin id',200)
        existed=db.execute('SELECT 1 FROM queue_origins WHERE scope=? AND item_id=? AND message_id=?',
                           (self.scope,item_id,message_id)).fetchone()
        db.execute('INSERT INTO queue_origins(scope,item_id,message_id,text,seq,payload) VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(scope,item_id,message_id) DO UPDATE SET text=excluded.text,seq=excluded.seq,payload=excluded.payload',
            (self.scope,item_id,message_id,data.get('text',''),data.get('seq',0),json.dumps(data,ensure_ascii=False)))
        if not existed:
            self._event(db,'message_received',item_id=item_id,message_id=message_id,actor='intake',origin=data)

    def revise_origin(self,db,origin):
        rows=db.execute('SELECT item_id FROM queue_origins WHERE scope=? AND message_id=?',(self.scope,origin['id'])).fetchall()
        for row in rows:
            old=db.execute('SELECT payload FROM queue_origins WHERE scope=? AND item_id=? AND message_id=?',(self.scope,row[0],origin['id'])).fetchone()
            self.link_origin(db,row[0],origin)
            self._event(db,'message_revised',item_id=row[0],message_id=origin['id'],actor='inbox',
                        previous=json.loads(old[0]),current=origin)

    def linked_items(self,db,message_id):
        return [r[0] for r in db.execute('SELECT item_id FROM queue_links WHERE scope=? AND message_id=?',(self.scope,message_id))]

    def record_intent(self,db,item_id,intent):
        self._item(db,item_id)
        db.execute('INSERT INTO task_annotations(scope,item_id,payload) VALUES(?,?,?) '
                   'ON CONFLICT(scope,item_id) DO UPDATE SET payload=excluded.payload',
                   (self.scope,item_id,json.dumps(intent,ensure_ascii=False)))

    def record_result(self,item_id,payload,*,complete=False,expected_revision=None,run_id=None):
        import hashlib
        if not isinstance(payload,dict) or type(complete) is not bool:
            raise ReaderError('Result must be an object; complete must be boolean')
        summary=text_value(payload.get('summary',''),'result summary',1000)
        paths=payload.get('artifacts')
        if not summary or not isinstance(paths,list) or not 1<=len(paths)<=20:
            raise ReaderError('Result needs summary and 1..20 artifact paths')
        if type(payload.get('full_video_verified',False)) is not bool:
            raise ReaderError('full_video_verified must be boolean')
        artifacts=[]
        for value in paths:
            path=Path(text_value(value,'artifact path',4000)).resolve()
            if not path.is_file(): raise ReaderError('Result artifact not found: '+str(path))
            artifacts.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        record={**payload,'summary':summary,'artifacts':artifacts,'task_complete':complete,
                'full_video_verified':payload.get('full_video_verified',False)}
        if run_id:
            record['run_id'] = run_id
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            item=self._item(db,item_id)
            if run_id:
                run = db.execute('SELECT * FROM task_runs WHERE scope=? AND id=? AND item_id=?',
                                 (self.scope,run_id,item_id)).fetchone()
                if not run:
                    raise ReaderError('Task run does not belong to this task library/item')
                if run['status']=='superseded':
                    raise ReaderError('Superseded task run cannot commit a result')
                if run['result_id']:
                    return self.show(item_id)
                if item['state'] != 'pending' or digest([item['canonical'],item['task']]) != run['task_identity']:
                    raise ReaderError('Task changed or is no longer pending; old run cannot complete it')
                run_payload=json.loads(run['payload'])
                if run_payload.get('background_token'):
                    from .control import ControlWait,in_window
                    control=db.execute('SELECT * FROM task_background_control WHERE scope=?',(self.scope,)).fetchone()
                    permit=db.execute('SELECT status,run_id FROM task_background_slots WHERE scope=? AND token=?',
                                      (self.scope,run_payload['background_token'])).fetchone()
                    if not control or not permit or permit['run_id']!=run_id or permit['status'] not in ('active','waiting'):
                        raise ReaderError('Background permit is no longer active at result commit')
                    policy=json.loads(control['policy'])
                    if not policy['enabled'] or not policy['read_enabled'] or control['paused_reason'] or control['hold_until']>time.time() or not in_window(policy,time.time()):
                        raise ControlWait('policy_changed_before_commit')
            if expected_revision is not None and item['revision'] != expected_revision:
                raise ReaderError('Task revision changed before result commit; resume against current task state')
            db.execute('INSERT INTO task_results(scope,item_id,created,record) VALUES(?,?,?,?)',
                       (self.scope,item_id,time.time(),json.dumps(record,ensure_ascii=False,allow_nan=False)))
            result_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            self._event(db,'result_saved',item_id=item_id,result=record)
            if complete and item['state']!='done':
                db.execute("UPDATE queue_items SET state='done',updated=?,revision=revision+1 WHERE scope=? AND id=?",(time.time(),self.scope,item_id))
                self._event(db,'state_changed',item_id=item_id,previous=item['state'],current='done',basis='explicit_task_result')
                self._bump(db)
            if run_id:
                db.execute('UPDATE task_runs SET status=?,result_id=?,updated=? WHERE scope=? AND id=?',
                           ('completed' if complete else 'needs_attention',result_id,time.time(),self.scope,run_id))
        return self.show(item_id)

    def update(self, item_id, *, state=None, priority=None, task=None, reason='', expected_revision=None, first=False):
        if state is not None and state not in STATES:
            raise ReaderError('state must be pending, paused, done, cancelled or archived')
        if priority is not None:
            bounded_int(priority, 'priority', -1000000000, 1000000000)
        if expected_revision is not None:
            bounded_int(expected_revision, 'expected_revision', 1, 2147483647)
        reason = text_value(reason, 'reason')
        if task is not None:
            task = text_value(task, 'task')
        if not first and state is None and priority is None and task is None:
            raise ReaderError('Choose a state, priority or task change')
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self._item(db, item_id)
            if expected_revision is not None and old['revision'] != expected_revision:
                raise ReaderError('Queue item changed; inspect its current revision before updating')
            if first:
                if old['state'] != 'pending':
                    raise ReaderError('Only pending items can move to the front; resume paused items explicitly')
                priority = db.execute("SELECT COALESCE(MAX(priority),0)+1 FROM queue_items WHERE scope=? AND state='pending'",
                                      (self.scope,)).fetchone()[0]
            changes = {key: value for key, value in (('state', state), ('priority', priority), ('task', task))
                       if value is not None and value != old[key]}
            if changes:
                db.execute('UPDATE queue_items SET ' + ','.join(key+'=?' for key in changes) + ',updated=?,revision=revision+1 '
                           'WHERE scope=? AND id=?', (*changes.values(), time.time(), self.scope, item_id))
                self._event(db, 'prioritized' if first else 'updated', item_id=item_id,
                            before={key: old[key] for key in changes}, after=changes, reason=reason,
                            completion_basis='manual' if state == 'done' else None)
                self._bump(db)
        return self.show(item_id)

    def _cursor(self, kind, filters, data):
        value = {'context': digest([self.scope, kind, filters]), **data}
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')

    def _parse_cursor(self, cursor, kind, filters):
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if value.get('context') != digest([self.scope, kind, filters]):
                raise ValueError()
            return value
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise ReaderError('Invalid cursor for this account/query') from None

    def list(self, state='pending', *, query='', limit=20, cursor=None):
        if state != 'all' and state not in STATES:
            raise ReaderError('Unknown queue state')
        bounded_int(limit, 'limit', 1, 100)
        query = text_value(query, 'query', 200)
        filters = [state, query]
        page = self._parse_cursor(cursor, 'queue', filters)
        with self.memory.connect() as db:
            db.execute('BEGIN')
            revision = db.execute('SELECT revision FROM queue_meta WHERE scope=?', (self.scope,)).fetchone()[0]
            if page and page.get('revision') != revision:
                raise ReaderError('Queue changed while paging; restart the list to see the current order')
            where, params = ['scope=?'], [self.scope]
            if state != 'all':
                where.append('state=?')
                params.append(state)
            if query:
                from video_reader.content import normalized
                db.create_function('task_search',1,lambda value:normalized(value or ''))
                where.append("instr(task_search(title||' '||canonical||' '||task),task_search(?))>0")
                params.append(query)
            if page:
                last = page.get('last')
                if not isinstance(last, list) or len(last) != 3 or any(type(v) not in (int, float) for v in last):
                    raise ReaderError('Invalid queue cursor')
                where.append('(priority<? OR (priority=? AND (order_at>? OR (order_at=? AND row_id>?))))')
                params.extend((last[0], last[0], last[1], last[1], last[2]))
            rows = db.execute('SELECT * FROM queue_items WHERE ' + ' AND '.join(where) +
                              ' ORDER BY priority DESC,order_at,row_id LIMIT ?', (*params, limit+1)).fetchall()
            counts = {row[0]: row[1] for row in db.execute('SELECT state,count(*) FROM queue_items WHERE scope=? GROUP BY state', (self.scope,))}
        items = [dict(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = self._cursor('queue', filters, {'revision': revision, 'last': [last['priority'], last['order_at'], last['row_id']]})
        return {'items': self._decorate(items), 'counts': counts, 'revision': revision, 'next_cursor': next_cursor,
                'video_reading_started': False}

    def search(self,query,*,limit=20,cursor=None):
        """Search registered task/result material, not arbitrary files or private Inbox."""
        import hashlib
        from video_reader.content import normalized
        query=text_value(query,'query',200)
        needle=normalized(query)
        if not needle: raise ReaderError('History query must contain letters or numbers')
        bounded_int(limit,'limit',1,100)
        page=self._parse_cursor(cursor,'material_search',[query])
        with self.store.connect() as db:
            db.execute('BEGIN')
            revision=db.execute('SELECT revision FROM queue_meta WHERE scope=?',(self.scope,)).fetchone()[0]
            result_revision=db.execute('SELECT COALESCE(max(id),0) FROM task_results WHERE scope=?',(self.scope,)).fetchone()[0]
            if page and [revision,result_revision]!=page.get('revision'):
                raise ReaderError('Task/results changed while searching; restart the query')
            items=[dict(r) for r in db.execute('SELECT * FROM queue_items WHERE scope=? ORDER BY updated DESC,row_id DESC',(self.scope,))]
            records=db.execute('SELECT * FROM task_results WHERE scope=? ORDER BY id DESC',(self.scope,)).fetchall()
        by_item={}
        for row in records:
            by_item.setdefault(row['item_id'],[]).append(json.loads(row['record']))
        hits=[]
        for item in items:
            fields=[key for key in ('title','task','canonical') if needle in normalized(item[key])]
            matches=[]
            results=by_item.get(item['id'],[])
            for index,result in enumerate(results):
                if needle in normalized(str(result.get('summary',''))+' '+str(result.get('task_scope',''))):
                    fields.append('result_summary')
                for artifact in result.get('artifacts',[]):
                    path=Path(artifact['path'])
                    if not path.is_file():
                        validity='missing'
                    elif path.stat().st_size>2_000_000:
                        validity='not_text_indexed_size'
                    else:
                        raw=path.read_bytes()
                        validity='valid' if hashlib.sha256(raw).hexdigest()==artifact['sha256'] else 'changed'
                        if validity=='valid' and path.suffix.lower() in ('.md','.txt'):
                            text=raw.decode('utf-8-sig',errors='replace')
                            if needle in normalized(text):
                                fields.append('artifact_text')
                                line=next((line for line in text.splitlines() if needle in normalized(line)),'')
                                matches.append({'path':str(path),'snippet':line[:280],
                                    'snippet_complete':len(line)<=280,'result_history_index':index})
                    if index==0:
                        artifact['current_validity']=validity
            if fields:
                hits.append({'item_id':item['id'],'title':item['title'],'task':item['task'],
                    'canonical':item['canonical'],'state':item['state'],'matched_fields':sorted(set(fields)),
                    'latest_result':results[0] if results else None,'artifact_matches':matches,
                    'next_steps':{'show_task':item['id'],'content_target':item['canonical'],
                                  'artifact_paths':[a['path'] for a in (results[0].get('artifacts',[]) if results else [])]}})
        hits.sort(key=lambda hit:bool(hit['latest_result']),reverse=True)
        offset=page.get('offset',0) if page else 0
        bounded_int(offset,'search cursor offset',0,2147483647)
        selected=hits[offset:offset+limit]
        following=offset+len(selected)
        return {'query':query,'items':selected,'total_matches':len(hits),
            'next_cursor':self._cursor('material_search',[query],{'revision':[revision,result_revision],'offset':following}) if following<len(hits) else None,
            'search_scope':'task fields, saved result summaries, hash-valid registered Markdown/text artifacts up to 2 MB',
            'artifact_checks':'live; changed/missing files are not treated as their saved original',
            'video_reading_started':False}

    def _decorate(self, items):
        from video_reader.catalog import lookup
        sources=list({item['canonical'] for item in items})
        materials=(self.material_lookup(sources) if self.material_lookup else
                   lookup(self.cache_dir,sources,scopes={source:self.scope for source in sources}))
        sessions={source:[r['session_id'] for r in rows] for source,rows in materials.items()}
        with self.memory.connect() as db:
            for item in items:
                related = db.execute('SELECT id,state,task FROM queue_items WHERE scope=? AND canonical=? AND id<>? '
                                     'ORDER BY row_id DESC LIMIT 5', (self.scope, item['canonical'], item.get('id', ''))).fetchall()
                item['related_tasks'] = [dict(row) for row in related]
                item['existing_material'] = {'session_ids': sessions.get(item['canonical'], []), 'reading_completed': 'not_inferred'}
        return items

    def history(self, *, item_id=None, query='', limit=20, cursor=None):
        bounded_int(limit, 'limit', 1, 100)
        query = text_value(query, 'query', 200)
        filters = [item_id, query]
        page = self._parse_cursor(cursor, 'events', filters)
        with self.memory.connect() as db:
            if item_id:
                self._item(db, item_id)
            where, params = ['e.scope=?'], [self.scope]
            if item_id:
                where.append('(e.item_id=? OR (e.item_id IS NULL AND e.message_id IN '
                             '(SELECT message_id FROM queue_links WHERE scope=? AND item_id=?)))')
                params.extend((item_id, self.scope, item_id))
            if query:
                where.append("instr(lower(e.details||' '||COALESCE(q.canonical,'')||' '||COALESCE(q.task,'')||' '||COALESCE(m.text,'')),lower(?))>0")
                params.append(query)
            if page:
                bounded_int(page.get('before'), 'history cursor', 1, 9223372036854775807)
                where.append('e.id<?')
                params.append(page['before'])
            rows = db.execute('SELECT e.*,q.canonical,q.state AS current_state,m.text AS message_text '
                              'FROM queue_events e LEFT JOIN queue_items q ON q.id=e.item_id AND q.scope=e.scope '
                              'LEFT JOIN (SELECT scope,message_id,max(text) AS text FROM queue_origins GROUP BY scope,message_id) m ON m.message_id=e.message_id AND m.scope=e.scope WHERE ' + ' AND '.join(where) +
                              ' ORDER BY e.id DESC LIMIT ?', (*params, limit+1)).fetchall()
        events = [{**dict(row), 'details': json.loads(row['details'])} for row in rows[:limit]]
        return {'events': events, 'next_cursor': self._cursor('events', filters, {'before': events[-1]['id']}) if len(rows)>limit else None}
