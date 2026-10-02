"""A real process exit around durable inference admission; no network/GPU calls."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness.core.models import RemoteHealth, StreamChunk
from harness.core.runtime_models import ModelProfile, Worker
from harness.core.service import CoreService

TEXT = frozenset({"text", "code_tools"})
LOCAL = ModelProfile("local", "local-small", "local-fixture", "fixture", TEXT)
QWEN = ModelProfile("qwen", model="Qwen-27B-fixture", engine="fixture", capabilities=TEXT,
                    resource_requirements=frozenset({"gpu0", "gpu1"}))


class Engine:
    def __init__(self, directory, crash=False):
        self.directory, self.crash = directory, crash

    def get_capabilities(self):
        return TEXT

    def get_health(self):
        return RemoteHealth("healthy", 0, 0, 0, 0)

    def stream(self, *args):
        counter = self.directory / "inference-count.txt"
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        with counter.open("w") as output:
            output.write(str(count))
            output.flush()
            os.fsync(output.fileno())
        if self.crash:
            os._exit(73)
        yield StreamChunk(delta_content="fixture completed", finish_reason="stop")
        yield StreamChunk(stream_complete=True)


def main():
    mode, directory = sys.argv[1:3]
    directory = Path(directory)
    workspace = directory / "workspace"
    workspace.mkdir(exist_ok=True)
    core = CoreService(workspace, Engine(directory), LOCAL, state_dir=directory / "state", system_prompt="fixture")
    core.attach_worker(Worker("kaggle-qwen", "kaggle", "fixture", TEXT,
                              resource_pool="dual-t4", resources=QWEN.resource_requirements),
                       [QWEN], Engine(directory, mode == "running"))
    try:
        task_file = directory / "tasks.json"
        if mode in {"queued", "running", "cancelled"}:
            tasks = [core.submit("fixture", profile_id="qwen", allowed_tools=[]) for _ in range(2)]
            task_file.write_text(json.dumps(tasks), encoding="utf-8")
            if mode == "cancelled":
                core.cancel(tasks[0])
            if mode == "running":
                core.run(tasks[0])
            os._exit(73)
        tasks = json.loads(task_file.read_text())
        if mode == "inspect":
            core.run(tasks[0])
        elif mode == "reconcile":
            core.inference.reconcile_idle(lambda *_: True)
            core.run_next()
        elif mode == "drain":
            core.run_next()
            core.run_next()
        else:
            raise ValueError("Unknown fixture mode")
        count = directory / "inference-count.txt"
        print(json.dumps({"states": [core.task(t)["state"] for t in tasks],
                          "queue": core.list_queue(), "allocation": core.inference.allocation(),
                          "claims": core.store.all("SELECT pool_id,resource_id FROM resource_claims"),
                          "inference_calls": int(count.read_text()) if count.exists() else 0}))
    finally:
        core.close()


if __name__ == "__main__":
    main()
