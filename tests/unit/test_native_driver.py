import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from harness.core.native_driver import InferenceResponse, NativeAgentDriver, NativeState
from harness.core.context import budget_context
from harness.security import scrubber


def response(arguments='{"path":"a.txt"}', identity="call-1"):
    return InferenceResponse(tool_calls=[{"id": identity, "function": {"name": "read_file", "arguments": arguments}}],
                             finish_reason="tool_calls", stream_complete=True)


class NativeQualificationTests(unittest.TestCase):
    def setUp(self):
        self.driver = NativeAgentDriver()
        self.state = NativeState("agent-1", "profile-1")

    def test_proposal_only_state_roundtrip_and_sequential_turns(self):
        decision = self.driver.advance(self.state, response())
        self.assertEqual(decision.kind, "tool_proposals")
        self.assertEqual(vars(self.driver), {})
        recovered = NativeState.recover(self.state.serialize())
        self.assertEqual(asdict(recovered), asdict(self.state))
        self.assertEqual(recovered.serialize(), self.state.serialize())
        with self.assertRaises(ValueError):
            self.driver.advance(recovered, response())
        with self.assertRaises(ValueError):
            self.driver.accept_results(recovered, ["different-id"])
        self.driver.accept_results(recovered, ["call-1"])
        result = self.driver.advance(recovered, InferenceResponse("done", finish_reason="stop", stream_complete=True))
        self.assertEqual(result.answer, "done")
        self.assertEqual(recovered.turns, 2)

    def test_entire_batch_rejects_malformed_duplicates_and_sensitive_json(self):
        for raw in ('{', '[]', 'null', '{"a":1,"a":2}', '{"a":NaN}'):
            state = NativeState("a", "p")
            good = response()
            bad = response(raw, "call-2")
            result = self.driver.advance(state, InferenceResponse(tool_calls=good.tool_calls + bad.tool_calls,
                finish_reason="tool_calls", stream_complete=True))
            self.assertEqual(result.kind, "malformed")
            self.assertEqual(state.pending, [])
        calls = response().tool_calls * 2
        self.assertEqual(self.driver.advance(self.state, InferenceResponse(tool_calls=calls,
            finish_reason="tool_calls", stream_complete=True)).kind, "malformed")
        secret = "NATIVE_SYNTHETIC_CREDENTIAL_1234"
        scrubber.register_secret(secret)
        state = NativeState("a", "p")
        outcome = self.driver.advance(state, response(json.dumps({"content": secret}, ensure_ascii=True)))
        self.assertEqual(outcome.kind, "malformed")
        self.assertNotIn(secret, state.serialize())

    def test_truncated_incomplete_failure_empty_and_cancel_are_distinct(self):
        cases = [(InferenceResponse("partial", finish_reason="length", stream_complete=True), "truncated"),
                 (InferenceResponse("partial", finish_reason="stop"), "incomplete"),
                 (InferenceResponse(error="disconnected"), "failed"),
                 (InferenceResponse(finish_reason="stop", stream_complete=True), "malformed")]
        for reply, expected in cases:
            self.assertEqual(self.driver.advance(NativeState("a", "p"), reply).kind, expected)
        self.state.cancellation_requested = True
        self.assertEqual(self.driver.advance(self.state, response()).kind, "cancelled")
        self.assertFalse(self.state.remote_cancel_confirmed)

    def test_profile_epoch_and_turn_budget(self):
        self.driver.advance(self.state, response())
        self.assertTrue(self.state.change_profile("new-profile"))
        self.assertEqual(self.state.pending, [])
        self.assertEqual(self.state.context_epoch, 1)
        self.assertFalse(self.state.change_profile("new-profile"))
        self.assertEqual(self.driver.advance(self.state, response(), max_turns=1).kind, "max_turns")

    def test_generic_budget_separates_inputs_and_never_changes_prompt(self):
        profile = SimpleNamespace(profile_id="generic", context_capacity=1000, reserved_completion=100)
        history = [{"role": "user", "content": "hi"}, {"role": "tool", "content": "result"}]
        before = json.dumps(history)
        budget = budget_context(profile, "system", [{"name": "tool"}], history, "selected")
        self.assertTrue(budget.fits)
        self.assertGreater(budget.tool_results, 0)
        self.assertGreater(budget.selected_context, 0)
        self.assertIn("estimate", budget.method)
        self.assertEqual(json.dumps(history), before)
        profile.context_capacity = 30
        self.assertFalse(budget_context(profile, "system", [], history).fits)

    def test_proposals_cannot_bypass_existing_broker_permissions(self):
        import tempfile
        from pathlib import Path
        from harness.tools.registry import ToolBroker, ToolRegistry
        with tempfile.TemporaryDirectory() as directory:
            registry = ToolRegistry(directory)
            broker = ToolBroker(registry)
            raw = '{"path":"a.txt","content":"approved"}'
            reply = response(raw)
            reply.tool_calls[0]["function"]["name"] = "write_file"
            proposal = self.driver.advance(self.state, reply).proposals[0]
            for resolver in (None, lambda *_: False):
                result = broker.execute(proposal.name, proposal.arguments, approval_callback=resolver)
                self.assertEqual(result["status"], "rejected")
                self.assertFalse((Path(directory) / "a.txt").exists())
            child = broker.child(["read_file"])
            self.assertEqual(child.execute(proposal.name, proposal.arguments)["status"], "rejected")
            with self.assertRaises(ValueError):
                child.child(["write_file"])
            recovered = NativeState.recover(self.state.serialize())
            self.assertEqual(recovered.pending[0]["call_id"], proposal.call_id)
            result = broker.execute(proposal.name, proposal.arguments, approval_callback=lambda *_: True)
            self.assertNotIn("error", result)
            self.driver.accept_results(recovered, [proposal.call_id])
            self.assertEqual((Path(directory) / "a.txt").read_text(), "approved")


if __name__ == "__main__":
    unittest.main()
