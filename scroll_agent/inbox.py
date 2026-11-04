"""Explicit private Inbox synchronization, queue intake and retained message history."""
import json
import re
import time
import uuid
from urllib.parse import urlencode

from filelock import FileLock, Timeout

from video_reader.common import ReaderError, digest, read_json, write_json
from video_reader.platform import Platform, PlatformError, credentials
from .queue import bounded_int, source_identity, text_value
from .runtime import error_details

ENDPOINT = 'https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs'
URLS = re.compile(r'https?://[^\s<>"，。！？；（）]+')
BARE_BV = re.compile(r'(?<![A-Za-z0-9])(BV[A-Za-z0-9]{10}(?:\?p=[0-9]+)?)(?![A-Za-z0-9])')


def configured_sender(reader):
    """Pin the old default once; outbound recipient changes never change intake."""
    from pathlib import Path
    agent=reader.config.get('agent') or {}
    explicit=(agent.get('inbox') or {}).get('sender_uid')
    if explicit is not None: return explicit
    root=(reader.config_path.parent/agent.get('directory','data/agent')).resolve()
    path=root/'inbox-settings.json'
    if path.is_file(): return read_json(path)['sender_uid']
    from reading_tasks.store import Store
    store=Store.from_settings(reader.config,reader.config_path)
    with store.connect() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='inbox_feeds'").fetchone()
        peers=[r[0] for r in db.execute('SELECT DISTINCT peer FROM inbox_feeds')] if exists else []
    previous=peers[0] if len(peers)==1 else (agent.get('delivery') or {}).get('recipient_uid')
    if previous is None: raise ReaderError('Configure agent.inbox.sender_uid before using Inbox')
    write_json(path,{'sender_uid':previous,'migrated_from':'retained_inbox' if len(peers)==1 else 'legacy_delivery_recipient'})
    return previous


def extract_text(text):
    sources, spans = [], []
    bare_text = text
    url_spans = []
    for match in URLS.finditer(text):
        url_spans.append((match.start(), match.end()))
        value = match[0].rstrip('.,;!?)）]】')
        try:
            canonical = source_identity(value)
        except ReaderError:
            continue
        sources.append({'source': value, 'canonical': canonical, 'title': ''})
        spans.append((match.start(), match.start()+len(value)))
    for start, end in reversed(url_spans):
        bare_text = bare_text[:start] + ' ' * (end-start) + bare_text[end:]
    for match in BARE_BV.finditer(bare_text):
        try:
            canonical = source_identity(match[0])
        except ReaderError:
            continue
        sources.append({'source': match[0], 'canonical': canonical, 'title': ''})
        spans.append((match.start(), match.end()))
    note = text
    for start, end in sorted(spans, reverse=True):
        note = note[:start] + ' ' * (end-start) + note[end:]
    note = note.strip()
    unique = {item['canonical']: item for item in sources}
    return list(unique.values()), note


def parse_content(row):
    try:
        content = row.get('content', '{}')
        content = json.loads(content) if isinstance(content, str) else content
    except (ValueError, TypeError):
        return {'text': '', 'videos': [], 'parse_status': 'invalid_content_json'}
    if row.get('msg_type') == 5 or row.get('msg_status', 0) != 0:
        return {'text': '', 'videos': [], 'parse_status': 'recalled_or_unavailable'}
    if not isinstance(content, dict):
        return {'text': '', 'videos': [], 'parse_status': 'unsupported_content'}
    videos, task, text = [], '', ''
    if row.get('msg_type') == 1:
        text = content.get('content', '')
        if not isinstance(text, str):
            return {'text': '', 'videos': [], 'parse_status': 'invalid_text'}
        videos, task = extract_text(text)
    elif row.get('msg_type') == 7 and content.get('source') == 5:
        title = content.get('title', '')
        text = title if isinstance(title, str) else ''
        source = None
        if isinstance(content.get('url'), str):
            try:
                candidate = source_identity(content['url'])
                if '/video/' in candidate:
                    source = candidate
            except ReaderError:
                pass
        if source is None and re.fullmatch(r'BV[A-Za-z0-9]{10}', str(content.get('bvid', ''))):
            source = content['bvid']
        if source is None and str(content.get('id', '')).isdigit() and int(content['id']) > 0:
            source = 'https://www.bilibili.com/video/av' + str(content['id'])
        attached = content.get('attach_msg')
        if isinstance(attached, str):
            task = attached
        elif isinstance(attached, dict):
            task = attached.get('content') or attached.get('text') or ''
        if not isinstance(task, str):
            task = ''
        if source:
            videos = [{'source': source, 'canonical': source_identity(source), 'title': text}]
    else:
        return {'text': '', 'videos': [], 'parse_status': 'unsupported_message_type'}
    if len(task) > 4000 or any(len(item['title']) > 1000 for item in videos):
        return {'text': text, 'videos': videos, 'parse_status': 'task_or_title_too_long'}
    return {'text': text, 'videos': [{**item, 'task': task.strip()} for item in videos],
            'parse_status': 'video' if videos else 'text_only'}


