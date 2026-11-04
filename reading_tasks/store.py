"""SQLite connection and stable library identity, independent of Scroll preferences/login."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from video_reader.common import ReaderError, read_json, write_json


class Store:
    def __init__(self, directory, scope='local', *, database=None):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=Path(database) if database else self.directory/'tasks.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not isinstance(scope,str) or not scope or len(scope)>100:
            raise ReaderError('Task library must be a nonempty identifier')
        self.scope=scope

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=15)
        connection.row_factory=sqlite3.Row
        try:
            with connection: yield connection
        finally:
            connection.close()

    @classmethod
    def from_settings(cls,config,config_path):
        base=Path(config_path).parent
        options=config.get('tasks') or {}
        directory=(base/options.get('directory','data/tasks')).resolve()
        directory.mkdir(parents=True,exist_ok=True)
        location=directory/'library.json'
        saved=read_json(location) if location.is_file() else {}
        database=options.get('database') or saved.get('database')
        if not database:
            # One-time location compatibility. New task queries never initialize Memory.
            legacy=(base/(config.get('agent') or {}).get('directory','data/agent')/'memory.sqlite3').resolve()
            database=legacy if legacy.is_file() else directory/'tasks.sqlite3'
        database=(base/Path(database)).resolve()
        scope=options.get('library') or saved.get('library')
        store=cls(directory,scope or 'local',database=database)
        if not scope:
            with store.connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='queue_items'").fetchone()
                scopes=[r[0] for r in db.execute('SELECT DISTINCT scope FROM queue_items ORDER BY scope')] if exists else []
            # Legacy account keys become opaque library IDs; they no longer follow login changes.
            scope=scopes[0] if scopes else 'local'
            store.scope=scope
        selected={'database':str(database),'library':scope}
        if saved!=selected: write_json(location,selected)
        return store
