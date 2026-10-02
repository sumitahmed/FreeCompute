"""Versioned local authority, transactions, checkpoints and workspace ownership."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from harness.security import scrubber
from harness.storage.scheduler_schema import SCHEDULER_SCHEMA


SCHEMA_VERSION = 2


def identity():
    return uuid.uuid4().hex


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(scrubber.structured(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    # Hash the exact transient input; do not hash its redacted replacement.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def runtime_home(workspace):
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    key = hashlib.sha256(os.path.normcase(str(Path(workspace).resolve())).encode()).hexdigest()
    return base / "FreeCompute" / "workspaces" / key


class WorkspaceOwner:
    """An OS-held lock, released on process exit. SQLite alone is insufficient."""
    def __init__(self, workspace):
        home = runtime_home(workspace)
        home.mkdir(parents=True, exist_ok=True)
        self.file = (home / "owner.lock").open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another CoreService owns this workspace; close it before resuming") from None

    def close(self):
        if self.file.closed:
            return
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE workspaces(id TEXT PRIMARY KEY, version INTEGER NOT NULL, root_hash TEXT UNIQUE NOT NULL);
CREATE TABLE sessions(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), version INTEGER NOT NULL,
 revision INTEGER NOT NULL, status TEXT NOT NULL, profile_id TEXT NOT NULL, context_epoch INTEGER NOT NULL,
 system_prefix TEXT NOT NULL, tool_prefix TEXT NOT NULL, history TEXT NOT NULL,
 current_task_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE tasks(
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), agent_id TEXT NOT NULL,
 version INTEGER NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, prompt TEXT NOT NULL,
 driver TEXT NOT NULL, history TEXT NOT NULL, allowed_tools TEXT NOT NULL, profile_id TEXT NOT NULL,
 context_epoch INTEGER NOT NULL, max_turns INTEGER NOT NULL, selected_context TEXT NOT NULL,
 final_answer TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE agents(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
 profile_id TEXT NOT NULL, context_epoch INTEGER NOT NULL, capabilities TEXT NOT NULL);
CREATE TABLE commands(
 request_id TEXT PRIMARY KEY, version INTEGER NOT NULL, operation TEXT NOT NULL,
 fingerprint TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id));
CREATE TABLE inference_attempts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
 profile_id TEXT NOT NULL, context_epoch INTEGER NOT NULL, state TEXT NOT NULL,
 request_hash TEXT NOT NULL, response TEXT, usage TEXT, error TEXT,
 started_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE actions(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), agent_id TEXT NOT NULL REFERENCES agents(id),
 version INTEGER NOT NULL, revision INTEGER NOT NULL, turn INTEGER NOT NULL, call_id TEXT NOT NULL,
 name TEXT NOT NULL, arguments TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
 result TEXT, target TEXT, pre_hash TEXT, post_hash TEXT, profile_id TEXT NOT NULL,
 context_epoch INTEGER NOT NULL, requires_reproposal INTEGER NOT NULL DEFAULT 0,
 UNIQUE(task_id, turn, call_id));
CREATE TABLE approvals(
 id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES actions(id), version INTEGER NOT NULL,
 action_revision INTEGER NOT NULL, task_revision INTEGER NOT NULL, profile_id TEXT NOT NULL,
 context_epoch INTEGER NOT NULL, capabilities_hash TEXT NOT NULL, arguments_hash TEXT NOT NULL,
 target_hash TEXT, state TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE events(
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), task_id TEXT,
 version INTEGER NOT NULL, sequence INTEGER NOT NULL, entity_id TEXT NOT NULL,
 revision INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(session_id, sequence));
CREATE TABLE checkpoints(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
 task_revision INTEGER NOT NULL, event_sequence INTEGER NOT NULL, state TEXT NOT NULL,
 driver TEXT NOT NULL, history TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE artifacts(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), action_id TEXT NOT NULL REFERENCES actions(id),
 version INTEGER NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL, media_type TEXT NOT NULL,
 relative_path TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE snapshots(
 id TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL REFERENCES actions(id), version INTEGER NOT NULL,
 target TEXT NOT NULL, pre_artifact_id TEXT REFERENCES artifacts(id), pre_hash TEXT, post_hash TEXT,
 state TEXT NOT NULL, diff TEXT NOT NULL DEFAULT '');
CREATE INDEX actions_task_state ON actions(task_id, state);
CREATE INDEX events_session_sequence ON events(session_id, sequence);
CREATE INDEX checkpoints_task_revision ON checkpoints(task_id, task_revision);
"""


