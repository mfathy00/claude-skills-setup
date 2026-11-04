"""Durable state. Each mutation is one immediate SQLite transaction."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import time
import uuid

from .workspace import fingerprint, review_context, enforce_changed_paths
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
 approval TEXT, result_ref TEXT, detail TEXT, accepted TEXT, session_id TEXT, binding TEXT, workspace_stamp TEXT, review_stamp TEXT);
CREATE TABLE dependencies(task_id TEXT, depends_on TEXT, PRIMARY KEY(task_id,depends_on));
CREATE TABLE subscriptions(task_id TEXT, kind TEXT, PRIMARY KEY(task_id,kind));
CREATE TABLE artifacts(ref TEXT PRIMARY KEY, body BLOB NOT NULL, size INTEGER NOT NULL);
CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
 external_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, created REAL NOT NULL, subject TEXT NOT NULL DEFAULT 'repository',
 UNIQUE(source,external_id));
CREATE TABLE inbox(task_id TEXT, event_seq INTEGER, attempt TEXT, disposition TEXT NOT NULL DEFAULT 'pending',
 wake INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(task_id,event_seq));
CREATE TABLE attempts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, owner TEXT NOT NULL,
 started REAL NOT NULL, ended REAL, status TEXT NOT NULL, reserved_cents INTEGER NOT NULL, context_ref TEXT NOT NULL, session_id TEXT, result_ref TEXT);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
 task_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX task_state ON tasks(state,created);
CREATE UNIQUE INDEX owned_session ON tasks(session_id) WHERE session_id IS NOT NULL;
CREATE TABLE edges(task_id TEXT, parent_ref TEXT, child_ref TEXT, relation TEXT,
 PRIMARY KEY(task_id,parent_ref,child_ref,relation));
CREATE TABLE recalls(task_id TEXT, ref TEXT, PRIMARY KEY(task_id,ref));
CREATE TABLE factory_policies(id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE factory_items(source_key TEXT PRIMARY KEY, policy_id TEXT NOT NULL, item_id TEXT NOT NULL,
 content_hash TEXT NOT NULL, source_ref TEXT NOT NULL, build_id TEXT NOT NULL, check_id TEXT NOT NULL, review_id TEXT NOT NULL);
"""


