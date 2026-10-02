"""Scheduled inference, normalized streams and atomic attempt/lease receipts."""
from dataclasses import asdict
import json
import threading

from harness.core.native_driver import InferenceResponse, strict_json
from harness.core.engines import EngineFailure
from harness.core.scheduler import AllocationUnavailable, QueueWaiting
from harness.security import scrubber, StreamRedactor
from harness.storage.runtime import encode, fingerprint, identity, timestamp

MAX_STREAM_BYTES = 4 * 1024 * 1024


def persistent_response(response):
    value = asdict(response)
    requires_reproposal = False
    calls = []
    for call in response.tool_calls:
        function = call.get("function", {})
        arguments = function.get("arguments")
        try:
            decoded = strict_json(arguments)
            clean = scrubber.structured(decoded)
            requires_reproposal |= clean != decoded
            arguments = json.dumps(clean, sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            # Malformed fragments are never persisted as opaque escaped strings.
            arguments = None
        calls.append({"id": scrubber.scrub(call.get("id", "")), "type": call.get("type", "function"),
                      "function": {"name": scrubber.scrub(function.get("name", "")), "arguments": arguments}})
    value["tool_calls"] = calls
    return {"response": scrubber.structured(value), "requires_reproposal": requires_reproposal}


class InferenceBroker:
    def __init__(self, store, registry, scheduler, publish, default_worker):
        self.store, self.registry, self.scheduler, self.publish = store, registry, scheduler, publish
        self.default_worker = default_worker
        self._active, self._lock = {}, threading.RLock()

    @property
    def engine(self):
        return self.registry.engine(self.default_worker)

    @engine.setter
    def engine(self, value):
        if self.store.one("SELECT id FROM inference_leases WHERE worker_id=? AND state IN ('active','quarantined')", (self.default_worker,)):
            raise AllocationUnavailable("Resolve attached worker leases before replacing its engine")
        self.registry.engines[self.default_worker] = value

    def allocation(self):
        return self.scheduler.allocation()

    def _begin(self, task, profile, request, capabilities, cancellation):
        route = self.scheduler.requested_worker(task["id"])
        self.registry.refresh_candidates(profile.profile_id, route)
        job = self.scheduler.enqueue(task, profile, capabilities, requested_worker=route, request_hash=fingerprint(request))
        emitted = []
        with self.store.transaction() as db:
            lease, reason, quarantined = self.scheduler.claim(db, job["id"])
            if lease:
                attempt_id = identity()
                db.execute("INSERT INTO inference_attempts(id,task_id,version,profile_id,context_epoch,state,request_hash,started_at) VALUES(?,?,1,?,?,'active',?,?)",
                           (attempt_id, task["id"], profile.profile_id, task["context_epoch"], fingerprint(request), timestamp()))
                db.execute("UPDATE inference_leases SET attempt_id=? WHERE id=?", (attempt_id, lease["id"]))
                self.scheduler.sync_allocation(db)
                emitted.append(self.store.event(db, task["session_id"], task["id"], "queue.assigned",
                                               {"queue_id": job["id"], "lease_id": lease["id"], "worker_id": lease["worker_id"], "resources": lease["resources"]}))
                emitted.append(self.store.event(db, task["session_id"], task["id"], "model.requested",
                                        {"attempt_id": attempt_id, "profile_id": profile.profile_id,
                                         "worker_id": lease["worker_id"], "lease_id": lease["id"], "context_epoch": task["context_epoch"]},
                                        entity_id=attempt_id, revision=task["revision"]))
            else:
                emitted.append(self.store.event(db, task["session_id"], task["id"], "queue.waiting", {"queue_id": job["id"], "reason": reason}))
            self.store.checkpoint(db, task["id"])
        if lease:
            with self._lock:
                self._active[attempt_id] = (cancellation, lease)
        for event in emitted:
            self.publish(event)
        if not lease:
            raise (AllocationUnavailable if quarantined else QueueWaiting)(reason)
        return attempt_id, lease, self.registry.engine(lease["worker_id"])

    def _finish(self, task, attempt_id, lease, response, usage, ttft_ms, remote_finished):
        saved = persistent_response(response)
        with self.store.transaction() as db:
            state = "failed" if response.error else "completed"
            db.execute("UPDATE inference_attempts SET state=?,response=?,usage=?,error=?,ended_at=? WHERE id=?",
                       (state, encode(saved), encode(usage), scrubber.scrub(response.error) if response.error else None, timestamp(), attempt_id))
            self.scheduler.finish(db, lease["id"], confirmed=remote_finished, failed=bool(response.error), reason=response.error or "" if remote_finished else "Remote completion unconfirmed")
            self.scheduler.sync_allocation(db)
            allocation = self.scheduler.allocation()
            if response.error:
                db.execute("UPDATE workers SET health='unreachable',observation=? WHERE id=?", (encode({"error": response.error}), lease["worker_id"]))
            event = self.store.event(db, task["session_id"], task["id"], "model.received",
                                    {"attempt_id": attempt_id, "finish_reason": response.finish_reason,
                                     "stream_complete": response.stream_complete, "error": response.error,
                                     "usage": usage, "ttft_ms": ttft_ms, "allocation": allocation["state"], "worker_id": lease["worker_id"], "lease_id": lease["id"]},
                                    entity_id=attempt_id, revision=task["revision"])
            self.store.checkpoint(db, task["id"])
        self.publish(event)

    def infer(self, task, profile, messages, tools, cancellation):
        if "text" not in profile.capabilities or tools and "code_tools" not in profile.capabilities:
            raise ValueError("Active profile lacks text/code_tools capability; attach a compatible profile")
        request = {"profile": profile.to_dict(), "messages": messages, "tools": tools}
        required = {"text", "code_tools"} if tools else {"text"}
        attempt_id, lease, engine = self._begin(task, profile, request, required, cancellation)
        text, calls = "", {}
        reason, done, usage, ttft_ms = None, False, None, None
        content_redactor, reasoning_redactor = StreamRedactor(), StreamRedactor()
        error = None
        remote_not_started = cancellation.is_cancelled
        received_bytes = 0
        stream_limit = min(MAX_STREAM_BYTES, max(8192, profile.reserved_completion * 32))
        try:
            for chunk in (() if remote_not_started else engine.stream(profile, messages, tools, cancellation)):
                if cancellation.is_cancelled:
                    break
                received_bytes += len(json.dumps({"text": chunk.delta_content, "reasoning": chunk.delta_reasoning,
                    "tools": chunk.tool_call_deltas}, ensure_ascii=True).encode("utf-8"))
                if received_bytes > stream_limit:
                    raise ValueError("Inference output exceeded the profile's stream byte allowance; no proposals accepted")
                if done and (chunk.delta_content or chunk.tool_call_deltas or chunk.delta_reasoning):
                    raise ValueError("Content received after stream completion")
                if chunk.finish_reason:
                    if reason and reason != chunk.finish_reason:
                        raise ValueError("Conflicting finish reasons")
                    reason = chunk.finish_reason
                done |= chunk.stream_complete
                if chunk.usage is not None:
                    usage = scrubber.structured(chunk.usage)
                if ttft_ms is None and chunk.ttft_ms is not None:
                    ttft_ms = chunk.ttft_ms
                text += chunk.delta_content or ""
                for kind, value in (("stream.text", content_redactor.feed(chunk.delta_content or "")),
                                    ("stream.reasoning", reasoning_redactor.feed(chunk.delta_reasoning or ""))):
                    if value:
                        self._stream_event(task, kind, value)
                for delta in chunk.tool_call_deltas or []:
                    index = delta.get("index")
                    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                        raise ValueError("Tool fragments require an explicit nonnegative index")
                    current = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if delta.get("type", "function") != "function":
                        raise ValueError("Unsupported tool-call type")
                    if delta.get("id"):
                        if not isinstance(delta["id"], str) or current["id"] and current["id"] != delta["id"]:
                            raise ValueError("Conflicting or invalid tool identity")
                        current["id"] = delta["id"]
                    function = delta.get("function", {})
                    if not isinstance(function, dict):
                        raise ValueError("Invalid function delta")
                    for key in ("name", "arguments"):
                        fragment = function.get(key)
                        if fragment is not None:
                            if not isinstance(fragment, str):
                                raise ValueError("Function fragments must be strings")
                            current["function"][key] += fragment
            if not cancellation.is_cancelled:
                for kind, value in (("stream.text", content_redactor.finish()), ("stream.reasoning", reasoning_redactor.finish())):
                    if value:
                        self._stream_event(task, kind, value)
        except EngineFailure as exc:
            error, remote_not_started = scrubber.scrub(exc), exc.remote_not_started and received_bytes == 0
        except Exception as exc:
            error = scrubber.scrub(exc)
        except KeyboardInterrupt:
            cancellation.cancel()
        finally:
            response = InferenceResponse(scrubber.scrub(text), [calls[i] for i in sorted(calls)], reason, done, error)
            try:
                self._finish(task, attempt_id, lease, response, usage, ttft_ms, remote_not_started or done and not cancellation.is_cancelled)
            finally:
                with self._lock:
                    self._active.pop(attempt_id, None)
        return response, attempt_id, usage, ttft_ms

    def _stream_event(self, task, kind, value):
        with self.store.transaction() as db:
            event = self.store.event(db, task["session_id"], task["id"], kind, {"text": value}, revision=task["revision"])
        self.publish(event)

    def reconcile_idle(self, resolver=None, lease_id=None):
        with self._lock:
            if self._active and (not lease_id or any(l["id"] == lease_id for _, l in self._active.values())):
                raise AllocationUnavailable("Cannot reconcile an active local inference")
        return self.scheduler.reconcile(resolver, lease_id)

    def image(self, task, profile, prompt, cancellation):
        if "image_gen" not in profile.capabilities:
            raise ValueError("Select an image-generation profile for this operation")
        attempt, lease, engine = self._begin(task, profile, {"operation": "image", "prompt": prompt}, {"image_gen"}, cancellation)
        try:
            result = engine.generate(profile, prompt, cancellation)
            response = InferenceResponse("image job completed", finish_reason="stop", stream_complete=True)
            self._finish(task, attempt, lease, response, None, None, True)
            return scrubber.structured(result)
        except Exception as exc:
            self._finish(task, attempt, lease, InferenceResponse(error=scrubber.scrub(exc)), None, None, isinstance(exc, EngineFailure) and exc.remote_not_started)
            raise RuntimeError(scrubber.scrub(exc)) from None
        except KeyboardInterrupt:
            self._finish(task, attempt, lease, InferenceResponse(error="Image interrupted locally; remote job outcome unconfirmed"), None, None, False)
            raise
        finally:
            with self._lock:
                self._active.pop(attempt, None)
