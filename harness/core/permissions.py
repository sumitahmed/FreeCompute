"""Durable, single-action decisions. Capability declarations never grant consent."""
import json

from harness.storage.runtime import fingerprint, identity, timestamp


class PermissionService:
    def __init__(self, store, publish):
        self.store = store
        self.publish = publish

    def request(self, action, target_hash):
        with self.store.transaction() as db:
            db.execute("UPDATE actions SET state='awaiting_approval',revision=revision+1 WHERE id=?", (action["id"],))
            current = db.execute("SELECT * FROM actions WHERE id=?", (action["id"],)).fetchone()
            task = self.store.update_task(db, action["task_id"], state="waiting_approval")
            approval_id = identity()
            db.execute("""INSERT INTO approvals(id,action_id,version,action_revision,task_revision,profile_id,
                context_epoch,capabilities_hash,arguments_hash,target_hash,state,actor,created_at)
                VALUES(?,?,1,?,?,?,?,?,?,?,'pending','interactive',?)""", (
                approval_id, action["id"], current["revision"], task["revision"], task["profile_id"],
                task["context_epoch"], fingerprint(json.loads(task["allowed_tools"])),
                action["fingerprint"], target_hash, timestamp()))
            event = self.store.event(db, task["session_id"], task["id"], "approval.requested",
                                    {"approval_id": approval_id, "action_id": action["id"], "tool": action["name"],
                                     "arguments": json.loads(action["arguments"]), "target_hash": target_hash},
                                    entity_id=approval_id, revision=current["revision"])
            self.store.checkpoint(db, task["id"])
        self.publish(event)
        return approval_id

    def resolve(self, approval_id, decision, current_hash):
        with self.store.transaction() as db:
            approval = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not approval or approval["state"] != "pending":
                raise ValueError("Approval is absent, stale or already decided")
            action = db.execute("SELECT * FROM actions WHERE id=?", (approval["action_id"],)).fetchone()
            task = db.execute("SELECT * FROM tasks WHERE id=?", (action["task_id"],)).fetchone()
            valid = (action["state"] == "awaiting_approval" and action["revision"] == approval["action_revision"]
                     and task["revision"] == approval["task_revision"] and task["state"] == "waiting_approval"
                     and task["profile_id"] == approval["profile_id"] and task["context_epoch"] == approval["context_epoch"]
                     and fingerprint(json.loads(task["allowed_tools"])) == approval["capabilities_hash"]
                     and action["fingerprint"] == approval["arguments_hash"] and current_hash == approval["target_hash"])
            approved = valid and decision is True
            state = "approved" if approved else "denied"
            db.execute("UPDATE approvals SET state=?,decided_at=? WHERE id=?", (state, timestamp(), approval_id))
            db.execute("UPDATE actions SET state=?,revision=revision+1 WHERE id=?", (state, action["id"]))
            task = self.store.update_task(db, task["id"], state="running")
            event = self.store.event(db, task["session_id"], task["id"], "approval.decided",
                                    {"approval_id": approval_id, "action_id": action["id"], "decision": state,
                                     "binding_valid": valid}, entity_id=approval_id, revision=task["revision"], actor="user")
            self.store.checkpoint(db, task["id"])
        self.publish(event)
        return approved
