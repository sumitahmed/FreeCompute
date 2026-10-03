"""Read-only public projections shared by clients. No agent or scheduling policy."""
import difflib
from datetime import datetime, timezone
import json

from harness.security import scrubber


class CoreViews:
    def __init__(self, core):
        self.core, self.store = core, core.store

    def sessions(self):
        rows = self.core.list_sessions()
        for row in rows:
            first = self.store.one("SELECT prompt FROM tasks WHERE session_id=? ORDER BY rowid LIMIT 1", (row["id"],))
            row["title"] = first["prompt"][:100] if first else "New session"
        return scrubber.structured(rows)

    def tasks(self, session_id=None):
        rows = self.store.all("SELECT id,session_id,revision,state,prompt,profile_id,context_epoch,final_answer,created_at,updated_at FROM tasks"
                              + (" WHERE session_id=?" if session_id else "") + " ORDER BY rowid",
                              (session_id,) if session_id else ())
        for row in rows:
            row["cancellation"] = self.core._summary(row["id"])["cancellation"]
        return scrubber.structured(rows)

    def task(self, task_id):
        task = self.core.task(task_id)
        return next(row for row in self.tasks(task["session_id"]) if row["id"] == task_id)

    def session(self, session_id):
        # Snapshot and cursor must describe the same committed state.
        with self.store.transaction():
            session = self.store.one("SELECT id,status,profile_id,context_epoch,revision,current_task_id,created_at,updated_at FROM sessions WHERE id=?", (session_id,))
            if not session:
                raise ValueError("Unknown session")
            return scrubber.structured({"session": session, "tasks": self.tasks(session_id),
                                        "approvals": self.approvals(session_id), "cursor": self.cursor(session_id)})

    def cursor(self, session_id):
        return self.store.one("SELECT COALESCE(MAX(sequence),0) n FROM events WHERE session_id=?", (session_id,))["n"]

    def events(self, session_id, after=0, limit=200):
        if not self.store.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
            raise ValueError("Unknown session")
        if type(after) is not int or after < 0 or after > self.cursor(session_id):
            raise ValueError("Event cursor is outside this session's durable sequence")
        rows = self.store.all("SELECT * FROM events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?", (session_id, after, limit))
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return scrubber.structured(rows)

    def approvals(self, session_id=None):
        rows = self.store.all("""SELECT p.id,p.action_id,p.action_revision,p.task_revision,p.profile_id,
            p.context_epoch,p.arguments_hash,p.target_hash,p.state,p.created_at,a.name AS tool,a.task_id,t.session_id
            FROM approvals p JOIN actions a ON a.id=p.action_id JOIN tasks t ON t.id=a.task_id
            WHERE p.state='pending'""" + (" AND t.session_id=?" if session_id else "") + " ORDER BY p.created_at",
            (session_id,) if session_id else ())
        for row in rows:
            event = self.store.one("SELECT payload FROM events WHERE entity_id=? AND kind='approval.requested' ORDER BY sequence DESC LIMIT 1", (row["id"],))
            preview = json.loads(event["payload"])["arguments"] if event else {}
            row["preview"] = preview
            row["diff"] = preview.get("diff", "")
            if row["tool"] == "edit_file" and not row["diff"]:
                # Exact replacement preview only. Core checks the complete target hash.
                row["diff"] = "".join(difflib.unified_diff(
                    [line + "\n" for line in preview.get("old_str", "").splitlines()],
                    [line + "\n" for line in preview.get("new_str", "").splitlines()],
                    fromfile="a/" + preview.get("path", "file"), tofile="b/" + preview.get("path", "file")))
        return scrubber.structured(rows)

    def workers(self):
        rows = self.core.list_workers()
        for row in rows:
            checked = self.store.one("SELECT checked_at FROM workers WHERE id=?", (row["worker_id"],))["checked_at"]
            row["observed_at"] = datetime.fromtimestamp(checked, timezone.utc).isoformat() if checked is not None else None
        return scrubber.structured(rows)

    def queue(self):
        fields = ("id", "task_id", "profile_id", "requested_worker", "assigned_worker", "state", "task_state", "waiting_reason", "sequence", "created_at")
        rows = []
        for job in self.core.list_queue():
            row = {key: job.get(key) for key in fields}
            lease = self.store.one("SELECT worker_id FROM inference_leases WHERE queue_id=? AND state IN ('active','quarantined')", (job["id"],))
            row["assigned_worker"] = lease["worker_id"] if lease else None
            rows.append(row)
        return scrubber.structured(rows)

    def leases(self):
        return scrubber.structured(self.store.all("""SELECT l.id,l.worker_id,l.profile_id,l.state,l.reason,l.created_at,q.task_id
            FROM inference_leases l JOIN inference_queue q ON q.id=l.queue_id
            WHERE l.state IN ('active','quarantined') ORDER BY l.created_at"""))

    def actions(self, task_id=None):
        rows = self.store.all("SELECT id,task_id,name,arguments,revision,state,target,pre_hash,post_hash,result FROM actions"
                              + (" WHERE task_id=?" if task_id else "") + " ORDER BY rowid DESC LIMIT 100", (task_id,) if task_id else ())
        for row in rows:
            row["arguments"] = json.loads(row["arguments"])
            row["result"] = json.loads(row["result"]) if row["result"] else None
        return scrubber.structured(rows)
