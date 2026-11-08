"""Embedded, account-scoped memory and delivery records; no database service."""
from __future__ import annotations

import json
from pathlib import Path
import time

from video_reader.common import ReaderError
from reading_tasks.store import Store

KINDS = ('preference', 'feedback', 'observation')


class Memory(Store):
    @classmethod
    def from_reader(cls, reader):
        """Open the logged-in account's memory without recommendation or transport setup."""
        from video_reader.bilibili_auth import BilibiliAuth
        from video_reader.platform import PlatformError
        directory = reader.config['agent']['directory']
        if not isinstance(directory,str) or not directory.strip():
            raise ReaderError('agent.directory must be a nonempty path')
        auth = BilibiliAuth(reader.config)
        if not auth.options['enabled']:
            raise PlatformError('managed_login_disabled')
        scope = auth.account_scope()
        if scope is None:
            raise PlatformError('login_required')
        return cls((reader.config_path.parent/directory).resolve(),scope)

    def __init__(self, directory, scope):
        super().__init__(directory,scope,database=Path(directory)/'memory.sqlite3')
        with self.connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                    text TEXT NOT NULL, source TEXT NOT NULL, created REAL NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(text, tokenize='trigram');
                CREATE TABLE IF NOT EXISTS videos (
                    scope TEXT, source TEXT, status TEXT, reason TEXT, updated REAL,
                    PRIMARY KEY(scope, source));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, scope TEXT, status TEXT, created REAL, result TEXT);
                CREATE TABLE IF NOT EXISTS deliveries (
                    scope TEXT, recipient TEXT, source TEXT, status TEXT, updated REAL,
                    PRIMARY KEY(scope, recipient, source));
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, scope TEXT NOT NULL,
                    created REAL NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS run_events_lookup ON run_events(scope,run_id,id);
            ''')

    def remember(self, text, kind='observation', source=''):
        if kind not in KINDS or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise ReaderError('Memory requires a valid kind and 1..4000 characters')
        if not isinstance(source, str) or len(source) > 200:
            raise ReaderError('Memory source must contain at most 200 characters')
        with self.connect() as connection:
            existing = connection.execute('SELECT id FROM memories WHERE scope=? AND kind=? AND text=? AND source=?',
                                          (self.scope, kind, text.strip(), source)).fetchone()
            if existing:
                return {'id': existing['id'], 'created': False, 'kind': kind}
            cursor = connection.execute('INSERT INTO memories(scope,kind,text,source,created) VALUES(?,?,?,?,?)',
                                        (self.scope, kind, text.strip(), source, time.time()))
            connection.execute('INSERT INTO memory_fts(rowid,text) VALUES(?,?)', (cursor.lastrowid, text.strip()))
            return {'id': cursor.lastrowid, 'created': True, 'kind': kind}

    def recall(self, query='', kind=None, limit=12):
        if kind is not None and kind not in KINDS:
            raise ReaderError('Unknown memory kind')
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ReaderError('Memory limit must be 1..50')
        if not isinstance(query, str) or len(query) > 200:
            raise ReaderError('Memory query must contain at most 200 characters')
        params = [self.scope]
        where = ['memories.scope=?']
        join = ''
        if kind:
            where.append('memories.kind=?')
            params.append(kind)
        if len(query.strip()) >= 3:
            join = ' JOIN memory_fts ON memory_fts.rowid=memories.id'
            where.append('memory_fts MATCH ?')
            params.append('"' + query.strip().replace('"', '""') + '"')
        elif query.strip():
            where.append('instr(memories.text,?)>0')
            params.append(query.strip())
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute('SELECT memories.* FROM memories' + join + ' WHERE ' + ' AND '.join(where)
                                      + ' ORDER BY memories.id DESC LIMIT ?', params).fetchall()
        return [dict(row) for row in rows]

    def context(self, query=''):
        return {'preferences': self.recall(kind='preference', limit=12),
                'feedback': self.recall(kind='feedback', limit=12),
                'related_observations': self.recall(query, kind='observation', limit=8)}

    def forget(self, memory_id):
        with self.connect() as connection:
            row = connection.execute('SELECT id FROM memories WHERE id=? AND scope=?', (memory_id, self.scope)).fetchone()
            if not row:
                raise ReaderError('Memory not found for this account')
            connection.execute('DELETE FROM memory_fts WHERE rowid=?', (memory_id,))
            connection.execute('DELETE FROM memories WHERE id=?', (memory_id,))
        return {'deleted': memory_id}

    def record_video(self, source, status, reason):
        with self.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?)',
                               (self.scope, source, status, reason, time.time()))

    def excluded(self, reconsider_hours):
        with self.connect() as connection:
            rows = connection.execute('SELECT source FROM videos WHERE scope=? AND '
                                      '(status IN (\'recommended\',\'read\') OR updated>?)',
                                      (self.scope, time.time() - reconsider_hours * 3600)).fetchall()
        return {row['source'] for row in rows}

    def save_run(self, run_id, status, result):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT scope,status,result FROM runs WHERE id=?', (run_id,)).fetchone()
            if row and row['scope'] != self.scope:
                raise ReaderError('Run belongs to a different account')
            result = {**result, 'status': status}
            if row and (runtime := json.loads(row['result']).get('runtime')):
                result['runtime'] = runtime
            connection.execute('INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               'status=excluded.status,result=excluded.result',
                               (run_id, self.scope, status, time.time(), json.dumps(result, ensure_ascii=False)))
            if not row or row['status'] != status:
                connection.execute('INSERT INTO run_events(run_id,scope,created,kind,details) VALUES(?,?,?,?,?)',
                                   (run_id, self.scope, time.time(), 'status', json.dumps({'status': status})))

    def load_run(self, run_id):
        with self.connect() as connection:
            row = connection.execute('SELECT result,status,created FROM runs WHERE id=? AND scope=?', (run_id, self.scope)).fetchone()
        if not row:
            raise ReaderError('Run not found for this account')
        return {**json.loads(row['result']), 'status': row['status'], 'created_at': row['created']}

    def update_runtime(self, run_id, fields, *, event=None):
        """Merge only runtime fields, so heartbeat writes cannot replace a newer result."""
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT result FROM runs WHERE id=? AND scope=?', (run_id, self.scope)).fetchone()
            if not row:
                raise ReaderError('Run not found for this account')
            result = json.loads(row['result'])
            result['runtime'] = {**result.get('runtime', {}), **fields}
            connection.execute('UPDATE runs SET result=? WHERE id=? AND scope=?',
                               (json.dumps(result, ensure_ascii=False), run_id, self.scope))
            if event:
                connection.execute('INSERT INTO run_events(run_id,scope,created,kind,details) VALUES(?,?,?,?,?)',
                                   (run_id, self.scope, time.time(), event, json.dumps(fields, ensure_ascii=False)))
        return result['runtime']

    def run_events(self, run_id, limit=100):
        self.load_run(run_id)
        with self.connect() as connection:
            rows = connection.execute('SELECT id,created,kind,details FROM run_events WHERE scope=? AND run_id=? '
                                      'ORDER BY id DESC LIMIT ?', (self.scope, run_id, limit)).fetchall()
        return [{**dict(row), 'details': json.loads(row['details'])} for row in reversed(rows)]

    def record_run_event(self, run_id, kind, details):
        self.load_run(run_id)
        with self.connect() as connection:
            connection.execute('INSERT INTO run_events(run_id,scope,created,kind,details) VALUES(?,?,?,?,?)',
                               (run_id, self.scope, time.time(), kind, json.dumps(details, ensure_ascii=False)))

    def daily_run(self, day):
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM runs WHERE scope=? AND json_extract(result,'$.trial_day')=? "
                                     'ORDER BY created LIMIT 1', (self.scope, day)).fetchone()
        return self.load_run(row['id']) if row else None

    def recent_runs(self, limit=10):
        with self.connect() as connection:
            rows = connection.execute('SELECT id,status,created FROM runs WHERE scope=? ORDER BY created DESC LIMIT ?',
                                      (self.scope, limit)).fetchall()
        return [dict(row) for row in rows]

    def reserve_delivery(self, recipient, sources):
        if not sources:
            raise ReaderError('Cannot reserve an empty delivery')
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for source in sources:
                row = connection.execute('SELECT status FROM deliveries WHERE scope=? AND recipient=? AND source=?',
                                         (self.scope, str(recipient), source)).fetchone()
                if row:
                    return False
            connection.executemany('INSERT INTO deliveries VALUES(?,?,?,?,?)',
                                   [(self.scope, str(recipient), source, 'sending', time.time()) for source in sources])
        return True

    def delivery_result(self, recipient, sources, status):
        with self.connect() as connection:
            connection.executemany('UPDATE deliveries SET status=?,updated=? WHERE scope=? AND recipient=? AND source=?',
                                   [(status, time.time(), self.scope, str(recipient), source) for source in sources])

    def delivery_status(self, recipient, sources=None):
        if sources == []:
            return []
        clause = ' AND source IN (' + ','.join('?' for _ in sources) + ')' if sources is not None else ''
        with self.connect() as connection:
            rows = connection.execute('SELECT source,status,updated FROM deliveries WHERE scope=? AND recipient=? '
                                      + clause + ' ORDER BY updated DESC LIMIT 20',
                                      (self.scope, str(recipient), *(sources or []))).fetchall()
        return [dict(row) for row in rows]
