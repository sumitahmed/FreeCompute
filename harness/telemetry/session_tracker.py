"""
harness/telemetry/session_tracker.py — Honest Session & Uptime Tracker.
Distinguishes locally measured connected uptime from Kaggle container lifetime,
and computes honest countdown to the 12-hour platform cutoff.
"""

from harness.security import scrubber
import time
from typing import Dict, Any, Optional


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable H:MM:SS or M:SS string."""
    seconds = max(0, int(seconds))
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {secs:02d}s"
    return f"{mins}m {secs:02d}s"


class SessionTracker:
    def __init__(self):
        self.connected_start_time: Optional[float] = None
        self.last_container_uptime_seconds: Optional[float] = None
        self.last_sync_timestamp: Optional[float] = None
        self.is_connected = False
        self.session_age_source = "unknown"
        self.session_limit_seconds = None

    def mark_connected(self):
        """Record the start of active local harness connection."""
        if self.connected_start_time is None:
            self.connected_start_time = time.time()
        self.is_connected = True

    def mark_disconnected(self):
        """Record connection loss."""
        self.is_connected = False

    def update_from_remote_health(self, health_data: Dict[str, Any]):
        """Ingest remote health payload from Kaggle supervisor."""
        self.mark_connected()
        self.last_sync_timestamp = time.time()
        self.session_age_source = health_data.get("sessionAgeSource", "legacy_unverified")
        if health_data.get("maxSessionSeconds") is not None:
            self.session_limit_seconds = float(health_data["maxSessionSeconds"])
        container_uptime = health_data.get("sessionAgeSeconds", health_data.get("containerUptimeSeconds"))
        if container_uptime is not None:
            self.last_container_uptime_seconds = float(container_uptime)

    @property
    def connected_uptime_seconds(self) -> float:
        """Locally measured connected duration in seconds."""
        if not self.connected_start_time:
            return 0.0
        return time.time() - self.connected_start_time

    @property
    def estimated_container_uptime_seconds(self) -> Optional[float]:
        """Estimated container age in seconds since Kaggle started."""
        if self.last_container_uptime_seconds is None or self.last_sync_timestamp is None:
            return None
        elapsed_since_sync = time.time() - self.last_sync_timestamp
        return self.last_container_uptime_seconds + elapsed_since_sync

    @property
    def seconds_remaining_in_12h_session(self) -> Optional[float]:
        """Remaining seconds before Kaggle terminates the 12-hour session."""
        container_age = self.estimated_container_uptime_seconds
        if container_age is None or self.session_limit_seconds is None:
            return None
        return max(0.0, self.session_limit_seconds - container_age)

    @property
    def is_warning(self) -> bool:
        """True if session has less than 60 minutes remaining."""
        rem = self.seconds_remaining_in_12h_session
        return rem is not None and rem <= 3600.0

    @property
    def is_critical(self) -> bool:
        """True if session has less than 30 minutes remaining."""
        rem = self.seconds_remaining_in_12h_session
        return rem is not None and rem <= 1800.0

    def get_summary(self) -> Dict[str, Any]:
        """Generate a complete honest telemetry snapshot."""
        rem = self.seconds_remaining_in_12h_session
        container_age = self.estimated_container_uptime_seconds
        return scrubber.structured({
            "is_connected": self.is_connected,
            "is_estimate": True,
            "session_age_source": self.session_age_source,
            "session_limit_source": "legacy explicitly reported limit; not authoritative" if self.session_limit_seconds is not None else "unknown",
            "connected_uptime_seconds": round(self.connected_uptime_seconds, 1),
            "connected_uptime_formatted": format_duration(self.connected_uptime_seconds),
            "container_uptime_seconds": round(container_age, 1) if container_age is not None else None,
            "container_uptime_formatted": format_duration(container_age) if container_age is not None else "Unknown (waiting for heartbeat)",
            "seconds_remaining_12h": round(rem, 1) if rem is not None else None,
            "remaining_12h_formatted": format_duration(rem) if rem is not None else "Unknown",
            "is_warning": self.is_warning,
            "is_critical": self.is_critical,
        })
