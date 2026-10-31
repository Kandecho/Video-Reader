"""Embedded, account-scoped memory and delivery records; no database service."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from video_reader.common import ReaderError

KINDS = ('preference', 'feedback', 'observation')


class Memory:
    def __init__(self, directory, scope):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'memory.sqlite3'
        self.scope = scope
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
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
            row = connection.execute('SELECT scope FROM runs WHERE id=?', (run_id,)).fetchone()
            if row and row['scope'] != self.scope:
                raise ReaderError('Run belongs to a different account')
            connection.execute('INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               'status=excluded.status,result=excluded.result',
                               (run_id, self.scope, status, time.time(), json.dumps(result, ensure_ascii=False)))

    def load_run(self, run_id):
        with self.connect() as connection:
            row = connection.execute('SELECT result FROM runs WHERE id=? AND scope=?', (run_id, self.scope)).fetchone()
        if not row:
            raise ReaderError('Run not found for this account')
        return json.loads(row['result'])

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

    def delivery_status(self, recipient):
        with self.connect() as connection:
            rows = connection.execute('SELECT source,status,updated FROM deliveries WHERE scope=? AND recipient=? '
                                      'ORDER BY updated DESC LIMIT 20', (self.scope, str(recipient))).fetchall()
        return [dict(row) for row in rows]
