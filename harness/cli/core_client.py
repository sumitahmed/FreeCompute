"""CLI presentation adapter. Conversation, providers and effects belong to the core."""
from harness.core.sessions import TERMINAL


class CoreClient:
    def __init__(self, core):
        self._core = core

    @property
    def cancellation_token(self):
        return self._core.cancellation_token

    def _rendered(self, operation, callbacks):
        observed_terminal = False
        def render(event):
            nonlocal observed_terminal
            kind, payload = event["kind"], event["payload"]
            phase = callbacks.get("on_phase_change")
            if kind == "stream.text" and callbacks.get("on_token"):
                callbacks["on_token"](payload["text"])
            elif kind == "stream.reasoning" and callbacks.get("on_reasoning"):
                callbacks["on_reasoning"](payload["text"])
            elif kind == "tool.proposed" and callbacks.get("on_tool_proposed"):
                callbacks["on_tool_proposed"](payload["tool"], payload["arguments"])
            elif kind in {"tool.completed", "tool.denied", "tool.outcome_unknown", "tool.replayed"} and callbacks.get("on_tool_executed"):
                result = dict(payload["result"])
                if kind == "tool.replayed":
                    result["receipt_replayed"] = True
                if kind == "tool.outcome_unknown":
                    result["outcome_unknown"] = True
                callbacks["on_tool_executed"](payload["tool"], result)
            elif phase:
                if kind == "model.requested":
                    phase("requesting_model", payload['worker_id'])
                elif kind == "queue.enqueued":
                    phase("queued", f"Profile {payload['profile_id']} entered the queue")
                elif kind == "queue.waiting":
                    phase("waiting", payload['reason'])
                elif kind == "model.replayed":
                    phase("recovering", "Using the persisted inference receipt")
                elif kind == "tool.execution_intent":
                    phase("executing_tool", payload['tool'])
                elif kind == "approval.requested":
                    phase("waiting_approval", f"Action {payload['action_id'][:8]} requires a decision")
                elif kind == "task.started":
                    phase("started", f"Session {event['session_id']} / task {event['task_id']}")
                elif kind.startswith("task.") and "status" in payload:
                    observed_terminal = True
                    phase(payload["status"], payload.get("detail") or "Task " + payload["status"])
        remove = self._core.subscribe(render)
        try:
            result = operation()
            if not observed_terminal and callbacks.get("on_phase_change"):
                detail = ("Recorded task outcome: " + result["status"] if result.get("task_id")
                          else result.get("detail") or "Task " + result["status"])
                callbacks["on_phase_change"](result["status"], detail)
                if result["final_answer"] and callbacks.get("on_token"):
                    callbacks["on_token"](result["final_answer"])
            result['allocation'] = self._core.inference.allocation()
            return result
        finally:
            remove()

    def run_task(self, user_prompt, *, skill=None, **callbacks):
        resolver = callbacks.get("on_approval_request")
        def operation():
            task_id = self._core.submit(user_prompt, session_id=self._core.current_session_id, skill=skill)
            return self._core.run(task_id, approval_resolver=resolver)
        return self._rendered(operation, callbacks)

    def resume(self, session_id, **callbacks):
        session_id = self._resolve_id(session_id, self.list_sessions(), "id", "session")
        return self._rendered(lambda: self._core.resume(session_id, approval_resolver=callbacks.get("on_approval_request")), callbacks)

    @staticmethod
    def _resolve_id(value, rows, field, label):
        exact = [row[field] for row in rows if row[field] == value]
        matches = exact or [row[field] for row in rows if row[field].startswith(value)]
        if len(matches) != 1:
            raise ValueError(f"Unknown or ambiguous {label} ID; use /{label}s to see available IDs")
        return matches[0]

    def list_sessions(self):
        return self._core.list_sessions()

    def new_session(self):
        self._core.new_session()

    def actions(self):
        return self._core.list_actions()

    def reconcile(self, action_id, outcome, expected_hash, resolver):
        return self._core.tool_broker.reconcile(action_id, outcome, expected_hash, resolver)

    def reconcile_inference(self, resolver, lease_id=None):
        return self._core.inference.reconcile_idle(resolver, lease_id)

    def cancel(self, task_id=None):
        if task_id is None:
            task_id = self._core._running_task_id
            if task_id is None and self._core.current_session_id:
                session = self._core.store.one("SELECT current_task_id FROM sessions WHERE id=?", (self._core.current_session_id,))
                task_id = session['current_task_id'] if session else None
        if task_id is None or self._core.task(task_id)['state'] in TERMINAL:
            return None
        self._core.cancel(task_id)
        return self._core._summary(task_id)

    def workers(self):
        return self._core.list_workers(refresh=True)

    def models(self):
        return self._core.list_models()

    def queue(self):
        return self._core.list_queue()

    def select_model(self, profile_id, worker_id=None):
        profile_id = self._resolve_id(profile_id, self.models(), "profile_id", "model")
        return self._core.select_model(profile_id, worker_id)

    def run_next(self, **callbacks):
        return self._rendered(lambda: self._core.run_next(approval_resolver=callbacks.get("on_approval_request")), callbacks)

    def get_health(self):
        return self._core.get_health()

    def connect(self, value):
        return self._core.connect_worker(value)

    def connect_image(self, value):
        return self._core.connect_image_worker(value)

    def select_image_model(self, profile_id, worker_id=None):
        rows = [p for p in self.models() if "image_gen" in p["capabilities"]]
        profile_id = self._resolve_id(profile_id, rows, "profile_id", "image profile")
        return self._core.select_image_model(profile_id, worker_id)

    def image_model_info(self):
        return self._core.image_model_info()

    def model_info(self):
        return self._core.model_info()

    def get_last_diff(self):
        return self._core.get_last_diff()

    def undo_last(self, approval_callback=None):
        return self._core.undo_last(approval_callback)

    @property
    def server_url(self):
        return self._core.image_provider.server_url if self._core.image_provider else ""

    @server_url.setter
    def server_url(self, value):
        self._core.set_image_endpoint(value)

    def generate_image(self, prompt):
        return self._core.generate_image(prompt)
