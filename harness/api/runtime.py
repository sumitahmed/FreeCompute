"""Thread/approval plumbing. Durable work and resource decisions belong to Core."""
import threading

from harness.security import scrubber


class Conflict(ValueError):
    pass


class LocalRuntime:
    def __init__(self, core, *, simulated=False):
        self.core, self.simulated = core, simulated
        self.stop = threading.Event()
        self.changed = threading.Condition()
        self.operation = threading.Lock()
        self._gate = None
        self._decisions = {}
        self._resume = None
        self.last_error = None
        self._unsubscribe = core.subscribe(self._event)
        self.thread = threading.Thread(target=self._dispatch, name="freecompute-core", daemon=True)

    def _event(self, event):
        with self.changed:
            if event["kind"] == "approval.requested":
                self._gate = event["payload"]["approval_id"]
            self.changed.notify_all()

    def start(self):
        self.thread.start()

    def wake(self):
        with self.changed:
            self.changed.notify_all()

    def _approval(self, _tool, _preview):
        with self.changed:
            approval_id = self._gate
            while approval_id not in self._decisions:
                if self.stop.is_set() or self.core.cancellation_token.is_cancelled:
                    self._gate = None
                    return False
                self.changed.wait(0.2)
            decision = self._decisions.pop(approval_id)
            self._gate = None
            return decision

    def decide(self, approval_id, body):
        if type(body.get("decision")) is not bool:
            raise ValueError("Approval decision must be true or false")
        with self.changed:
            approval = next((a for a in self.core.views.approvals() if a["id"] == approval_id), None)
            if not approval or approval_id != self._gate or approval_id in self._decisions:
                raise Conflict("Approval is stale or already delivered; refresh or resume for a fresh request")
            for field in ("action_revision", "task_revision", "arguments_hash", "target_hash"):
                if field not in body or type(body[field]) is not type(approval[field]) or body[field] != approval[field]:
                    raise Conflict("Approval binding changed; refresh the card before deciding")
            self._decisions[approval_id] = body["decision"]
            self.changed.notify_all()
        # PermissionService.resolve validates the current file/capabilities/revisions
        # inside the executing Core thread. Delivery is not an approval receipt.
        return {"status": "decision_delivered", "approval_id": approval_id}

    def resume(self, task_id):
        task = self.core.views.task(task_id)
        with self.changed:
            if self.operation.locked() or self._resume:
                raise Conflict("A local task is active; wait for it before resuming")
            self._resume = task["session_id"]
            self.changed.notify_all()
        return {"status": "resume_requested", "task_id": task_id}

    def cancel(self, task_id):
        self.core.cancel(task_id)
        self.wake()
        return self.core.views.task(task_id)

    def _dispatch(self):
        while not self.stop.is_set():
            with self.changed:
                session_id, self._resume = self._resume, None
            try:
                with self.operation:
                    if self.stop.is_set():
                        break
                    result = (self.core.resume(session_id, approval_resolver=self._approval) if session_id
                              else self.core.run_next(approval_resolver=self._approval))
                if result["status"] != "waiting":
                    continue
            except Exception as exc:
                self.last_error = scrubber.scrub(exc)
            with self.changed:
                if not self._resume and not self.stop.is_set():
                    self.changed.wait(1)

    def close(self):
        self.stop.set()
        self.core.cancel()
        self.wake()
        if self.thread.is_alive():
            self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("Core is still stopping; keep the process alive to preserve its receipt")
        self._unsubscribe()
        self.core.close()
