"""CLI presentation adapter. Conversation, providers and effects belong to the core."""
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
                    phase("requesting_model", f"Model request {payload['attempt_id'][:8]}")
                elif kind == "model.replayed":
                    phase("recovering", "Using the persisted inference receipt")
                elif kind == "tool.execution_intent":
                    phase("executing_tool", f"Approved execution intent: {payload['tool']}")
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
                callbacks["on_phase_change"](result["status"], "Recorded task outcome: " + result["status"])
                if result["final_answer"] and callbacks.get("on_token"):
                    callbacks["on_token"](result["final_answer"])
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
        return self._rendered(lambda: self._core.resume(session_id, approval_resolver=callbacks.get("on_approval_request")), callbacks)

    def list_sessions(self):
        return self._core.list_sessions()

    def new_session(self):
        self._core.new_session()

    def actions(self):
        return self._core.list_actions()

    def reconcile(self, action_id, outcome, expected_hash, resolver):
        return self._core.tool_broker.reconcile(action_id, outcome, expected_hash, resolver)

    def reconcile_inference(self, resolver):
        return self._core.inference.reconcile_idle(resolver)

    def cancel(self):
        self._core.cancel()

    def get_health(self):
        return self._core.get_health()

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
