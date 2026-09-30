"""
tests/unit/test_telemetry.py — Unit tests for session tracking and quota estimation.
"""

import time
import unittest
from harness.telemetry.session_tracker import SessionTracker, format_duration
from harness.telemetry.quota_ledger import QuotaLedger


class TestSessionTracker(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(45), "0m 45s")
        self.assertEqual(format_duration(125), "2m 05s")
        self.assertEqual(format_duration(3665), "1h 01m 05s")
        self.assertEqual(format_duration(43200), "12h 00m 00s")

    def test_tracker_countdown_and_warnings(self):
        tracker = SessionTracker()
        tracker.mark_connected()

        health_payload = {
            "status": "healthy",
            "containerUptimeSeconds": 7200.0,
            "maxSessionSeconds": 43200.0,
        }
        tracker.update_from_remote_health(health_payload)

        rem = tracker.seconds_remaining_in_12h_session
        self.assertIsNotNone(rem)
        self.assertAlmostEqual(rem, 36000.0, delta=2.0)
        self.assertFalse(tracker.is_warning)
        self.assertFalse(tracker.is_critical)

        tracker.update_from_remote_health({"containerUptimeSeconds": 39600.0})
        self.assertTrue(tracker.is_warning)
        self.assertFalse(tracker.is_critical)

        tracker.update_from_remote_health({"containerUptimeSeconds": 41760.0})
        self.assertTrue(tracker.is_warning)
        self.assertTrue(tracker.is_critical)


class TestQuotaLedger(unittest.TestCase):
    def test_quota_estimation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = Path(tmpdir) / "quota.json"
            ledger = QuotaLedger(storage_path=str(ledger_file))

            ledger.set_user_observed_balance(25.0, as_of_iso="2026-09-27T10:00:00Z")
            self.assertEqual(ledger.last_observed_hours, 25.0)

            ledger.start_session()
            ledger.current_session_start = time.time() - 5400.0

            summary = ledger.get_summary()
            self.assertTrue(summary["is_estimate"])
            self.assertEqual(summary["last_observed_hours"], 25.0)
            self.assertAlmostEqual(summary["session_consumed_hours"], 1.5, delta=0.05)
            self.assertAlmostEqual(summary["estimated_remaining_hours"], 23.5, delta=0.05)

            ledger.stop_session()
            reloaded = QuotaLedger(storage_path=str(ledger_file))
            self.assertAlmostEqual(reloaded.cumulative_consumed_hours, 1.5, delta=0.05)


if __name__ == "__main__":
    unittest.main()
