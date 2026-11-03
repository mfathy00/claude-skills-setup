"""Durable state. Each mutation is one immediate SQLite transaction."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .safety import (SafetyError, bounded_text, canonical, encoded, identifier,
                     integer, overlap, private_directory, private_file, scope_path, within)


@dataclass(frozen=True)
class Limits:
    workers: int = 4
    queue: int = 64
    tasks: int = 1024
    events: int = 2048
    artifact_bytes: int = 64 * 1024 * 1024
    event_bytes: int = 65536
    output_bytes: int = 1024 * 1024
    run_seconds: int = 3600
    budget_cents: int = 1000
    starts: int = 64

    def validate(self):
        bounds = {"workers": (1, 6), "queue": (1, 1024), "tasks": (1, 100000),
                  "events": (1, 100000), "artifact_bytes": (1024, 1024**3),
                  "event_bytes": (256, 1024**2), "output_bytes": (256, 16*1024**2),
                  "run_seconds": (1, 86400), "budget_cents": (1, 1000000), "starts": (1, 10000)}
        for key, value in asdict(self).items():
            integer(value, key, *bounds[key])
        return self


SCHEMA = """
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE tasks(id TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL,
 created REAL NOT NULL, updated REAL NOT NULL, owner TEXT, attempt TEXT,
 approval TEXT, result_ref TEXT, detail TEXT, accepted TEXT);
CREATE TABLE dependencies(task_id TEXT, depends_on TEXT, PRIMARY KEY(task_id,depends_on));
CREATE TABLE subscriptions(task_id TEXT, kind TEXT, PRIMARY KEY(task_id,kind));
CREATE TABLE artifacts(ref TEXT PRIMARY KEY, body BLOB NOT NULL, size INTEGER NOT NULL);
CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
 external_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(source,external_id));
CREATE TABLE inbox(task_id TEXT, event_seq INTEGER, PRIMARY KEY(task_id,event_seq));
CREATE TABLE attempts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, owner TEXT NOT NULL,
 started REAL NOT NULL, ended REAL, status TEXT NOT NULL, reserved_cents INTEGER NOT NULL, context_ref TEXT NOT NULL);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
 task_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX task_state ON tasks(state,created);
