"""The one-process local runtime. Clients submit commands and render its events."""
import json
import threading

from harness.core.client import CancellationToken
from harness.core.context import budget_context
from harness.core.inference import AllocationUnavailable, InferenceBroker
from harness.core.native_driver import InferenceResponse, NativeAgentDriver, NativeState
from harness.core.permissions import PermissionService
from harness.core.prompt import PromptBuilder
from harness.core.runtime_models import LlamaCppEngine, ModelProfile, Worker
from harness.core.sessions import SessionManager, TERMINAL
from harness.core.tool_broker import DurableToolBroker, OutcomeUnknown
from harness.security import scrubber
from harness.skills.manager import SkillManager
from harness.storage.artifacts import ArtifactManager
from harness.storage.runtime import RuntimeStore, encode, fingerprint, identity
from harness.tools.registry import ToolDefinition, ToolRegistry


def bounded_result(result, limit):
    encoded = encode(result).encode("utf-8")
    if len(encoded) <= limit:
        return encoded.decode("utf-8")
    metadata = {"status": "truncated", "original_bytes": len(encoded), "preview": "",
                "notice": "Full receipt remains in local state"}
    low, high = 0, len(encoded)
    while low < high:
        middle = (low + high + 1) // 2
        metadata["preview"] = encoded[:middle].decode("utf-8", errors="ignore")
        if len(encode(metadata).encode("utf-8")) <= limit:
            low = middle
        else:
            high = middle - 1
    metadata["preview"] = encoded[:low].decode("utf-8", errors="ignore")
    return encode(metadata)


