"""Core-owned action identities, approval binding, receipts and uncertainty fences."""
import json
import threading
import uuid

from harness.security import scrubber
from harness.storage.runtime import encode, fingerprint
from harness.storage.undo import file_hash
from harness.tools.sandbox import validate_workspace_path


class OutcomeUnknown(RuntimeError):
    pass


class DurableToolBroker:
    def __init__(self, store, registry, permissions, artifacts, publish, fault_hook=None):
        self.store, self.registry, self.permissions = store, registry, permissions
        self.artifacts, self.publish = artifacts, publish
        self._lock = threading.RLock()
        self._fault_hook = fault_hook

    def fault(self, stage, action):
        if self._fault_hook:
            self._fault_hook(stage, dict(action))

    def propose(self, db, task, proposals, turn):
        actions = []
        for proposal in proposals:
            action_id = uuid.uuid5(uuid.NAMESPACE_URL, f"freecompute:{task['id']}:{turn}:{proposal.call_id}").hex
            exact = {"name": proposal.name, "arguments": proposal.arguments}
            digest = fingerprint(exact)
            existing = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != digest:
                    raise ValueError("Action identity reused with different arguments")
            else:
                db.execute("""INSERT INTO actions(id,task_id,agent_id,version,revision,turn,call_id,name,arguments,
                    fingerprint,state,profile_id,context_epoch,requires_reproposal)
                    VALUES(?,?,?,1,0,?,?,?,?,?,'proposed',?,?,?)""", (
                    action_id, task["id"], task["agent_id"], turn, proposal.call_id, proposal.name,
                    encode(proposal.arguments), digest, task["profile_id"], task["context_epoch"],
                    int(scrubber.structured(exact) != exact)))
            actions.append(action_id)
        return actions

    def _receipt(self, action, result, state="completed"):
        result = scrubber.structured(result)
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM actions WHERE id=?", (action["id"],)).fetchone()
            target = current["target"]
            try:
                post_hash = file_hash(validate_workspace_path(target, str(self.store.workspace), True)) if target else None
            except Exception as exc:
                post_hash = None
                result = dict(result, file_check_error=scrubber.scrub(exc))
                if current["state"] == "executing" and self.registry.is_approval_required(action["name"]):
                    state = "outcome_unknown"
            db.execute("UPDATE actions SET state=?,result=?,post_hash=?,revision=revision+1 WHERE id=?",
                       (state, encode(result), post_hash, action["id"]))
            if state == "completed" and "error" not in result and result.get("status") != "rejected":
                self.artifacts.seal(db, dict(current), result)
            task = db.execute("SELECT * FROM tasks WHERE id=?", (action["task_id"],)).fetchone()
            if state == "outcome_unknown":
                task = self.store.update_task(db, task["id"], state="outcome_unknown")
            event = self.store.event(db, task["session_id"], task["id"], "tool." + state,
                                    {"action_id": action["id"], "call_id": action["call_id"],
                                     "tool": action["name"], "result": result}, entity_id=action["id"], revision=current["revision"] + 1)
            self.store.checkpoint(db, task["id"])
        self.publish(event)
        return result

    def _intent(self, action, target, before):
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM actions WHERE id=?", (action["id"],)).fetchone()
            if current["state"] not in {"approved", "proposed"}:
                raise ValueError("Action is no longer executable")
            if target and file_hash(target) != before:
                raise ValueError("File changed after approval")
            if action["name"] in {"write_file", "edit_file"}:
                self.artifacts.capture(db, action, target, before)
            db.execute("UPDATE actions SET state='executing',revision=revision+1 WHERE id=?", (action["id"],))
            task = db.execute("SELECT * FROM tasks WHERE id=?", (action["task_id"],)).fetchone()
            event = self.store.event(db, task["session_id"], task["id"], "tool.execution_intent",
                                    {"action_id": action["id"], "tool": action["name"]},
                                    entity_id=action["id"], revision=current["revision"] + 1)
            self.store.checkpoint(db, task["id"])
        self.publish(event)
        self.fault("before_execution", action)

    def execute(self, action_id, resolver=None, cancellation=None):
        with self._lock:
            action = self.store.one("SELECT * FROM actions WHERE id=?", (action_id,))
            if not action:
                raise ValueError("Unknown action identity")
            if action["state"] in {"completed", "denied"}:
                return json.loads(action["result"])
            if action["state"] in {"executing", "outcome_unknown"}:
                raise OutcomeUnknown("Action outcome is uncertain; reconcile before retry")
            task = self.store.one("SELECT * FROM tasks WHERE id=?", (action["task_id"],))
            arguments = json.loads(action["arguments"])
            try:
                if action["requires_reproposal"] or fingerprint({"name": action["name"], "arguments": arguments}) != action["fingerprint"]:
                    raise ValueError("Redacted or changed proposal requires a new proposal")
                if action["name"] not in json.loads(task["allowed_tools"]):
                    raise ValueError("Tool is outside this task's allowed capabilities")
                if action["profile_id"] != task["profile_id"] or action["context_epoch"] != task["context_epoch"]:
                    raise ValueError("Stale model profile/context epoch")
                arguments = self.registry.validate_arguments(action["name"], arguments)
                high_risk = self.registry.is_approval_required(action["name"])
                if high_risk and self.store.one("SELECT id FROM actions WHERE state IN ('executing','outcome_unknown') AND id<>? LIMIT 1", (action_id,)):
                    raise OutcomeUnknown("Uncertain workspace effect blocks fresh action IDs; reconcile it first")
                target = None
                if action["name"] in {"write_file", "edit_file"}:
                    target = validate_workspace_path(arguments["path"], str(self.store.workspace), True)
                elif action["name"] == "restore_snapshot":
                    snapshot = self.artifacts.snapshot(arguments["snapshot_id"])
                    target = validate_workspace_path(snapshot["target"], str(self.store.workspace), True)
                before = file_hash(target) if target else None
                if target:
                    with self.store.transaction() as db:
                        db.execute("UPDATE actions SET target=?,pre_hash=? WHERE id=?", (str(target.relative_to(self.store.workspace)), before, action_id))
                if cancellation and cancellation.is_cancelled:
                    return self._receipt(action, {"status": "rejected", "message": "Cancellation requested"}, "denied")
            except OutcomeUnknown:
                raise
            except Exception as exc:
                return self._receipt(action, {"status": "rejected", "message": scrubber.scrub(exc)}, "denied")

            def gate(name, preview):
                self.fault("before_approval", action)
                approval = self.permissions.request(action, before)
                decision = False
                try:
                    decision = resolver(name, preview) is True if resolver else False
                except KeyboardInterrupt:
                    if cancellation:
                        cancellation.cancel()
                except Exception:
                    decision = False
                if cancellation and cancellation.is_cancelled:
                    decision = False
                current_hash = file_hash(target) if target else None
                approved = self.permissions.resolve(approval, decision, current_hash)
                if not approved:
                    return False
                self.fault("after_approval", action)
                if cancellation and cancellation.is_cancelled:
                    return False
                self._intent(action, target, before)
                return True

            if not high_risk:
                self._intent(action, target, before)
            result = self.registry.execute(action["name"], arguments, approval_callback=gate if high_risk else None,
                                           cancellation_token=cancellation)
            current = self.store.one("SELECT * FROM actions WHERE id=?", (action_id,))
            uncertain = current["state"] == "executing" and high_risk and (
                "error" in result or result.get("timed_out") or result.get("cancellation_requested")
                or result.get("descendant_cancellation") == "unknown")
            state = "outcome_unknown" if uncertain else "denied" if result.get("status") == "rejected" else "completed"
            result = self._receipt(action, result, state)
            self.fault("after_result", action)
            if uncertain or self.store.one("SELECT state FROM actions WHERE id=?", (action_id,))["state"] == "outcome_unknown":
                raise OutcomeUnknown("Tool may have had effects; result recorded as outcome_unknown")
            return result

    def reconcile(self, action_id, outcome, expected_hash=None, resolver=None):
        """An explicit operator assertion plus a file witness; never executes a retry."""
        with self._lock:
            action = self.store.one("SELECT * FROM actions WHERE id=?", (action_id,))
            if not action or action["state"] != "outcome_unknown" or outcome not in {"completed", "not_executed"}:
                raise ValueError("Select an uncertain action and completed/not_executed outcome")
            target = validate_workspace_path(action["target"], str(self.store.workspace), True) if action["target"] else None
            before = file_hash(target) if target else None
            if target and (before != expected_hash or outcome == "not_executed" and before != action["pre_hash"]):
                raise ValueError("Reconciliation witness does not match the current file")
            preview = {"action_id": action_id, "tool": action["name"], "outcome": outcome,
                       "current_hash": before, "arguments": json.loads(action["arguments"])}
            if resolver is None or resolver("reconcile", scrubber.structured(preview)) is not True:
                raise ValueError("Explicit reconciliation approval required")
            if target and file_hash(target) != before:
                raise ValueError("File changed during reconciliation approval")
            result = {"status": "reconciled", "outcome": outcome, "source": "explicit operator decision", "file_hash": before}
            with self.store.transaction() as db:
                db.execute("UPDATE actions SET state='completed',result=?,post_hash=?,revision=revision+1 WHERE id=?",
                           (encode(result), before, action_id))
                if outcome == "completed":
                    self.artifacts.seal(db, action, result)
                task = self.store.update_task(db, action["task_id"], state="paused")
                event = self.store.event(db, task["session_id"], task["id"], "tool.reconciled", preview,
                                        entity_id=action_id, revision=action["revision"] + 1, actor="user")
                self.store.checkpoint(db, task["id"])
            self.publish(event)
            return result
