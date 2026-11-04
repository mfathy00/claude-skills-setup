"""Explicit v1-to-v2 migration with a private consistent backup and no task replay."""
import os
import sqlite3
import time
import uuid

from .runtime import runner_lock
from .safety import SafetyError, bounded_text, encoded
from .state import Store
import json

ALTERS = [
    "ALTER TABLE tasks ADD COLUMN session_id TEXT", "ALTER TABLE tasks ADD COLUMN binding TEXT",
    "ALTER TABLE tasks ADD COLUMN workspace_stamp TEXT", "ALTER TABLE tasks ADD COLUMN review_stamp TEXT",
    "ALTER TABLE events ADD COLUMN subject TEXT NOT NULL DEFAULT 'repository'",
    "ALTER TABLE inbox ADD COLUMN attempt TEXT", "ALTER TABLE inbox ADD COLUMN disposition TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE inbox ADD COLUMN wake INTEGER NOT NULL DEFAULT 0", "ALTER TABLE attempts ADD COLUMN session_id TEXT",
    "ALTER TABLE attempts ADD COLUMN result_ref TEXT",
    "CREATE UNIQUE INDEX owned_session ON tasks(session_id) WHERE session_id IS NOT NULL",
    "CREATE TABLE edges(task_id TEXT,parent_ref TEXT,child_ref TEXT,relation TEXT,PRIMARY KEY(task_id,parent_ref,child_ref,relation))",
    "CREATE TABLE recalls(task_id TEXT,ref TEXT,PRIMARY KEY(task_id,ref))",
    "CREATE TABLE factory_policies(id TEXT PRIMARY KEY,content_hash TEXT NOT NULL,body TEXT NOT NULL)",
    "CREATE TABLE factory_items(source_key TEXT PRIMARY KEY,policy_id TEXT NOT NULL,item_id TEXT NOT NULL,content_hash TEXT NOT NULL,source_ref TEXT NOT NULL,build_id TEXT NOT NULL,check_id TEXT NOT NULL,review_id TEXT NOT NULL)",
]


def migrate(directory, evidence):
    bounded_text(evidence, "migration/recovery evidence", 4096)
    store = Store(directory, legacy=True)
    with runner_lock(store), store.connection() as db:
        if store._get(db, "version") == "2":
            return {"version": 2, "changed": False}
        backup = store.directory / ("pre-v2-" + uuid.uuid4().hex + ".sqlite3")
        fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        # A separate reader sees a consistent committed snapshot while this transaction
        # holds the reserved writer lock. No user/account files are touched.
        with sqlite3.connect(str(store.database)) as source, sqlite3.connect(str(backup)) as destination:
            source.backup(destination)
        for statement in ALTERS:
            db.execute(statement)
        for task in db.execute("SELECT * FROM tasks").fetchall():
            spec = store.validate_spec(json.loads(task["spec"]))
            db.execute("UPDATE tasks SET spec=? WHERE id=?", (encoded(spec), task["id"]))
            if task["state"] in ("running", "cancelling"):
                db.execute("UPDATE tasks SET state='interrupted',detail='explicit migration after worker inspection',updated=? WHERE id=?", (time.time(), task["id"]))
                db.execute("UPDATE attempts SET status='interrupted',ended=? WHERE id=?", (time.time(), task["attempt"]))
                db.execute("UPDATE inbox SET disposition='uncertain' WHERE task_id=?", (task["id"],))
        store._set(db, "version", "2")
        store._set(db, "dirty", "0")
        store._set(db, "recovery_required", "0")
        store._audit(db, None, "migration_v2", evidence)
    with sqlite3.connect(str(store.database)) as db:
        db.execute("PRAGMA journal_mode=WAL")
    return {"version": 2, "changed": True, "backup": str(backup)}