class CoreService:
    def __init__(self, workspace, engine, profile, *, state_dir=None, skill_manager=None,
                 driver=None, system_prompt=None, fault_hook=None, worker=None):
        self.store = RuntimeStore(workspace, state_dir)
        try:
            self.profile = profile
            self.worker = worker or Worker(profile.worker_id, "fixture", profile.engine, profile.capabilities)
            if profile.worker_id != self.worker.worker_id or profile.engine != self.worker.engine or not profile.capabilities <= self.worker.capabilities:
                raise ValueError("Profile is incompatible with the attached worker")
            self._listeners = []
            self._run_lock = threading.Lock()
            self.cancellation_token = CancellationToken()
            self.driver = driver or NativeAgentDriver()
            self.skills = skill_manager or SkillManager(str(self.store.workspace))
            self.prompt_builder = PromptBuilder(skill_manager=self.skills) if system_prompt is None else PromptBuilder(system_prompt, self.skills)
            self.artifacts = ArtifactManager(self.store)
            self.tools = ToolRegistry(str(self.store.workspace), skill_manager=self.skills)
            self.tools.register(ToolDefinition("restore_snapshot", "Restore an immutable preimage after approval and conflict checks",
                {"type": "object", "properties": {"snapshot_id": {"type": "string"}}, "required": ["snapshot_id"]},
                self.artifacts.restore, requires_approval=True))
            self.permissions = PermissionService(self.store, self._publish)
            self.tool_broker = DurableToolBroker(self.store, self.tools, self.permissions, self.artifacts, self._publish, fault_hook)
            self.inference = InferenceBroker(self.store, engine, self._publish)
            self.sessions = SessionManager(self.store, self._publish)
            self.current_session_id = None
            self.quota = self.session_tracker = self.image_provider = None
            for event in self.store.recover():
                self._publish(event)
            with self.store.transaction() as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES('active_profile',?)", (encode(profile.to_dict()),))
                db.execute("INSERT OR REPLACE INTO metadata VALUES('worker',?)", (encode({
                    "worker_id": self.worker.worker_id, "location": self.worker.location, "engine": self.worker.engine,
                    "capabilities": sorted(self.worker.capabilities), "health": self.worker.health,
                    "observed_resources": self.worker.observed_resources, "version": self.worker.version}),))
        except BaseException:
            self.store.close()
            raise

    @classmethod
    def from_config(cls, config):
        # Composition authority lives here, never in the proposal driver or CLI.
        from pathlib import Path
        from harness.core.client import KaggleBrainClient
        from harness.providers.comfyui import ComfyUIProvider
        from harness.telemetry.quota_ledger import QuotaLedger
        from harness.telemetry.session_tracker import SessionTracker
        scrubber.register_secret(config.api_key)
        scrubber.register_secret(config.remote_url)
        scrubber.register_secret(config.image_server_url)
        capabilities = frozenset({"text", "code_tools"})
        profile_id = fingerprint({"model": config.model_alias, "engine": "llama.cpp", "context": config.max_context_tokens})
        worker = Worker("supervisor-text", "remote-supervisor", "llama.cpp", capabilities)
        profile = ModelProfile(profile_id, worker.worker_id, config.model_alias, worker.engine, capabilities,
                               config.max_context_tokens, min(2048, max(1, config.max_context_tokens // 4)))
        client = KaggleBrainClient(config.remote_url, config.api_key, config.model_alias, config.request_timeout_seconds)
        service = cls(config.workspace_root, LlamaCppEngine(client), profile, worker=worker)
        try:
            service.image_provider = ComfyUIProvider(server_url=config.image_server_url, workspace_root=str(service.store.workspace))
            service.session_tracker = SessionTracker()
            # Preserve the existing quota ledger location; it is not task authority.
            service.quota = QuotaLedger(storage_path=str(Path(config.journal_dir) / "quota_ledger.json"))
        except BaseException:
            service.close()
            raise
        return service

    def close(self):
        if self._run_lock.locked():
            raise RuntimeError("Cancel and finish the active task before closing CoreService")
        self.store.close()

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _publish(self, event):
        # Durability precedes presentation. A renderer cannot roll back authority.
        for listener in tuple(self._listeners):
            try:
                listener(scrubber.structured(event))
            except KeyboardInterrupt:
                self.cancellation_token.cancel()
            except Exception:
                pass

    def _event(self, task, kind, payload=None):
        with self.store.transaction() as db:
            event = self.store.event(db, task["session_id"], task["id"], kind, payload, revision=task["revision"])
        self._publish(event)

    def submit(self, prompt, *, session_id=None, request_id=None, skill=None, allowed_tools=None, max_turns=15, selected_context=None):
        available = frozenset(self.tools.tools)
        allowed = available if allowed_tools is None else frozenset(allowed_tools)
        if not allowed <= available:
            raise ValueError("Task requested unknown tools; inspect the core tool catalog")
        if skill:
            manifest = self.skills.get_skill(skill) if isinstance(skill, str) else skill
            if not manifest:
                raise ValueError("Unknown skill; use /skills to inspect available commands")
            allowed &= self.skills.restrictions(manifest, available, self.profile.capabilities)
            prompt = self.skills.build_skill_prompt(manifest, prompt)
        schemas = [self.tools.tools[name].to_openai_tool() for name in sorted(allowed)]
        task_id = self.sessions.submit(prompt, self.profile, self.prompt_builder.build_system_content(), schemas,
                                      allowed, session_id=session_id, request_id=request_id,
                                      max_turns=max_turns, selected_context=selected_context)
        self.current_session_id = self.task(task_id)["session_id"]
        return task_id

    def task(self, task_id):
        task = self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task or task["version"] != 1:
            raise ValueError("Unknown task or unsupported task version")
        return task

    def _summary(self, task_id, usage=None, ttft_ms=None):
        task = self.task(task_id)
        state = NativeState.recover(task["driver"])
        return {"status": task["state"], "run_id": task_id, "task_id": task_id, "session_id": task["session_id"],
                "agent_id": task["agent_id"], "turns": state.turns, "final_answer": task["final_answer"],
                "usage": usage, "ttft_ms": ttft_ms,
                "cancellation": {"requested": state.cancellation_requested, "local_stop_confirmed": state.local_stop_confirmed,
                    "remote_cancel_confirmed": state.remote_cancel_confirmed,
                    "remote_outcome": "unknown" if state.cancellation_requested else "not_requested"},
                "is_cancelled": state.cancellation_requested}

    def _end(self, task_id, state, history, status, answer="", detail="", attempt_id=None):
        state.cancellation_requested |= self.cancellation_token.is_cancelled
        state.local_stop_confirmed = state.cancellation_requested
        with self.store.transaction() as db:
            task = self.store.update_task(db, task_id, state=status, driver=state.serialize(), history=history, final_answer=scrubber.scrub(answer))
            db.execute("UPDATE sessions SET history=? WHERE id=?", (encode(history), task["session_id"]))
            if attempt_id:
                db.execute("UPDATE inference_attempts SET state='consumed' WHERE id=?", (attempt_id,))
            event = self.store.event(db, task["session_id"], task_id, "task." + status,
                                    {"status": status, "answer": answer, "detail": detail,
                                     "local_stop_confirmed": state.local_stop_confirmed, "remote_cancel_confirmed": state.remote_cancel_confirmed}, revision=task["revision"])
            self.store.checkpoint(db, task_id)
        self._publish(event)

    def _narrow_loaded_skill(self, task_id, action, result):
        if action["name"] != "read_skill" or "error" in result or result.get("status") == "rejected":
            return
        manifest = self.skills.get_skill(json.loads(action["arguments"])["skill_name"])
        if not manifest:
            return
        task = self.task(task_id)
        allowed = set(json.loads(task["allowed_tools"]))
        restricted = allowed & self.skills.restrictions(manifest, self.tools.tools, self.profile.capabilities)
        with self.store.transaction() as db:
            db.execute("UPDATE tasks SET allowed_tools=?,revision=revision+1 WHERE id=?", (encode(sorted(restricted)), task_id))
            db.execute("UPDATE agents SET capabilities=? WHERE id=?", (encode(sorted(restricted)), task["agent_id"]))
            event = self.store.event(db, task["session_id"], task_id, "skill.activated", {"skill": manifest.name, "allowed_tools": sorted(restricted)})
            self.store.checkpoint(db, task_id)
        self._publish(event)

    def run(self, task_id, *, approval_resolver=None):
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("This local core already has an active task")
        usage = ttft_ms = None
        try:
            task = self.task(task_id)
            self.current_session_id = task["session_id"]
            if task["state"] in TERMINAL:
                return self._summary(task_id)
            if task["profile_id"] != self.profile.profile_id:
                raise ValueError("Resume requires the recorded model profile; attach matching model/context configuration")
            state = NativeState.recover(task["driver"])
            if (state.agent_id != task["agent_id"] or state.profile_id != task["profile_id"]
                or state.context_epoch != task["context_epoch"]):
                raise ValueError("Checkpoint identity/profile/epoch does not match its durable task")
            history = json.loads(task["history"])
            self.cancellation_token = CancellationToken()
            if self.quota:
                self.quota.start_session()
            if state.requires_reproposal:
                self._end(task_id, state, history, "failed", detail="Checkpoint was redacted; pending actions require a fresh proposal")
                return self._summary(task_id)
            state.cancellation_requested = state.local_stop_confirmed = False
            with self.store.transaction() as db:
                task = self.store.update_task(db, task_id, state="running", driver=state.serialize())
                started = self.store.event(db, task["session_id"], task_id, "task.started", {"profile_id": task["profile_id"]}, revision=task["revision"])
                self.store.checkpoint(db, task_id)
            self._publish(started)
            while True:
                task = self.task(task_id)
                if self.store.one("SELECT id FROM actions WHERE task_id=? AND state='outcome_unknown'", (task_id,)):
                    self._end(task_id, state, history, "outcome_unknown", detail="Reconcile uncertain effects before resuming")
                    break
                if self.cancellation_token.is_cancelled and state.phase != "pending":
                    state.phase = "cancelled"
                    self._end(task_id, state, history, "cancelled", detail="Local task stopped; remote cancellation is unconfirmed")
                    break
                if state.phase == "pending":
                    results = []
                    for proposal in state.pending:
                        action = self.store.one("SELECT * FROM actions WHERE task_id=? AND turn=? AND call_id=?", (task_id, state.turns, proposal["call_id"]))
                        if not action:
                            raise ValueError("Checkpoint is missing its durable action identity; no re-proposal/re-execution is safe")
                        if fingerprint({"name": proposal["name"], "arguments": proposal["arguments"]}) != action["fingerprint"]:
                            raise ValueError("Recovered proposal disagrees with its durable action")
                        result = self.tool_broker.execute(action["id"], approval_resolver, self.cancellation_token)
                        results.append((proposal, result))
                        self._narrow_loaded_skill(task_id, action, result)
                    if len(results) != len(state.pending):
                        self._end(task_id, state, history, "cancelled", detail="Stopped between sequential tool actions")
                        break
                    history += [{"role": "tool", "tool_call_id": p["call_id"], "name": p["name"],
                                 "content": bounded_result(r, self.profile.max_tool_result_bytes)} for p, r in results]
                    self.driver.accept_results(state, [p["call_id"] for p, _ in results])
                    with self.store.transaction() as db:
                        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                        schemas = [self.tools.tools[name].to_openai_tool() for name in json.loads(task["allowed_tools"])]
                        session = db.execute("SELECT * FROM sessions WHERE id=?", (task["session_id"],)).fetchone()
                        if session["tool_prefix"] != encode(schemas):
                            state.context_epoch += 1
                            db.execute("UPDATE sessions SET tool_prefix=?,context_epoch=? WHERE id=?", (encode(schemas), state.context_epoch, task["session_id"]))
                            db.execute("UPDATE tasks SET context_epoch=? WHERE id=?", (state.context_epoch, task_id))
                            db.execute("UPDATE agents SET context_epoch=? WHERE id=?", (state.context_epoch, task["agent_id"]))
                        task = self.store.update_task(db, task_id, state="running", driver=state.serialize(), history=history)
                        db.execute("UPDATE sessions SET history=? WHERE id=?", (encode(history), task["session_id"]))
                        event = self.store.event(db, task["session_id"], task_id, "task.turn_completed", {"turn": state.turns}, revision=task["revision"])
                        self.store.checkpoint(db, task_id)
                    self._publish(event)
                    continue
                if state.turns >= task["max_turns"]:
                    state.phase = "max_turns"
                    self._end(task_id, state, history, "max_turns", detail="No more inference turns permitted")
                    break
                session = self.store.one("SELECT * FROM sessions WHERE id=?", (task["session_id"],))
                schemas = json.loads(session["tool_prefix"])
                selected = json.loads(task["selected_context"])
                selected_messages = [{"role": "user", "content": "[SELECTED CONTEXT]\n" + encode(selected)}] if selected else []
                budget = budget_context(self.profile, session["system_prefix"], schemas, history, selected_messages)
                self._event(task, "context.budget", budget.to_dict())
                if not budget.fits:
                    state.phase = "failed"
                    self._end(task_id, state, history, "context_overflow", detail="Input estimate plus reserved completion exceeds declared capacity; reduce history/context or start a new session")
                    break
                completed = self.store.one("SELECT * FROM inference_attempts WHERE task_id=? AND state='completed' ORDER BY rowid DESC LIMIT 1", (task_id,))
                if completed:
                    saved = json.loads(completed["response"])
                    reply = InferenceResponse(error="Redacted inference receipt requires a fresh proposal") if saved["requires_reproposal"] else InferenceResponse(**saved["response"])
                    attempt_id, usage = completed["id"], json.loads(completed["usage"])
                    self._event(task, "model.replayed", {"attempt_id": attempt_id})
                else:
                    messages = [{"role": "system", "content": session["system_prefix"]}] + selected_messages + history
                    reply, attempt_id, usage, ttft_ms = self.inference.infer(task, self.profile, messages, schemas, self.cancellation_token)
                state.cancellation_requested = self.cancellation_token.is_cancelled
                decision = self.driver.advance(state, reply, task["max_turns"])
                if decision.kind == "tool_proposals":
                    calls = [{"id": p.call_id, "type": "function", "function": {"name": p.name, "arguments": json.dumps(p.arguments, ensure_ascii=False, sort_keys=True)}} for p in decision.proposals]
                    history.append({"role": "assistant", "content": reply.text or None, "tool_calls": calls})
                    emitted = []
                    with self.store.transaction() as db:
                        task = self.store.update_task(db, task_id, driver=state.serialize(), history=history)
                        ids = self.tool_broker.propose(db, task, decision.proposals, state.turns)
                        db.execute("UPDATE inference_attempts SET state='consumed' WHERE id=?", (attempt_id,))
                        for action_id, proposal in zip(ids, decision.proposals):
                            emitted.append(self.store.event(db, task["session_id"], task_id, "tool.proposed",
                                {"action_id": action_id, "call_id": proposal.call_id, "tool": proposal.name, "arguments": proposal.arguments}, entity_id=action_id, revision=task["revision"]))
                        self.store.checkpoint(db, task_id)
                    for event in emitted:
                        self._publish(event)
                    self.tool_broker.fault("after_proposals", {"task_id": task_id})
                elif decision.kind == "completed":
                    history.append({"role": "assistant", "content": decision.answer})
                    self._end(task_id, state, history, "completed", decision.answer, attempt_id=attempt_id)
                    break
                else:
                    self._end(task_id, state, history, decision.kind, detail=decision.detail, attempt_id=attempt_id)
                    break
        except AllocationUnavailable as exc:
            self._end(task_id, state, history, "paused", detail=scrubber.scrub(exc))
        except OutcomeUnknown as exc:
            self._end(task_id, state, history, "outcome_unknown", detail=scrubber.scrub(exc))
        except KeyboardInterrupt:
            self.cancellation_token.cancel()
            task = self.task(task_id)
            state = NativeState.recover(task["driver"])
            history = json.loads(task["history"])
            uncertain = self.store.one("SELECT id FROM actions WHERE task_id=? AND state IN ('executing','outcome_unknown')", (task_id,))
            self._end(task_id, state, history, "outcome_unknown" if uncertain else "cancelled", detail="Interrupted locally; external effects may require reconciliation")
        except Exception as exc:
            # Invalid task/profile input has no running state to checkpoint.
            if "state" not in locals():
                raise RuntimeError(scrubber.scrub(exc)) from None
            uncertain = self.store.one("SELECT id FROM actions WHERE task_id=? AND state='executing'", (task_id,))
            if uncertain:
                with self.store.transaction() as db:
                    db.execute("UPDATE actions SET state='outcome_unknown',revision=revision+1 WHERE task_id=? AND state='executing'", (task_id,))
            self._end(task_id, state, history, "outcome_unknown" if uncertain else "failed", detail=scrubber.scrub(exc))
        finally:
            if self.quota:
                self.quota.stop_session()
            self._run_lock.release()
        return self._summary(task_id, usage, ttft_ms)

    def resume(self, session_id, *, approval_resolver=None):
        session = self.store.one("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not session or not session["current_task_id"]:
            raise ValueError("Unknown session or no task to resume")
        return self.run(session["current_task_id"], approval_resolver=approval_resolver)

    def cancel(self):
        self.cancellation_token.cancel()

    def get_health(self):
        health = self.inference.engine.get_health()
        if self.session_tracker:
            self.session_tracker.update_from_remote_health(health.raw)
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('worker_observation',?)", (encode({"status": health.status, "resources": health.raw}),))
        return health

    def select_profile(self, profile):
        if self._run_lock.locked() or self.inference.allocation()["state"] != "idle":
            raise ValueError("Cannot change profiles while inference is active or uncertain")
        unfinished = self.store.one("SELECT id FROM tasks WHERE state NOT IN ('completed','failed','malformed','truncated','incomplete','max_turns','context_overflow','cancelled') LIMIT 1")
        if unfinished:
            raise ValueError("Resume/resolve the pending task before changing its model profile")
        if profile.worker_id != self.worker.worker_id or profile.engine != self.worker.engine or not profile.capabilities <= self.worker.capabilities:
            raise ValueError("Profile is incompatible with the attached worker")
        self.profile = profile
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('active_profile',?)", (encode(profile.to_dict()),))

    def get_last_diff(self):
        snapshot = self.artifacts.latest()
        return scrubber.scrub(snapshot["diff"]) if snapshot else None

    def undo_last(self, approval_callback=None):
        snapshot = self.artifacts.latest()
        if not snapshot:
            return {"status": "empty", "message": "No V2 file changes available to undo; legacy undo records are preserved separately"}
        task_id = self.submit("Restore the most recent sealed snapshot", allowed_tools=["restore_snapshot"])
        task = self.task(task_id)
        from harness.core.native_driver import Proposal
        with self.store.transaction() as db:
            action_id = self.tool_broker.propose(db, task, [Proposal("undo-" + identity(), "restore_snapshot", {"snapshot_id": snapshot["id"]})], 0)[0]
        result = self.tool_broker.execute(action_id, approval_callback, CancellationToken())
        state = NativeState.recover(task["driver"])
        self._end(task_id, state, json.loads(task["history"]), "completed" if result.get("status") == "success" else "failed", detail=result.get("message", result.get("error", "")))
        return result

    def generate_image(self, prompt):
        if self.image_provider is None or not self.image_provider.server_url:
            raise ValueError("Image worker is unconfigured; set FREECOMPUTE_IMAGE_SERVER or /image-server")
        profile = ModelProfile("comfy-image", "comfy-worker", "ComfyUI-default", "ComfyUI", frozenset({"image_gen"}))
        task_id = self.sessions.submit(prompt, profile, "Image generation", [], [], operation="image")
        task = self.task(task_id)
        state = NativeState.recover(task["driver"])
        try:
            result = self.inference.image(task, profile, self.image_provider.generate_image, scrubber.scrub(prompt))
            self._end(task_id, state, json.loads(task["history"]), "completed", answer=result.get("file_path", ""))
            return result
        except Exception as exc:
            self._end(task_id, state, json.loads(task["history"]), "failed", detail=scrubber.scrub(exc))
            raise RuntimeError(scrubber.scrub(exc)) from None
