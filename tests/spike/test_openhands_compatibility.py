"""Pinned SDK characterization, not an adoption test or production integration.

Run in the optional Python 3.12+ spike venv. Network is restricted to the fake
loopback inference server before SDK import; no credentials or GPU are used.
"""
import contextlib
import http.server
import importlib.metadata
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
for key in tuple(os.environ):
    if key.startswith(("LMNR_", "OTEL_", "OPENAI_", "ANTHROPIC_")):
        os.environ.pop(key)

_sdk_home = tempfile.TemporaryDirectory(prefix="freecompute-sdk-home-")
os.environ["OH_PERSISTENCE_DIR"] = _sdk_home.name
_external_attempts = []
_connect = socket.socket.connect


def loopback_connect(connection, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
        _external_attempts.append(address[0])
        raise RuntimeError("Spike forbids external network")
    return _connect(connection, address)


socket.socket.connect = loopback_connect

from openhands.sdk import Agent, LLM
from openhands.sdk.conversation import LocalConversation as Conversation
from openhands.sdk.io import InMemoryFileStore
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.security.confirmation_policy import AlwaysConfirm, NeverConfirm
from openhands.sdk.tool.client_tool import ClientToolSpec
from openhands.sdk.observability.laminar import should_enable_observability
from harness.core.agent_driver import DriverState, ProposalDriver
from harness.security import scrubber
from harness.tools.registry import ToolRegistry, ToolBroker


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        if self.server.retry_once:
            self.server.retry_once = False
            data = {"error": {"message": "deterministic retry", "type": "server_error"}}
            status = 500
        else:
            status = 200
            message = self.server.message
            if self.server.sanitize:
                message = scrubber.structured(message)
            data = {"id": "fixture-" + uuid.uuid4().hex, "object": "chat.completion", "created": 1,
                    "model": "fixture", "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        if self.server.delay:
            time.sleep(self.server.delay)
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)


class OpenHandsCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert importlib.metadata.version("openhands-sdk") == "1.50.1"
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        print(f"Spike external connection attempts blocked: {len(_external_attempts)} (including tokenizer metadata download)")
        socket.socket.connect = _connect
        _sdk_home.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="freecompute-sdk-spike-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server.requests = []
        self.server.retry_once = False
        self.server.sanitize = True
        self.server.delay = 0
        self.server.message = {"role": "assistant", "content": "fixture answer"}
        self.callbacks = []
        self.llm = LLM(model="openai/fixture", base_url=f"http://127.0.0.1:{self.server.server_port}/v1",
                       api_key="fixture-auth-not-live", usage_id="freecompute-spike", stream=False,
                       num_retries=2, retry_min_wait=0, retry_max_wait=0, retry_multiplier=0,
                       timeout=5, max_input_tokens=32768, max_output_tokens=256, log_completions=False)

    def conversation(self, **kwargs):
        agent = Agent(llm=self.llm, tools=[], include_default_tools=[])
        conversation = Conversation(agent=agent, workspace=self.root, visualizer=None,
                                    callbacks=[self.callbacks.append], max_iteration_per_run=1, **kwargs)
        self.addCleanup(conversation.close)
        return conversation

    def test_01_normal_and_retry_requests_reach_controlled_gateway(self):
        self.server.retry_once = True
        response = self.llm.completion(messages=[Message(role="user", content=[TextContent(text="fixture")])])
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(response.message.content[0].text, "fixture answer")
        # This does not enforce which LLM profile a future condenser/child chooses.

    def test_02_default_dangerous_tools_can_be_omitted(self):
        conversation = self.conversation()
        conversation.send_message("fixture")
        conversation.run()
        names = {t["function"]["name"] for request in self.server.requests for t in request.get("tools", [])}
        self.assertFalse(names & {"terminal", "browser", "file_editor", "delegate", "write_file"})

    def test_03_sdk_confirmation_default_and_core_missing_approval(self):
        conversation = self.conversation()
        self.assertIsInstance(conversation.state.confirmation_policy, NeverConfirm)
        conversation.set_confirmation_policy(AlwaysConfirm())
        broker = ToolBroker(ToolRegistry(str(self.root)))
        result = broker.execute("write_file", {"path": "denied.txt", "content": "denied"})
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.root / "denied.txt").exists())

    def test_04_external_observability_disabled_and_no_external_connects(self):
        self.assertFalse(should_enable_observability())
        conversation = self.conversation()
        conversation.send_message("fixture")
        conversation.run()
        self.assertEqual(_external_attempts, [])

    def test_05_callback_redaction_is_after_default_persistence(self):
        # Synthetic sentinel intentionally probes an unsafe default; never a live key.
        sentinel = "SYNTHETIC_SPIKE_SECRET_ABCDE"
        scrubber.register_secret(sentinel)
        store = InMemoryFileStore()
        persisted_before_callback = []
        def callback(event):
            persisted_before_callback.append(any(sentinel in store.read(path) for path in store.files))
            scrubber.scrub(str(event))
        agent = Agent(llm=self.llm, tools=[], include_default_tools=[])
        conversation = Conversation(agent=agent, workspace=self.root, visualizer=None,
                                    file_store=store, callbacks=[callback])
        self.addCleanup(conversation.close)
        conversation.send_message(sentinel)
        self.assertTrue(any(persisted_before_callback))
        # A safe adapter must sanitize BEFORE calling SDK APIs, not in callbacks.

    def test_06_in_memory_store_avoids_competing_disk_ledger(self):
        store = InMemoryFileStore()
        conversation = self.conversation(file_store=store)
        conversation.send_message(scrubber.scrub("fixture"))
        conversation.run()
        self.assertTrue(store.files)
        self.assertFalse(list(self.root.rglob("base_state.json")))
        # Public injection exists; comprehensive core-owned checkpoint mapping unproven.

    def test_07_pending_client_action_has_stable_serializable_ids(self):
        self.server.message = {"role": "assistant", "content": None,
            "tool_calls": [{"id": "stable-sdk-call", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path":"pending.txt","content":"fixture"}'}}]}
        spec = ClientToolSpec(name="write_file", description="Proposal only", parameters={
            "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]})
        conversation = self.conversation(client_tools=[spec], file_store=InMemoryFileStore())
        conversation.set_confirmation_policy(AlwaysConfirm())
        conversation.send_message("propose a file")
        conversation.run()
        from openhands.sdk.event import ActionEvent
        actions = [e for e in self.callbacks if isinstance(e, ActionEvent)]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].tool_call_id, "stable-sdk-call")
        encoded = actions[0].model_dump_json()
        self.assertEqual(ActionEvent.model_validate_json(encoded).id, actions[0].id)
        self.assertFalse((self.root / "pending.txt").exists())
        conversation.reject_pending_actions("FreeCompute denied: no approval callback")
        self.assertFalse((self.root / "pending.txt").exists())

    def test_08_pause_does_not_acknowledge_remote_cancellation(self):
        conversation = self.conversation()
        conversation.pause()
        self.assertEqual(conversation.state.execution_status.value, "paused")
        state = DriverState(cancellation_requested=True, local_stop_confirmed=True)
        self.assertFalse(state.remote_cancel_confirmed)
        # pause() is a local state transition, not a remote engine acknowledgement.

    def test_09_malformed_fragments_never_execute_in_core_adapter(self):
        state = DriverState()
        with self.assertRaises(ValueError):
            ProposalDriver().propose(state, {"finish_reason": "tool_calls", "tool_calls": [
                {"id": "malformed", "function": {"name": "write_file", "arguments": "{"}}]})
        self.assertEqual(state.pending, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_10_child_scope_narrows_broker_but_sdk_profile_is_independent(self):
        parent = ToolBroker(ToolRegistry(str(self.root)))
        child = parent.child(["read_file"])
        self.assertEqual(child.execute("write_file", {"path": "denied", "content": "x"})["status"], "rejected")
        with self.assertRaises(ValueError):
            child.child(["run_command"])
        # SDK LLM configuration is independently replaceable, with no broker binding.
        changed = self.llm.model_copy(update={"base_url": "http://127.0.0.1:1/v1"})
        self.assertNotEqual(changed.base_url, self.llm.base_url)

    def test_11_one_slot_sequential_parent_child_fixture_releases(self):
        # Bounded fixture only: native SDK delegation/scheduler is not adopted.
        slot = threading.BoundedSemaphore(1)
        for usage in ("parent", "child"):
            self.assertTrue(slot.acquire(timeout=1))
            try:
                child_llm = self.llm.model_copy(update={"usage_id": usage})
                child_llm.completion(messages=[Message(role="user", content=[TextContent(text=usage)])])
            finally:
                slot.release()
        self.assertEqual(len(self.server.requests), 2)

    def test_12_profile_invalidation_is_explicit_in_core_not_sdk_enforced(self):
        state = DriverState(profile_id="fixture-32768")
        self.assertTrue(state.change_profile("fixture-65536"))
        self.assertEqual(state.context_epoch, 1)
        changed = self.llm.model_copy(update={"max_input_tokens": 65536})
        self.assertEqual(changed.max_input_tokens, 65536)
        self.assertEqual(self.llm.max_input_tokens, 32768)

    def test_13_real_condenser_uses_controlled_gateway(self):
        from openhands.sdk.context.condenser import LLMSummarizingCondenser
        from openhands.sdk.context.view import View
        from openhands.sdk.event import MessageEvent
        events = [MessageEvent(source="user" if i % 2 == 0 else "agent",
                  llm_message=Message(role="user" if i % 2 == 0 else "assistant",
                                      content=[TextContent(text=f"fixture message {i}")])) for i in range(12)]
        condenser = LLMSummarizingCondenser(llm=self.llm, max_size=8, keep_first=1)
        result = condenser.get_condensation(View(events=events), agent_llm=self.llm)
        self.assertTrue(result.forgotten_event_ids)
        self.assertEqual(result.summary, "fixture answer")
        self.assertEqual(len(self.server.requests), 1)

    def test_14_pre_sdk_gateway_redaction_reaches_callbacks_and_store_clean(self):
        sentinel = "SYNTHETIC_GATEWAY_SECRET_ABCDE"
        scrubber.register_secret(sentinel)
        self.server.message = {"role": "assistant", "content": sentinel}
        store = InMemoryFileStore()
        conversation = self.conversation(file_store=store)
        conversation.send_message(scrubber.scrub(sentinel))
        conversation.run()
        self.assertNotIn(sentinel, "".join(store.read(path) for path in store.files))
        self.assertNotIn(sentinel, "".join(event.model_dump_json() for event in self.callbacks))
        self.assertTrue(self.server.requests)

    def test_15_async_interrupt_stops_local_task_without_remote_ack(self):
        import asyncio
        self.server.delay = 1
        conversation = self.conversation()
        conversation.send_message("fixture cancellation")
        async def interrupt_run():
            task = asyncio.create_task(conversation.arun())
            deadline = time.monotonic() + 4
            while not self.server.requests and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            self.assertTrue(self.server.requests)
            conversation.interrupt()
            await asyncio.wait_for(task, timeout=3)
        asyncio.run(interrupt_run())
        self.assertEqual(conversation.state.execution_status.value, "paused")
        from openhands.sdk.event import InterruptEvent
        self.assertTrue(any(isinstance(event, InterruptEvent) for event in self.callbacks))
        # The fake server still completes its request independently; no remote ack.


if __name__ == "__main__":
    unittest.main()
