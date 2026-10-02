"""Public SDK adapter for pinned 1.50.1; optional, never imported by the CLI.

Explicitly provision every LLM/tool. Plain SDK profiles, native Delegate, ACP,
hooks, plugins and SDK secret registries are outside this bounded envelope.
"""
import asyncio
from contextlib import contextmanager
import json
import uuid
from typing import ClassVar

from litellm.types.utils import ModelResponse
from pydantic import PrivateAttr
from openhands.sdk import Agent, LLM
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.conversation.state import ConversationState
from openhands.sdk.event import ActionEvent
from openhands.sdk.io import FileStore
from openhands.sdk.llm import LLMResponse, Message, MessageToolCall, TextContent
from openhands.sdk.llm.utils.metrics import MetricsSnapshot
from openhands.sdk.tool import Tool, ToolDefinition, ToolExecutor, register_tool
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.workspace import LocalWorkspace

from harness.security import scrubber


class ProjectionStore(FileStore):
    """SDK snapshots in the core DB, separate from authoritative actions."""
    def __init__(self, store, prefix):
        self.store, self.prefix = store, prefix + "/"

    def write(self, path, contents):
        if isinstance(contents, bytes):
            contents = contents.decode("utf-8")
        try:
            contents = json.dumps(scrubber.structured(json.loads(contents)), sort_keys=True)
        except json.JSONDecodeError:
            contents = scrubber.scrub(contents)
        self.store.put("sdk", self.prefix + path, contents)

    def read(self, path):
        value = self.store.get("sdk", self.prefix + path)
        if value is None:
            raise FileNotFoundError(path)
        return value

    def list(self, path):
        path = path.rstrip("/") + "/" if path else ""
        prefix = self.prefix + path
        return sorted({path + key[len(prefix):].split("/")[0] for key, _ in self.store.all("sdk") if key.startswith(prefix)})

    def delete(self, path):
        self.store.delete("sdk", self.prefix + path)

    def exists(self, path):
        return self.store.get("sdk", self.prefix + path) is not None

    def get_absolute_path(self, path):
        raise PermissionError("SDK direct persistence paths are disabled")

    @contextmanager
    def lock(self, path, timeout=30):
        with self.store.lock:
            yield


class DeniedWorkspace(LocalWorkspace):
    """Empty presentation directory; no workspace execution capabilities."""
    def execute_command(self, *args, **kwargs):
        raise PermissionError("Workspace command authority belongs to FreeCompute")

    def file_upload(self, *args, **kwargs):
        raise PermissionError("Workspace file authority belongs to FreeCompute")

    file_download = file_upload
    git_changes = file_upload
    git_diff = file_upload

    def __exit__(self, *args):
        pass  # No automation callback POST.


