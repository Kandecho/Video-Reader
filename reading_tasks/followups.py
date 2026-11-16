"""Independent follow-up actions and decisions attached to an existing task."""
import json
import time
import uuid

from video_reader.common import ReaderError
from .queue import STATES, artifact_values, bounded_int, text_value, nullable_text


class Followups:
    def __init__(self, queue):
        self.queue = queue

    def _records(self, db, item_id=None):
        where, params = 'scope=?', [self.queue.scope]
        if item_id is not None:
            where += ' AND item_id=?'
            params.append(item_id)
        return [{**json.loads(row['record']), 'id': row['id'], 'item_id': row['item_id'],
                 'created_at': row['created'], 'updated_at': row['updated'], 'revision': row['revision']}
                for row in db.execute('SELECT * FROM task_followups WHERE ' + where +
                                      ' ORDER BY created,id', params)]

    def _history(self, db, item_id=None):
        descriptions = [record['description'] for record in self._records(db, item_id)]
        where, params = "scope=? AND kind IN ('followup_added','followup_updated')", [self.queue.scope]
        if item_id is not None:
            where += ' AND item_id=?'
            params.append(item_id)
        for row in db.execute('SELECT details FROM queue_events WHERE ' + where + ' ORDER BY id', params):
            event = json.loads(row['details'])
            for key in ('before', 'after'):
                record = event.get(key)
                if isinstance(record, dict):
                    descriptions.append(record.get('description'))
        return list(dict.fromkeys(value for value in descriptions if isinstance(value, str) and value.strip()))

    def list(self, item_id=None):
        with self.queue.store.connect() as db:
            db.execute('BEGIN')
            if item_id is not None:
                self.queue._item(db, item_id)
            return {'followups': self._records(db, item_id),
                    'description_history': self._history(db, item_id)}

    def save(self, item_id, payload):
        fields = {'id', 'description', 'state', 'reason', 'notes', 'artifacts',
                  'source_result_id', 'expected_revision'}
        if not isinstance(payload, dict) or not payload or set(payload) - fields:
            raise ReaderError('Follow-up needs description and optional state/reason/notes/artifacts/source_result_id')
        followup_id = text_value(payload['id'], 'follow-up id', 100) if 'id' in payload else None
        if followup_id == '':
            raise ReaderError('Follow-up id must not be empty')
        expected_revision = payload.get('expected_revision')
        if expected_revision is not None:
            bounded_int(expected_revision, 'follow-up expected revision', 1, 2147483647)
            if followup_id is None:
                raise ReaderError('Follow-up expected revision requires an existing id')
        values = {key: (text_value(payload[key], 'follow-up ' + key) if key == 'description'
                        else nullable_text(payload[key], 'follow-up ' + key))
                  for key in ('description', 'reason', 'notes') if key in payload}
        if 'description' in values and not values['description']:
            raise ReaderError('Follow-up description must not be empty')
        if 'state' in payload:
            if payload['state'] not in STATES:
                raise ReaderError('Follow-up state must be pending, paused, done, cancelled or archived')
            values['state'] = payload['state']
        if 'artifacts' in payload:
            values['artifacts'] = artifact_values(payload['artifacts'], 'Follow-up')
        if 'source_result_id' in payload:
            result_id = payload['source_result_id']
            if result_id is not None:
                bounded_int(result_id, 'follow-up source result id', 1, 9223372036854775807)
            values['source_result_id'] = result_id
        with self.queue.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.queue._item(db, item_id)
            old = None
            if followup_id is not None:
                row = db.execute('SELECT * FROM task_followups WHERE scope=? AND item_id=? AND id=?',
                                 (self.queue.scope, item_id, followup_id)).fetchone()
                if row is None:
                    raise ReaderError('Follow-up not found for this task in the current library')
                old = {**json.loads(row['record']), 'id': row['id'], 'item_id': row['item_id'],
                       'created_at': row['created'], 'updated_at': row['updated'], 'revision': row['revision']}
                if expected_revision is not None and expected_revision != row['revision']:
                    raise ReaderError('Follow-up revision changed; inspect the current record before updating')
                record = {**json.loads(row['record']), **values}
                created, revision = row['created'], row['revision'] + 1
            else:
                if not values.get('description'):
                    raise ReaderError('Follow-up needs a nonempty description')
                followup_id = 'fu_' + uuid.uuid4().hex
                created, revision = time.time(), 1
                record = {'description': '', 'state': 'pending', 'reason': None, 'notes': None,
                          'artifacts': [], 'source_result_id': None, **values}
            result_id = record.get('source_result_id')
            if result_id is not None and not db.execute(
                    'SELECT 1 FROM task_results WHERE scope=? AND item_id=? AND id=?',
                    (self.queue.scope, item_id, result_id)).fetchone():
                raise ReaderError('Follow-up source result does not belong to this task')
            updated = time.time()
            db.execute('INSERT INTO task_followups(id,scope,item_id,created,updated,revision,record) '
                       'VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'updated=excluded.updated,revision=excluded.revision,record=excluded.record',
                       (followup_id, self.queue.scope, item_id, created, updated, revision,
                        json.dumps(record, ensure_ascii=False, allow_nan=False)))
            saved = {**record, 'id': followup_id, 'item_id': item_id,
                     'created_at': created, 'updated_at': updated, 'revision': revision}
            self.queue._event(db, 'followup_updated' if old else 'followup_added', item_id=item_id,
                              followup_id=followup_id, before=old, after=saved)
        output = {'followup': saved, 'created': old is None}
        from .catalog import refresh
        refreshed = refresh(self.queue)
        if refreshed is not None:
            output['catalog_refresh'] = refreshed
        return output
