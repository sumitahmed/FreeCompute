"""One allocation across engines, normalized streaming and durable attempt receipts."""
from dataclasses import asdict
import json
import threading

from harness.core.native_driver import InferenceResponse, strict_json
from harness.security import scrubber, StreamRedactor
from harness.storage.runtime import encode, fingerprint, identity, timestamp


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


class AllocationUnavailable(RuntimeError):
    pass


class InferenceBroker:
    def __init__(self, store, engine, publish):
        self.store, self.engine, self.publish = store, engine, publish
        self._slot = threading.Lock()

    def allocation(self):
        row = self.store.one("SELECT value FROM metadata WHERE key='allocation'")
        return json.loads(row["value"]) if row else {"state": "idle"}

    def _begin(self, task, profile, request):
        if not self._slot.acquire(blocking=False):
            raise AllocationUnavailable("The single inference allocation is already active")
        try:
            with self.store.transaction() as db:
                row = db.execute("SELECT value FROM metadata WHERE key='allocation'").fetchone()
                allocation = json.loads(row[0]) if row else {"state": "idle"}
                if allocation["state"] != "idle":
                    raise AllocationUnavailable("Inference allocation is quarantined; explicitly confirm the remote worker is idle")
                attempt_id = identity()
                db.execute("INSERT INTO inference_attempts(id,task_id,version,profile_id,context_epoch,state,request_hash,started_at) VALUES(?,?,1,?,?,'active',?,?)",
                           (attempt_id, task["id"], profile.profile_id, task["context_epoch"], fingerprint(request), timestamp()))
                db.execute("INSERT OR REPLACE INTO metadata VALUES('allocation',?)", (encode({"state": "active", "attempt_id": attempt_id, "profile_id": profile.profile_id}),))
                event = self.store.event(db, task["session_id"], task["id"], "model.requested",
                                        {"attempt_id": attempt_id, "profile_id": profile.profile_id,
                                         "worker_id": profile.worker_id, "context_epoch": task["context_epoch"]},
                                        entity_id=attempt_id, revision=task["revision"])
                self.store.checkpoint(db, task["id"])
            self.publish(event)
            return attempt_id
        except BaseException:
            self._slot.release()
            raise

    def _finish(self, task, attempt_id, response, usage, ttft_ms, remote_finished):
        saved = persistent_response(response)
        with self.store.transaction() as db:
            state = "failed" if response.error else "completed"
            db.execute("UPDATE inference_attempts SET state=?,response=?,usage=?,error=?,ended_at=? WHERE id=?",
                       (state, encode(saved), encode(usage), scrubber.scrub(response.error) if response.error else None, timestamp(), attempt_id))
            allocation = {"state": "idle"} if remote_finished else {"state": "quarantined", "attempt_id": attempt_id, "reason": "Remote completion unconfirmed"}
            db.execute("UPDATE metadata SET value=? WHERE key='allocation'", (encode(allocation),))
            event = self.store.event(db, task["session_id"], task["id"], "model.received",
                                    {"attempt_id": attempt_id, "finish_reason": response.finish_reason,
                                     "stream_complete": response.stream_complete, "error": response.error,
                                     "usage": usage, "ttft_ms": ttft_ms, "allocation": allocation["state"]},
                                    entity_id=attempt_id, revision=task["revision"])
            self.store.checkpoint(db, task["id"])
        self.publish(event)

    def infer(self, task, profile, messages, tools, cancellation):
        if "text" not in profile.capabilities or tools and "code_tools" not in profile.capabilities:
            raise ValueError("Active profile lacks text/code_tools capability; attach a compatible profile")
        request = {"profile": profile.to_dict(), "messages": messages, "tools": tools}
        attempt_id = self._begin(task, profile, request)
        text, calls = "", {}
        reason, done, usage, ttft_ms = None, False, None, None
        content_redactor, reasoning_redactor = StreamRedactor(), StreamRedactor()
        error = None
        try:
            for chunk in self.engine.stream(profile, messages, tools, cancellation):
                if cancellation.is_cancelled:
                    break
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
        except Exception as exc:
            error = scrubber.scrub(exc)
        except KeyboardInterrupt:
            cancellation.cancel()
        finally:
            response = InferenceResponse(scrubber.scrub(text), [calls[i] for i in sorted(calls)], reason, done, error)
            try:
                self._finish(task, attempt_id, response, usage, ttft_ms, done and not cancellation.is_cancelled)
            finally:
                self._slot.release()
        return response, attempt_id, usage, ttft_ms

    def _stream_event(self, task, kind, value):
        with self.store.transaction() as db:
            event = self.store.event(db, task["session_id"], task["id"], kind, {"text": value}, revision=task["revision"])
        self.publish(event)

    def reconcile_idle(self, resolver=None):
        if not self._slot.acquire(blocking=False):
            raise AllocationUnavailable("Cannot reconcile an active allocation")
        try:
            allocation = self.allocation()
            if allocation["state"] == "idle":
                return allocation
            if resolver is None or resolver("reconcile_inference", {"allocation": allocation, "assertion": "remote worker is idle"}) is not True:
                raise ValueError("Explicit confirmation that the remote worker is idle is required")
            with self.store.transaction() as db:
                db.execute("UPDATE metadata SET value=? WHERE key='allocation'", (encode({"state": "idle", "source": "operator confirmation"}),))
                db.execute("INSERT OR REPLACE INTO metadata VALUES('allocation_reconciliation',?)", (encode({"previous": allocation, "at": timestamp(), "actor": "user"}),))
            return self.allocation()
        finally:
            self._slot.release()

    def image(self, task, profile, generate, prompt):
        if "image_gen" not in profile.capabilities:
            raise ValueError("Select an image-generation profile for this operation")
        attempt = self._begin(task, profile, {"operation": "image", "prompt": prompt})
        try:
            result = generate(prompt=prompt)
            response = InferenceResponse("image job completed", finish_reason="stop", stream_complete=True)
            self._finish(task, attempt, response, None, None, True)
            return scrubber.structured(result)
        except Exception as exc:
            self._finish(task, attempt, InferenceResponse(error=scrubber.scrub(exc)), None, None, False)
            raise RuntimeError(scrubber.scrub(exc)) from None
        except KeyboardInterrupt:
            self._finish(task, attempt, InferenceResponse(error="Image interrupted locally; remote job outcome unconfirmed"), None, None, False)
            raise
        finally:
            self._slot.release()
