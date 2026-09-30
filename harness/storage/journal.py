"""
harness/storage/journal.py — Persistent Task & Event Journal.
Stores an append-only JSONL log of every event, tool call, approval, and task checkpoint.
Enables task resumption after disconnection or Kaggle session restart.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


class TaskJournal:
    def __init__(self, journal_dir: str = ".qwen_harness"):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.journal_dir / "journal.jsonl"
        self.checkpoints_file = self.journal_dir / "checkpoints.json"

    def record_event(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Record an event in the append-only journal."""
        event = {
            "eventId": f"evt_{uuid.uuid4().hex[:12]}",
            "runId": run_id,
            "timestampUtc": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": payload,
        }
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def save_checkpoint(self, run_id: str, state: Dict[str, Any]):
        """Save a task milestone checkpoint for resuming later."""
        checkpoints = self.load_checkpoints()
        checkpoints[run_id] = {
            "runId": run_id,
            "updatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        with open(self.checkpoints_file, "w", encoding="utf-8") as f:
            json.dump(checkpoints, f, indent=2, ensure_ascii=False)

    def get_checkpoint(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the latest checkpoint for a run ID."""
        checkpoints = self.load_checkpoints()
        return checkpoints.get(run_id)

    def load_checkpoints(self) -> Dict[str, Any]:
        """Load all checkpoints from disk."""
        if not self.checkpoints_file.is_file():
            return {}
        try:
            with open(self.checkpoints_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def get_events_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all historical events for a specific run."""
        if not self.journal_file.is_file():
            return []
        events = []
        with open(self.journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("runId") == run_id:
                        events.append(ev)
                except Exception:
                    continue
        return events
