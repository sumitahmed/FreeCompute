"""Real process-exit fixture for the production runtime; never starts a GPU."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.core.models import StreamChunk
from harness.core.runtime_models import ModelProfile
from harness.core.service import CoreService
from harness.tools.registry import ToolDefinition


PROFILE = ModelProfile("crash-profile", "crash-worker", "fixture", "fixture", frozenset({"text", "code_tools"}))


def increment(path):
    value = int(path.read_text()) + 1 if path.exists() else 1
    with path.open("w", encoding="utf-8") as stream:
        stream.write(str(value))
        stream.flush()
        os.fsync(stream.fileno())
    return value


class Engine:
    def __init__(self, create, stage):
        self.create, self.stage, self.requests = create, stage, 0
        self.fresh_proposal = False

    def stream(self, profile, messages, tools, cancellation):
        self.requests += 1
        if self.stage == "during_inference":
            os._exit(73)
        if self.create and self.requests == 1 or self.fresh_proposal:
            self.fresh_proposal = False
            call_id = "effect-1" if self.create else "fresh-effect-2"
            yield StreamChunk(tool_call_deltas=[{"index": 0, "id": call_id,
                "function": {"name": "count_effect", "arguments": "{}"}}], finish_reason="tool_calls")
        else:
            yield StreamChunk(delta_content="completed from fixture", finish_reason="stop")
        yield StreamChunk(stream_complete=True)


def main():
    mode, stage, directory = sys.argv[1:4]
    directory = Path(directory)
    workspace = directory / "workspace"
    workspace.mkdir(exist_ok=True)
    engine = Engine(mode == "create", stage if mode == "create" else "")
    def fault(point, action):
        if mode == "create" and point == stage:
            os._exit(73)
    core = CoreService(workspace, engine, PROFILE, state_dir=directory / "state", system_prompt="fixture", fault_hook=fault)
    def effect():
        result = {"counter": increment(workspace / "counter.txt")}
        if mode == "create" and stage == "during_execution":
            os._exit(73)
        return result
    core.tools.register(ToolDefinition("count_effect", "Approved counter fixture", {"type": "object", "properties": {}}, effect, True))
    def approve(name, args):
        increment(workspace / "approvals.txt")
        return True
    def model_receipt(event):
        if mode == "create" and event["kind"] == "model.received":
            if stage == "after_inference_receipt" and engine.requests == 1:
                os._exit(73)
            if stage == "after_final_inference_receipt" and engine.requests == 2:
                os._exit(73)
    core.subscribe(model_receipt)
    try:
        if mode == "create":
            result = core.run(core.submit("count one effect", allowed_tools=["count_effect"]), approval_resolver=approve)
        else:
            session_id = sys.argv[4]
            if mode == "reconcile":
                unknown = core.store.one("SELECT id FROM actions WHERE state='outcome_unknown' ORDER BY rowid LIMIT 1")
                core.tool_broker.reconcile(unknown["id"], "completed", resolver=approve)
            elif mode == "reconcile_idle":
                core.inference.reconcile_idle(approve)
            result = core.resume(session_id, approval_resolver=approve)
            if mode == "resume" and result["status"] == "outcome_unknown":
                engine.fresh_proposal = True
                fresh = core.run(core.submit("try a fresh action ID", allowed_tools=["count_effect"]), approval_resolver=approve)
                result["fresh_id_status"] = fresh["status"]
        counter = workspace / "counter.txt"
        approval_count = workspace / "approvals.txt"
        result["counter"] = int(counter.read_text()) if counter.exists() else 0
        result["approvals"] = int(approval_count.read_text()) if approval_count.exists() else 0
        result["inference_requests"] = engine.requests
        result["allocation"] = core.inference.allocation()["state"]
        print(json.dumps(result))
    finally:
        core.close()


if __name__ == "__main__":
    main()
