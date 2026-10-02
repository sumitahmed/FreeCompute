"""The one-process local runtime. Clients submit commands and render its events."""
import json
import threading
from urllib.parse import urlsplit

from harness.core.client import CancellationToken
from harness.core.context import budget_context
from harness.core.inference import AllocationUnavailable, InferenceBroker
from harness.core.engines import ComfyUIEngine
from harness.core.native_driver import InferenceResponse, NativeAgentDriver, NativeState
from harness.core.permissions import PermissionService
from harness.core.prompt import PromptBuilder
from harness.core.runtime_models import ModelProfile, Worker
from harness.core.scheduler import QueueWaiting, Scheduler
from harness.core.workers import WorkerRegistry
from harness.core.sessions import SessionManager, TERMINAL
from harness.core.tool_broker import DurableToolBroker, OutcomeUnknown
from harness.security import scrubber
from harness.skills.manager import SkillManager
from harness.storage.artifacts import ArtifactManager
from harness.storage.runtime import RuntimeStore, encode, fingerprint, identity, timestamp
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
                 driver=None, system_prompt=None, fault_hook=None, worker=None, attachments=None, selected_worker=None):
        self.store = RuntimeStore(workspace, state_dir)
        try:
            self.profile = profile
            self.worker = worker or Worker(profile.worker_id or "attached-text", "fixture", profile.engine, profile.capabilities,
                                          resource_pool="attached-default", resources=frozenset({"inference"}))
            if self.worker.engine not in profile.engine_requirements or not profile.capabilities <= self.worker.capabilities:
                raise ValueError("Profile is incompatible with the attached worker")
            self._listeners = []
            self._run_lock = threading.Lock()
            self._running_task_id = None
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
            self.registry = WorkerRegistry(self.store)
            for attached_worker, profiles, adapter in attachments or [(self.worker, [profile], engine)]:
                self.registry.attach(attached_worker, profiles, adapter, trusted_embedding=attachments is None and worker is None)
            self.selected_worker = selected_worker if attachments is not None else self.worker.worker_id
            self.scheduler = Scheduler(self.store, self.registry, self._publish)
            self.inference = InferenceBroker(self.store, self.registry, self.scheduler, self._publish, self.worker.worker_id)
            self.sessions = SessionManager(self.store, self._publish, self.scheduler.admit_submission)
            self.current_session_id = None
            self.quota = self.session_tracker = self.image_provider = None
            self.image_profile_id = None
            self.legacy_undo = None
            for event in self.store.recover():
                self._publish(event)
            self.scheduler.recover()
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
        from harness.core.engine_config import configured_engines
        from harness.telemetry.quota_ledger import QuotaLedger
        from harness.telemetry.session_tracker import SessionTracker
        from harness.storage.undo import UndoManager
        scrubber.register_secret(config.api_key)
        scrubber.register_secret(config.remote_url)
        scrubber.register_secret(config.image_server_url)
        profile, (worker, _, engine), attachments = configured_engines(config, config.workspace_root)
        service = cls(config.workspace_root, engine, profile, worker=worker, attachments=attachments,
                      selected_worker=config.selected_worker or None)
        try:
            for _, profiles, adapter in attachments:
                if isinstance(adapter, ComfyUIEngine):
                    service.image_provider, service.image_profile_id = adapter.provider, profiles[0].profile_id
                    break
            service.session_tracker = SessionTracker()
            # Preserve the existing quota ledger location; it is not task authority.
            service.quota = QuotaLedger(storage_path=str(Path(config.journal_dir) / "quota_ledger.json"))
            if (Path(config.journal_dir) / "undo_history.json").is_file():
                service.attach_legacy_undo(UndoManager(str(service.store.workspace), config.journal_dir))
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

    def submit(self, prompt, *, session_id=None, request_id=None, skill=None, allowed_tools=None, max_turns=15, selected_context=None,
               profile_id=None, worker_id=None):
        profile = self.registry.profile(profile_id or self.profile.profile_id)
        if "text" not in profile.capabilities:
            raise ValueError("Select a text model for coding/chat tasks; use image generation for an image profile")
        available = frozenset(self.tools.tools)
        allowed = (available if "code_tools" in profile.capabilities else frozenset()) if allowed_tools is None else frozenset(allowed_tools)
        if not allowed <= available:
            raise ValueError("Task requested unknown tools; inspect the core tool catalog")
        if allowed and "code_tools" not in profile.capabilities:
            raise ValueError("Selected model does not declare code_tools support")
        if skill:
            manifest = self.skills.get_skill(skill) if isinstance(skill, str) else skill
            if not manifest:
                raise ValueError("Unknown skill; use /skills to inspect available commands")
            allowed &= self.skills.restrictions(manifest, available, profile.capabilities)
            prompt = self.skills.build_skill_prompt(manifest, prompt)
        schemas = [self.tools.tools[name].to_openai_tool() for name in sorted(allowed)]
        route = worker_id if worker_id is not None else self.selected_worker if profile.profile_id == self.profile.profile_id else None
        if not self.registry.candidates(profile.profile_id, route):
            raise ValueError("Selected worker cannot serve this model profile")
        task_id = self.sessions.submit(prompt, profile, self.prompt_builder.build_system_content(), schemas,
                                      allowed, session_id=session_id, request_id=request_id,
                                      max_turns=max_turns, selected_context=selected_context, requested_worker=route)
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
            self.scheduler.finalize_task(db, task_id, status)
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
        restricted = allowed & self.skills.restrictions(manifest, self.tools.tools, self.registry.profile(task["profile_id"]).capabilities)
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
        self._running_task_id = task_id
        try:
            task = self.task(task_id)
            self.current_session_id = task["session_id"]
            if task["state"] in TERMINAL:
                return self._summary(task_id)
            profile = self.registry.profile(task["profile_id"])
            state = NativeState.recover(task["driver"])
            if (state.agent_id != task["agent_id"] or state.profile_id != task["profile_id"]
                or state.context_epoch != task["context_epoch"]):
                raise ValueError("Checkpoint identity/profile/epoch does not match its durable task")
            history = json.loads(task["history"])
            command = self.store.one("SELECT operation FROM commands WHERE task_id=?", (task_id,))
            self.cancellation_token = CancellationToken()
            if self.quota:
                self.quota.start_session()
            if state.requires_reproposal:
                self._end(task_id, state, history, "failed", detail="Checkpoint was redacted; pending actions require a fresh proposal")
                return self._summary(task_id)
            if state.cancellation_requested:
                self.cancellation_token.cancel()
            else:
                state.local_stop_confirmed = False
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
                                 "content": bounded_result(r, profile.max_tool_result_bytes)} for p, r in results]
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
                    if command and command["operation"] == "undo":
                        success = all(r.get("status") == "success" for _, r in results)
                        state.phase = "completed" if success else "failed"
                        self._end(task_id, state, history, "completed" if success else "failed",
                                  answer="Snapshot restored" if success else "", detail="Approved restore receipt recorded" if success else encode(results[-1][1]))
                        break
                    continue
                if command and command["operation"] in {"undo", "image"}:
                    state.phase = "failed"
                    self._end(task_id, state, history, "failed", detail="Manual operation has no recoverable proposal; inspect its receipts rather than requesting text inference")
                    break
                if state.turns >= task["max_turns"]:
                    state.phase = "max_turns"
                    self._end(task_id, state, history, "max_turns", detail="No more inference turns permitted")
                    break
                session = self.store.one("SELECT * FROM sessions WHERE id=?", (task["session_id"],))
                schemas = json.loads(session["tool_prefix"])
                selected = json.loads(task["selected_context"])
                selected_messages = [{"role": "user", "content": "[SELECTED CONTEXT]\n" + encode(selected)}] if selected else []
                budget = budget_context(profile, session["system_prefix"], schemas, history, selected_messages)
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
                    reply, attempt_id, usage, ttft_ms = self.inference.infer(task, profile, messages, schemas, self.cancellation_token)
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
        except QueueWaiting as exc:
            self._end(task_id, state, history, "queued", detail=scrubber.scrub(exc))
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
            self._running_task_id = None
            self._run_lock.release()
        return self._summary(task_id, usage, ttft_ms)

    def resume(self, session_id, *, approval_resolver=None):
        session = self.store.one("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not session or not session["current_task_id"]:
            raise ValueError("Unknown session or no task to resume")
        command = self.store.one("SELECT operation FROM commands WHERE task_id=?", (session["current_task_id"],))
        if command and command["operation"] == "image":
            task = self.task(session["current_task_id"])
            if task["state"] in TERMINAL:
                return self._summary(task["id"])
            raise ValueError("Interrupted image job has no confirmed task receipt; inspect the provider job and reconcile inference capacity before a new request")
        return self.run(session["current_task_id"], approval_resolver=approval_resolver)

    def cancel(self, task_id=None):
        if task_id is None:
            task_id = self._running_task_id
            if task_id is None and self.current_session_id:
                session = self.store.one("SELECT current_task_id FROM sessions WHERE id=?", (self.current_session_id,))
                task_id = session["current_task_id"] if session else None
        if task_id is None:
            self.cancellation_token.cancel()
            return
        if task_id == self._running_task_id:
            with self.store.transaction() as db:
                task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if task["state"] in TERMINAL:
                    return
                self.cancellation_token.cancel()
                state = NativeState.recover(task["driver"])
                if task["state"] == "cancel_requested" and state.cancellation_requested:
                    return
                state.cancellation_requested = True
                updated = self.store.update_task(db, task_id, state="cancel_requested", driver=state.serialize())
                event = self.store.event(db, task["session_id"], task_id, "task.cancel_requested", {"status": "cancel_requested", "remote_cancel_confirmed": False}, revision=updated["revision"])
                self.store.checkpoint(db, task_id)
            self._publish(event)
            return
        if not self.scheduler.cancel_queued(task_id):
            raise ValueError("Remote inference outcome is unknown; reconcile its lease before cancelling queued work")

    def attach_worker(self, worker, profiles, engine):
        self.registry.attach(worker, profiles, engine)

    def list_workers(self, refresh=False):
        if refresh:
            for worker_id in tuple(self.registry.engines):
                self.registry.refresh(worker_id)
        return self.registry.list_workers()

    def list_models(self):
        return self.registry.list_profiles()

    def list_queue(self):
        return self.scheduler.list_queue()

    def run_next(self, *, approval_resolver=None):
        task_id = self.scheduler.next_task()
        if not task_id:
            return {"status": "waiting", "final_answer": "", "detail": "No queued task currently has an eligible free worker"}
        command = self.store.one("SELECT operation FROM commands WHERE task_id=?", (task_id,))
        if command["operation"] == "image":
            if not self._run_lock.acquire(blocking=False):
                raise RuntimeError("This local core already has an active task")
            try:
                self.cancellation_token = CancellationToken()
                self._execute_image_task(task_id)
                return self._summary(task_id)
            finally:
                self._running_task_id = None
                self._run_lock.release()
        return self.run(task_id, approval_resolver=approval_resolver)

    def list_sessions(self):
        return self.sessions.list_sessions()

    def new_session(self):
        self.current_session_id = None

    def list_actions(self):
        from harness.storage.undo import file_hash
        from harness.tools.sandbox import validate_workspace_path
        rows = self.store.all("SELECT id,task_id,name,state,target,pre_hash,post_hash FROM actions ORDER BY rowid DESC LIMIT 30")
        for row in rows:
            row["current_hash"] = None
            if row["target"]:
                try:
                    row["current_hash"] = file_hash(validate_workspace_path(row["target"], str(self.store.workspace), True))
                except Exception as exc:
                    row["file_check_error"] = scrubber.scrub(exc)
        return scrubber.structured(rows)

    def set_image_endpoint(self, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Image endpoint must be HTTP(S) without embedded credentials")
        if self._run_lock.locked() or self.inference.allocation()["state"] != "idle":
            raise ValueError("Resolve the active/uncertain allocation before changing the image endpoint")
        if not self.image_provider:
            raise ValueError("Image provider is not configured in this core composition")
        scrubber.register_secret(value)
        self.image_provider.server_url = value.rstrip("/")
        if self.image_profile_id:
            for row in self.registry.candidates(self.image_profile_id):
                adapter = self.registry.engine(row["id"])
                if isinstance(adapter, ComfyUIEngine) and adapter.provider is self.image_provider:
                    profiles = [self.registry.profile(p["profile_id"]) for p in self.store.all("SELECT profile_id FROM worker_profiles WHERE worker_id=?", (row["id"],))]
                    self.registry.attach(self.registry.worker(row["id"]), profiles, ComfyUIEngine(self.image_provider))

    def get_health(self):
        worker_id = self.selected_worker or next((r["id"] for r in self.registry.candidates(self.profile.profile_id)), self.worker.worker_id)
        health = self.registry.refresh(worker_id)
        if health is None:
            from harness.core.models import RemoteHealth
            observation = next(w for w in self.list_workers() if w["worker_id"] == worker_id)
            health = RemoteHealth(observation["health"], 0, 0, 0, 0, raw=observation["observed_resources"])
        if self.session_tracker and "supervisorUptimeSeconds" in health.raw:
            self.session_tracker.update_from_remote_health(health.raw)
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('worker_observation',?)", (encode({"status": health.status, "resources": health.raw,
                "observed_at": timestamp(), "source": "attached engine health"}),))
        return health

    def model_info(self):
        return dict(self.profile.to_dict(), selected_worker=self.selected_worker, allocation=self.inference.allocation(),
                    eligible_workers=[w for w in self.list_workers() if self.profile.profile_id in w["profiles"]])

    def select_profile(self, profile):
        if isinstance(profile, str):
            profile = self.registry.profile(profile)
        if self._run_lock.locked() or self.inference.allocation()["state"] != "idle":
            raise ValueError("Cannot change profiles while inference is active or uncertain")
        unfinished = self.store.one("SELECT id FROM tasks WHERE state NOT IN ('completed','failed','malformed','truncated','incomplete','max_turns','context_overflow','cancelled') LIMIT 1")
        if unfinished:
            raise ValueError("Resume/resolve the pending task before changing its model profile")
        registered = self.store.one("SELECT id FROM model_profiles WHERE id=?", (profile.profile_id,))
        if not registered:
            worker = self.worker
            bound_profiles = [self.registry.profile(p["profile_id"]) for p in self.store.all("SELECT profile_id FROM worker_profiles WHERE worker_id=?", (worker.worker_id,))]
            self.registry.attach(worker, bound_profiles + [profile], self.registry.engine(worker.worker_id), trusted_embedding=worker.worker_id in self.registry.trusted_embeddings)
        elif self.registry.profile(profile.profile_id).to_dict() != profile.to_dict():
            raise ValueError("Profile IDs are immutable; use a new ID for changed declarations")
        self.profile = profile
        self.selected_worker = profile.worker_id or None
        with self.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('active_profile',?)", (encode(profile.to_dict()),))

    def select_model(self, profile_id, worker_id=None):
        profile = self.registry.profile(profile_id)
        if not self.registry.candidates(profile_id, worker_id):
            raise ValueError("Selected worker cannot serve this model profile")
        self.select_profile(profile)
        self.selected_worker = worker_id

    def get_last_diff(self):
        snapshot = self.artifacts.latest()
        return scrubber.scrub(snapshot["diff"]) if snapshot else self.legacy_undo.get_last_diff() if self.legacy_undo else None

    def attach_legacy_undo(self, manager):
        self.legacy_undo = manager
        self.tool_broker.legacy_undo = manager
        self.tools.register(ToolDefinition("restore_legacy_snapshot", "Restore a preserved legacy snapshot through a durable approval",
            {"type": "object", "properties": {"snapshot_id": {"type": "string"}}, "required": ["snapshot_id"]},
            self._restore_legacy, requires_approval=True))

    def _restore_legacy(self, snapshot_id):
        if not self.legacy_undo or not self.legacy_undo.snapshots or self.legacy_undo.snapshots[-1].snapshot_id != snapshot_id:
            raise ValueError("Legacy snapshot is no longer current")
        # The outer durable broker already obtained this single-action approval.
        return self.legacy_undo.undo_last(approval_callback=lambda *_: True)

    def undo_last(self, approval_callback=None):
        if self._run_lock.locked():
            raise RuntimeError("Finish/cancel the active task before restoring a snapshot")
        snapshot = self.artifacts.latest()
        legacy = self.legacy_undo.snapshots[-1] if self.legacy_undo and self.legacy_undo.snapshots else None
        if not snapshot and not legacy:
            return {"status": "empty", "message": "No V2 file changes available to undo; legacy undo records are preserved separately"}
        name = "restore_snapshot" if snapshot else "restore_legacy_snapshot"
        snapshot_id = snapshot["id"] if snapshot else legacy.snapshot_id
        task_id = self.sessions.submit("Restore the most recent sealed snapshot", self.profile,
            self.prompt_builder.build_system_content(), [self.tools.tools[name].to_openai_tool()], [name], operation="undo")
        task = self.task(task_id)
        from harness.core.native_driver import Proposal
        state = NativeState.recover(task["driver"])
        proposal = Proposal("undo-" + identity(), name, {"snapshot_id": snapshot_id})
        state.turns, state.phase, state.pending = 1, "pending", [{"call_id": proposal.call_id, "name": name, "arguments": proposal.arguments}]
        history = json.loads(task["history"]) + [{"role": "assistant", "content": None, "tool_calls": [{"id": proposal.call_id,
            "type": "function", "function": {"name": name, "arguments": encode(proposal.arguments)}}]}]
        with self.store.transaction() as db:
            task = self.store.update_task(db, task_id, driver=state.serialize(), history=history)
            action_id = self.tool_broker.propose(db, task, [proposal], 1)[0]
            event = self.store.event(db, task["session_id"], task_id, "tool.proposed", {"action_id": action_id, "tool": name, "arguments": proposal.arguments})
            self.store.checkpoint(db, task_id)
        self._publish(event)
        summary = self.run(task_id, approval_resolver=approval_callback)
        action = self.store.one("SELECT * FROM actions WHERE id=?", (action_id,))
        result = json.loads(action["result"]) if action["result"] else {"status": summary["status"]}
        if summary["status"] == "outcome_unknown":
            result = dict(result, status="outcome_unknown", action_id=action_id, message="Reconcile the uncertain restore before retry")
        return result

    def generate_image(self, prompt):
        if self.image_provider is None or not self.image_provider.server_url:
            raise ValueError("Image worker is unconfigured; set FREECOMPUTE_IMAGE_SERVER or /image-server")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Finish/cancel the active task before starting image inference")
        try:
            self.cancellation_token = CancellationToken()
            return self._generate_image(prompt)
        finally:
            self._running_task_id = None
            self._run_lock.release()

    def _generate_image(self, prompt):
        if self.image_profile_id is None:
            profile = ModelProfile("comfy-image", "comfy-worker", "ComfyUI-default", "ComfyUI", frozenset({"image_gen"}))
            worker = Worker("comfy-worker", "fixture", "ComfyUI", profile.capabilities,
                            resource_pool=self.worker.resource_pool or self.worker.worker_id, resources=self.worker.resources)
            self.registry.attach(worker, [profile], ComfyUIEngine(self.image_provider), trusted_embedding=self.worker.location == "fixture")
            self.image_profile_id = profile.profile_id
        profile_id = self.profile.profile_id if "image_gen" in self.profile.capabilities else self.image_profile_id
        profile = self.registry.profile(profile_id)
        task_id = self.sessions.submit(prompt, profile, "Image generation", [], [], operation="image",
                                      requested_worker=self.selected_worker if profile_id == self.profile.profile_id else None)
        return self._execute_image_task(task_id)

    def _execute_image_task(self, task_id):
        task = self.task(task_id)
        self._running_task_id = task_id
        profile = self.registry.profile(task["profile_id"])
        state = NativeState.recover(task["driver"])
        try:
            result = self.inference.image(task, profile, scrubber.scrub(task["prompt"]), self.cancellation_token)
            self._end(task_id, state, json.loads(task["history"]), "completed", answer=result.get("file_path", ""))
            return result
        except QueueWaiting as exc:
            self._end(task_id, state, json.loads(task["history"]), "queued", detail=scrubber.scrub(exc))
            return {"status": "queued", "task_id": task_id, "message": scrubber.scrub(exc)}
        except AllocationUnavailable as exc:
            self._end(task_id, state, json.loads(task["history"]), "paused", detail=scrubber.scrub(exc))
            return {"status": "paused", "task_id": task_id, "message": scrubber.scrub(exc)}
        except Exception as exc:
            self._end(task_id, state, json.loads(task["history"]), "failed", detail=scrubber.scrub(exc))
            raise RuntimeError(scrubber.scrub(exc)) from None
        except KeyboardInterrupt:
            self.cancellation_token.cancel()
            self._end(task_id, state, json.loads(task["history"]), "cancelled", detail="Image job stopped locally; remote outcome unconfirmed")
            raise
