"""FIFO inference admission with durable worker capacity and exclusive resource claims."""
import json

from harness.core.native_driver import NativeState
from harness.core.sessions import TERMINAL
from harness.security import scrubber
from harness.storage.runtime import encode, identity, timestamp


class AllocationUnavailable(RuntimeError):
    pass


class QueueWaiting(AllocationUnavailable):
    pass


class Scheduler:
    def __init__(self, store, registry, publish):
        self.store, self.registry, self.publish = store, registry, publish

    def _event(self, db, task_id, kind, payload):
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self.store.event(db, task["session_id"], task_id, kind, payload, revision=task["revision"])

    def admit_submission(self, db, task, profile, schemas, route, operation):
        """Submission and its first queue entry cannot be separated by a crash."""
        capabilities = {"image_gen"} if operation == "image" else {"text", "code_tools"} if schemas else {"text"}
        queue_id = identity()
        db.execute("""INSERT INTO inference_queue(id,task_id,profile_id,context_epoch,turn,required_capabilities,
            requested_worker,state,created_at,updated_at) VALUES(?,?,?,?,0,?,?,'queued',?,?)""",
                   (queue_id, task["id"], profile.profile_id, task["context_epoch"], encode(sorted(capabilities)), route, timestamp(), timestamp()))
        self.store.update_task(db, task["id"], state="queued")
        return self._event(db, task["id"], "queue.enqueued", {"queue_id": queue_id, "profile_id": profile.profile_id,
                                                              "requested_worker": route, "turn": 0})

    def enqueue(self, task, profile, capabilities, *, requested_worker=None, request_hash=None):
        capabilities = frozenset(capabilities)
        if not capabilities <= profile.capabilities:
            raise ValueError("Required inference capabilities exceed the model profile")
        self.registry.profile(profile.profile_id)
        state = NativeState.recover(task["driver"])
        emitted = []
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM inference_queue WHERE task_id=? AND context_epoch=? AND turn=?",
                             (task["id"], task["context_epoch"], state.turns)).fetchone()
            if row:
                if row["state"] != "queued":
                    raise AllocationUnavailable("Inference request is active, completed or awaiting reconciliation")
                if row["profile_id"] != profile.profile_id or json.loads(row["required_capabilities"]) != sorted(capabilities):
                    raise ValueError("Queue identity reused with changed model/capability requirements")
                if row["requested_worker"] != requested_worker:
                    raise ValueError("Queue identity reused with a changed worker route")
                if row["request_hash"] and request_hash and row["request_hash"] != request_hash:
                    raise ValueError("Queued inference payload changed; inspect the checkpoint")
                if request_hash and not row["request_hash"]:
                    db.execute("UPDATE inference_queue SET request_hash=? WHERE id=?", (request_hash, row["id"]))
                result = dict(row)
            else:
                queue_id = identity()
                db.execute("""INSERT INTO inference_queue(id,task_id,profile_id,context_epoch,turn,required_capabilities,
                    requested_worker,request_hash,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'queued',?,?)""",
                           (queue_id, task["id"], profile.profile_id, task["context_epoch"], state.turns, encode(sorted(capabilities)),
                            requested_worker, request_hash, timestamp(), timestamp()))
                if task["state"] == "created":
                    self.store.update_task(db, task["id"], state="queued")
                emitted.append(self._event(db, task["id"], "queue.enqueued", {"queue_id": queue_id, "profile_id": profile.profile_id,
                    "requested_worker": requested_worker, "turn": state.turns}))
                self.store.checkpoint(db, task["id"])
                result = dict(db.execute("SELECT * FROM inference_queue WHERE id=?", (queue_id,)).fetchone())
        for event in emitted:
            self.publish(event)
        return result

    def requested_worker(self, task_id):
        row = self.store.one("SELECT requested_worker FROM inference_queue WHERE task_id=? ORDER BY sequence LIMIT 1", (task_id,))
        return row["requested_worker"] if row else None

    def _legacy_quarantine(self, db):
        allocation = db.execute("SELECT value FROM metadata WHERE key='allocation'").fetchone()
        # Schema-v1 unknown remote work has no worker/resource identity to narrow.
        return (allocation and json.loads(allocation[0])["state"] == "quarantined"
                and not db.execute("SELECT 1 FROM inference_leases WHERE state IN ('active','quarantined')").fetchone())

    def _eligible(self, db, job):
        profile = self.registry.profile(job["profile_id"])
        capabilities = frozenset(json.loads(job["required_capabilities"]))
        reasons, quarantined = [], False
        rows = db.execute("SELECT w.* FROM workers w JOIN worker_profiles p ON p.worker_id=w.id WHERE p.profile_id=? ORDER BY w.id", (profile.profile_id,)).fetchall()
        for row in rows:
            if job["requested_worker"] and row["id"] != job["requested_worker"]:
                continue
            declaration = json.loads(row["declaration"])
            if declaration["engine"] not in profile.engine_requirements or not capabilities <= set(declaration["capabilities"]):
                continue
            if not self.registry.available(row):
                reasons.append(row["id"] + ": unhealthy, stale or unattached")
                continue
            observed_models = json.loads(row["observation"]).get("models")
            if observed_models is not None and profile.model not in observed_models:
                reasons.append(row["id"] + ": configured model is not advertised")
                continue
            held = db.execute("SELECT state FROM inference_leases WHERE worker_id=? AND state IN ('active','quarantined')", (row["id"],)).fetchall()
            if len(held) >= declaration["concurrency_limit"]:
                quarantined |= any(r[0] == "quarantined" for r in held)
                reasons.append(row["id"] + ": capacity busy")
                continue
            resources = profile.resource_requirements or frozenset(declaration["resources"])
            pool = declaration["resource_pool"] or row["id"]
            conflicts = [db.execute("SELECT l.state FROM resource_claims c JOIN inference_leases l ON l.id=c.lease_id WHERE c.pool_id=? AND c.resource_id=?", (pool, resource)).fetchone() for resource in resources]
            if any(conflicts):
                quarantined |= any(r and r[0] == "quarantined" for r in conflicts)
                reasons.append(row["id"] + ": shared resources busy")
                continue
            return {"worker_id": row["id"], "pool": pool, "resources": sorted(resources)}, "", False
        return None, "; ".join(reasons) or "No eligible worker is attached", quarantined

    def claim(self, db, queue_id):
        """Caller shares this transaction with the inference attempt/intent."""
        job = db.execute("SELECT * FROM inference_queue WHERE id=?", (queue_id,)).fetchone()
        if not job or job["state"] != "queued":
            raise AllocationUnavailable("Inference request is active, cancelled or awaiting reconciliation")
        if self._legacy_quarantine(db):
            return None, "Legacy inference outcome is unknown; confirm the remote worker is idle", True
        target, reason, quarantined = self._eligible(db, job)
        if not target:
            db.execute("UPDATE inference_queue SET waiting_reason=?,updated_at=? WHERE id=?", (reason, timestamp(), queue_id))
            return None, reason, quarantined
        for earlier in db.execute("SELECT * FROM inference_queue WHERE state='queued' AND sequence<? ORDER BY sequence", (job["sequence"],)):
            eligible, _, _ = self._eligible(db, earlier)
            if eligible:
                reason = "An earlier eligible request is waiting; use /run-next"
                db.execute("UPDATE inference_queue SET waiting_reason=? WHERE id=?", (reason, queue_id))
                return None, reason, False
        lease_id = identity()
        db.execute("INSERT INTO inference_leases(id,queue_id,worker_id,profile_id,state,created_at) VALUES(?,?,?,?,'active',?)",
                   (lease_id, queue_id, target["worker_id"], job["profile_id"], timestamp()))
        db.executemany("INSERT INTO resource_claims VALUES(?,?,?)", [(target["pool"], r, lease_id) for r in target["resources"]])
        db.execute("UPDATE inference_queue SET state='running',waiting_reason='',updated_at=? WHERE id=?", (timestamp(), queue_id))
        return dict(target, id=lease_id, queue_id=queue_id, task_id=job["task_id"], profile_id=job["profile_id"]), "", False

    def finish(self, db, lease_id, *, confirmed, failed=False, reason=""):
        lease = db.execute("SELECT * FROM inference_leases WHERE id=?", (lease_id,)).fetchone()
        if not lease or lease["state"] != "active":
            raise ValueError("Inference lease is no longer active")
        state = "released" if confirmed else "quarantined"
        db.execute("UPDATE inference_leases SET state=?,reason=?,ended_at=? WHERE id=?", (state, scrubber.scrub(reason), timestamp(), lease_id))
        db.execute("UPDATE inference_queue SET state=?,waiting_reason=?,updated_at=? WHERE id=?",
                   ("failed" if failed else "completed" if confirmed else "quarantined", scrubber.scrub(reason), timestamp(), lease["queue_id"]))
        if not confirmed:
            db.execute("UPDATE inference_queue SET state='quarantined' WHERE id=?", (lease["queue_id"],))
        else:
            db.execute("DELETE FROM resource_claims WHERE lease_id=?", (lease_id,))

    def allocation(self):
        leases = self.store.all("SELECT id,worker_id,profile_id,state,reason FROM inference_leases WHERE state IN ('active','quarantined') ORDER BY created_at")
        if leases:
            return {"state": "quarantined" if any(l["state"] == "quarantined" for l in leases) else "active", "leases": leases}
        row = self.store.one("SELECT value FROM metadata WHERE key='allocation'")
        previous = json.loads(row["value"]) if row else {"state": "idle"}
        return previous if previous["state"] == "quarantined" else {"state": "idle"}

    def sync_allocation(self, db):
        rows = db.execute("SELECT state FROM inference_leases WHERE state IN ('active','quarantined')").fetchall()
        state = "quarantined" if any(r[0] == "quarantined" for r in rows) else "active" if rows else "idle"
        db.execute("INSERT OR REPLACE INTO metadata VALUES('allocation',?)", (encode({"state": state}),))

    def finalize_task(self, db, task_id, status):
        if status in TERMINAL:
            db.execute("UPDATE inference_queue SET state='cancelled',waiting_reason=?,updated_at=? WHERE task_id=? AND state='queued'",
                       ("Task ended: " + status, timestamp(), task_id))

    def cancel_queued(self, task_id):
        emitted = []
        with self.store.transaction() as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                raise ValueError("Unknown task to cancel")
            held = db.execute("SELECT l.id FROM inference_leases l JOIN inference_queue q ON q.id=l.queue_id WHERE q.task_id=? AND l.state IN ('active','quarantined')", (task_id,)).fetchone()
            if held:
                return False
            if task["state"] in TERMINAL:
                return True
            pending = db.execute("SELECT 1 FROM actions WHERE task_id=? AND state IN ('proposed','awaiting_approval','approved','executing','outcome_unknown')", (task_id,)).fetchone()
            if pending:
                raise ValueError("Resolve pending local actions before cancelling a paused task")
            state = NativeState.recover(task["driver"])
            state.phase, state.cancellation_requested, state.local_stop_confirmed = "cancelled", True, True
            self.store.update_task(db, task_id, state="cancelled", driver=state.serialize())
            self.finalize_task(db, task_id, "cancelled")
            emitted.append(self._event(db, task_id, "task.cancelled", {"status": "cancelled", "detail": "Cancelled before dispatch", "remote_cancel_confirmed": False}))
            self.store.checkpoint(db, task_id)
        for event in emitted:
            self.publish(event)
        return True

    def reconcile(self, resolver=None, lease_id=None):
        held = self.store.all("SELECT * FROM inference_leases WHERE state='quarantined' ORDER BY created_at")
        if lease_id:
            held = [row for row in held if row["id"] == lease_id]
            if not held:
                raise ValueError("Unknown quarantined lease")
        if len(held) > 1:
            raise ValueError("Specify one lease ID; each worker outcome requires its own confirmation")
        if not held:
            previous = self.allocation()
            if previous["state"] == "idle":
                return previous
            if previous["state"] == "active":
                raise AllocationUnavailable("Cannot reconcile active inference")
            target = {"allocation": previous, "assertion": "all legacy remote inference is idle"}
        else:
            lease = held[0]
            target = {"lease_id": lease["id"], "worker_id": lease["worker_id"], "profile_id": lease["profile_id"],
                      "resources": self.store.all("SELECT pool_id,resource_id FROM resource_claims WHERE lease_id=?", (lease["id"],)),
                      "assertion": "this worker's inference is idle"}
        if resolver is None or resolver("reconcile_inference", scrubber.structured(target)) is not True:
            raise ValueError("Explicit confirmation that the remote worker is idle is required")
        emitted = []
        with self.store.transaction() as db:
            if held:
                current = db.execute("SELECT * FROM inference_leases WHERE id=?", (lease["id"],)).fetchone()
                if current["state"] != "quarantined":
                    raise ValueError("Lease changed while awaiting confirmation")
                job = db.execute("SELECT * FROM inference_queue WHERE id=?", (lease["queue_id"],)).fetchone()
                task = db.execute("SELECT state FROM tasks WHERE id=?", (job["task_id"],)).fetchone()
                db.execute("UPDATE inference_leases SET state='reconciled',reason='operator idle confirmation',ended_at=? WHERE id=?", (timestamp(), lease["id"]))
                db.execute("DELETE FROM resource_claims WHERE lease_id=?", (lease["id"],))
                db.execute("UPDATE inference_queue SET state=?,waiting_reason='operator idle confirmation',updated_at=? WHERE id=?",
                           ("cancelled" if task[0] in TERMINAL else "queued", timestamp(), job["id"]))
                emitted.append(self._event(db, job["task_id"], "lease.reconciled", target))
                self.store.checkpoint(db, job["task_id"])
            db.execute("INSERT OR REPLACE INTO metadata VALUES('allocation_reconciliation',?)", (encode({"target": target, "at": timestamp(), "actor": "user"}),))
            self.sync_allocation(db)
        for event in emitted:
            self.publish(event)
        return self.allocation()

    def recover(self):
        emitted = []
        with self.store.transaction() as db:
            for lease in db.execute("SELECT l.*,q.task_id FROM inference_leases l JOIN inference_queue q ON q.id=l.queue_id WHERE l.state='active'").fetchall():
                db.execute("UPDATE inference_leases SET state='quarantined',reason='core restarted during inference' WHERE id=?", (lease["id"],))
                db.execute("UPDATE inference_queue SET state='quarantined',waiting_reason='Remote completion unconfirmed after restart' WHERE id=?", (lease["queue_id"],))
                emitted.append(self._event(db, lease["task_id"], "lease.quarantined", {"lease_id": lease["id"], "worker_id": lease["worker_id"]}))
                self.store.checkpoint(db, lease["task_id"])
            # Keep a schema-v1 global quarantine until explicitly reconciled.
            if db.execute("SELECT 1 FROM inference_leases WHERE state IN ('active','quarantined')").fetchone():
                self.sync_allocation(db)
        for event in emitted:
            self.publish(event)

    def list_queue(self):
        return self.store.all("SELECT q.*,t.state AS task_state FROM inference_queue q JOIN tasks t ON t.id=q.task_id WHERE q.state IN ('queued','running','quarantined') ORDER BY q.sequence")

    def next_task(self):
        # Consume a committed result without needing healthy/free remote capacity.
        receipt = self.store.one("""SELECT q.task_id FROM inference_queue q
            JOIN tasks t ON t.id=q.task_id JOIN inference_attempts a ON a.task_id=t.id
            WHERE a.state IN ('completed','failed') AND a.profile_id=t.profile_id
            AND a.context_epoch=t.context_epoch
            AND t.state NOT IN ('completed','failed','malformed','truncated','incomplete','max_turns','context_overflow','cancelled')
            ORDER BY q.sequence LIMIT 1""")
        if receipt:
            return receipt["task_id"]
        for row in self.list_queue():
            self.registry.refresh_candidates(row["profile_id"], row["requested_worker"])
        with self.store.transaction() as db:
            if self._legacy_quarantine(db):
                return None
            for row in db.execute("SELECT * FROM inference_queue WHERE state='queued' ORDER BY sequence"):
                eligible, _, _ = self._eligible(db, row)
                if eligible:
                    return row["task_id"]
        return None
