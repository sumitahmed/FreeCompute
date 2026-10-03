"""Bounded optional terminal telemetry during long model waits."""
import threading
import sys

from harness.cli.formatter import terminal_text
from harness.cli.telemetry import value
from harness.telemetry.models import normalize
from harness.security import safe_print


class LiveTelemetry:
    def __init__(self, client, presentation, interval=15):
        self.client, self.presentation, self.interval = client, presentation, interval
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        return self

    def _run(self):
        while not self.stop.wait(self.interval):
            worker = self.presentation.waiting_worker
            if not worker:
                continue
            try:
                health = self.client._core.registry.refresh(worker)
                if health is None or self.stop.is_set():
                    continue
                t = normalize(health.raw)
                with self.presentation.output_lock:
                    # Never interrupt a streamed paragraph or an approval prompt.
                    if self.presentation.waiting_worker != worker or self.presentation.line_open:
                        continue
                    m = t.metrics
                    safe_print(terminal_text("  Live " + worker + " | " + health.status + " | CPU " + value(m['cpu_utilization_pct'], unit='%') + " | session remaining " + value(m['session_remaining_seconds'], duration=True)), file=sys.stderr)
                    if t.warning():
                        safe_print("  Session warning: " + t.warning() + " or less (sampled; " + m['session_limit_seconds']['status'] + " limit)", file=sys.stderr)
            except Exception:
                # Optional telemetry failure never cancels or fails an inference.
                continue

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=12)
