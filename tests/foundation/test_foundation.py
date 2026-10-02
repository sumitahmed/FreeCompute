"""Real SDK broker loop, crash recovery and negative adoption boundaries."""
import support  # Environment/network isolation precedes SDK import.
import asyncio
import contextlib
import io
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

from openhands.sdk import Agent, LLM
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.context.view import View
from openhands.sdk.event import MessageEvent
from openhands.sdk.llm import Message, TextContent
from harness.core.client import CancellationToken
from harness.security import scrubber
from harness.tools.registry import ToolRegistry, ToolDefinition
from harness.experiments.foundation.runtime import Actor, ExperimentStore, DurableToolBroker, InferenceBroker, identity
from harness.experiments.foundation.openhands_adapter import BrokeredLLM, DeniedWorkspace, ProjectionStore, conversation, send_message, run_conversation, reconcile_projection, BrokerExecutor


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert importlib.metadata.version("openhands-sdk") == "1.50.1"
        cls.server, cls.thread = support.server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        print(f"Foundation fixture blocked external attempts: {support.external_attempts}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-foundation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "workspace").mkdir()
        (self.root / "presentation").mkdir()
        (self.root / "workspace" / "read.txt").write_text("known fixture contents", encoding="utf-8")
        self.store = ExperimentStore(self.root / "runtime.sqlite")
        self.addCleanup(self.store.close)
        self.actor = Actor(identity(), identity(), frozenset({"read_file", "write_file", "fail"}))
        self.token = CancellationToken()
        self.registry = ToolRegistry(str(self.root / "workspace"))
        self.registry.register(ToolDefinition("fail", "fixture failure", {"properties": {}}, lambda: (_ for _ in ()).throw(RuntimeError("fixture tool failure")), requires_approval=False))
        self.authority = DurableToolBroker(self.store, self.registry, self.actor, self.token)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"
        self.broker = InferenceBroker(self.store, self.endpoint)
        self.server.requests = []
        self.server.retry_once = False
        self.server.proposal = None
        self.server.plan = None
        self.server.fragments = None
        self.server.release = None
        self.server.stream_gate = None
        self.server.stream_done = True
        self.server.answer = "fixture completed"
        self.server.thought = "fixture proposal"
        self.server.entered.clear()

    def run_tool(self, name, args, approval=None):
        self.server.proposal = name, args
        self.authority.approval = approval
        events = []
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation", callbacks=[events.append])
        self.addCleanup(conv.close)
        send_message(conv, "Run the fixture action")
        try:
            run_conversation(conv, self.authority)
        except Exception:
            if not self.token.is_cancelled:
                raise
        observations = [m for req in self.server.requests for m in req["messages"] if m["role"] == "tool"]
        if self.token.is_cancelled:
            rows = self.store.all("actions")
            self.assertTrue(rows)
            self.assertFalse(self.token.remote_cancel_confirmed)
            return rows[-1][1]["result"], events
        self.assertTrue(observations, "SDK must continue with the actual result")
        self.assertGreaterEqual(len(self.server.requests), 2)
        return json.loads("".join(c["text"] for c in observations[-1]["content"]).split("\n", 1)[-1]), events

    def test_approved_read_roundtrip(self):
        result, _ = self.run_tool("read_file", {"path": "read.txt"})
        self.assertIn("known fixture contents", str(result))
        self.assertEqual(self.store.all("actions")[0][1]["state"], "completed")

    def test_missing_approval_denies_write_roundtrip(self):
        result, _ = self.run_tool("write_file", {"path": "denied.txt", "content": "x"})
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.root / "workspace" / "cancelled.txt").exists())
        self.assertFalse((self.root / "workspace" / "denied.txt").exists())

    def test_approved_write_roundtrip(self):
        result, _ = self.run_tool("write_file", {"path": "approved.txt", "content": "x"}, lambda *_: True)
        self.assertNotIn("error", result)
        self.assertEqual((self.root / "workspace" / "approved.txt").read_text(), "x")

    def test_malformed_arguments_roundtrip(self):
        result, _ = self.run_tool("write_file", {"path": "malformed.txt", "content": 42}, lambda *_: True)
        self.assertIn("error", result)
        self.assertFalse((self.root / "workspace" / "malformed.txt").exists())

    def test_protected_path_roundtrip(self):
        result, _ = self.run_tool("write_file", {"path": ".env", "content": "x"}, lambda *_: True)
        self.assertIn("error", result)
        self.assertFalse((self.root / "workspace" / ".env").exists())

    def test_cancelled_approval_roundtrip(self):
        def approve(*_):
            self.token.cancel()
            return True
        result, _ = self.run_tool("write_file", {"path": "cancelled.txt", "content": "x"}, approve)
        # Cancellation also stops subsequent model generation; tested separately
        # if the loop raises before its next continuation.
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.root / "workspace" / "cancelled.txt").exists())

    def test_cancel_during_actual_approval_wait(self):
        entered, release = threading.Event(), threading.Event()
        def approval(*_):
            entered.set()
            release.wait(3)
            return True
        self.authority.approval = approval
        self.server.proposal = "write_file", {"path": "wait.txt", "content": "x"}
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        send_message(conv, "Approval wait fixture")
        errors = []
        def run():
            try:
                run_conversation(conv, self.authority)
            except Exception as exc:
                errors.append(type(exc).__name__)
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.store.all("actions")[0][1]["state"], "pending")
        self.token.cancel()
        self.assertFalse(self.token.local_stop_confirmed, "Request alone is not a stopped loop")
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertTrue(self.token.local_stop_confirmed)
        self.assertEqual(self.store.all("actions")[0][1]["state"], "denied")
        self.assertFalse((self.root / "workspace" / "wait.txt").exists())
        self.assertFalse(self.token.remote_cancel_confirmed)

    def test_tool_failure_roundtrip(self):
        result, _ = self.run_tool("fail", {})
        self.assertIn("fixture tool failure", result["error"])

    def test_retry_lineage_and_all_public_generation_entries(self):
        llm = BrokeredLLM.bound(self.broker, self.actor, self.token)
        messages = [Message(role="user", content=[TextContent(text="fixture")])]
        self.server.retry_once = True
        llm.generate(messages)
        llm.completion(messages)
        asyncio.run(llm.agenerate(messages))
        asyncio.run(llm.acompletion(messages))
        rows = [v for _, v in self.store.all("requests")]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]["parent_request"], rows[0]["request_id"])
        self.assertEqual(rows[1]["purpose"], "retry")
        for row in rows:
            self.assertEqual(row["agent_id"], self.actor.agent_id)
            self.assertGreaterEqual(row["finished"], row["started"])
        for fn in (llm.responses, lambda *a: asyncio.run(llm.aresponses(*a))):
            with self.assertRaises(RuntimeError):
                fn(messages)

    def test_real_condenser_summary_routes_broker(self):
        llm = BrokeredLLM.bound(self.broker, self.actor, self.token, "condensation_summary")
        events = [MessageEvent(source="user" if i % 2 == 0 else "agent", llm_message=Message(role="user" if i % 2 == 0 else "assistant", content=[TextContent(text=f"fixture {i}")])) for i in range(12)]
        result = LLMSummarizingCondenser(llm=llm, max_size=8, keep_first=1).get_condensation(View(events=events), agent_llm=llm)
        self.assertEqual(result.summary, "fixture completed")
        self.assertEqual(self.store.all("requests")[0][1]["purpose"], "condensation_summary")

    def test_model_mutation_and_unbound_restore_fail_closed(self):
        llm = BrokeredLLM.bound(self.broker, self.actor, self.token)
        with self.assertRaises(RuntimeError):
            llm.model_copy(update={"base_url": "http://127.0.0.1:2"}).generate([])
        restored = BrokeredLLM.model_validate_json(llm.model_dump_json())
        with self.assertRaises(RuntimeError):
            restored.generate([])
        self.assertEqual(self.server.requests, [])

    def test_denied_workspace_and_sdk_direct_paths(self):
        workspace = DeniedWorkspace(working_dir=str(self.root / "presentation"))
        for fn in (workspace.execute_command, workspace.file_upload, workspace.file_download, workspace.git_changes, workspace.git_diff):
            with self.assertRaises(PermissionError):
                fn("fixture")
        with self.assertRaises(PermissionError):
            ProjectionStore(self.store, self.actor.agent_id).get_absolute_path("raw.log")

    def test_missing_action_projection_cannot_generate_fresh_replay(self):
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        self.store.put("actions", "missing-projection", {"task_id": self.actor.task_id, "agent_id": self.actor.agent_id,
                       "action_id": str(uuid.uuid4()), "state": "outcome_unknown"})
        with self.assertRaises(RuntimeError):
            reconcile_projection(conv, self.authority)
        self.assertEqual(self.server.requests, [])

    def test_ambiguous_sdk_action_identity_has_no_execution_authority(self):
        from openhands.sdk.event import ActionEvent
        from openhands.sdk.security.confirmation_policy import AlwaysConfirm
        self.server.proposal = "read_file", {"path": "read.txt"}
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        conv.set_confirmation_policy(AlwaysConfirm())
        send_message(conv, "Ambiguous identity fixture")
        conv.run()
        event = next(e for e in conv.state.events if isinstance(e, ActionEvent))
        conv.state.append_event(event.model_copy(update={"id": str(uuid.uuid4())}))
        result = BrokerExecutor(self.authority)(event.action, conv)
        self.assertTrue(result.is_error)
        self.assertIn("ambiguous", result.text)
        self.assertEqual(self.store.all("actions"), [])

    def test_registered_secrets_before_sdk_sinks(self):
        secret = "fixture credential " + uuid.uuid4().hex
        scrubber.register_secret(secret)
        (self.root / "workspace" / "read.txt").write_text(secret)
        self.server.answer = "answer " + secret
        self.server.thought = "thought " + secret
        result, events = self.run_tool("read_file", {"path": "read.txt"})
        self.assertNotIn(secret, str(result))
        self.assertNotIn(secret, "".join(e.model_dump_json() + str(e.visualize) for e in events))
        self.assertNotIn(secret, json.dumps(self.store.all("sdk")))
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        send_message(conv, "input " + secret)
        self.assertNotIn(secret, json.dumps(self.store.all("sdk")))
        self.server.proposal = "write_file", {"path": "secret.txt", "content": secret}
        self.authority.approval = lambda *_: True
        conv.run()
        self.assertFalse((self.root / "workspace" / "secret.txt").exists())
        self.assertNotIn(secret, json.dumps(self.store.all("actions")))

    def test_fragmented_stream_buffered_before_sdk_callback(self):
        secret = "fragmented-" + uuid.uuid4().hex
        scrubber.register_secret(secret)
        self.server.fragments = ["start " + secret[:8], secret[8:17], secret[17:] + " end"]
        callback = []
        response = BrokeredLLM.bound(self.broker, self.actor, self.token).generate([], on_token=callback.append)
        self.assertNotIn(secret, str(callback))
        self.assertNotIn(secret, response.model_dump_json())
        self.assertIn("REDACTED", str(callback))

    def test_json_escaped_credentials_are_scrubbed_before_sdk_argument_parsing(self):
        secret = 'quoted"credential\\' + uuid.uuid4().hex
        scrubber.register_secret(secret)
        result, events = self.run_tool("write_file", {"path": "quoted.txt", "content": secret}, lambda *_: True)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.root / "workspace" / "quoted.txt").exists())
        encoded_secret = json.dumps(secret)[1:-1]
        for collection in (self.store.all("sdk"), self.store.all("actions")):
            self.assertNotIn(secret, str(collection))
            self.assertNotIn(encoded_secret, str(collection))
        self.assertNotIn(secret, "".join(str(e.visualize) for e in events))
        projection = ProjectionStore(self.store, "quoted-probe")
        projection.write("event.json", json.dumps({"value": secret}))
        self.assertEqual(json.loads(projection.read("event.json"))["value"], "[REDACTED_SECRET]")

    def test_malformed_model_json_never_reaches_sdk_tool_execution(self):
        self.server.plan = lambda _: {"role": "assistant", "content": "malformed fixture", "tool_calls": [{"id": "malformed", "type": "function", "function": {"name": "fc_action", "arguments": "{"}}]}
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        send_message(conv, "Malformed model response")
        with self.assertRaises(Exception):
            conv.run()
        self.assertEqual(self.store.all("actions"), [])
        self.assertEqual(self.store.all("requests")[-1][1]["status"], "failed")

    def test_streamed_tool_calls_fail_closed_before_callbacks(self):
        self.server.fragments = [{"tool_calls": [{"index": 0, "function": {"arguments": "{"}}]}]
        callbacks = []
        with self.assertRaises(RuntimeError):
            BrokeredLLM.bound(self.broker, self.actor, self.token).generate([], on_token=callbacks.append)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.store.all("actions"), [])

    def test_incomplete_stream_does_not_emit_sdk_success(self):
        self.server.fragments = ["partial answer"]
        self.server.stream_done = False
        callbacks = []
        with self.assertRaises(RuntimeError):
            BrokeredLLM.bound(self.broker, self.actor, self.token).generate([], on_token=callbacks.append)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.store.all("requests")[-1][1]["status"], "failed")

    def test_cancel_model_stream_reports_remote_unknown(self):
        self.server.fragments = ["partial", " rest"]
        self.server.stream_gate = threading.Event()
        errors = []
        def run():
            try:
                BrokeredLLM.bound(self.broker, self.actor, self.token).generate([])
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(self.server.entered.wait(2))
        self.token.cancel()
        self.server.stream_gate.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertTrue(self.token.local_stop_confirmed)
        self.assertFalse(self.token.remote_cancel_confirmed)
        self.assertEqual(self.store.all("requests")[-1][1]["status"], "outcome_unknown")

    def test_real_process_crashes_and_sdk_restart_no_duplicate_effect(self):
        self.server.proposal = "write_file", {"path": "effect.txt", "content": "one effect"}
        for point in ("before_approval", "after_approval", "during_execution", "after_result"):
            with self.subTest(point=point), tempfile.TemporaryDirectory(prefix="fc-crash-") as directory:
                root = Path(directory)
                (root / "workspace").mkdir()
                (root / "presentation").mkdir()
                command = [sys.executable, str(Path(__file__).with_name("crash_worker.py")), directory, self.endpoint, point]
                crashed = subprocess.run(command + ["crash"], capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(crashed.returncode, 73, crashed.stderr)
                resumed = subprocess.run(command + ["resume"], capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                self.assertEqual((root / "effects.txt").read_text().splitlines(), ["effect"])
                recovered = ExperimentStore(root / "runtime.sqlite")
                try:
                    row = recovered.all("actions")[0][1]
                    self.assertEqual(row["state"], "outcome_unknown" if point == "during_execution" else "completed")
                    self.assertEqual(len((root / "approvals.txt").read_text().splitlines()), 2 if point == "after_approval" else 1)
                    self.assertEqual(recovered.get("tasks", "task")["state"], "needs_reconciliation" if point == "during_execution" else "finished")
                    self.assertTrue(any(r["purpose"] == "recovery" for _, r in recovered.all("requests")))
                finally:
                    recovered.close()

    def test_tool_process_cancellation_keeps_effect_outcome_unknown(self):
        actor = Actor(self.actor.task_id, self.actor.agent_id, frozenset({"run_command"}))
        authority = DurableToolBroker(self.store, self.registry, actor, self.token, lambda *_: True)
        results = []
        command = f'"{sys.executable}" -c "import time; time.sleep(1)"'
        thread = threading.Thread(target=lambda: results.append(authority.execute("process", "run_command", {"command": command})))
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(r["state"] == "executing" for _, r in self.store.all("actions")):
            time.sleep(0.01)
        # Allow the owned subprocess to start after the approved transition.
        time.sleep(0.15)
        self.token.cancel()
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]["owned_process_exit_confirmed"])
        self.assertEqual(results[0]["descendant_cancellation"], "unknown")
        self.assertEqual(results[0]["status"], "outcome_unknown")
        self.assertFalse(self.token.remote_cancel_confirmed)

    def test_exception_secret_sanitized_before_sdk_logs_and_debug(self):
        secret = "error-credential-" + uuid.uuid4().hex
        scrubber.register_secret(secret)
        self.registry.tools["fail"].handler = lambda: (_ for _ in ()).throw(RuntimeError(secret))
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        loggers = [value for name, value in logging.Logger.manager.loggerDict.items()
                   if name.startswith("openhands.") and isinstance(value, logging.Logger)]
        levels = {logger: logger.level for logger in loggers}
        for logger in loggers:
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                result, events = self.run_tool("fail", {})
            self.assertIn("Created new conversation", captured.getvalue(), "SDK log capture must actually observe framework logs")
            self.assertNotIn(secret, captured.getvalue())
            self.assertNotIn(secret, json.dumps(self.store.all("sdk")))
            self.assertNotIn(secret, "".join(str(e.visualize) for e in events))
            self.assertIn("REDACTED", result["error"])
        finally:
            for logger in loggers:
                logger.removeHandler(handler)
                logger.setLevel(levels[logger])

    def test_public_sdk_model_switch_can_bypass_broker_negative_probe(self):
        conv = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(conv.close)
        plain = LLM(model="openai/fixture", base_url=self.endpoint.removesuffix("/chat/completions"),
                    api_key="synthetic-not-live", usage_id="unbrokered-probe", stream=False,
                    timeout=3, num_retries=1, max_input_tokens=32768, max_output_tokens=256)
        conv.switch_llm(plain)
        send_message(conv, "Negative bypass probe")
        conv.run()
        self.assertTrue(self.server.requests)
        self.assertEqual(self.store.all("requests"), [], "A plain public model switch has no broker authority binding")

    def test_native_child_narrow_grants_and_one_slot_but_workspace_boundary_lost(self):
        from openhands.sdk.subagent import register_agent
        from openhands.sdk.subagent import AgentDefinition
        from openhands.sdk.tool import Tool, register_tool
        from openhands.tools.delegate import DelegateExecutor, DelegateAction
        from harness.experiments.foundation.openhands_adapter import BrokerTool, BrokerAction, BrokerObservation, BrokerExecutor
        child = self.actor.child({"read_file"}, parent_request="parent-fixture-request")
        with self.assertRaises(ValueError):
            child.child({"write_file"})
        child_authority = DurableToolBroker(self.store, self.registry, child, self.token)
        self.assertEqual(child_authority.execute("deny", "write_file", {"path": "denied.txt", "content": "x"})["status"], "rejected")
        parent = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(parent.close)
        send_message(parent, "Initialize parent broker")
        parent.run()
        parent_request = self.store.all("requests")[-1][1]["request_id"]
        child = Actor(child.task_id, child.agent_id, child.tools, parent_request)
        child_authority = DurableToolBroker(self.store, self.registry, child, self.token)
        def factory(_parent_copy):
            tool = BrokerTool(description="Narrow research capability", action_type=BrokerAction,
                              observation_type=BrokerObservation, executor=BrokerExecutor(child_authority))
            register_tool("fc_action", tool)
            return Agent(llm=BrokeredLLM.bound(self.broker, child, self.token, "child_research"),
                         tools=[Tool(name="fc_action")], include_default_tools=[])
        name = "fixture-research-" + uuid.uuid4().hex
        register_agent(name, factory, AgentDefinition(name=name, description="Fixture research only", max_iteration_per_run=3))
        delegate = DelegateExecutor(max_children=1)
        self.addCleanup(delegate.close)
        spawned = delegate(DelegateAction(command="spawn", ids=["research"], agent_types=[name]), parent)
        self.assertFalse(spawned.is_error, spawned.text)
        # Inspection only, never an integration fix through private SDK state.
        native_child = delegate._sub_agents["research"]
        self.assertNotIsInstance(native_child.workspace, DeniedWorkspace)
        self.assertNotIsInstance(native_child.state._fs, ProjectionStore)
        self.server.proposal = "read_file", {"path": "read.txt"}
        result = delegate(DelegateAction(command="delegate", tasks={"research": "Read fixture research file"}), parent)
        self.assertFalse(result.is_error, result.text)
        self.assertIn("fixture completed", result.text)
        rows = [r for _, r in self.store.all("requests") if r["agent_id"] == child.agent_id]
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(r["parent_request"] == parent_request for r in rows))
        self.assertTrue(any(r["state"] == "completed" and r["agent_id"] == child.agent_id for _, r in self.store.all("actions")))
        # Native result is unbounded; characterize, do not hide with a mock.
        self.server.proposal = None
        self.server.answer = "x" * 10000
        result = delegate(DelegateAction(command="delegate", tasks={"research": "Long fixture result"}), parent)
        self.assertGreater(len(result.text), 10000)
        # A core-bound token propagates into child inference. Native Executor
        # interrupt itself is inherited no-op; no remote acknowledgement.
        self.server.release = threading.Event()
        self.server.entered.clear()
        results = []
        thread = threading.Thread(target=lambda: results.append(delegate(DelegateAction(command="delegate", tasks={"research": "Cancellation fixture"}), parent)))
        thread.start()
        self.assertTrue(self.server.entered.wait(2))
        self.token.cancel()
        self.server.release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive(), "One-slot delegation deadlocked")
        self.assertFalse(self.token.remote_cancel_confirmed)
        self.assertTrue(any(r["status"] == "outcome_unknown" and r["agent_id"] == child.agent_id for _, r in self.store.all("requests")))

    def test_native_delegate_logs_raw_registered_task_before_inference_negative_probe(self):
        from openhands.sdk.subagent import register_agent
        from openhands.sdk.subagent import AgentDefinition
        from openhands.tools.delegate import DelegateExecutor, DelegateAction
        secret = "native-task-credential-" + uuid.uuid4().hex
        scrubber.register_secret(secret)
        parent = conversation(self.store, self.actor, self.broker, self.authority, self.root / "presentation")
        self.addCleanup(parent.close)
        child = self.actor.child(set())
        name = "fixture-empty-" + uuid.uuid4().hex
        register_agent(name, lambda _: Agent(llm=BrokeredLLM.bound(self.broker, child, self.token, "child"), tools=[], include_default_tools=[]),
                       AgentDefinition(name=name, description="Negative sink probe", max_iteration_per_run=1))
        delegate = DelegateExecutor(max_children=1)
        self.addCleanup(delegate.close)
        self.assertFalse(delegate(DelegateAction(command="spawn", ids=["child"], agent_types=[name]), parent).is_error)
        captured = io.StringIO()
        logger = logging.getLogger("openhands.tools.delegate.impl")
        handler = logging.StreamHandler(captured)
        logger.addHandler(handler)
        try:
            delegate(DelegateAction(command="delegate", tasks={"child": secret}), parent)
        finally:
            logger.removeHandler(handler)
        self.assertIn(secret, captured.getvalue(), "Native executor logs raw task before brokered inference")
        native_child = delegate._sub_agents["child"]
        self.assertTrue(any(secret in e.model_dump_json() for e in native_child.state.events))
        self.assertNotIn(secret, json.dumps(self.server.requests), "Inference input was sanitized even though earlier native sinks were not")

    def test_model_driven_parent_native_child_roundtrip_one_slot(self):
        from openhands.sdk.subagent import register_agent, AgentDefinition
        from openhands.sdk.tool import Tool, register_tool
        from openhands.tools.delegate import DelegateExecutor, DelegateAction
        from harness.experiments.foundation.openhands_adapter import BrokerTool, BrokerAction, BrokerObservation, BrokerExecutor
        actor = Actor(self.actor.task_id, self.actor.agent_id, frozenset({"delegate", "read_file"}))
        child = actor.child({"read_file"})
        child_authority = DurableToolBroker(self.store, self.registry, child, self.token)
        name = "fixture-driven-" + uuid.uuid4().hex
        def factory(_):
            nonlocal child, child_authority
            parent_request = self.store.all("requests")[-1][1]["request_id"]
            child = Actor(child.task_id, child.agent_id, child.tools, parent_request)
            child_authority = DurableToolBroker(self.store, self.registry, child, self.token)
            tool = BrokerTool(description="Read-only child", action_type=BrokerAction, observation_type=BrokerObservation, executor=BrokerExecutor(child_authority))
            register_tool("fc_action", tool)
            return Agent(llm=BrokeredLLM.bound(self.broker, child, self.token, "child_research"), tools=[Tool(name="fc_action")], include_default_tools=[])
        register_agent(name, factory, AgentDefinition(name=name, description="Model driven child fixture", max_iteration_per_run=3))
        delegate = DelegateExecutor(max_children=1)
        self.addCleanup(delegate.close)
        parent = None
        def handle(**args):
            result = delegate(DelegateAction(**args), parent)
            # Boundary adaptation can bound the result at core entry; native
            # executor itself remains unbounded and loses workspace/store.
            return {"result": scrubber.scrub(result.text)[:2048], "is_error": result.is_error}
        self.registry.register(ToolDefinition("delegate", "Native probe", {"properties": {"command": {"type": "string"}, "ids": {"type": "array"}, "agent_types": {"type": "array"}, "tasks": {"type": "object"}}, "required": ["command"]}, handle, requires_approval=True))
        authority = DurableToolBroker(self.store, self.registry, actor, self.token, lambda *_: True)
        parent = conversation(self.store, actor, self.broker, authority, self.root / "presentation")
        self.addCleanup(parent.close)
        def plan(payload):
            text = json.dumps([m for m in payload["messages"] if m["role"] == "user"])
            count = sum(m["role"] == "tool" for m in payload["messages"])
            if "Parent native delegation fixture" in text:
                if count == 0:
                    tool, args = "delegate", {"command": "spawn", "ids": ["research"], "agent_types": [name]}
                elif count == 1:
                    tool, args = "delegate", {"command": "delegate", "tasks": {"research": "Read fixture research file"}}
                else:
                    return {"role": "assistant", "content": "parent completed"}
            elif count == 0:
                tool, args = "read_file", {"path": "read.txt"}
            else:
                return {"role": "assistant", "content": "bounded research result"}
            return {"role": "assistant", "content": "fixture proposal", "tool_calls": [{"id": "call-" + uuid.uuid4().hex, "type": "function", "function": {"name": "fc_action", "arguments": json.dumps({"tool": tool, "arguments": args})}}]}
        self.server.plan = plan
        send_message(parent, "Parent native delegation fixture")
        errors = []
        def run():
            try:
                parent.run()
            except Exception as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(8)
        self.assertFalse(thread.is_alive(), "Model-driven native parent/child deadlocked with one slot")
        self.assertEqual(errors, [])
        rows = [r for _, r in self.store.all("requests")]
        self.assertEqual(sum(r["agent_id"] == actor.agent_id for r in rows), 3)
        self.assertEqual(sum(r["agent_id"] == child.agent_id for r in rows), 2)
        self.assertTrue(all(r["parent_request"] in {p["request_id"] for p in rows if p["agent_id"] == actor.agent_id} for r in rows if r["agent_id"] == child.agent_id))
        effects = [r for _, r in self.store.all("actions")]
        self.assertEqual(sum(r["name"] == "delegate" and r["state"] == "completed" for r in effects), 2)
        self.assertEqual(sum(r["name"] == "read_file" and r["agent_id"] == child.agent_id and r["state"] == "completed" for r in effects), 1)
        self.assertTrue(all(len(str(r["result"])) <= 2200 for r in effects if r["name"] == "delegate"))
        self.assertNotIsInstance(delegate._sub_agents["research"].workspace, DeniedWorkspace)


if __name__ == "__main__":
    unittest.main()
