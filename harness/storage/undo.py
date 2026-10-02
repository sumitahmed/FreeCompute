"""Immutable preimages with sealed hashes and explicitly authorized restoration."""
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from harness.tools.atomic import replace_bytes
from harness.tools.sandbox import validate_workspace_path
from harness.security import scrubber


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

@dataclass(frozen=True)
class UndoSnapshot:
    snapshot_id: str
    timestamp: float
    file_path: str
    backup_path: str | None
    operation: str
    diff: str = ""
    pre_hash: str | None = None
    post_hash: str | None = None
    sealed: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

class UndoManager:
    def __init__(self, workspace_root=".", storage_dir=".qwen_harness"):
        self.workspace_root = Path(workspace_root).resolve()
        self.storage_dir = Path(storage_dir).resolve()
        self.snapshot_dir = self.storage_dir / "snapshots"
        self.history_file = self.storage_dir / "undo_history.json"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots = []
        self._load_history()

    def _load_history(self):
        if self.history_file.exists():
            self.snapshots = [UndoSnapshot.from_dict(d) for d in json.loads(self.history_file.read_text(encoding="utf-8"))]

    def _save_history(self):
        temporary = self.storage_dir / (uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps([s.to_dict() for s in self.snapshots], indent=2), encoding="utf-8")
            os.replace(temporary, self.history_file)
        finally:
            temporary.unlink(missing_ok=True)

    def record_pre_change(self, target_path, operation="edit_file", diff=""):
        target = validate_workspace_path(target_path, str(self.workspace_root), True)
        identity = uuid.uuid4().hex
        backup = None
        before = file_hash(target)
        if before is not None:
            backup = self.snapshot_dir / (identity + ".bak")
            with backup.open("xb") as stream:
                stream.write(target.read_bytes())
            if file_hash(backup) != before:
                raise RuntimeError("File changed during snapshot")
        snapshot = UndoSnapshot(identity, time.time(), str(target), str(backup) if backup else None,
                                operation, scrubber.scrub(diff), before)
        self.snapshots.append(snapshot)
        self._save_history()
        return snapshot

    def record_post_change(self, snapshot, diff=""):
        from dataclasses import replace
        identity = snapshot.snapshot_id if isinstance(snapshot, UndoSnapshot) else snapshot
        index = next(i for i, s in enumerate(self.snapshots) if s.snapshot_id == identity)
        previous = self.snapshots[index]
        if previous.sealed:
            raise ValueError("Snapshot is already sealed")
        target = validate_workspace_path(previous.file_path, str(self.workspace_root))
        self.snapshots[index] = replace(previous, post_hash=file_hash(target), sealed=True,
                                        diff=scrubber.scrub(diff or previous.diff))
        self._save_history()

    def undo_last(self, approval_callback=None):
        if not self.snapshots:
            return {"status": "empty", "message": "No file changes available to undo."}
        snapshot = self.snapshots[-1]
        try:
            target = validate_workspace_path(snapshot.file_path, str(self.workspace_root), True)
            if not snapshot.sealed:
                raise ValueError("Snapshot has no verified post-change hash")
            if file_hash(target) != snapshot.post_hash:
                raise ValueError("Conflict: file changed after the recorded operation")
            backup = None
            if snapshot.pre_hash is not None:
                expected = self.snapshot_dir / (uuid.UUID(hex=snapshot.snapshot_id).hex + ".bak")
                backup = Path(snapshot.backup_path or "")
                if backup != expected or backup.is_symlink() or not backup.is_file() or file_hash(backup) != snapshot.pre_hash:
                    raise ValueError("Backup is missing, invalid, or corrupted; target was preserved")
            if approval_callback is None or approval_callback("undo", scrubber.structured(snapshot.to_dict())) is not True:
                return {"status": "rejected", "message": "Explicit restore approval required"}
            target = validate_workspace_path(snapshot.file_path, str(self.workspace_root), True)
            if file_hash(target) != snapshot.post_hash:
                raise ValueError("Conflict: file changed during approval")
            if backup:
                # Recheck the immutable preimage immediately before restoration.
                content = backup.read_bytes()
                if hashlib.sha256(content).hexdigest() != snapshot.pre_hash:
                    raise ValueError("Backup changed during approval")
                replace_bytes(target, content, str(self.workspace_root), snapshot.post_hash)
            elif target.exists():
                target.unlink()
            self.snapshots.pop()
            self._save_history()
            return {"status": "success", "file_path": str(target), "action": "restored" if backup else "deleted", "snapshot_id": snapshot.snapshot_id}
        except Exception as exc:
            return {"status": "error", "error": scrubber.scrub(exc)}

    def get_last_diff(self):
        return scrubber.scrub(self.snapshots[-1].diff or "No recorded diff text for this operation.") if self.snapshots else None

    def get_history(self, limit=10):
        return scrubber.structured([dict(s.to_dict(), has_backup=s.backup_path is not None) for s in reversed(self.snapshots[-limit:])])
