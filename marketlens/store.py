import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, result TEXT NOT NULL)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()
    def save(self,result):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO experiments(id,result) VALUES (?,?)',(result['id'],json.dumps(result,allow_nan=False)))
        return self.get(result['id'])
    def get(self,id):
        with self.connect() as db:
            row=db.execute('SELECT result FROM experiments WHERE id=?',(id,)).fetchone()
        if not row:raise KeyError(id)
        return json.loads(row[0])
    def list(self):
        with self.connect() as db:
            rows=db.execute('SELECT id,created_at,result FROM experiments ORDER BY created_at DESC,id DESC LIMIT 100').fetchall()
        return [{'id':r[0],'created_at':r[1],'config':json.loads(r[2])['config']} for r in rows]
