"""
harness/storage/undo.py — Transactional file snapshotting, diff inspection, and rollback ledger.
"""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class UndoSnapshot:
    def __init__(
        self,
        snapshot_id: str,
        timestamp: float,
        file_path: str,
        backup_path: Optional[str],
        operation: str,
        diff: str = "",
    ):
        self.snapshot_id = snapshot_id
        self.timestamp = timestamp
        self.file_path = file_path
        self.backup_path = backup_path
        self.operation = operation
        self.diff = diff

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "backup_path": self.backup_path,
            "operation": self.operation,
            "diff": self.diff,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UndoSnapshot":
        return cls(
            snapshot_id=data["snapshot_id"],
            timestamp=data["timestamp"],
            file_path=data["file_path"],
            backup_path=data.get("backup_path"),
            operation=data.get("operation", "edit_file"),
            diff=data.get("diff", ""),
        )


class UndoManager:
    """
    Manages safe pre-execution snapshots of files before agent modification.
    Allows inspecting recent diffs and rolling back unwanted changes cleanly.
    """

    def __init__(self, workspace_root: str = ".", storage_dir: str = ".qwen_harness"):
        self.workspace_root = Path(workspace_root).resolve()
        self.storage_dir = Path(storage_dir).resolve()
        self.snapshot_dir = self.storage_dir / "snapshots"
        self.history_file = self.storage_dir / "undo_history.json"

        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: List[UndoSnapshot] = []
        self._load_history()

    def _load_history(self):
        if self.history_file.is_file():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.snapshots = [UndoSnapshot.from_dict(d) for d in data]
            except Exception:
                self.snapshots = []

    def _save_history(self):
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([s.to_dict() for s in self.snapshots], f, indent=2)
        except Exception:
            pass

    def record_pre_change(
        self,
        target_path: str,
        operation: str = "edit_file",
        diff: str = "",
    ) -> UndoSnapshot:
        """
        Takes a snapshot of target_path BEFORE a write or edit tool modifies it.
        If the file exists, copies its current state into the snapshot directory.
        If the file does not exist, marks backup_path as None (for clean deletion upon undo).
        """
        abs_target = (self.workspace_root / target_path).resolve()
        ts = time.time()
        snap_id = f"snap_{int(ts)}_{hashlib.sha256(str(abs_target).encode()).hexdigest()[:8]}"

        backup_file_path = None
        if abs_target.is_file():
            backup_name = f"{snap_id}_{abs_target.name}"
            backup_dest = self.snapshot_dir / backup_name
            shutil.copy2(abs_target, backup_dest)
            backup_file_path = str(backup_dest)

        snapshot = UndoSnapshot(
            snapshot_id=snap_id,
            timestamp=ts,
            file_path=str(abs_target),
            backup_path=backup_file_path,
            operation=operation,
            diff=diff,
        )
        self.snapshots.append(snapshot)
        self._save_history()
        return snapshot

    def undo_last(self) -> Dict[str, Any]:
        """
        Reverts the most recent file modification recorded in the snapshot ledger.
        """
        if not self.snapshots:
            return {"status": "empty", "message": "No file changes available to undo."}

        last_snap = self.snapshots.pop()
        target = Path(last_snap.file_path)

        try:
            if last_snap.backup_path and Path(last_snap.backup_path).is_file():
                # Restore previous file content
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(last_snap.backup_path, target)
                # Cleanup snapshot file
                try:
                    os.remove(last_snap.backup_path)
                except OSError:
                    pass
                self._save_history()
                return {
                    "status": "success",
                    "file_path": str(target),
                    "action": "restored",
                    "snapshot_id": last_snap.snapshot_id,
                }
            else:
                # File was newly created by the agent; remove it
                if target.is_file():
                    target.unlink()
                self._save_history()
                return {
                    "status": "success",
                    "file_path": str(target),
                    "action": "deleted",
                    "snapshot_id": last_snap.snapshot_id,
                }
        except Exception as exc:
            # Re-insert snapshot on failure so state isn't lost
            self.snapshots.append(last_snap)
            return {
                "status": "error",
                "file_path": str(target),
                "error": str(exc),
            }

    def get_last_diff(self) -> Optional[str]:
        """Return the unified diff recorded during the last file operation."""
        if not self.snapshots:
            return None
        return self.snapshots[-1].diff or "No recorded diff text for this operation."

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return a summary of recent file snapshots."""
        items = []
        for s in reversed(self.snapshots[-limit:]):
            items.append({
                "snapshot_id": s.snapshot_id,
                "timestamp": s.timestamp,
                "file_path": s.file_path,
                "operation": s.operation,
                "has_backup": s.backup_path is not None,
            })
        return items
