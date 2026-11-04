"""One-time adapters for the old mixed Scroll tables; no runtime Inbox dependency."""
import json


def import_origins(db,scope):
    marker='origins_v1:'+scope
    if db.execute('SELECT 1 FROM task_migrations WHERE id=?',(marker,)).fetchone(): return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='inbox_messages'").fetchone():
        rows=db.execute('SELECT l.item_id,m.* FROM queue_links l JOIN inbox_messages m ON m.id=l.message_id AND m.scope=l.scope WHERE l.scope=?',(scope,)).fetchall()
        for row in rows:
            data={key:row[key] for key in ('id','peer','message_key','seq','sent_at','msg_type','period','parse_status','text')}
            data.update(provider='bilibili_dm',account_scope=row['scope'])
            db.execute('INSERT OR IGNORE INTO queue_origins(scope,item_id,message_id,text,seq,payload) VALUES(?,?,?,?,?,?)',
                (scope,row['item_id'],row['id'],row['text'],row['seq'],json.dumps(data,ensure_ascii=False)))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='queue_triage'").fetchone():
        for row in db.execute('SELECT item_id,record FROM queue_triage WHERE scope=?',(scope,)):
            intent=(json.loads(row['record']).get('assessment') or {}).get('intent')
            if intent:
                db.execute('INSERT OR IGNORE INTO task_annotations(scope,item_id,payload) VALUES(?,?,?)',
                    (scope,row['item_id'],json.dumps(intent,ensure_ascii=False)))
    db.execute('INSERT INTO task_migrations VALUES(?)',(marker,))
