"""Crash/restart the real CoreService in separate operating-system processes."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "runtime" / "crash_worker.py"


class RuntimeProcessRecoveryTests(unittest.TestCase):
    def crash(self, stage, directory):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, str(SCRIPT), "create", stage, str(directory)],
                                capture_output=True, text=True, env=environment, timeout=20)
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        db = sqlite3.connect(directory / "state" / "runtime.sqlite3")
        session_id, task_id = db.execute("SELECT id,current_task_id FROM sessions ORDER BY rowid LIMIT 1").fetchone()
        actions = db.execute("SELECT id,call_id,state FROM actions ORDER BY rowid").fetchall()
        db.close()
        return session_id, task_id, actions

    def resume(self, mode, directory, session_id):
        result = subprocess.run([sys.executable, str(SCRIPT), mode, "", str(directory), session_id],
                                capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def recover_case(self, stage, expected_approvals):
        with tempfile.TemporaryDirectory(prefix="fc-process-recovery-") as temporary:
            directory = Path(temporary)
            session_id, task_id, before = self.crash(stage, directory)
            result = self.resume("resume", directory, session_id)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["session_id"], session_id)
            self.assertEqual(result["task_id"], task_id)
            self.assertEqual(result["counter"], 1)
            self.assertEqual(result["approvals"], expected_approvals)
            db = sqlite3.connect(directory / "state" / "runtime.sqlite3")
            after = db.execute("SELECT id,call_id,state FROM actions ORDER BY rowid").fetchall()
            if before:
                self.assertEqual(before[0][:2], after[0][:2])
            self.assertEqual(len(after), 1)
            self.assertEqual(after[0][2], "completed")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            db.close()
            return result

    def test_restart_after_proposal_checkpoint(self):
        self.recover_case("after_proposals", 1)

    def test_restart_before_approval(self):
        self.recover_case("before_approval", 1)

    def test_restart_after_approval_requires_fresh_decision(self):
        self.recover_case("after_approval", 2)

    def test_restart_after_receipt_does_not_repeat_completed_effect(self):
        self.recover_case("after_result", 1)

    def test_restart_after_inference_receipt_replays_without_losing_action(self):
        result = self.recover_case("after_inference_receipt", 1)
        self.assertEqual(result["inference_requests"], 1)  # final answer only

    def test_restart_after_final_inference_receipt_needs_no_new_request(self):
        result = self.recover_case("after_final_inference_receipt", 1)
        self.assertEqual(result["inference_requests"], 0)

    def test_restart_during_effect_fences_fresh_ids_until_explicit_reconciliation(self):
        with tempfile.TemporaryDirectory(prefix="fc-uncertain-effect-") as temporary:
            directory = Path(temporary)
            session_id, task_id, actions = self.crash("during_execution", directory)
            self.assertEqual(actions[0][2], "executing")
            result = self.resume("resume", directory, session_id)
            self.assertEqual(result["status"], "outcome_unknown")
            self.assertEqual(result["fresh_id_status"], "outcome_unknown")
            self.assertEqual(result["counter"], 1)
            self.assertEqual(result["approvals"], 1)
            reconciled = self.resume("reconcile", directory, session_id)
            self.assertEqual(reconciled["status"], "completed")
            self.assertEqual(reconciled["task_id"], task_id)
            self.assertEqual(reconciled["counter"], 1)
            self.assertEqual(reconciled["approvals"], 2)  # separate reconciliation decision

    def test_restart_after_intent_before_handler_is_conservatively_uncertain(self):
        with tempfile.TemporaryDirectory(prefix="fc-uncertain-intent-") as temporary:
            directory = Path(temporary)
            session_id, _, _ = self.crash("before_execution", directory)
            result = self.resume("resume", directory, session_id)
            self.assertEqual(result["status"], "outcome_unknown")
            self.assertEqual(result["counter"], 0)
            self.assertEqual(result["approvals"], 1)

    def test_restart_during_inference_requires_idle_confirmation(self):
        with tempfile.TemporaryDirectory(prefix="fc-uncertain-inference-") as temporary:
            directory = Path(temporary)
            session_id, _, _ = self.crash("during_inference", directory)
            result = self.resume("resume", directory, session_id)
            self.assertEqual(result["status"], "paused")
            self.assertEqual(result["allocation"], "quarantined")
            self.assertEqual(result["inference_requests"], 0)
            result = self.resume("reconcile_idle", directory, session_id)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["counter"], 0)
            self.assertEqual(result["allocation"], "idle")


if __name__ == "__main__":
    unittest.main()
