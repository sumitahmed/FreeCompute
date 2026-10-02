"""
harness/telemetry/quota_ledger.py — Quota ledger tracking user-reported balance and local run consumption.
Explicitly labels all calculations as estimates without inventing machine-readable Kaggle quota APIs.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional


class QuotaLedger:
    def __init__(self, storage_path: str = ".qwen_harness/quota_ledger.json"):
        self.storage_path = Path(storage_path)
        self.last_observed_hours: Optional[float] = None
        self.observed_timestamp_iso: Optional[str] = None
        self.total_logged_seconds: float = 0.0
        self.observation_logged_seconds: float = 0.0
        self.current_session_start: Optional[float] = None
        self.load()

    def set_user_observed_balance(self, hours: float, as_of_iso: Optional[str] = None):
        """Set the user-observed weekly GPU quota balance from Kaggle's dashboard."""
        if not __import__("math").isfinite(float(hours)) or float(hours) < 0:
            raise ValueError("Quota balance must be finite and nonnegative")
        self.last_observed_hours = float(hours)
        self.observation_logged_seconds = self.total_logged_seconds + self.active_session_seconds
        self.observed_timestamp_iso = as_of_iso or datetime.now(timezone.utc).isoformat()
        self.save()

    def start_session(self):
        """Record the start of a local task interval."""
        if self.current_session_start is None:
            self.current_session_start = time.time()
            self.save()

    def stop_session(self):
        """Record the end of a local task interval."""
        if self.current_session_start is not None:
            elapsed = time.time() - self.current_session_start
            self.total_logged_seconds += elapsed
            self.current_session_start = None
            self.save()

    @property
    def active_session_seconds(self) -> float:
        """Seconds spent in the current active session."""
        if self.current_session_start is None:
            return 0.0
        return time.time() - self.current_session_start

    @property
    def cumulative_consumed_hours(self) -> float:
        """Total hours consumed locally across all logged sessions."""
        total_s = self.total_logged_seconds + self.active_session_seconds
        return total_s / 3600.0

    @property
    def estimated_remaining_hours(self) -> Optional[float]:
        """Estimated remaining weekly GPU hours."""
        if self.last_observed_hours is None:
            return None
        return max(0.0, self.last_observed_hours - ((self.total_logged_seconds + self.active_session_seconds - self.observation_logged_seconds) / 3600.0))

    def get_summary(self) -> Dict[str, Any]:
        """Return the current quota accounting status."""
        return {
            "last_observed_hours": self.last_observed_hours,
            "observed_as_of": self.observed_timestamp_iso,
            "session_consumed_hours": round(self.active_session_seconds / 3600.0, 3),
            "estimated_remaining_hours": round(self.estimated_remaining_hours, 2) if self.estimated_remaining_hours is not None else None,
            "is_estimate": True,
            "accounting_basis": "local_task_wall_time; not GPU billing or allocation uptime",
            "disclaimer": "Local task time excludes idle GPU allocation and other clients. Verify actual quota in the provider dashboard.",
        }

    def save(self):
        """Persist ledger to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_observed_hours": self.last_observed_hours,
            "observed_timestamp_iso": self.observed_timestamp_iso,
            "total_logged_seconds": self.total_logged_seconds,
            "observation_logged_seconds": self.observation_logged_seconds,
            "current_session_start": self.current_session_start,
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self):
        """Load ledger from disk if it exists."""
        if self.storage_path.is_file():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_observed_hours = data.get("last_observed_hours")
                    self.observed_timestamp_iso = data.get("observed_timestamp_iso")
                    self.total_logged_seconds = float(data.get("total_logged_seconds", 0.0))
                    self.observation_logged_seconds = float(data.get("observation_logged_seconds", self.total_logged_seconds))
                    # A crashed process cannot measure an ongoing GPU session.
                    self.current_session_start = None
            except Exception:
                pass
