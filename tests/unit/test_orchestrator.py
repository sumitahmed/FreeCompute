"""
tests/unit/test_orchestrator.py — Integration unit test for multi-turn agent tool loop and approvals.
"""

import json
import tempfile
import unittest
from unittest.mock import MagicMock

from harness.core.models import StreamChunk
from harness.core.orchestrator import AgentOrchestrator
from harness.core.prompt import PromptBuilder
from harness.storage.journal import TaskJournal
from harness.telemetry.quota_ledger import QuotaLedger
from harness.telemetry.session_tracker import SessionTracker
from harness.tools.registry import ToolRegistry


class TestAgentOrchestrator(unittest.TestCase):
    def test_full_agent_turn_loop_with_tool_call_and_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup dummy file
            test_file = "src/app.py"
            registry = ToolRegistry(workspace_root=tmpdir)
            registry.execute("write_file", {"path": test_file, "content": "x = 10\n"}, approval_callback=lambda *_: True)

            journal = TaskJournal(journal_dir=tmpdir)
            session_tracker = SessionTracker()
            quota_ledger = QuotaLedger(storage_path=f"{tmpdir}/quota.json")
            prompt_builder = PromptBuilder()

            # Mock KaggleBrainClient
            mock_client = MagicMock()

            # Turn 1 response: Model proposes edit_file tool call
            chunk_tool = StreamChunk(
                delta_content="",
                tool_call_deltas=[
                    {
                        "index": 0,
                        "id": "call_edit_001",
                        "function": {
                            "name": "edit_file",
                            "arguments": json.dumps({
                                "path": test_file,
                                "old_str": "x = 10",
                                "new_str": "x = 20",
                            }),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

            # Turn 2 response: Model says "Task complete!"
            chunk_done = StreamChunk(
                delta_content="I have updated x to 20.",
                finish_reason="stop",
            )

            # Client stream_chat returns Turn 1 then Turn 2
            mock_client.stream_chat.side_effect = [
                iter([chunk_tool]),
                iter([chunk_done]),
            ]

            orchestrator = AgentOrchestrator(
                client=mock_client,
                prompt_builder=prompt_builder,
                tool_registry=registry,
                journal=journal,
                session_tracker=session_tracker,
                quota_ledger=quota_ledger,
            )

            approvals = []

            def mock_approval(tool_name, args):
                approvals.append(tool_name)
                return True  # User approves

            result = orchestrator.run_task(
                user_prompt="Please change x from 10 to 20 in src/app.py",
                on_approval_request=mock_approval,
            )

            # Verify orchestrator loop executed 2 turns
            self.assertEqual(result["turns"], 2)
            self.assertEqual(result["final_answer"], "I have updated x to 20.")
            self.assertIn("edit_file", approvals)

            # Verify file was actually modified on disk
            read_back = registry.execute("read_file", {"path": test_file})
            self.assertIn("x = 20", read_back["raw_content"])

            # Verify task events and checkpoints were recorded
            events = journal.get_events_for_run(result["run_id"])
            event_types = [e["type"] for e in events]
            self.assertIn("task_start", event_types)
            self.assertIn("tool_executed", event_types)
            self.assertIn("task_completed", event_types)


if __name__ == "__main__":
    unittest.main()