class Store:
    def __init__(self, directory, legacy=False):
        self.directory = private_directory(directory)
        self.database = private_file(self.directory / "state.sqlite3")
        with self.connection(write=False) as db:
            self.root = canonical(json.loads(self._get(db, "workspace_root")))
            self.repository = json.loads(self._get(db, "repository"))
            self.limits = Limits(**json.loads(self._get(db, "limits"))).validate()
            version = self._get(db, "version")
            if version != "2" and not (legacy and version == "1"):
                raise SafetyError("state schema requires explicit migrate (stop runner first)")

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
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                settings = {"version": "2", "workspace_root": encoded(str(root)),
                            "repository": encoded(repository), "limits": encoded(asdict(limits)),
                            "dirty": "0", "recovery_required": "0", "stop": "0", "heartbeat": "0"}
                db.executemany("INSERT INTO settings VALUES (?,?)", settings.items())
        finally:
            os.umask(old)
        return cls(directory)

    @contextmanager
    def connection(self, write=True):
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
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
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
        with self.connection(write=False) as db:
            row = db.execute("SELECT body FROM artifacts WHERE ref=?", (ref,)).fetchone()
            if row is None:
                raise SafetyError("unknown artifact")
            return bytes(row[0]).decode("utf-8")

    def validate_spec(self, spec):
        allowed = {"id", "goal", "acceptance", "provider", "model", "workspace", "project", "mode",
                   "paths", "timeout_seconds", "budget_cents", "max_turns", "dependencies",
                   "subscriptions", "previous_task", "continuation", "subject", "max_attempts", "total_budget_cents", "lifetime_seconds", "dependency_mode", "checks", "routing", "protect_workspace", "check_image", "repair_of"}
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise SafetyError("unknown task fields (task specs are trusted local instructions)")
        spec = dict(spec)
        for key in ("id", "project"):
            identifier(spec.get(key), key)
        for key in ("goal", "acceptance"):
            bounded_text(spec.get(key), key)
        if spec.get("provider") not in ("mock", "claude", "codex", "checks"):
            raise SafetyError("provider must be mock, claude, codex or checks")
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
                                      ("budget_cents", 100, 0 if spec["provider"] in ("mock", "checks") else 1, 100000), ("max_turns", 12, 1, 100)):
            spec[key] = integer(spec.get(key, default), key, low, high)
        for key in ("dependencies", "subscriptions"):
            value = spec.setdefault(key, [])
            if not isinstance(value, list) or len(value) > 32:
                raise SafetyError("invalid " + key)
            spec[key] = sorted(set(identifier(v, key) for v in value))
        if "previous_task" in spec:
            identifier(spec["previous_task"], "previous task")
        continuation = spec.setdefault("continuation", "none")
        if continuation not in ("none", "owner", "subscribed"):
            raise SafetyError("continuation must be none, owner or subscribed")
        subject = spec.setdefault("subject", "repository")
        if subject != "repository" and (not isinstance(subject, str) or not re.fullmatch(r"(?:issue|pr):[1-9][0-9]{0,11}", subject)):
            raise SafetyError("invalid thread subject")
        if continuation == "subscribed" and (subject == "repository" or not spec["subscriptions"]):
            raise SafetyError("subscription wake requires an explicit issue/PR subject and kinds")
        spec["max_attempts"] = integer(spec.get("max_attempts", 1 if continuation == "none" else 4), "max_attempts", 1, 16)
        spec["total_budget_cents"] = integer(spec.get("total_budget_cents", spec["budget_cents"] * spec["max_attempts"]), "total_budget_cents", 0 if spec["provider"] in ("mock", "checks") else 1, 1000000)
        spec["lifetime_seconds"] = integer(spec.get("lifetime_seconds", 3600), "lifetime_seconds", 1, 86400)
        if continuation == "none" and spec["max_attempts"] != 1:
            raise SafetyError("once-mode allows exactly one attempt")
        if spec.setdefault("dependency_mode", "accepted") not in ("accepted", "completed"):
            raise SafetyError("invalid dependency mode")
        checks = spec.setdefault("checks", [])
        if not isinstance(checks, list) or len(checks) > 4 or any(c not in ("git-diff-check", "python-unittest") for c in checks):
            raise SafetyError("unsupported verification command; use fixed check IDs")
        if spec["provider"] == "checks" and (not checks or continuation != "none" or spec["mode"] != "workspace-write"):
            raise SafetyError("checks adapter requires a nonempty once-only writer-scoped check list")
        check_image = spec.setdefault("check_image", None)
        if check_image is not None and (not isinstance(check_image, str) or not re.fullmatch(r"[A-Za-z0-9./_-]+@sha256:[a-f0-9]{64}", check_image)):
            raise SafetyError("check image must be an explicitly approved digest-pinned local image")
        if spec["provider"] == "checks" and "python-unittest" in checks and not check_image:
            raise SafetyError("project tests require a preconfigured digest-pinned isolated check image; never run on credential host")
        if "repair_of" in spec:
            identifier(spec["repair_of"], "repair parent")
        if type(spec.setdefault("protect_workspace", False)) is not bool:
            raise SafetyError("protect_workspace must be boolean")
        routing = spec.setdefault("routing", {})
        if not isinstance(routing, dict) or (routing and set(routing) != {"role", "profile", "policy", "risk", "reason"}):
            raise SafetyError("invalid immutable route decision")
        for value in routing.values():
            bounded_text(value, "routing value", 512)
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
            if spec.get("repair_of"):
                self._task(db, spec["repair_of"])
                repairs = db.execute("SELECT COUNT(*) FROM tasks WHERE json_extract(spec,'$.repair_of')=?", (spec["repair_of"],)).fetchone()[0]
                if repairs >= 2:
                    raise SafetyError("repair draft cap reached; owner must reassess the plan")
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
        initial = self.task(task_id)
        initial_spec = self.validate_spec(json.loads(initial["spec"]))
        stamp = None
        if initial["state"] == "draft" and initial_spec["provider"] != "mock" and (initial_spec["mode"] == "workspace-write" or initial_spec["protect_workspace"]):
            stamp = fingerprint(initial_spec["workspace"], clean=not initial_spec["dependencies"] and not initial_spec.get("repair_of"))
            if initial_spec.get("repair_of"):
                previous = self.task(initial_spec["previous_task"])
                if not previous["workspace_stamp"] or previous["workspace_stamp"] != stamp:
                    raise SafetyError("repair workspace differs from the captured failed/check result")
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["state"] == "queued":
                return
            if row["state"] != "draft":
                raise SafetyError("only a draft may be approved; create a new task for a retry")
            if db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0] >= self.limits.queue:
                raise SafetyError("queue capacity reached")
            spec = self.validate_spec(json.loads(row["spec"]))
            if spec["routing"] and not db.execute("SELECT 1 FROM factory_policies WHERE id=?", (spec["routing"]["policy"],)).fetchone():
                raise SafetyError("factory import is incomplete; no approval before its durable policy/context record")
            db.execute("UPDATE tasks SET state='queued', approval=?,workspace_stamp=?,updated=? WHERE id=?",
                       (evidence, stamp, time.time(), task_id))
            self._audit(db, task_id, "approved", evidence)

    @staticmethod
    def _task(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise SafetyError("unknown task: " + str(task_id))
        return row

    def tasks(self):
        with self.connection(write=False) as db:
            return [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY created,id")]

    def task(self, task_id):
        with self.connection(write=False) as db:
            result = dict(self._task(db, task_id))
            if result["attempt"]:
                result["attempt_record"] = dict(db.execute("SELECT * FROM attempts WHERE id=?", (result["attempt"],)).fetchone())
            return result

    @staticmethod
    def subject_for(kind, payload):
        if kind == "issue_comment":
            issue = payload.get("issue", {})
            if isinstance(issue, dict) and type(issue.get("number")) is int and issue["number"] > 0:
                return ("pr:" if "pull_request" in issue else "issue:") + str(issue["number"])
        if kind == "pull_request":
            pull = payload.get("pull_request", {})
            number = pull.get("number", payload.get("number")) if isinstance(pull, dict) else None
            if type(number) is int and number > 0:
                return "pr:" + str(number)
        return "repository"

    def _event(self, db, source, external_id, kind, body, subject):
        digest = hashlib.sha256(body.encode()).hexdigest()
        row = db.execute("SELECT seq,kind,ref,subject FROM events WHERE source=? AND external_id=?", (source, external_id)).fetchone()
        if row:
            if row["kind"] != kind or row["ref"] != digest or row["subject"] != subject:
                raise SafetyError("delivery ID reused with conflicting content")
            return row["seq"], False
        if db.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= self.limits.events:
            raise SafetyError("event capacity reached")
        ref = self._artifact(db, body)
        cur = db.execute("INSERT INTO events(source,external_id,kind,ref,created,subject) VALUES (?,?,?,?,?,?)",
                         (source, external_id, kind, ref, time.time(), subject))
        return cur.lastrowid, True

    def _wake(self, db, task_id, trusted=False):
        task = self._task(db, task_id)
        if task["state"] == "waiting" or (trusted and task["state"] == "held"):
            if db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0] >= self.limits.queue:
                # Preserve pending input. Scheduler promotes it after capacity frees.
                return
            db.execute("UPDATE tasks SET state='queued',updated=? WHERE id=?", (time.time(), task_id))

    def ingest(self, delivery_id, kind, payload):
        """Offline untrusted data. Waking only executes an existing bounded mandate."""
        identifier(delivery_id, "delivery ID")
        identifier(kind, "event kind")
        if (not isinstance(payload, dict) or not isinstance(payload.get("repository"), dict)
                or payload["repository"].get("full_name") != self.repository):
            raise SafetyError("event repository does not match configured repository")
        body = encoded(payload)
        if len(body.encode()) > self.limits.event_bytes:
            raise SafetyError("event exceeds byte limit")
        subject = self.subject_for(kind, payload)
        with self.connection() as db:
            seq, fresh = self._event(db, "github", delivery_id, kind, body, subject)
            if fresh:
                rows = db.execute("SELECT t.* FROM subscriptions s JOIN tasks t ON t.id=s.task_id WHERE s.kind=? "
                                  "AND t.state IN ('draft','queued','running','waiting','held')", (kind,)).fetchall()
                for row in rows:
                    spec = json.loads(row["spec"])
                    if spec["subject"] != "repository" and spec["subject"] != subject:
                        continue
                    wake = int(spec["continuation"] == "subscribed")
                    db.execute("INSERT INTO inbox(task_id,event_seq,wake) VALUES (?,?,?)", (row["id"], seq, wake))
                    if wake:
                        self._wake(db, row["id"])
            return seq

    def instruct(self, task_id, message_id, text):
        identifier(message_id, "message ID")
        bounded_text(text, "owner instruction", 16384)
        with self.connection() as db:
            task = self._task(db, task_id)
            spec = json.loads(task["spec"])
            if spec["continuation"] == "none":
                raise SafetyError("owner messages require an approved continuation mandate")
            body = encoded({"task_id": task_id, "instruction": text, "authority": "within immutable task scope only"})
            # Dedup is allowed after task completion, but never reopens or mutates it.
            existing = db.execute("SELECT seq,ref FROM events WHERE source='owner' AND external_id=?", (message_id,)).fetchone()
            if existing:
                if existing["ref"] != hashlib.sha256(body.encode()).hexdigest():
                    raise SafetyError("delivery ID reused with conflicting content")
                return existing["seq"]
            if task["state"] not in ("draft", "queued", "running", "waiting", "held"):
                raise SafetyError("stopped/completed tasks cannot receive new instructions; create a new task")
            seq, _ = self._event(db, "owner", message_id, "owner_instruction", body, spec["subject"])
            db.execute("INSERT INTO inbox(task_id,event_seq,wake) VALUES (?,?,1)", (task_id, seq))
            self._wake(db, task_id, trusted=True)
            self._audit(db, task_id, "owner_instruction", str(seq))
            return seq

    def events(self, task_id=None):
        with self.connection(write=False) as db:
            if task_id:
                self._task(db, task_id)
                rows = db.execute("SELECT e.*,i.attempt,i.disposition,i.wake FROM events e JOIN inbox i ON i.event_seq=e.seq WHERE i.task_id=? ORDER BY e.seq", (task_id,))
            else:
                rows = db.execute("SELECT * FROM events ORDER BY seq")
            return [dict(r) for r in rows]

    def cancel(self, task_id):
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["state"] in ("draft", "queued", "running", "waiting", "held"):
                target = "cancelling" if row["state"] == "running" else "cancelled"
                db.execute("UPDATE tasks SET state=?,updated=? WHERE id=?", (target, time.time(), task_id))
                self._audit(db, task_id, "cancel_requested")
            return self._task(db, task_id)["state"]

    def accept(self, task_id, evidence):
        bounded_text(evidence, "acceptance evidence", 4096)
        initial = self.task(task_id)
        stamp = initial["workspace_stamp"]
        if stamp and fingerprint(json.loads(initial["spec"])["workspace"]) != stamp:
            raise SafetyError("workspace changed after result; acceptance evidence is stale")
        with self.connection() as db:
            task = self._task(db, task_id)
            if task["state"] != "completed" or task["workspace_stamp"] != stamp or task["result_ref"] != initial["result_ref"]:
                raise SafetyError("only unchanged completed output may be accepted after review")
            db.execute("UPDATE tasks SET state='accepted',accepted=?,review_stamp=?,updated=? WHERE id=?", (evidence, stamp, time.time(), task_id))
            self._audit(db, task_id, "accepted", evidence)

    def claim(self, owner, live=False):
        identifier(owner, "owner")
        with self.connection() as db:
            if self._get(db, "recovery_required") == "1" or self._get(db, "stop") == "1":
                return None
            # Pending input survives a full queue. Only owner input releases a hold.
            for row in db.execute("SELECT DISTINCT t.id,t.state,e.source FROM tasks t JOIN inbox i ON i.task_id=t.id JOIN events e ON e.seq=i.event_seq "
                                  "WHERE t.state IN ('waiting','held') AND i.disposition='pending' AND i.wake=1 AND (t.state='waiting' OR e.created>t.updated)").fetchall():
                self._wake(db, row["id"], trusted=row["source"] == "owner")
            for row in db.execute("SELECT * FROM tasks WHERE state IN ('queued','waiting','held')").fetchall():
                spec = json.loads(row["spec"])
                if time.time() >= row["created"] + spec["lifetime_seconds"]:
                    db.execute("UPDATE tasks SET state='cancelled',detail='task lifetime expired',updated=? WHERE id=?", (time.time(), row["id"]))
            active = list(db.execute("SELECT spec FROM tasks WHERE state IN ('running','cancelling')"))
            if len(active) >= self.limits.workers:
                return None
            used, count = db.execute("SELECT COALESCE(SUM(reserved_cents),0),COUNT(*) FROM attempts").fetchone()
            for row in db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY created,id").fetchall():
                spec = json.loads(row["spec"])
                if spec["provider"] != "mock" and not live:
                    continue
                deps = list(db.execute("SELECT t.* FROM dependencies d JOIN tasks t ON d.depends_on=t.id WHERE d.task_id=?", (row["id"],)))
                if any(d["state"] in ("failed", "cancelled", "interrupted", "blocked") for d in deps):
                    db.execute("UPDATE tasks SET state='blocked',detail='dependency failed or stopped',updated=? WHERE id=?", (time.time(), row["id"]))
                    continue
                eligible = ("accepted", "completed") if spec["dependency_mode"] == "completed" else ("accepted",)
                if any(d["state"] not in eligible for d in deps) or any(self.conflict(spec, json.loads(other["spec"])) for other in active):
                    continue
                own_used, own_count = db.execute("SELECT COALESCE(SUM(reserved_cents),0),COUNT(*) FROM attempts WHERE task_id=?", (row["id"],)).fetchone()
                if (used + spec["budget_cents"] > self.limits.budget_cents or count >= self.limits.starts or
                        own_used + spec["budget_cents"] > spec["total_budget_cents"] or own_count >= spec["max_attempts"]):
                    db.execute("UPDATE tasks SET state='blocked',detail='admission budget/start cap reached',updated=? WHERE id=?", (time.time(), row["id"]))
                    self._audit(db, row["id"], "budget_blocked")
                    continue
                guard_stamp = row["workspace_stamp"]
                try:
                    self.validate_spec(spec)
                    if own_count and spec["continuation"] != "none" and not row["session_id"]:
                        raise SafetyError("continuation session missing; no fresh-session fallback")
                except SafetyError as exc:
                    db.execute("UPDATE tasks SET state='blocked',detail=?,updated=? WHERE id=?", (str(exc), time.time(), row["id"]))
                    continue
                attempt = uuid.uuid4().hex
                events = [dict(e) for e in db.execute("SELECT e.* FROM events e JOIN inbox i ON i.event_seq=e.seq WHERE i.task_id=? AND i.disposition='pending' ORDER BY seq", (row["id"],))]
                predecessors = [dict(r) for r in db.execute("SELECT t.id,t.result_ref FROM dependencies d JOIN tasks t ON t.id=d.depends_on WHERE d.task_id=?", (row["id"],))]
                if row["result_ref"]:
                    predecessors.append({"id": row["id"], "result_ref": row["result_ref"]})
                if spec.get("previous_task"):
                    previous = self._task(db, spec["previous_task"])
                    if previous["result_ref"]:
                        predecessors.append({"id": previous["id"], "result_ref": previous["result_ref"]})
                planned_session = row["session_id"] or (str(uuid.uuid4()) if spec["continuation"] != "none" and spec["provider"] == "claude" else None)
                snapshot = {"spec": spec, "events": events, "predecessors": predecessors, "session_id": row["session_id"], "requested_session_id": planned_session, "workspace_stamp": guard_stamp}
                context_ref = self._artifact(db, encoded(snapshot))
                refs = [(e["ref"], "event") for e in events] + [(r["result_ref"], "predecessor") for r in predecessors if r["result_ref"]]
                db.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?,?)", [(row["id"], context_ref, ref, relation) for ref, relation in refs])
                db.execute("UPDATE tasks SET state='running',owner=?,attempt=?,workspace_stamp=?,updated=? WHERE id=?", (owner, attempt, guard_stamp, time.time(), row["id"]))
                db.execute("INSERT INTO attempts(id,task_id,owner,started,status,reserved_cents,context_ref,session_id) VALUES (?,?,?,?,'running',?,?,?)",
                           (attempt, row["id"], owner, time.time(), spec["budget_cents"], context_ref, planned_session))
                db.execute("UPDATE inbox SET disposition='claimed',attempt=? WHERE task_id=? AND disposition='pending'", (attempt, row["id"]))
                self._audit(db, row["id"], "claimed", attempt)
                result = dict(self._task(db, row["id"]))
                result.update(events=events, predecessors=predecessors, context_ref=context_ref, requested_session_id=planned_session)
                return result
        return None

    def prepare(self, task):
        """Expensive Git checks happen outside database locks and the event loop."""
        spec = json.loads(task["spec"])
        if spec["provider"] == "mock" or not (spec["mode"] == "workspace-write" or spec["protect_workspace"]):
            return task
        with self.connection(write=False) as db:
            row = self._task(db, task["id"])
            expected = row["workspace_stamp"]
            deps = list(db.execute("SELECT t.* FROM dependencies d JOIN tasks t ON t.id=d.depends_on WHERE d.task_id=?", (task["id"],)))
            for dep in deps:
                if json.loads(dep["spec"])["workspace"] == spec["workspace"] and dep["workspace_stamp"]:
                    expected = dep["workspace_stamp"]
        current = fingerprint(spec["workspace"])
        if not expected or current != expected:
            raise SafetyError("workspace changed outside the last approved/completed snapshot")
        context = review_context(spec["workspace"], current) if spec["protect_workspace"] and spec["routing"].get("role") in ("plan", "security") else None
        with self.connection() as db:
            row = self._task(db, task["id"])
            if row["owner"] != task["owner"] or row["attempt"] != task["attempt"] or row["state"] not in ("running", "cancelling"):
                raise SafetyError("stale preparation owner")
            if context:
                ref = self._artifact(db, context)
                task["predecessors"].append({"id": "git-change-context", "result_ref": ref})
            snapshot = {"spec": spec, "events": task["events"], "predecessors": task["predecessors"], "session_id": task["session_id"],
                        "requested_session_id": task.get("requested_session_id"), "workspace_stamp": current}
            ref = self._artifact(db, encoded(snapshot))
            for entry in task["predecessors"]:
                db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,'predecessor')", (task["id"], ref, entry["result_ref"]))
            for event in task["events"]:
                db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,'event')", (task["id"], ref, event["ref"]))
            db.execute("UPDATE attempts SET context_ref=? WHERE id=?", (ref, task["attempt"]))
            db.execute("UPDATE tasks SET workspace_stamp=? WHERE id=?", (current, task["id"]))
            task.update(workspace_stamp=current, context_ref=ref)
        return task

    @staticmethod
    def conflict(a, b):
        if a["mode"] == b["mode"] == "read-only":
            return False
        if overlap(a["workspace"], b["workspace"]):
            return True  # serialize any writer in a shared/overlapping checkout
        return a["project"] == b["project"] and any(overlap(x, y) for x in a["paths"] for y in b["paths"])

    @staticmethod
    def session_binding(spec):
        return encoded({k: spec[k] for k in ("provider", "workspace", "model", "mode", "paths")})

    def graph(self, task_id):
        with self.connection(write=False) as db:
            self._task(db, task_id)
            return [dict(r) for r in db.execute("SELECT * FROM edges WHERE task_id=?", (task_id,))]

    @staticmethod
    def worker_report(output):
        try:
            envelope = json.loads(output)
            report = json.loads(envelope.get("result", ""))
        except (ValueError, AttributeError, TypeError) as exc:
            raise SafetyError("invalid ongoing worker report; owner intervention required") from exc
        if not isinstance(report, dict) or report.get("status") not in ("waiting", "ready", "blocked", "recall"):
            raise SafetyError("unknown ongoing worker status; owner intervention required")
        refs = report.get("recall", [])
        if not isinstance(refs, list) or len(refs) > 4 or any(not isinstance(r, str) or not re.fullmatch(r"[a-f0-9]{64}", r) for r in refs):
            raise SafetyError("invalid bounded worker recall report")
        return {"status": report["status"], "recall": list(dict.fromkeys(refs))}

    def _recall_request(self, db, task_id, attempt, refs):
        if not refs:
            raise SafetyError("empty recall request")
        allowed = {r[0] for r in db.execute("SELECT child_ref FROM edges WHERE task_id=?", (task_id,))}
        if not set(refs).issubset(allowed):
            raise SafetyError("recall reference is outside this task's authorized context")
        bodies, size = [], 0
        for ref in refs:
            if db.execute("SELECT 1 FROM recalls WHERE task_id=? AND ref=?", (task_id, ref)).fetchone():
                raise SafetyError("duplicate recall request; owner intervention required")
            raw = db.execute("SELECT body,size FROM artifacts WHERE ref=?", (ref,)).fetchone()
            size += raw["size"]
            if size > 16384:
                raise SafetyError("recall exceeds 16 KiB round cap; owner must narrow context")
            bodies.append({"ref": ref, "untrusted_content": bytes(raw["body"]).decode()})
        if db.execute("SELECT COUNT(*) FROM recalls WHERE task_id=?", (task_id,)).fetchone()[0] + len(refs) > 8:
            raise SafetyError("recall count cap reached")
        db.executemany("INSERT INTO recalls VALUES (?,?)", [(task_id, ref) for ref in refs])
        seq, _ = self._event(db, "controller", attempt, "recall_response", encoded({"task_id": task_id, "artifacts": bodies}), "local")
        db.execute("INSERT INTO inbox(task_id,event_seq,wake) VALUES (?,?,1)", (task_id, seq))

    def finish(self, task_id, owner, attempt, state, output, detail="", session_id=None):
        if state not in ("completed", "failed", "cancelled", "interrupted"):
            raise SafetyError("invalid terminal state")
        before = self.task(task_id)
        prior_spec = json.loads(before["spec"])
        stamp = before["workspace_stamp"]
        if prior_spec["provider"] != "mock" and (prior_spec["mode"] == "workspace-write" or prior_spec["protect_workspace"]):
            try:
                stamp = fingerprint(prior_spec["workspace"])
                if prior_spec["mode"] == "workspace-write" and prior_spec["provider"] != "checks":
                    enforce_changed_paths(prior_spec["workspace"], prior_spec["paths"])
                if (prior_spec["mode"] == "read-only" or prior_spec["provider"] == "checks") and before["workspace_stamp"] and stamp != before["workspace_stamp"]:
                    raise SafetyError("review/check workspace changed during execution")
            except SafetyError as exc:
                state, detail = "failed", str(exc)
        with self.connection() as db:
            row = self._task(db, task_id)
            if row["owner"] != owner or row["attempt"] != attempt or row["state"] not in ("running", "cancelling"):
                raise SafetyError("stale worker ownership")
            spec = json.loads(row["spec"])
            if row["state"] == "cancelling":
                state = "cancelled"
            ref = self._artifact(db, output) if output else None
            context = db.execute("SELECT context_ref FROM attempts WHERE id=?", (attempt,)).fetchone()[0]
            if ref:
                db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,'based_on')", (task_id, ref, context))
            target = state
            if state == "completed" and spec["continuation"] != "none":
                binding = self.session_binding(spec)
                try:
                    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
                        raise SafetyError("persistent worker did not return a valid exact session ID")
                    if spec["provider"] != "mock":
                        try:
                            uuid.UUID(session_id)
                        except (ValueError, AttributeError):
                            raise SafetyError("provider session must be an exact UUID, not a name")
                    expected = db.execute("SELECT session_id FROM attempts WHERE id=?", (attempt,)).fetchone()[0]
                    if expected and session_id != expected:
                        raise SafetyError("provider session does not match the claimed session")
                    if row["session_id"] and (session_id != row["session_id"] or row["binding"] != binding):
                        raise SafetyError("provider session identity/binding mismatch")
                    other = db.execute("SELECT id FROM tasks WHERE session_id=? AND id!=?", (session_id, task_id)).fetchone()
                    if other:
                        raise SafetyError("provider session is already owned by another task")
                    # Identity is valid even when the report needs owner clarification.
                    db.execute("UPDATE tasks SET session_id=?,binding=? WHERE id=?", (session_id, binding, task_id))
                    report = self.worker_report(output)
                    target = {"ready": "completed", "blocked": "held"}.get(report["status"], "waiting")
                    if report["status"] == "recall":
                        db.execute("SAVEPOINT recall_round")
                        try:
                            self._recall_request(db, task_id, attempt, report["recall"])
                            db.execute("RELEASE recall_round")
                        except SafetyError:
                            db.execute("ROLLBACK TO recall_round")
                            db.execute("RELEASE recall_round")
                            raise
                    if target == "completed" and db.execute("SELECT 1 FROM inbox WHERE task_id=? AND disposition='pending' AND wake=1", (task_id,)).fetchone():
                        target = "waiting"
                    db.execute("UPDATE tasks SET session_id=?,binding=? WHERE id=?", (session_id, binding, task_id))
                except SafetyError as exc:
                    target, detail = "held", str(exc)
                    if "session" in detail:
                        target = "failed"
            db.execute("UPDATE tasks SET state=?,result_ref=?,detail=?,workspace_stamp=?,updated=? WHERE id=?", (target, ref, detail[:4096], stamp, time.time(), task_id))
            db.execute("UPDATE attempts SET status=?,ended=?,result_ref=?,session_id=? WHERE id=?", (state if target in ('waiting','held') else target, time.time(), ref, session_id, attempt))
            disposition = "delivered" if state == "completed" else "uncertain"
            db.execute("UPDATE inbox SET disposition=? WHERE task_id=? AND attempt=?", (disposition, task_id, attempt))
            self._audit(db, task_id, target, detail)
            # Do not consume next-turn input in this turn. Held tasks require a NEW owner input.
            if target == "waiting" and db.execute("SELECT 1 FROM inbox WHERE task_id=? AND disposition='pending' AND wake=1", (task_id,)).fetchone():
                self._wake(db, task_id)

    def start_session(self):
        """Caller must hold runner lock. Never replay an uncertain prior attempt."""
        with self.connection() as db:
            stale = (self._get(db, "dirty") == "1" or
                     db.execute("SELECT 1 FROM tasks WHERE state IN ('running','cancelling')").fetchone() is not None)
            if stale:
                for row in db.execute("SELECT id,attempt FROM tasks WHERE state IN ('running','cancelling')").fetchall():
                    db.execute("UPDATE tasks SET state='interrupted',detail='unclean runner exit; inspect isolated host',updated=? WHERE id=?", (time.time(), row["id"]))
                    db.execute("UPDATE attempts SET status='interrupted',ended=? WHERE id=?", (time.time(), row["attempt"]))
                    db.execute("UPDATE inbox SET disposition='uncertain' WHERE task_id=? AND disposition='claimed'", (row["id"],))
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
                db.execute("UPDATE inbox SET disposition='uncertain' WHERE task_id=? AND disposition='claimed'", (row["id"],))
            self._set(db, "recovery_required", "0")
            self._set(db, "dirty", "0")
            self._audit(db, None, "operator_recovery", evidence)

    def heartbeat(self):
        with self.connection() as db:
            self._set(db, "heartbeat", time.time())
            return self._get(db, "stop") == "1"

    def repair_draft(self, build_id, failed_id, new_id, goal):
        identifier(new_id, "new repair ID")
        bounded_text(goal, "repair goal")
        build, failed = self.task(build_id), self.task(failed_id)
        spec, failed_spec = json.loads(build["spec"]), json.loads(failed["spec"])
        if spec["mode"] != "workspace-write" or spec["provider"] == "checks":
            raise SafetyError("repair scope must come from the original implementation task")
        if failed["state"] not in ("failed", "held", "blocked", "interrupted", "completed"):
            raise SafetyError("repair requires a captured unsuccessful/review result")
        if (spec["project"], spec["workspace"]) != (failed_spec["project"], failed_spec["workspace"]):
            raise SafetyError("repair evidence must belong to the same project/workspace")
        with self.connection(write=False) as db:
            existing = db.execute("SELECT 1 FROM tasks WHERE id=?", (new_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM tasks WHERE json_extract(spec,'$.repair_of')=?", (build_id,)).fetchone()[0]
            if count >= 2 and not existing:
                raise SafetyError("two repair drafts already exist for this build; owner must re-plan")
        spec.update(id=new_id, goal=goal, previous_task=failed_id, repair_of=build_id, dependencies=[],
                    continuation="none", max_attempts=1, total_budget_cents=spec["budget_cents"], subscriptions=[])
        return self.create_task(spec)  # Never inherits approval or starts a model.

    def require_recovery(self, detail):
        with self.connection() as db:
            self._set(db, "recovery_required", "1")
            self._audit(db, None, "recovery_required", detail)

    def stopping(self):
        with self.connection(write=False) as db:
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
        with self.connection(write=False) as db:
            return {"settings": {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings")},
                    "states": {r[0]: r[1] for r in db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state")},
                    "reserved_cents": db.execute("SELECT COALESCE(SUM(reserved_cents),0) FROM attempts").fetchone()[0]}