class RuntimeStore:
    def __init__(self, workspace, state_dir=None):
        self.workspace = Path(workspace).resolve()
        self.directory = Path(state_dir).resolve() if state_dir else runtime_home(self.workspace)
        # Test injection is supported, but never permits an in-workspace/sync DB.
        if self.directory.is_relative_to(self.workspace) or any(p.casefold().startswith("onedrive") for p in self.directory.parts):
            raise ValueError("Runtime state must be outside the workspace and OneDrive")
        self.owner = WorkspaceOwner(self.workspace)
        self._lock = threading.RLock()
        self.db = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                self.directory.chmod(0o700)
            self.db = sqlite3.connect(self.directory / "runtime.sqlite3", isolation_level=None, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            if os.name != "nt":
                (self.directory / "runtime.sqlite3").chmod(0o600)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("Unversioned database requires explicit migration; preserved")
                self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + SCHEDULER_SCHEMA + "\nPRAGMA user_version=2;\nCOMMIT;")
            elif version == 1:
                # Validate workspace ownership before an additive, atomic migration.
                prior = self.db.execute("SELECT root_hash FROM workspaces").fetchone()
                root_hash = hashlib.sha256(os.path.normcase(str(self.workspace)).encode()).hexdigest()
                if not prior or prior[0] != root_hash:
                    raise ValueError("Runtime database belongs to another workspace; migration refused")
                self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEDULER_SCHEMA + "\nPRAGMA user_version=2;\nCOMMIT;")
            elif version != SCHEMA_VERSION:
                raise ValueError("Unsupported runtime schema; explicit migration required")
            root_hash = hashlib.sha256(os.path.normcase(str(self.workspace)).encode()).hexdigest()
            with self.transaction() as db:
                row = db.execute("SELECT * FROM workspaces").fetchone()
                if row and row["root_hash"] != root_hash:
                    raise ValueError("Runtime database belongs to another workspace")
                if not row:
                    db.execute("INSERT INTO workspaces VALUES(?,1,?)", (identity(), root_hash))
                self.workspace_id = db.execute("SELECT id FROM workspaces").fetchone()[0]
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        self.owner.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def one(self, sql, parameters=()):
        with self._lock:
            row = self.db.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def all(self, sql, parameters=()):
        with self._lock:
            return [dict(row) for row in self.db.execute(sql, parameters).fetchall()]

    def event(self, db, session_id, task_id, kind, payload=None, entity_id=None, revision=0, actor="core"):
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE session_id=?", (session_id,)).fetchone()[0]
        event = dict(id=identity(), session_id=session_id, task_id=task_id, version=1, sequence=sequence,
                     entity_id=entity_id or task_id or session_id, revision=revision, kind=kind,
                     actor=actor, payload=scrubber.structured(payload or {}), created_at=timestamp())
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            event["id"], session_id, task_id, 1, sequence, event["entity_id"], revision,
            kind, actor, encode(event["payload"]), event["created_at"]))
        return event

    def checkpoint(self, db, task_id):
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE session_id=?", (task["session_id"],)).fetchone()[0]
        db.execute("INSERT INTO checkpoints VALUES(?,?,1,?,?,?,?,?,?)", (
            identity(), task_id, task["revision"], sequence, task["state"], task["driver"], task["history"], timestamp()))

    def update_task(self, db, task_id, *, state=None, driver=None, history=None, final_answer=None):
        changes = {"updated_at": timestamp()}
        for name, value in (("state", state), ("driver", driver), ("history", history), ("final_answer", final_answer)):
            if value is not None:
                changes[name] = encode(value) if name == "history" else value
        query = ",".join(name + "=?" for name in changes)
        db.execute("UPDATE tasks SET revision=revision+1," + query + " WHERE id=?", (*changes.values(), task_id))
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        db.execute("UPDATE sessions SET revision=revision+1,status=?,updated_at=? WHERE id=?",
                   (task["state"], timestamp(), task["session_id"]))
        return dict(task)

    def recover(self):
        """Under exclusive ownership: invalidate grants and fence uncertain effects."""
        emitted = []
        with self.transaction() as db:
            db.execute("UPDATE approvals SET state='expired',decided_at=? WHERE state IN ('pending','approved')", (timestamp(),))
            db.execute("UPDATE inference_attempts SET state='interrupted',ended_at=? WHERE state='active'", (timestamp(),))
            allocation = db.execute("SELECT value FROM metadata WHERE key='allocation'").fetchone()
            if allocation and json.loads(allocation[0])["state"] == "active":
                db.execute("UPDATE metadata SET value=? WHERE key='allocation'", (encode({"state": "quarantined", "reason": "core restarted during inference"}),))
            tasks = db.execute("SELECT * FROM tasks WHERE state IN ('created','queued','running','waiting_approval','paused','outcome_unknown','cancel_requested')").fetchall()
            for task in tasks:
                db.execute("UPDATE actions SET state='outcome_unknown',revision=revision+1 WHERE task_id=? AND state='executing'", (task["id"],))
                db.execute("UPDATE actions SET state='proposed',revision=revision+1 WHERE task_id=? AND state IN ('approved','awaiting_approval')", (task["id"],))
                uncertain = db.execute("SELECT 1 FROM actions WHERE task_id=? AND state='outcome_unknown'", (task["id"],)).fetchone()
                state = "outcome_unknown" if uncertain else "queued" if task["state"] == "queued" else "paused"
                updated = self.update_task(db, task["id"], state=state)
                emitted.append(self.event(db, task["session_id"], task["id"], "task.recovered", {"state": state}, revision=updated["revision"]))
                self.checkpoint(db, task["id"])
        return emitted

    def events(self, session_id, after=0):
        rows = self.all("SELECT * FROM events WHERE session_id=? AND sequence>? ORDER BY sequence", (session_id, after))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows
