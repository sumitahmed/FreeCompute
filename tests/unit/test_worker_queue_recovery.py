"""Fresh-process recovery with stable queue order and unknown remote leases."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "runtime" / "worker_queue_process.py"


class WorkerProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-v1-queue-process-")
        self.directory = Path(self.temp.name)
        self.environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LOCALAPPDATA=str(self.directory / "appdata"))

    def tearDown(self):
        self.temp.cleanup()

    def child(self, mode, crash=False):
        result = subprocess.run([sys.executable, str(SCRIPT), mode, str(self.directory)],
                                env=self.environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 73 if crash else 0, result.stdout + result.stderr)
        return json.loads(result.stdout) if not crash else None

    def test_queued_tasks_survive_process_exit_and_run_once_in_order(self):
        self.child("queued", True)
        result = self.child("drain")
        self.assertEqual(result["states"], ["completed", "completed"])
        self.assertEqual(result["inference_calls"], 2)
        self.assertEqual(result["allocation"]["state"], "idle")
        self.assertEqual(result["claims"], [])

    def test_running_request_retains_both_gpus_without_blind_retry(self):
        self.child("running", True)
        result = self.child("inspect")
        self.assertEqual(result["inference_calls"], 1)
        self.assertEqual(result["allocation"]["state"], "quarantined")
        self.assertEqual({c["resource_id"] for c in result["claims"]}, {"gpu0", "gpu1"})
        self.assertEqual(result["states"], ["paused", "queued"])
        confirmed = self.child("reconcile")
        self.assertEqual(confirmed["inference_calls"], 2)
        self.assertEqual(confirmed["states"], ["completed", "queued"])
        self.assertEqual(confirmed["claims"], [])

    def test_queued_cancel_survives_process_exit_and_is_not_dispatched(self):
        self.child("cancelled", True)
        result = self.child("drain")
        self.assertEqual(result["states"], ["cancelled", "completed"])
        self.assertEqual(result["inference_calls"], 1)


if __name__ == "__main__":
    unittest.main()