"""


class Store:
    def __init__(self, directory):
        self.directory = private_directory(directory)
        self.database = private_file(self.directory / "state.sqlite3")
        with self.connection() as db:
            self.root = canonical(json.loads(self._get(db, "workspace_root")))
            self.repository = json.loads(self._get(db, "repository"))
            self.limits = Limits(**json.loads(self._get(db, "limits"))).validate()
            if self._get(db, "version") != "1":
                raise SafetyError("unsupported state schema")

    @classmethod
    def initialize(cls, directory, workspace_root, repository, limits=None):
        limits = (limits or Limits()).validate()
        root = canonical(workspace_root)
        if not root.is_dir():
            raise SafetyError("workspace root must be a directory")
        bounded_text(repository, "repository", 200)
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise SafetyError("repository must be owner/name")
        directory = canonical(directory, must_exist=False)
        if within(directory, root) or within(root, directory):
            raise SafetyError("keep private state outside the workspace root")
        private_directory(directory, create=True)
        target = directory / "state.sqlite3"
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        old = os.umask(0o077)
        try:
            with sqlite3.connect(str(target)) as db:
                db.executescript(SCHEMA)
                settings = {"version": "1", "workspace_root": encoded(str(root)),
                            "repository": encoded(repository), "limits": encoded(asdict(limits)),
                            "dirty": "0", "recovery_required": "0", "stop": "0", "heartbeat": "0"}
                db.executemany("INSERT INTO settings VALUES (?,?)", settings.items())
        finally:
            os.umask(old)
        return cls(directory)

    @contextmanager
    def connection(self):
        # Same-uid malicious races are not contained; the state owner is trusted.
        private_directory(self.directory)
        for name in ("state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm", "state.sqlite3-journal"):
            path = self.directory / name
            # SQLite removes sidecars as its last connection closes. Their disappearance
            # during concurrent connection setup is normal, not an unsafe file to follow.
            private_file(path, missing_ok=name != "state.sqlite3")
        db = sqlite3.connect(str(self.database), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _get(db, key):
        return db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]

    @staticmethod
    def _set(db, key, value):
        db.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))

    @staticmethod
    def _audit(db, task_id, action, detail=""):
        db.execute("INSERT INTO audit(at,task_id,action,detail) VALUES (?,?,?,?)",
                   (time.time(), task_id, action, detail[:4096]))

    def _artifact(self, db, body):
        data = body.encode("utf-8")
        ref = hashlib.sha256(data).hexdigest()
        if db.execute("SELECT 1 FROM artifacts WHERE ref=?", (ref,)).fetchone():
            return ref
        used = db.execute("SELECT COALESCE(SUM(size),0) FROM artifacts").fetchone()[0]
        if used + len(data) > self.limits.artifact_bytes:
            raise SafetyError("artifact capacity reached; archive state before admitting more work")
        db.execute("INSERT INTO artifacts VALUES (?,?,?)", (ref, data, len(data)))
        return ref

    def recall(self, ref):
        if not isinstance(ref, str) or len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref):
            raise SafetyError("invalid artifact reference")
        with self.connection() as db:
            row = db.execute("SELECT body FROM artifacts WHERE ref=?", (ref,)).fetchone()
            if row is None:
                raise SafetyError("unknown artifact")
            return bytes(row[0]).decode("utf-8")

    def validate_spec(self, spec):
        allowed = {"id", "goal", "acceptance", "provider", "model", "workspace", "project", "mode",
                   "paths", "timeout_seconds", "budget_cents", "max_turns", "dependencies",
                   "subscriptions", "previous_task"}
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise SafetyError("unknown task fields (task specs are trusted local instructions)")
        spec = dict(spec)
        for key in ("id", "project"):
            identifier(spec.get(key), key)
        for key in ("goal", "acceptance"):
            bounded_text(spec.get(key), key)
        if spec.get("provider") not in ("mock", "claude", "codex"):
            raise SafetyError("provider must be mock, claude or codex")
        if spec.get("mode", "read-only") not in ("read-only", "workspace-write"):
            raise SafetyError("unsupported permission mode")
        spec.setdefault("mode", "read-only")
        model = spec.setdefault("model", "opus" if spec["provider"] == "claude" else "default")
        identifier(model, "requested model")
        workspace = canonical(spec.get("workspace", ""))
        if not workspace.is_dir() or not within(workspace, self.root):
            raise SafetyError("workspace is outside configured root")
        spec["workspace"] = str(workspace)
        paths = spec.get("paths", [])
        if not isinstance(paths, list) or not paths or len(paths) > 32:
            raise SafetyError("list 1-32 explicit allowed paths")
        spec["paths"] = sorted(set(scope_path(p, workspace) for p in paths))
        for key, default, low, high in (("timeout_seconds", 300, 1, 3600),
                                      ("budget_cents", 100, 1, 100000), ("max_turns", 12, 1, 100)):
            spec[key] = integer(spec.get(key, default), key, low, high)
        for key in ("dependencies", "subscriptions"):
            value = spec.setdefault(key, [])
            if not isinstance(value, list) or len(value) > 32:
                raise SafetyError("invalid " + key)
            spec[key] = sorted(set(identifier(v, key) for v in value))
        if "previous_task" in spec:
            identifier(spec["previous_task"], "previous task")
        return spec

    def create_task(self, spec):
        spec = self.validate_spec(spec)
        task_id, now = spec["id"], time.time()
        with self.connection() as db:
            existing = db.execute("SELECT spec FROM tasks WHERE id=?", (task_id,)).fetchone()
            if existing:
                if existing[0] != encoded(spec):
                    raise SafetyError("task ID already has different immutable scope")
                return task_id
            if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= self.limits.tasks:
                raise SafetyError("task capacity reached")
            for dependency in spec["dependencies"] + ([spec["previous_task"]] if "previous_task" in spec else []):
                if not db.execute("SELECT 1 FROM tasks WHERE id=?", (dependency,)).fetchone():
                    raise SafetyError("unknown dependency/previous task: " + dependency)
            db.execute("INSERT INTO tasks(id,spec,state,created,updated) VALUES (?,?,'draft',?,?)",
                       (task_id, encoded(spec), now, now))
            db.executemany("INSERT INTO dependencies VALUES (?,?)", [(task_id, d) for d in spec["dependencies"]])
            db.executemany("INSERT INTO subscriptions VALUES (?,?)", [(task_id, k) for k in spec["subscriptions"]])
            self._audit(db, task_id, "created")
        return task_id

    def approve(self, task_id, evidence):
        bounded_text(evidence, "approval evidence", 4096)
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["state"] == "queued":
                return
            if row["state"] != "draft":
                raise SafetyError("only a draft may be approved; create a new task for a retry")
            if db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0] >= self.limits.queue:
                raise SafetyError("queue capacity reached")
            self.validate_spec(json.loads(row["spec"]))
            db.execute("UPDATE tasks SET state='queued', approval=?,updated=? WHERE id=?",
                       (evidence, time.time(), task_id))
            self._audit(db, task_id, "approved", evidence)

    @staticmethod
    def _task(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise SafetyError("unknown task: " + str(task_id))
        return row

    def tasks(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY created,id")]

    def task(self, task_id):
        with self.connection() as db:
            result = dict(self._task(db, task_id))
            if result["attempt"]:
                result["attempt_record"] = dict(db.execute("SELECT * FROM attempts WHERE id=?", (result["attempt"],)).fetchone())
            return result

    def ingest(self, delivery_id, kind, payload):
        """Offline data intake only. Repository comments never become commands."""
        identifier(delivery_id, "delivery ID")
        identifier(kind, "event kind")
        if (not isinstance(payload, dict) or not isinstance(payload.get("repository"), dict)
                or payload["repository"].get("full_name") != self.repository):
            raise SafetyError("event repository does not match configured repository")
        body = encoded(payload)
        if len(body.encode()) > self.limits.event_bytes:
            raise SafetyError("event exceeds byte limit")
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute("SELECT seq,kind,ref FROM events WHERE source='github' AND external_id=?", (delivery_id,)).fetchone()
            if row:
                if row["kind"] != kind or row["ref"] != digest:
                    raise SafetyError("delivery ID reused with conflicting content")
                return row["seq"]
            if db.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= self.limits.events:
                raise SafetyError("event capacity reached")
            ref = self._artifact(db, body)
            cur = db.execute("INSERT INTO events(source,external_id,kind,ref,created) VALUES ('github',?,?,?,?)",
                             (delivery_id, kind, ref, time.time()))
            seq = cur.lastrowid
            # Fixed subscription router: no model, shell, actor trust or parsing of commands.
            db.execute("INSERT INTO inbox SELECT s.task_id,? FROM subscriptions s JOIN tasks t ON t.id=s.task_id "
                       "WHERE s.kind=? AND t.state IN ('draft','queued','running','cancelling')", (seq, kind))
            return seq

    def events(self, task_id=None):
        with self.connection() as db:
            if task_id:
                self._task(db, task_id)
                rows = db.execute("SELECT e.* FROM events e JOIN inbox i ON i.event_seq=e.seq WHERE i.task_id=? ORDER BY e.seq", (task_id,))
            else:
                rows = db.execute("SELECT * FROM events ORDER BY seq")
            return [dict(r) for r in rows]

    def cancel(self, task_id):
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["state"] in ("draft", "queued", "running"):
                target = "cancelling" if row["state"] == "running" else "cancelled"
                db.execute("UPDATE tasks SET state=?,updated=? WHERE id=?", (target, time.time(), task_id))
                self._audit(db, task_id, "cancel_requested")
            return self._task(db, task_id)["state"]

    def accept(self, task_id, evidence):
        bounded_text(evidence, "acceptance evidence", 4096)
        with self.connection() as db:
            if self._task(db, task_id)["state"] != "completed":
                raise SafetyError("only completed output may be accepted after review")
            db.execute("UPDATE tasks SET state='accepted',accepted=?,updated=? WHERE id=?", (evidence, time.time(), task_id))
            self._audit(db, task_id, "accepted", evidence)

    def claim(self, owner, live=False):
        identifier(owner, "owner")
        with self.connection() as db:
            if self._get(db, "recovery_required") == "1" or self._get(db, "stop") == "1":
                return None
            active = list(db.execute("SELECT spec FROM tasks WHERE state IN ('running','cancelling')"))
            if len(active) >= self.limits.workers:
                return None
            used, count = db.execute("SELECT COALESCE(SUM(reserved_cents),0),COUNT(*) FROM attempts").fetchone()
            for row in db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY created,id").fetchall():
                spec = json.loads(row["spec"])
                if spec["provider"] != "mock" and not live:
                    continue
                pending = db.execute("SELECT 1 FROM dependencies d JOIN tasks t ON d.depends_on=t.id WHERE d.task_id=? AND t.state!='accepted'", (row["id"],)).fetchone()
                if pending:
                    continue
                if any(self.conflict(spec, json.loads(other["spec"])) for other in active):
                    continue
                if used + spec["budget_cents"] > self.limits.budget_cents or count >= self.limits.starts:
                    db.execute("UPDATE tasks SET state='blocked',detail='admission budget/start cap reached',updated=? WHERE id=?", (time.time(), row["id"]))
                    self._audit(db, row["id"], "budget_blocked")
                    continue
                try:
                    self.validate_spec(spec)
                except SafetyError as exc:
                    db.execute("UPDATE tasks SET state='blocked',detail=?,updated=? WHERE id=?", (str(exc), time.time(), row["id"]))
                    continue
                attempt = uuid.uuid4().hex
                db.execute("UPDATE tasks SET state='running',owner=?,attempt=?,updated=? WHERE id=?", (owner, attempt, time.time(), row["id"]))
                events = [dict(e) for e in db.execute("SELECT e.* FROM events e JOIN inbox i ON i.event_seq=e.seq WHERE i.task_id=? ORDER BY seq", (row["id"],))]
                context_ref = self._artifact(db, encoded({"spec": spec, "events": events}))
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,NULL,'running',?,?)", (attempt, row["id"], owner, time.time(), spec["budget_cents"], context_ref))
                self._audit(db, row["id"], "claimed", attempt)
                result = dict(self._task(db, row["id"]))
                # Atomic event snapshot; late events remain inbox data, never a hidden restart.
                result["events"] = events
                result["context_ref"] = context_ref
                return result
        return None

    @staticmethod
    def conflict(a, b):
        if a["mode"] == b["mode"] == "read-only":
            return False
        if overlap(a["workspace"], b["workspace"]):
            return True  # serialize any writer in a shared/overlapping checkout
        return a["project"] == b["project"] and any(overlap(x, y) for x in a["paths"] for y in b["paths"])

    def finish(self, task_id, owner, attempt, state, output, detail=""):
        if state not in ("completed", "failed", "cancelled", "interrupted"):
            raise SafetyError("invalid terminal state")
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["owner"] != owner or row["attempt"] != attempt or row["state"] not in ("running", "cancelling"):
                raise SafetyError("stale worker ownership")
            if row["state"] == "cancelling":
                state = "cancelled"
            ref = self._artifact(db, output) if output else None
            db.execute("UPDATE tasks SET state=?,result_ref=?,detail=?,updated=? WHERE id=?", (state, ref, detail[:4096], time.time(), task_id))
            db.execute("UPDATE attempts SET status=?,ended=? WHERE id=?", (state, time.time(), attempt))
            self._audit(db, task_id, state, detail)

    def start_session(self):
        """Caller must hold runner lock. Never replay an uncertain prior attempt."""
        with self.connection() as db:
            stale = (self._get(db, "dirty") == "1" or
                     db.execute("SELECT 1 FROM tasks WHERE state IN ('running','cancelling')").fetchone() is not None)
            if stale:
                for row in db.execute("SELECT id,attempt FROM tasks WHERE state IN ('running','cancelling')").fetchall():
                    db.execute("UPDATE tasks SET state='interrupted',detail='unclean runner exit; inspect isolated host',updated=? WHERE id=?", (time.time(), row["id"]))
                    db.execute("UPDATE attempts SET status='interrupted',ended=? WHERE id=?", (time.time(), row["attempt"]))
                    self._audit(db, row["id"], "recovered_interrupted")
                self._set(db, "recovery_required", "1")
            recovery_required = self._get(db, "recovery_required") == "1"
            if not recovery_required:
                self._set(db, "dirty", "1")
                self._set(db, "stop", "0")
                self._set(db, "heartbeat", time.time())
        if recovery_required:
            raise SafetyError("recovery required: stop surviving workers on isolated host, inspect changes, then acknowledge recovery")

    def recover(self, evidence):
        bounded_text(evidence, "recovery evidence", 4096)
        with self.connection() as db:
            for row in db.execute("SELECT id,attempt FROM tasks WHERE state IN ('running','cancelling')").fetchall():
                db.execute("UPDATE tasks SET state='interrupted',detail='operator recovery',updated=? WHERE id=?", (time.time(), row["id"]))
                db.execute("UPDATE attempts SET status='interrupted',ended=? WHERE id=?", (time.time(), row["attempt"]))
            self._set(db, "recovery_required", "0")
            self._set(db, "dirty", "0")
            self._audit(db, None, "operator_recovery", evidence)

    def heartbeat(self):
        with self.connection() as db:
            self._set(db, "heartbeat", time.time())
            return self._get(db, "stop") == "1"

    def stop(self):
        with self.connection() as db:
            self._set(db, "stop", "1")

    def clean_session(self):
        with self.connection() as db:
            if db.execute("SELECT 1 FROM tasks WHERE state IN ('running','cancelling')").fetchone():
                raise SafetyError("cannot mark a session clean with active workers")
            self._set(db, "dirty", "0")

    def status(self):
        with self.connection() as db:
            return {"settings": {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings")},
                    "states": {r[0]: r[1] for r in db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state")},
                    "reserved_cents": db.execute("SELECT COALESCE(SUM(reserved_cents),0) FROM attempts").fetchone()[0]}
