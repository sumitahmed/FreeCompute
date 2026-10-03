"""SIMULATED inference only. Tools execute locally in a disposable demo workspace."""
from pathlib import Path
import json
import sys
import tempfile
import time

from harness.core.engines import EngineFailure
from harness.core.models import RemoteHealth, StreamChunk
from harness.core.runtime_models import ModelProfile, Worker
from harness.core.service import CoreService


class DemoEngine:
    def __init__(self, delay=0.06):
        self.delay, self.connected = delay, True

    def get_capabilities(self):
        return frozenset({"text", "code_tools"})

    def get_health(self):
        return RemoteHealth("healthy" if self.connected else "unreachable", 0, 0, 0, 0,
                            raw={"source": "SIMULATED worker; no GPU", "gpus": []})

    def stream(self, profile, messages, tools, cancellation):
        if not self.connected:
            raise EngineFailure("SIMULATED worker disconnected before inference", remote_not_started=True)
        user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        prompt = messages[user]["content"]
        results = [m for m in messages[user + 1:] if m["role"] == "tool"]
        if "[demo:failure]" in prompt:
            raise EngineFailure("SIMULATED engine authentication failure; check worker credentials", remote_not_started=True, kind="authentication")
        tool = None
        if "[demo:edit]" in prompt:
            already_fixed = bool(results and "return a / b" in json.loads(results[0]["content"]).get("raw_content", ""))
            stages = [("read_file", {"path": "calculator.py"})]
            if not already_fixed:
                stages.append(("edit_file", {"path": "calculator.py", "old_str": "return a // b", "new_str": "return a / b"}))
            stages.append(("run_command", {"command": f'"{sys.executable}" -m unittest -v test_calculator', "timeout_seconds": 30}))
            if len(results) < len(stages):
                tool = stages[len(results)]
                text = ("I will read the disposable calculator. " if tool[0] == "read_file" else
                        "The division truncates fractions. Review this replacement. " if tool[0] == "edit_file" else
                        "I will run the local calculator tests after approval. ")
            else:
                edit_ok = already_fixed or json.loads(results[1]["content"]).get("status") == "applied"
                command = json.loads(results[-1]["content"])
                text = ("SIMULATED assistant: " + ("The calculator already uses true division. " if already_fixed else "Changed integer division to true division. ") + "The real local unittest command exited 0. "
                        if edit_ok and command.get("exit_code") == 0 else
                        "SIMULATED assistant: The change or command was denied or failed. Inspect the local receipts; tests are not confirmed passing. ")
        elif "[demo:write]" in prompt and not results:
            tool = ("write_file", {"path": "demo-note.txt", "content": "A disposable GUI fixture note.\n"})
            text = "Review this local file creation. No file is written until you approve. "
        else:
            text = "SIMULATED assistant: This is deterministic local development output. No model or GPU was contacted. "
        if "[demo:long]" in prompt:
            text *= 100
        for word in text.split(" "):
            if cancellation.is_cancelled:
                return  # Socket stop is deliberately not remote completion acknowledgement.
            time.sleep(self.delay)
            yield StreamChunk(delta_content=word + " ")
        if tool:
            name, arguments = tool
            yield StreamChunk(tool_call_deltas=[{"index": 0, "id": "demo-call-" + str(len(results)),
                              "function": {"name": name, "arguments": json.dumps(arguments)}}], finish_reason="tool_calls")
        else:
            yield StreamChunk(finish_reason="stop", usage={"fixture": True})
        yield StreamChunk(stream_complete=True)


def create_demo(workspace=None, *, state_dir=None, delay=0.06):
    # No loading .env, real worker configuration or remote clients in this path.
    workspace = Path(workspace or (Path(tempfile.gettempdir()) / "freecompute-gui-demo")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for name, contents in {
        "calculator.py": "def divide(a, b):\n    return a // b\n",
        "test_calculator.py": "import unittest\nfrom calculator import divide\n\nclass CalculatorTests(unittest.TestCase):\n    def test_fraction(self):\n        self.assertEqual(divide(7, 2), 3.5)\n    def test_whole(self):\n        self.assertEqual(divide(8, 2), 4)\n",
    }.items():
        target = workspace / name
        if not target.exists():
            target.write_text(contents, encoding="utf-8")
    engine = DemoEngine(delay)
    code = ModelProfile("demo-code", "demo-worker", "Simulated coding fixture", "fixture", frozenset({"text", "code_tools"}), verification="fixture-tested")
    chat = ModelProfile("demo-chat", "demo-chat-worker", "Simulated text only", "fixture", frozenset({"text"}), context_capacity=4096, reserved_completion=512, verification="fixture-tested")
    worker = Worker("demo-worker", "local simulation", "fixture", code.capabilities, resource_pool="demo-code-pool", resources=frozenset({"slot"}))
    chat_worker = Worker("demo-chat-worker", "local simulation", "fixture", chat.capabilities, resource_pool="demo-chat-pool", resources=frozenset({"slot"}))
    core = CoreService(workspace, engine, code, state_dir=state_dir, worker=worker,
                       attachments=[(worker, [code, chat], engine), (chat_worker, [chat], engine)], selected_worker=worker.worker_id)
    core.list_workers(refresh=True)
    return core
