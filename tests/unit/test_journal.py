"""
tests/unit/test_journal.py — Unit tests for persistent task journal and checkpoints.
"""

import tempfile
import unittest
from pathlib import Path
from harness.storage.journal import TaskJournal


class TestTaskJournal(unittest.TestCase):
    def test_journal_event_logging_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = TaskJournal(journal_dir=tmpdir)
            run_id = "test_run_123"

            evt1 = journal.record_event(run_id, "task_start", {"goal": "Refactor parser"})
            evt2 = journal.record_event(run_id, "tool_executed", {"tool": "patch_file", "exitCode": 0})

            self.assertTrue(evt1["eventId"].startswith("evt_"))
            self.assertEqual(evt1["type"], "task_start")

            events = journal.get_events_for_run(run_id)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["type"], "task_start")
            self.assertEqual(events[1]["type"], "tool_executed")

            state = {
                "step": 3,
                "completedFiles": ["src/parser.py"],
                "lastTestStatus": "PASSED",
            }
            journal.save_checkpoint(run_id, state)

            ckpt = journal.get_checkpoint(run_id)
            self.assertIsNotNone(ckpt)
            self.assertEqual(ckpt["state"]["step"], 3)
            self.assertEqual(ckpt["state"]["completedFiles"], ["src/parser.py"])

            new_journal = TaskJournal(journal_dir=tmpdir)
            reloaded_ckpt = new_journal.get_checkpoint(run_id)
            self.assertEqual(reloaded_ckpt["state"]["lastTestStatus"], "PASSED")


if __name__ == "__main__":
    unittest.main()
