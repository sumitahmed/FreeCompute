"""Single-writer experiment: durable authority plus a one-slot inference broker.

SQLite records decisions before effects. SDK persistence is only a projection.
No atomic transaction spans SQLite and filesystem/remote effects: an interrupted
executing action is quarantined rather than retried. Registered secrets in
arguments require reproposal because sanitized persistence cannot replay them.
"""
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import threading
import time
from typing import NewType
import uuid
from urllib import request, error
from urllib.parse import urlsplit

from harness.security import scrubber
from harness.tools.registry import ToolBroker

TaskID = NewType("TaskID", str)
AgentID = NewType("AgentID", str)
ActionID = NewType("ActionID", str)


def identity():
    return uuid.uuid4().hex


class ExperimentStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS records (category TEXT, id TEXT, value TEXT, PRIMARY KEY(category,id))")
        self.connection.commit()

    def put(self, category, key, value):
        encoded = json.dumps(scrubber.structured(value), sort_keys=True)
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (category, key, encoded))

    def get(self, category, key):
        with self.lock:
            row = self.connection.execute("SELECT value FROM records WHERE category=? AND id=?", (category, key)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, category):
        with self.lock:
            return [(key, json.loads(value)) for key, value in self.connection.execute("SELECT id,value FROM records WHERE category=? ORDER BY rowid", (category,)).fetchall()]

    def delete(self, category, key):
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM records WHERE category=? AND id=?", (category, key))

    def event(self, task_id, kind, **data):
        self.put("events", identity(), {"task_id": task_id, "kind": kind, "time": time.time(), **data})

    def close(self):
        self.connection.close()


@dataclass(frozen=True)
class Actor:
    task_id: TaskID
    agent_id: AgentID
    tools: frozenset
    parent_request: str | None = None

    def child(self, tools, parent_request=None):
        tools = frozenset(tools)
        if not tools <= self.tools:
            raise ValueError("Child cannot widen permissions")
        return Actor(self.task_id, AgentID(identity()), tools, parent_request)


class DurableToolBroker:
    def __init__(self, store, registry, actor, cancellation, approval=None, checkpoint=None):
        self.store, self.actor, self.cancellation = store, actor, cancellation
        self.broker = ToolBroker(registry, actor.tools)
        self.approval, self.checkpoint = approval, checkpoint or (lambda _: None)
        self.execution_lock = threading.RLock()

    def reconcile(self):
        # Call once on exclusive startup, before accepting SDK continuations.
        for key, row in self.store.all("actions"):
            if row["task_id"] != self.actor.task_id:
                continue
            if row["state"] == "executing":
                row.update(state="outcome_unknown", result={"status": "outcome_unknown", "message": "Interrupted effect requires human reconciliation"})
            elif row["state"] == "approved":
                row.update(state="pending", approval_invalidated_on_restart=True)
            self.store.put("actions", key, row)

    def execute(self, action_id, name, arguments, *, requires_reproposal=False):
        with self.execution_lock:
            return self._execute(action_id, name, arguments, requires_reproposal)

    def _execute(self, action_id, name, arguments, requires_reproposal):
        # Identity is bound to task AND actor, not controlled by model args.
        key = f"{self.actor.task_id}/{self.actor.agent_id}/{action_id}"
        clean = scrubber.structured(arguments)
        fingerprint = hashlib.sha256(json.dumps([name, arguments], sort_keys=True).encode()).hexdigest()
        row = self.store.get("actions", key)
        if row:
            if row["fingerprint"] != fingerprint:
                return {"status": "rejected", "message": "Action identity collision"}
            if row["state"] in {"completed", "failed", "denied", "outcome_unknown"}:
                return row["result"]
            if row["state"] == "executing":
                return {"status": "outcome_unknown", "message": "Effect already in flight"}
            if row["requires_reproposal"]:
                return {"status": "rejected", "message": "Sanitized action requires fresh proposal"}
        else:
            row = {"task_id": self.actor.task_id, "agent_id": self.actor.agent_id, "action_id": action_id,
                   "name": name, "arguments": clean, "fingerprint": fingerprint, "state": "pending",
                   "requires_reproposal": requires_reproposal or clean != arguments}
            self.store.put("actions", key, row)
            self.store.event(self.actor.task_id, "tool_proposed", action_id=action_id, agent_id=self.actor.agent_id)
        if requires_reproposal:
            result = {"status": "rejected", "message": "Sanitized action requires fresh proposal"}
            row.update(state="denied", result=result)
            self.store.put("actions", key, row)
            self.store.event(self.actor.task_id, "tool_denied", action_id=action_id, agent_id=self.actor.agent_id)
            return result
        if self.broker._registry.is_approval_required(name) and any(r["task_id"] == self.actor.task_id and r["state"] == "outcome_unknown" for _, r in self.store.all("actions")):
            result = {"status": "outcome_unknown", "message": "Task has an uncertain effect; reconcile before further mutations"}
            row.update(state="outcome_unknown", result=result)
            self.store.put("actions", key, row)
            return result
        self.checkpoint("before_approval")

        def transition(state):
            row["state"] = state
            self.store.put("actions", key, row)
            self.store.event(self.actor.task_id, "tool_" + state, action_id=action_id, agent_id=self.actor.agent_id)

        def approve(tool, args):
            if self.approval is None or self.approval(tool, args) is not True:
                return False
            if self.cancellation.is_cancelled:
                return False
            transition("approved")
            self.checkpoint("after_approval")
            transition("executing")
            return True

        # Reads may run under the immutable capability grant; writes still use
        # ToolRegistry's authoritative schema/path/hash/interactive gate.
        if name in self.actor.tools and not self.broker._registry.is_approval_required(name):
            transition("executing")
        result = self.broker.execute(name, arguments, approval_callback=approve, cancellation_token=self.cancellation)
        result = scrubber.structured(result)
        if result.get("cancellation_requested"):
            # An exited owned shell does not prove its descendants stopped or
            # that a partially executed effect did not occur.
            result["status"] = "outcome_unknown"
        if "error" in result and row["state"] == "executing" and self.broker._registry.is_approval_required(name):
            result["status"] = "outcome_unknown"
        if result.get("status") == "rejected":
            row["state"] = "denied"
        elif result.get("status") == "outcome_unknown":
            row["state"] = "outcome_unknown"
        else:
            row["state"] = "failed" if "error" in result else "completed"
        row["result"] = result
        # State and normalized result in ONE commit; no crash between a durable
        # completed marker and its result is permitted.
        self.store.put("actions", key, row)
        self.store.event(self.actor.task_id, "tool_" + row["state"], action_id=action_id, agent_id=self.actor.agent_id)
        self.checkpoint("after_result")
        return result


