"""Core-owned session/task submission and durable client idempotency keys."""
import json

from harness.core.native_driver import NativeState
from harness.security import scrubber
from harness.storage.runtime import encode, fingerprint, identity, timestamp


TERMINAL = {"completed", "failed", "malformed", "truncated", "incomplete", "max_turns", "context_overflow", "cancelled"}


class SessionManager:
    def __init__(self, store, publish):
        self.store, self.publish = store, publish

    def list_sessions(self):
        return self.store.all("SELECT id,status,profile_id,context_epoch,revision,current_task_id,created_at,updated_at FROM sessions ORDER BY updated_at DESC")

    def submit(self, prompt, profile, system, schemas, allowed_tools, *, session_id=None, request_id=None,
               max_turns=15, selected_context=None, operation="task", requested_worker=None):
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(max_turns, int) or isinstance(max_turns, bool) or not 0 < max_turns <= 100:
            raise ValueError("A nonempty prompt and a turn budget of 1..100 are required")
        request_id = request_id or identity()
        exact = {"prompt": prompt, "profile_id": profile.profile_id, "session_id": session_id,
                 "allowed_tools": sorted(allowed_tools), "max_turns": max_turns,
                 "selected_context": selected_context, "operation": operation}
        if requested_worker is not None:
            exact["requested_worker"] = requested_worker
        digest = fingerprint(exact)
        emitted = []
        with self.store.transaction() as db:
            existing = db.execute("SELECT * FROM commands WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != digest:
                    raise ValueError("Submission ID reused for a different command")
                return existing["task_id"]
            session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone() if session_id else None
            if session_id and not session:
                raise ValueError("Session does not belong to this workspace")
            if session and session["current_task_id"]:
                current = db.execute("SELECT state FROM tasks WHERE id=?", (session["current_task_id"],)).fetchone()
                if current[0] not in TERMINAL:
                    raise ValueError("Session has an unfinished task; resume or reconcile it first")
                previous = db.execute("SELECT driver FROM tasks WHERE id=?", (session["current_task_id"],)).fetchone()
                if NativeState.recover(previous[0]).phase == "pending":
                    raise ValueError("Failed session has unresolved proposals; inspect its actions and start a new session with /new")
            if not session:
                session_id = identity()
                db.execute("""INSERT INTO sessions(id,workspace_id,version,revision,status,profile_id,context_epoch,
                    system_prefix,tool_prefix,history,created_at,updated_at) VALUES(?,?,1,0,'created',?,0,?,?,'[]',?,?)""",
                           (session_id, self.store.workspace_id, profile.profile_id, scrubber.scrub(system), encode(schemas), timestamp(), timestamp()))
                emitted.append(self.store.event(db, session_id, None, "session.created", {"profile_id": profile.profile_id}))
                session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            elif session["profile_id"] != profile.profile_id or session["tool_prefix"] != encode(schemas):
                db.execute("UPDATE sessions SET context_epoch=context_epoch+1,profile_id=?,tool_prefix=?,revision=revision+1 WHERE id=?",
                           (profile.profile_id, encode(schemas), session_id))
                session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
                emitted.append(self.store.event(db, session_id, None, "session.context_changed",
                    {"profile_id": profile.profile_id, "context_epoch": session["context_epoch"]}, revision=session["revision"]))
            task_id, agent_id = identity(), identity()
            state = NativeState(agent_id, profile.profile_id, context_epoch=session["context_epoch"])
            history = json.loads(session["history"]) + [{"role": "user", "content": scrubber.scrub(prompt)}]
            db.execute("""INSERT INTO tasks(id,session_id,agent_id,version,revision,state,prompt,driver,history,
                allowed_tools,profile_id,context_epoch,max_turns,selected_context,created_at,updated_at)
                VALUES(?,?,?,1,0,'created',?,?,?,?,?,?,?,?,?,?)""", (
                task_id, session_id, agent_id, scrubber.scrub(prompt), state.serialize(), encode(history),
                encode(sorted(allowed_tools)), profile.profile_id, session["context_epoch"], max_turns,
                encode(selected_context), timestamp(), timestamp()))
            db.execute("INSERT INTO agents VALUES(?,?,1,?,?,?)", (agent_id, task_id, profile.profile_id, session["context_epoch"], encode(sorted(allowed_tools))))
            db.execute("INSERT INTO commands VALUES(?,1,?,?,?)", (request_id, operation, digest, task_id))
            db.execute("UPDATE sessions SET current_task_id=?,status='created',revision=revision+1,updated_at=? WHERE id=?", (task_id, timestamp(), session_id))
            emitted.append(self.store.event(db, session_id, task_id, "task.created", {"agent_id": agent_id, "prompt": prompt,
                "allowed_tools": sorted(allowed_tools), "request_id": request_id}, actor="user"))
            self.store.checkpoint(db, task_id)
        for event in emitted:
            self.publish(event)
        return task_id
