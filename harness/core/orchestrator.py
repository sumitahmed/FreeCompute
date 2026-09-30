"""
harness/core/orchestrator.py — Autonomous Coding Agent Orchestration Loop.
Manages multi-turn task execution, streaming, tool approval gates, and state persistence.
"""

import json
import time
import uuid
from typing import Dict, Any, List, Optional, Callable

from harness.core.client import KaggleBrainClient, CancellationToken
from harness.core.models import Message, ToolCall, FunctionCall
from harness.core.prompt import PromptBuilder
from harness.storage.journal import TaskJournal
from harness.telemetry.session_tracker import SessionTracker
from harness.telemetry.quota_ledger import QuotaLedger
from harness.tools.registry import ToolRegistry


class AgentOrchestrator:
    def __init__(
        self,
        client: KaggleBrainClient,
        prompt_builder: PromptBuilder,
        tool_registry: ToolRegistry,
        journal: TaskJournal,
        session_tracker: SessionTracker,
        quota_ledger: QuotaLedger,
        max_turns_per_task: int = 15,
        undo_manager: Optional[Any] = None,
    ):
        self.client = client
        self.prompt_builder = prompt_builder
        self.tools = tool_registry
        self.journal = journal
        self.session_tracker = session_tracker
        self.quota = quota_ledger
        self.max_turns = max_turns_per_task
        self.undo = undo_manager
        self.cancellation_token = CancellationToken()

    def run_task(
        self,
        user_prompt: str,
        run_id: Optional[str] = None,
        conversation_history: Optional[List[Message]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_phase_change: Optional[Callable[[str, str], None]] = None,
        on_tool_proposed: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_approval_request: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        on_tool_executed: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an autonomous coding task through the full agent tool loop.
        Returns final outcome summary.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        history = list(conversation_history) if conversation_history else []

        # Start session tracking
        self.session_tracker.mark_connected()
        self.quota.start_session()
        self.cancellation_token = CancellationToken()

        # Add user prompt — append /no_think so Qwen3 doesn't emit thinking-only empty output
        prompt_content = user_prompt if user_prompt.strip().endswith("/no_think") else f"{user_prompt} /no_think"
        user_msg = Message(role="user", content=prompt_content)
        history.append(user_msg)

        self.journal.record_event(run_id, "task_start", {"prompt": user_prompt})

        if on_phase_change:
            on_phase_change("started", f"Starting task: {user_prompt[:80]}")

        turn_count = 0
        final_answer = ""

        try:
            while turn_count < self.max_turns:
                if self.cancellation_token.is_cancelled:
                    if on_phase_change:
                        on_phase_change("cancelled", "Task cancelled by user.")
                    self.journal.record_event(run_id, "task_cancelled", {"turns": turn_count})
                    break

                turn_count += 1
                if on_phase_change:
                    on_phase_change("requesting_model", f"Turn {turn_count}: Requesting model inference...")

                # 1. Build messages and tool schemas
                messages = self.prompt_builder.build_messages(history)
                tool_schemas = self.tools.get_openai_schemas()

                # 2. Stream completions from Kaggle brain
                accumulated_text = ""
                accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}

                for chunk in self.client.stream_chat(
                    messages=messages,
                    tools=tool_schemas,
                    cancellation_token=self.cancellation_token,
                ):
                    if chunk.delta_reasoning and on_reasoning:
                        on_reasoning(chunk.delta_reasoning)

                    if chunk.delta_content:
                        accumulated_text += chunk.delta_content
                        if on_token:
                            on_token(chunk.delta_content)

                    if chunk.tool_call_deltas:
                        for tc_delta in chunk.tool_call_deltas:
                            idx = tc_delta.get("index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": tc_delta.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                                    "name": "",
                                    "arguments": "",
                                }
                            fn = tc_delta.get("function", {})
                            if "name" in fn and fn["name"]:
                                accumulated_tool_calls[idx]["name"] += fn["name"]
                            if "arguments" in fn and fn["arguments"]:
                                accumulated_tool_calls[idx]["arguments"] += fn["arguments"]

                # 3. Process result
                # Case A: Model called tools
                if accumulated_tool_calls:
                    parsed_tool_calls = []
                    for idx in sorted(accumulated_tool_calls.keys()):
                        call_info = accumulated_tool_calls[idx]
                        parsed_tool_calls.append(
                            ToolCall(
                                id=call_info["id"],
                                function=FunctionCall(
                                    name=call_info["name"],
                                    arguments=call_info["arguments"],
                                )
                            )
                        )

                    # Append assistant message with tool calls
                    assistant_msg = Message(
                        role="assistant",
                        content=accumulated_text if accumulated_text else None,
                        tool_calls=parsed_tool_calls,
                    )
                    history.append(assistant_msg)

                    # Execute each proposed tool
                    for tc in parsed_tool_calls:
                        tool_name = tc.function.name if tc.function else "unknown"
                        args_str = tc.function.arguments if tc.function else "{}"
                        try:
                            args_dict = json.loads(args_str)
                        except json.JSONDecodeError:
                            args_dict = {}

                        if on_tool_proposed:
                            on_tool_proposed(tool_name, args_dict)

                        # Check approval gate
                        approved = True
                        if self.tools.is_approval_required(tool_name):
                            if on_phase_change:
                                on_phase_change("awaiting_approval", f"Awaiting approval for {tool_name}")
                            if on_approval_request:
                                approved = on_approval_request(tool_name, args_dict)
                            else:
                                approved = True  # Default to auto-approve if no handler registered

                        if approved:
                            if on_phase_change:
                                on_phase_change("executing_tool", f"Executing {tool_name}...")
                            if self.undo and tool_name in ("write_file", "edit_file"):
                                target_path = args_dict.get("path")
                                if target_path:
                                    try:
                                        self.undo.record_pre_change(target_path, operation=tool_name)
                                    except Exception:
                                        pass
                            result = self.tools.execute(tool_name, args_dict)
                        else:
                            result = {"status": "rejected", "message": "User declined approval for this tool call."}

                        if on_tool_executed:
                            on_tool_executed(tool_name, result)

                        # Record event in journal
                        self.journal.record_event(
                            run_id,
                            "tool_executed",
                            {"tool": tool_name, "arguments": args_dict, "result": result, "approved": approved},
                        )

                        # Append tool response message to history
                        tool_msg = Message(
                            role="tool",
                            tool_call_id=tc.id,
                            name=tool_name,
                            content=json.dumps(result, ensure_ascii=False),
                        )
                        history.append(tool_msg)

                    # Save intermediate checkpoint
                    self.journal.save_checkpoint(run_id, {"turn": turn_count, "history_len": len(history)})

                # Case B: Model returned direct text response (Done)
                else:
                    if not accumulated_text.strip():
                        # Qwen3 sometimes emits only reasoning tokens (<think>…</think>)
                        # and no actual content. Retry before giving up.
                        if turn_count < self.max_turns:
                            if on_phase_change:
                                on_phase_change(
                                    "retrying",
                                    "Model returned empty output (thinking-only). Retrying...",
                                )
                            history.append(Message(role="user", content="Please respond with your answer."))
                            continue
                        raise RuntimeError(
                            "model output error: model output must contain either output text "
                            "or tool calls, these cannot both be empty, please try again"
                        )
                    final_answer = accumulated_text
                    assistant_msg = Message(role="assistant", content=accumulated_text)
                    history.append(assistant_msg)
                    if on_phase_change:
                        on_phase_change("completed", "Task completed.")
                    self.journal.record_event(run_id, "task_completed", {"finalAnswer": final_answer[:300]})
                    break

        finally:
            self.quota.stop_session()

        return {
            "run_id": run_id,
            "turns": turn_count,
            "final_answer": final_answer,
            "history": history,
            "is_cancelled": self.cancellation_token.is_cancelled,
        }