class BrokeredLLM(LLM):
    _broker = PrivateAttr(default=None)
    _actor = PrivateAttr(default=None)
    _cancellation = PrivateAttr(default=None)
    _purpose = PrivateAttr(default="generation")

    @classmethod
    def bound(cls, broker, actor, cancellation, purpose="generation"):
        llm = cls(model="openai/fixture", base_url="http://127.0.0.1:1/disabled",
                  api_key=None, usage_id=actor.agent_id, stream=False,
                  max_input_tokens=32768, max_output_tokens=256, log_completions=False)
        llm._broker, llm._actor, llm._cancellation, llm._purpose = broker, actor, cancellation, purpose
        return llm

    def generate(self, messages, tools=None, on_token=None, **kwargs):
        if self._broker is None:
            raise RuntimeError("Unbound SDK LLM cannot infer after deserialization")
        if self.model != "openai/fixture" or self.base_url != "http://127.0.0.1:1/disabled":
            raise RuntimeError("SDK profile change requires core rebinding")
        payload = [scrubber.structured(m.to_chat_dict(cache_enabled=False, vision_enabled=False,
                    function_calling_enabled=True, force_string_serializer=False,
                    send_reasoning_content=True)) for m in messages]
        schemas = [t.to_openai_tool() for t in tools or []]
        data = self._broker.generate(self._actor, self._purpose, payload, schemas,
                                     self._cancellation, on_fragment=on_token)
        msg = data["choices"][0]["message"]
        calls = [MessageToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"], origin="completion") for c in msg.get("tool_calls", [])]
        message = Message(role="assistant", content=[TextContent(text=msg["content"])] if msg.get("content") else [],
                          tool_calls=calls or None, reasoning_content=msg.get("reasoning_content"))
        return LLMResponse(message=message, metrics=MetricsSnapshot(model_name=self._broker.profile),
                           raw_response=ModelResponse(**data))

    completion = generate

    def responses(self, *args, **kwargs):
        raise RuntimeError("Responses API outside the experiment's pinned chat profile")

    async def agenerate(self, *args, **kwargs):
        return await asyncio.to_thread(self.generate, *args, **kwargs)

    acompletion = agenerate

    async def aresponses(self, *args, **kwargs):
        return self.responses(*args, **kwargs)

    def get_token_count(self, messages, **kwargs):
        # Deterministic fixture budget, not tokenizer evidence.
        return sum(len(m.model_dump_json()) for m in messages) // 4 + 1


class BrokerAction(Action):
    tool: str
    arguments: dict
    requires_reproposal: bool = False


class BrokerObservation(Observation):
    pass


class BrokerExecutor(ToolExecutor):
    def __init__(self, authority):
        self.authority = authority

    def __call__(self, action, conversation=None):
        matches = [e for e in conversation.state.events if isinstance(e, ActionEvent) and e.action == action and e.tool_name == "fc_action"]
        if len(matches) != 1:
            return BrokerObservation.from_text("Missing or ambiguous durable SDK action identity", is_error=True)
        result = self.authority.execute(str(matches[-1].id), action.tool, action.arguments,
                                        requires_reproposal=action.requires_reproposal)
        return BrokerObservation.from_text(json.dumps(scrubber.structured(result), sort_keys=True),
                                            is_error="error" in result or result.get("status") in {"rejected", "outcome_unknown"})

    def interrupt(self):
        self.authority.cancellation.cancel()


class BrokerTool(ToolDefinition):
    name: ClassVar[str] = "fc_action"

    @classmethod
    def create(cls, *args, **kwargs):
        raise RuntimeError("Core must explicitly provision the broker executor")


def conversation(store, actor, broker, authority, presentation_dir, conversation_id=None, purpose="generation", callbacks=None, visualizer=None):
    conversation_id = conversation_id or uuid.uuid4()
    llm = BrokeredLLM.bound(broker, actor, authority.cancellation, purpose)
    tool = BrokerTool(description="Propose a FreeCompute tool; core validates permissions and returns actual results.",
                      action_type=BrokerAction, observation_type=BrokerObservation, executor=BrokerExecutor(authority))
    # Fixed process-local name, one fixture conversation at a time. This is not
    # a safe production concurrent-tool registry.
    register_tool("fc_action", tool)
    agent = Agent(llm=llm, tools=[Tool(name="fc_action")], include_default_tools=[])
    return LocalConversation(agent=agent, workspace=DeniedWorkspace(working_dir=str(presentation_dir)),
                             conversation_id=conversation_id, file_store=ProjectionStore(store, actor.agent_id + "/" + str(conversation_id)),
                             visualizer=visualizer, callbacks=callbacks or [], max_iteration_per_run=3,
                             profile_store_dir=str(presentation_dir / "profiles"))


def send_message(conv, text):
    conv.send_message(scrubber.scrub(text))  # Sanitize before SDK entry/persistence.


def run_conversation(conv, authority):
    try:
        return conv.run()
    finally:
        if authority.cancellation.is_cancelled:
            # This synchronous loop actually returned/raised. It is not a
            # confirmation that the remote engine or descendants stopped.
            authority.cancellation.local_stop_confirmed = True
            authority.store.event(authority.actor.task_id, "local_loop_stopped", **authority.cancellation.summary())


def reconcile_projection(conv, authority):
    """Repair a stale SDK HEAD from core-owned pending action identities.

    SDK batches HEAD persistence until a step returns, so an abrupt crash may
    leave a durable ActionEvent outside its restored active branch. This fixture
    supports one linear in-flight action only; no speculative branch merging.
    """
    rows = [r for _, r in authority.store.all("actions") if r["task_id"] == authority.actor.task_id and r["agent_id"] == authority.actor.agent_id]
    by_id = {r["action_id"]: r for r in rows}
    projected_ids = {str(e.id) for e in conv.state.events if isinstance(e, ActionEvent)}
    if set(by_id) - projected_ids:
        raise RuntimeError("Missing core action projection; explicit reconciliation required")
    pending = [e for e in ConversationState.get_unmatched_actions(conv.state.events) if str(e.id) in by_id]
    if len(pending) > 1:
        raise RuntimeError("Multiple recovery actions require explicit reconciliation")
    if pending:
        conv.navigate_to(pending[0].id)
        authority.store.event(authority.actor.task_id, "sdk_head_reconciled", action_id=str(pending[0].id))