class Inbox:
    def __init__(self, queue, peer, *, config=None, platform=None):
        if not re.fullmatch(r'[1-9][0-9]{0,19}', str(peer or '')):
            raise ReaderError('Configure the Inbox sender before using Inbox')
        self.queue, self.memory = queue, queue.store
        if platform is not None:
            self.scope=platform.scope
        else:
            try:
                self.scope=credentials(config)['account_marker']
            except PlatformError as error:
                if error.code not in ('login_required','managed_login_disabled'): raise
                with self.memory.connect() as db:
                    present=db.execute("SELECT 1 FROM sqlite_master WHERE name='inbox_feeds'").fetchone()
                    scopes=[r[0] for r in db.execute('SELECT DISTINCT scope FROM inbox_feeds WHERE peer=?',(str(peer),))] if present else []
                self.scope=queue.source_scope or (scopes[0] if len(scopes)==1 else None)
                if not self.scope: raise ReaderError('No saved Inbox account; login is required for first sync') from None
        self.peer, self.config, self.platform = str(peer), config, platform
        self.lock_path = self.memory.directory / ('inbox-' + digest([self.scope, self.peer]) + '.lock')
        with self.memory.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS inbox_feeds (
                    scope TEXT NOT NULL, peer TEXT NOT NULL, activated_at INTEGER NOT NULL,
                    live_seq INTEGER, history_before INTEGER, history_complete INTEGER NOT NULL DEFAULT 0,
                    pending_before INTEGER, pending_lower INTEGER, pending_upper INTEGER,
                    status TEXT NOT NULL, started REAL, updated REAL NOT NULL, last_error TEXT,
                    PRIMARY KEY(scope,peer));
                CREATE TABLE IF NOT EXISTS inbox_messages (
                    row_id INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, scope TEXT NOT NULL, peer TEXT NOT NULL,
                    message_key TEXT NOT NULL, seq INTEGER NOT NULL, sent_at INTEGER NOT NULL,
                    msg_type INTEGER NOT NULL, period TEXT NOT NULL, parse_status TEXT NOT NULL,
                    text TEXT NOT NULL, videos TEXT NOT NULL, raw TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    received REAL NOT NULL, updated REAL NOT NULL, UNIQUE(scope,peer,message_key));
                CREATE INDEX IF NOT EXISTS inbox_history ON inbox_messages(scope,peer,row_id);
                CREATE TABLE IF NOT EXISTS inbox_events (
                    id INTEGER PRIMARY KEY,scope TEXT NOT NULL,item_id TEXT,message_id TEXT,
                    created REAL NOT NULL,kind TEXT NOT NULL,actor TEXT NOT NULL,details TEXT NOT NULL);
            ''')
            db.execute("INSERT OR IGNORE INTO inbox_events SELECT * FROM queue_events WHERE actor='inbox' AND item_id IS NULL")

    def _event(self,db,kind,*,item_id=None,message_id=None,actor='inbox',**details):
        db.execute('INSERT INTO inbox_events(scope,item_id,message_id,created,kind,actor,details) VALUES(?,?,?,?,?,?,?)',
            (self.scope,item_id,message_id,time.time(),kind,actor,json.dumps(details,ensure_ascii=False)))

    def _origin(self,db,message_id):
        row=db.execute('SELECT * FROM inbox_messages WHERE scope=? AND id=?',(self.scope,message_id)).fetchone()
        return {**{key:row[key] for key in ('id','peer','message_key','seq','sent_at','msg_type','period','parse_status','text')},
                'provider':'bilibili_dm','account_scope':self.scope}


    def _feed(self, db):
        row = db.execute('SELECT * FROM inbox_feeds WHERE scope=? AND peer=?', (self.scope, self.peer)).fetchone()
        return dict(row) if row else None

    def _set_feed(self, db, **fields):
        db.execute('UPDATE inbox_feeds SET ' + ','.join(key+'=?' for key in fields) + ' WHERE scope=? AND peer=?',
                   (*fields.values(), self.scope, self.peer))

    def activate(self):
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._feed(db):
                now = int(time.time())
                db.execute('INSERT INTO inbox_feeds(scope,peer,activated_at,status,updated) VALUES(?,?,?,\'ready\',?)',
                           (self.scope, self.peer, now, time.time()))
                self._event(db, 'inbox_activated', actor='inbox', peer=self.peer,
                                  activated_at=now, old_messages='history_only', new_messages='enqueue_on_sync')

    def status(self):
        # Serialize observers so probing a free sync lock cannot look like a worker.
        with FileLock(str(self.lock_path)+'.inspect', timeout=2):
            owner = FileLock(str(self.lock_path), timeout=0)
            try:
                owner.acquire()
            except Timeout:
                alive = True
            else:
                alive = False
            try:
                with self.memory.connect() as db:
                    feed = self._feed(db)
                    counts = {row[0]: row[1] for row in db.execute('SELECT period,count(*) FROM inbox_messages WHERE scope=? AND peer=? GROUP BY period',
                                                                   (self.scope, self.peer))}
            finally:
                if not alive:
                    owner.release()
        if feed:
            feed['recorded_status'] = feed['status']
            if feed['status'] == 'syncing' and not alive:
                feed['status'] = 'interrupted'
            if feed.get('last_error'):
                feed['last_error'] = json.loads(feed['last_error'])
        return {'initialized': feed is not None, 'feed': feed, 'message_counts': counts, 'sync_running': alive,
                'sync_mode': 'explicit', 'old_messages': 'history_only', 'new_messages': 'enqueue_on_sync',
                'video_reading_started': False, 'messages_sent': 0}

    def _normalize(self, row, sender):
        if str(row.get('sender_uid')) != self.peer:
            return None
        if str(row.get('receiver_id')) != str(sender) or row.get('receiver_type') != 1:
            return None
        seq = bounded_int(row.get('msg_seqno'), 'message sequence', 1, 9223372036854775807)
        sent_at = bounded_int(row.get('timestamp'), 'message timestamp', 0, 9223372036854775807)
        key = row.get('msg_key')
        key = str(key) if type(key) in (int, str) and str(key) else 'seq:' + str(seq)
        return {'message_key': key, 'seq': seq, 'sent_at': sent_at, 'msg_type': row.get('msg_type', 0),
                'raw': json.dumps(row, ensure_ascii=False), 'payload_hash': digest(row), **parse_content(row)}

    def _store_page(self, db, rows, sender, fields):
        feed = self._feed(db)
        summary = {'messages_added': 0, 'messages_updated': 0, 'duplicate_messages': 0, 'tasks_created': 0, 'tasks_reused': 0}
        for raw in sorted(rows, key=lambda row: row['msg_seqno']):
            message = self._normalize(raw, sender)
            if message is None:
                continue
            old = db.execute('SELECT * FROM inbox_messages WHERE scope=? AND peer=? AND message_key=?',
                             (self.scope, self.peer, message['message_key'])).fetchone()
            if old and old['payload_hash'] == message['payload_hash']:
                summary['duplicate_messages'] += 1
                continue
            now = time.time()
            if old:
                message_id, period = old['id'], old['period']
                db.execute('UPDATE inbox_messages SET parse_status=?,text=?,videos=?,raw=?,payload_hash=?,updated=? WHERE scope=? AND id=?',
                           (message['parse_status'], message['text'], json.dumps(message['videos'], ensure_ascii=False),
                            message['raw'], message['payload_hash'], now, self.scope, message_id))
                self._event(db, 'message_revised', message_id=message_id, actor='inbox',
                                  previous_raw=json.loads(old['raw']), current_raw=raw)
                summary['messages_updated'] += 1
                self.queue.revise_origin(db,self._origin(db,message_id))
            else:
                message_id = 'im_' + uuid.uuid4().hex
                period = 'new' if message['sent_at'] >= feed['activated_at'] else 'historical'
                db.execute('INSERT INTO inbox_messages(id,scope,peer,message_key,seq,sent_at,msg_type,period,parse_status,text,videos,raw,payload_hash,received,updated) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (message_id, self.scope, self.peer, message['message_key'], message['seq'], message['sent_at'], message['msg_type'],
                            period, message['parse_status'], message['text'], json.dumps(message['videos'], ensure_ascii=False),
                            message['raw'], message['payload_hash'], now, now))
                self._event(db, 'message_received', message_id=message_id, actor='inbox', peer=self.peer,
                                  period=period, parse_status=message['parse_status'], message_key=message['message_key'])
                summary['messages_added'] += 1
            if period == 'new' and message['parse_status'] == 'video':
                for video in message['videos']:
                    result = self.queue.enqueue_in_transaction(db, video['source'], video['task'], video['title'], message_id=message_id,
                                                 order_at=message['sent_at'], actor='inbox')
                    self.queue.link_origin(db,result['item_id'],self._origin(db,message_id))
                    summary['tasks_created' if result['created'] else 'tasks_reused'] += 1
        self._set_feed(db, updated=time.time(), **fields)
        return summary

    def _page(self, before, size):
        params = {'talker_id': self.peer, 'session_type': 1, 'size': size, 'build': 0, 'mobi_app': 'web'}
        if before is not None:
            # begin_seqno is the lower bound (newer messages); end_seqno pages backwards.
            params['end_seqno'] = before
        response = self.platform.request(ENDPOINT + '?' + urlencode(params))
        data = response.get('data') if isinstance(response, dict) else None
        if not isinstance(data, dict) or data.get('has_more') not in (0, 1) or 'messages' not in data:
            raise ReaderError('Inbox page has no reliable messages/has_more fields; cursor retained')
        rows = data['messages']
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ReaderError('Inbox messages is not an array; cursor retained')
        for row in rows:
            if not isinstance(row, dict):
                raise ReaderError('Malformed Inbox message; cursor retained')
            bounded_int(row.get('msg_seqno'), 'message sequence', 1, 9223372036854775807)
        if not rows and data['has_more']:
            raise ReaderError('Inbox returned an empty page with has_more; cursor retained')
        if before is not None and rows and min(row['msg_seqno'] for row in rows) >= before:
            raise ReaderError('Inbox pagination did not advance; cursor retained')
        return rows, bool(data['has_more'])

    def sync(self, *, max_pages=3, page_size=50):
        bounded_int(max_pages, 'max_pages', 1, 10)
        bounded_int(page_size, 'page_size', 1, 100)
        totals = {'pages': 0, 'messages_added': 0, 'messages_updated': 0, 'duplicate_messages': 0, 'tasks_created': 0, 'tasks_reused': 0}
        try:
            # A query observer may briefly hold this lock, but never a network operation.
            with FileLock(str(self.lock_path), timeout=.2):
                self.activate()
                with self.memory.connect() as db:
                    self._set_feed(db, status='syncing', started=time.time(), updated=time.time(), last_error=None)
                    self._event(db, 'sync_started', actor='inbox', peer=self.peer)
                try:
                    self.platform = self.platform or Platform(self.config, write_endpoints=())
                    if self.platform.scope != self.scope:
                        raise ReaderError('Component account changed; reopen the Inbox context before syncing')
                    head_checked = False
                    while totals['pages'] < max_pages:
                        with self.memory.connect() as db:
                            feed = self._feed(db)
                        if feed['pending_before'] is not None:
                            mode, before = 'catchup', feed['pending_before']
                        elif not head_checked:
                            mode, before, head_checked = 'head', None, True
                        elif not feed['history_complete'] and feed['history_before'] is not None:
                            mode, before = 'history', feed['history_before']
                        else:
                            break
                        rows, more = self._page(before, page_size)
                        seqs = [row['msg_seqno'] for row in rows]
                        minimum, maximum = (min(seqs), max(seqs)) if seqs else (0, 0)
                        fields = {}
                        if feed['live_seq'] is None:
                            fields.update(live_seq=maximum, history_before=minimum if more else None, history_complete=int(not more))
                        elif mode == 'head':
                            if maximum > feed['live_seq']:
                                if more and minimum > feed['live_seq']:
                                    fields.update(pending_before=minimum, pending_lower=feed['live_seq'], pending_upper=maximum)
                                else:
                                    fields['live_seq'] = maximum
                        elif mode == 'catchup':
                            if not more or minimum <= feed['pending_lower']:
                                fields.update(live_seq=feed['pending_upper'], pending_before=None, pending_lower=None, pending_upper=None)
                            else:
                                fields['pending_before'] = minimum
                        else:
                            fields.update(history_before=minimum if more else None, history_complete=int(not more))
                        with self.memory.connect() as db:
                            db.execute('BEGIN IMMEDIATE')
                            counts = self._store_page(db, rows, self.platform.sender, fields)
                        totals['pages'] += 1
                        for key, count in counts.items():
                            totals[key] += count
                    with self.memory.connect() as db:
                        feed = self._feed(db)
                        partial = feed['pending_before'] is not None or not feed['history_complete']
                        self._set_feed(db, status='partial' if partial else 'ready', updated=time.time())
                        self._event(db, 'sync_finished', actor='inbox', peer=self.peer, partial=partial, **totals)
                except BaseException as error:
                    with self.memory.connect() as db:
                        self._set_feed(db, status='failed' if isinstance(error, Exception) else 'interrupted',
                                       updated=time.time(), last_error=json.dumps(error_details(error), ensure_ascii=False))
                        self._event(db, 'sync_failed', actor='inbox', peer=self.peer, error=error_details(error), **totals)
                    raise
        except Timeout:
            raise ReaderError('Inbox sync is active; query the saved Inbox or queue while it finishes') from None
        return {**self.status(), 'sync': totals}

    def history(self, *, message_id=None, query='', limit=20, cursor=None):
        bounded_int(limit, 'limit', 1, 100)
        query = text_value(query, 'query', 200)
        filters = [self.scope, self.peer, query, message_id]
        page = self.queue.decode_cursor(cursor, 'messages', filters)
        with self.memory.connect() as db:
            where, params = ['scope=?', 'peer=?'], [self.scope, self.peer]
            if message_id:
                where.append('id=?')
                params.append(message_id)
            if query:
                where.append("instr(lower(text||' '||videos),lower(?))>0")
                params.append(query)
            if page:
                bounded_int(page.get('seq'), 'message cursor sequence', 1, 9223372036854775807)
                bounded_int(page.get('row'), 'message cursor row', 1, 9223372036854775807)
                where.append('(seq<? OR (seq=? AND row_id<?))')
                params.extend((page['seq'], page['seq'], page['row']))
            rows = db.execute('SELECT * FROM inbox_messages WHERE ' + ' AND '.join(where) + ' ORDER BY seq DESC,row_id DESC LIMIT ?',
                              (*params, limit+1)).fetchall()
            messages = []
            for row in rows[:limit]:
                data = {**dict(row), 'videos': json.loads(row['videos'])}
                if message_id:
                    data['raw'] = json.loads(row['raw'])
                    revisions = db.execute("SELECT id,created,kind,details FROM inbox_events WHERE scope=? AND message_id=? "
                                           "AND kind='message_revised' ORDER BY id DESC LIMIT 100",
                                           (self.scope, row['id'])).fetchall()
                    data['revisions'] = [{**dict(event), 'details': json.loads(event['details'])} for event in revisions]
                    data['revision_limit'] = 100
                else:
                    data.pop('raw')
                data['queue_items'] = self.queue.linked_items(db,row['id'])
                messages.append(data)
        if message_id and not messages:
            raise ReaderError('Inbox message not found in the current account/conversation')
        self.queue.describe_sources([video for message in messages for video in message['videos']])
        return {'messages': messages, 'next_cursor': self.queue.encode_cursor('messages', filters,
                {'seq': messages[-1]['seq'], 'row': messages[-1]['row_id']}) if len(rows)>limit else None}

    def enqueue(self, message_id, *, index=0, task=None):
        bounded_int(index, 'index', 0, 99)
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM inbox_messages WHERE scope=? AND peer=? AND id=?',
                             (self.scope, self.peer, message_id)).fetchone()
            if not row or row['parse_status'] != 'video':
                raise ReaderError('Choose a retained video message in the current Inbox')
            videos = json.loads(row['videos'])
            if index >= len(videos):
                raise ReaderError('Video index is outside this message')
            video = videos[index]
            result = self.queue.enqueue_in_transaction(db, video['source'], video['task'] if task is None else task,
                                         video['title'], message_id=message_id)
            self.queue.link_origin(db,result['item_id'],self._origin(db,message_id))
        return {**result, 'item': self.queue.show(result['item_id']), 'video_reading_started': False}