class InferenceBroker:
    """Transport owned by FreeCompute; retries are distinct, recorded requests.

    One slot is acquired only during inference, never while waiting for a tool
    or child. No remote cancellation acknowledgement is invented.
    """
    def __init__(self, store, endpoint, profile="fixture", attempts=2, timeout=3):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("This experiment permits a loopback fake endpoint only")
        self.store, self.endpoint, self.profile = store, endpoint, profile
        self.attempts, self.timeout = attempts, timeout
        self.slot = threading.BoundedSemaphore(1)

    def generate(self, actor, purpose, messages, tools, cancellation, on_fragment=None):
        payload = scrubber.structured({"model": self.profile, "messages": messages, "tools": tools})
        parent = actor.parent_request
        for attempt in range(self.attempts):
            if cancellation.is_cancelled:
                raise RuntimeError("Cancellation requested; remote outcome not confirmed")
            rid = identity()
            row = {"request_id": rid, "task_id": actor.task_id, "agent_id": actor.agent_id,
                   "model_profile": self.profile, "purpose": purpose if attempt == 0 else "retry",
                   "operation_purpose": purpose, "parent_request": parent, "started": time.time(), "finished": None}
            self.store.put("requests", rid, row)
            parent = rid
            try:
                while not self.slot.acquire(timeout=0.05):
                    if cancellation.is_cancelled:
                        raise RuntimeError("Cancelled while waiting for inference slot")
                try:
                    if cancellation.is_cancelled:
                        raise RuntimeError("Cancelled before transport")
                    req = request.Request(self.endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
                    # Redirects are forbidden even for the synthetic transport.
                    class NoRedirect(request.HTTPRedirectHandler):
                        def redirect_request(self, *args, **kwargs):
                            return None
                    with request.build_opener(NoRedirect).open(req, timeout=self.timeout) as response:
                        if response.headers.get_content_type() == "text/event-stream":
                            parts, done = [], False
                            for line in response:
                                if cancellation.is_cancelled:
                                    cancellation.local_stop_confirmed = True
                                    raise RuntimeError("Local stream stopped; remote cancellation unknown")
                                if not line.startswith(b"data: "):
                                    continue
                                raw = line[6:].strip()
                                if raw == b"[DONE]":
                                    done = True
                                    break
                                chunk = json.loads(raw)
                                if chunk["choices"][0]["delta"].get("tool_calls"):
                                    raise ValueError("Streaming tool-call codec outside the fixture profile")
                                parts.append(chunk["choices"][0]["delta"].get("content", ""))
                            if not done:
                                raise ValueError("Incomplete stream")
                            # Buffer the complete model message before ANY SDK
                            # callback/parser/log sink. Deliberately no TTFT claim.
                            data = {"id": rid, "choices": [{"message": {"role": "assistant", "content": "".join(parts)}, "finish_reason": "stop"}]}
                        else:
                            data = json.loads(response.read())
                finally:
                    self.slot.release()
                if cancellation.is_cancelled:
                    cancellation.local_stop_confirmed = True
                    raise RuntimeError("Cancelled after transport; remote outcome unknown")
                clean = scrubber.structured(data)
                # A sanitized tool proposal is no longer byte-for-byte the
                # proposed action. Do not execute replacement credential text.
                for raw_call, clean_call in zip(data["choices"][0]["message"].get("tool_calls", []), clean["choices"][0]["message"].get("tool_calls", [])):
                    # Decode before scrubbing: a quoted/backslashed credential
                    # may not match its representation inside JSON arguments.
                    original_args = json.loads(raw_call["function"]["arguments"])
                    args = scrubber.structured(original_args)
                    if args != original_args and clean_call["function"]["name"] == "fc_action" and isinstance(args, dict):
                        args["requires_reproposal"] = True
                    clean_call["function"]["arguments"] = json.dumps(args)
                row["status"] = "completed"
                if on_fragment:
                    on_fragment(clean["choices"][0]["message"].get("content") or "")
                return clean
            except error.HTTPError as exc:
                row["status"] = "failed"
                row["error"] = f"HTTP {exc.code}"
                if exc.code < 500 or attempt + 1 == self.attempts:
                    raise RuntimeError(row["error"]) from None
            except Exception as exc:
                row["status"] = "outcome_unknown" if cancellation.is_cancelled else "failed"
                row["error"] = scrubber.scrub(str(exc))
                raise RuntimeError(row["error"]) from None
            finally:
                row["finished"] = time.time()
                self.store.put("requests", rid, row)
        raise RuntimeError("Inference attempts exhausted")
