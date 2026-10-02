import json
import unittest
from harness.core.agent_driver import DriverState, ProposalDriver


class AgentDriverContractTests(unittest.TestCase):
    def response(self, arguments='{"path":"a.txt","content":"hello"}'):
        return {"finish_reason": "tool_calls", "tool_calls": [{"id": "stable-call-1", "function": {"name": "write_file", "arguments": arguments}}]}

    def test_proposal_only_and_stable_pending_recovery(self):
        state = DriverState()
        driver = ProposalDriver()
        proposals = driver.propose(state, self.response())
        recovered = DriverState.recover(state.serialize())
        self.assertEqual(recovered.pending, proposals)
        self.assertEqual(recovered.run_id, state.run_id)
        self.assertEqual(vars(driver), {})

    def test_malformed_fragments_and_duplicate_ids_are_atomic(self):
        state = DriverState()
        for raw in ("{", "[]", "null"):
            with self.assertRaises((ValueError, TypeError)):
                ProposalDriver().propose(state, self.response(raw))
            self.assertEqual(state.pending, [])
        response = self.response()
        response["tool_calls"] *= 2
        with self.assertRaises(ValueError):
            ProposalDriver().propose(state, response)
        self.assertEqual(state.pending, [])

    def test_profile_change_invalidates_pending_and_context_epoch(self):
        state = DriverState()
        ProposalDriver().propose(state, self.response())
        self.assertTrue(state.change_profile("different-model-context"))
        self.assertEqual(state.pending, [])
        self.assertEqual(state.context_epoch, 1)
        self.assertFalse(state.change_profile("different-model-context"))

    def test_cancel_does_not_propose_or_invent_remote_ack(self):
        state = DriverState(cancellation_requested=True)
        self.assertEqual(ProposalDriver().propose(state, self.response()), [])
        self.assertFalse(state.remote_cancel_confirmed)
