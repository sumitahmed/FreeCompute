"""Core authority properties do not require the optional SDK dependency."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from harness.core.client import CancellationToken
from harness.security import scrubber
from harness.tools.registry import ToolRegistry, ToolDefinition
from harness.experiments.foundation.runtime import Actor, DurableToolBroker, ExperimentStore, InferenceBroker, identity


class CoreFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-core-foundation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ExperimentStore(self.root / "state.sqlite")
        self.addCleanup(self.store.close)
        self.actor = Actor(identity(), identity(), frozenset({"read_file", "write_file"}))
        self.registry = ToolRegistry(str(self.root))
        self.token = CancellationToken()
        self.broker = DurableToolBroker(self.store, self.registry, self.actor, self.token, lambda *_: True)

    def test_missing_approval_and_truthy_nonboolean_are_denied(self):
        for index, callback in enumerate((None, lambda *_: "yes", lambda *_: 1)):
            self.broker.approval = callback
            result = self.broker.execute(str(index), "write_file", {"path": "file.txt", "content": "x"})
            self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.root / "file.txt").exists())

    def test_completed_action_returns_durable_result_without_repeating_handler(self):
        original = self.registry.tools["write_file"].handler
        calls = []
        def handler(**args):
            calls.append(args)
            return original(**args)
        self.registry.tools["write_file"].handler = handler
        args = {"path": "file.txt", "content": "one"}
        result = self.broker.execute("action", "write_file", args)
        self.assertEqual(self.broker.execute("action", "write_file", args), result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.all("actions")[0][1]["result"], result)

    def test_concurrent_same_action_cannot_duplicate_effect(self):
        calls = []
        self.registry.register(ToolDefinition("count", "count", {"properties": {}}, lambda: calls.append(1) or {"ok": True}, requires_approval=False))
        actor = Actor(self.actor.task_id, self.actor.agent_id, frozenset({"count"}))
        broker = DurableToolBroker(self.store, self.registry, actor, self.token)
        threads = [threading.Thread(target=lambda: broker.execute("same", "count", {})) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [1])

    def test_action_identity_collision_rejected(self):
        self.broker.execute("action", "write_file", {"path": "file.txt", "content": "one"})
        result = self.broker.execute("action", "write_file", {"path": "file.txt", "content": "two", "overwrite": True})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual((self.root / "file.txt").read_text(), "one")

    def test_capability_child_cannot_widen(self):
        child = self.actor.child({"read_file"})
        self.assertNotEqual(child.agent_id, self.actor.agent_id)
        self.assertEqual(child.task_id, self.actor.task_id)
        with self.assertRaises(ValueError):
            child.child({"write_file"})
        broker = DurableToolBroker(self.store, self.registry, child, self.token, lambda *_: True)
        self.assertEqual(broker.execute("action", "write_file", {"path": "denied.txt", "content": "x"})["status"], "rejected")
        self.assertFalse((self.root / "denied.txt").exists())

    def test_restart_invalidates_approval_and_quarantines_execution(self):
        for state in ("pending", "approved", "executing", "completed", "failed"):
            row = {"task_id": self.actor.task_id, "state": state}
            self.store.put("actions", state, row)
        self.broker.reconcile()
        self.assertEqual(self.store.get("actions", "pending")["state"], "pending")
        self.assertTrue(self.store.get("actions", "approved")["approval_invalidated_on_restart"])
        self.assertEqual(self.store.get("actions", "approved")["state"], "pending")
        self.assertEqual(self.store.get("actions", "executing")["state"], "outcome_unknown")
        self.assertEqual(self.store.get("actions", "completed")["state"], "completed")
        self.assertEqual(self.store.get("actions", "failed")["state"], "failed")

    def test_quarantined_action_never_replays_even_with_approval(self):
        args = {"path": "file.txt", "content": "x"}
        self.broker.execute("action", "write_file", args)
        key, row = self.store.all("actions")[0]
        (self.root / "file.txt").unlink()
        row["state"] = "executing"
        self.store.put("actions", key, row)
        self.broker.reconcile()
        self.assertEqual(self.broker.execute("action", "write_file", args)["status"], "outcome_unknown")
        self.assertEqual(self.broker.execute("fresh-model-id", "write_file", args)["status"], "outcome_unknown")
        self.assertFalse((self.root / "file.txt").exists())

    def test_sanitized_pending_action_requires_reproposal_after_restart(self):
        secret = "pending-credential-" + uuid.uuid4().hex
        scrubber.register_secret(secret)
        args = {"path": "file.txt", "content": secret}
        class SimulatedCrash(BaseException):
            pass
        self.broker.checkpoint = lambda _: (_ for _ in ()).throw(SimulatedCrash())
        with self.assertRaises(SimulatedCrash):
            self.broker.execute("action", "write_file", args)
        self.assertNotIn(secret, json.dumps(self.store.all("actions")))
        self.broker.checkpoint = lambda _: None
        self.assertEqual(self.broker.execute("action", "write_file", args)["status"], "rejected")
        self.assertFalse((self.root / "file.txt").exists())

    def test_cancel_before_execution_and_protected_path_fail_closed(self):
        self.token.cancel()
        result = self.broker.execute("cancel", "write_file", {"path": "file.txt", "content": "x"})
        self.assertEqual(result["status"], "rejected")
        result = self.broker.execute("protected", "write_file", {"path": ".env", "content": "x"})
        self.assertIn("error", result)
        self.assertFalse((self.root / "file.txt").exists())
        self.assertFalse((self.root / ".env").exists())

    def test_store_survives_reopen_and_scrubs_nested_records(self):
        secret = "store-credential-" + uuid.uuid4().hex
        scrubber.register_secret(secret)
        self.store.put("tasks", "one", {"input": [secret], "state": "pending"})
        reopened = ExperimentStore(self.root / "state.sqlite")
        try:
            self.assertEqual(reopened.get("tasks", "one")["input"], ["[REDACTED_SECRET]"])
            self.assertNotIn(secret.encode(), (self.root / "state.sqlite").read_bytes())
        finally:
            reopened.close()

    def test_nonfixture_inference_endpoint_rejected(self):
        for endpoint in ("https://example.invalid/v1/chat/completions", "http://127.0.0.1:8080@evil.invalid/v1", "http://127.0.0.1:8080.evil.invalid/v1"):
            with self.assertRaises(ValueError):
                InferenceBroker(self.store, endpoint)

    def test_sanitized_model_proposal_denial_is_core_owned(self):
        result = self.broker.execute("redacted", "write_file", {"path": "file.txt", "content": "[REDACTED_SECRET]"}, requires_reproposal=True)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.store.all("actions")[0][1]["state"], "denied")
        self.assertFalse((self.root / "file.txt").exists())

    def test_error_after_approved_effect_is_not_safe_to_replay(self):
        original = self.registry.tools["write_file"].handler
        def failing(**args):
            original(**args)
            raise RuntimeError("Failure after effect")
        self.registry.tools["write_file"].handler = failing
        args = {"path": "file.txt", "content": "effect"}
        result = self.broker.execute("partial", "write_file", args)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual((self.root / "file.txt").read_text(), "effect")
        self.assertEqual(self.broker.execute("partial", "write_file", args), result)
