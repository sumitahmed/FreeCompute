"""Actual process-crash worker; only disposable fixture files are affected."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support  # Network guard before SDK import.
import os
import uuid
from harness.core.client import CancellationToken
from harness.experiments.foundation.runtime import Actor, ExperimentStore, DurableToolBroker, InferenceBroker, identity
from harness.experiments.foundation.openhands_adapter import conversation, send_message, reconcile_projection, run_conversation
from harness.tools.registry import ToolRegistry

root, endpoint, point, mode = sys.argv[1:]
root = Path(root)
store = ExperimentStore(root / "runtime.sqlite")
task = store.get("tasks", "task")
if task is None:
    task = {"task_id": identity(), "agent_id": identity(), "conversation_id": str(uuid.uuid4()), "state": "running"}
    store.put("tasks", "task", task)
actor = Actor(task["task_id"], task["agent_id"], frozenset({"read_file", "write_file"}))
registry = ToolRegistry(str(root / "workspace"))
original = registry.tools["write_file"].handler


def write(**args):
    result = original(**args)
    # Separate durable effect counter distinguishes replay from equal contents.
    with (root / "effects.txt").open("a") as file:
        file.write("effect\n")
        file.flush()
        os.fsync(file.fileno())
    if mode == "crash" and point == "during_execution":
        os._exit(73)
    return result


registry.tools["write_file"].handler = write


def approval(*_):
    with (root / "approvals.txt").open("a") as file:
        file.write("approval\n")
    return True


def checkpoint(stage):
    if mode == "crash" and stage == point:
        os._exit(73)


authority = DurableToolBroker(store, registry, actor, CancellationToken(), approval, checkpoint)
if mode == "resume":
    authority.reconcile()
broker = InferenceBroker(store, endpoint)
conv = conversation(store, actor, broker, authority, root / "presentation", uuid.UUID(task["conversation_id"]),
                    purpose="recovery" if mode == "resume" else "generation")
if mode == "crash":
    send_message(conv, "Write the deterministic fixture file")
else:
    reconcile_projection(conv, authority)
run_conversation(conv, authority)
task["state"] = "needs_reconciliation" if any(row["state"] == "outcome_unknown" for _, row in store.all("actions")) else "finished"
store.put("tasks", "task", task)
conv.close()
store.close()
