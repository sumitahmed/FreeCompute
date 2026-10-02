"""Private immutable preimages and conflict-checked approved restoration."""
import hashlib
import os
from pathlib import Path

from harness.security import scrubber
from harness.storage.runtime import identity, timestamp
from harness.storage.undo import file_hash
from harness.tools.atomic import replace_bytes
from harness.tools.sandbox import validate_workspace_path


class ArtifactManager:
    def __init__(self, store):
        self.store = store
        self.blobs = store.directory / "blobs"
        self.blobs.mkdir(exist_ok=True)
        if os.name != "nt":
            self.blobs.chmod(0o700)

    def capture(self, db, action, target, expected_hash):
        target = validate_workspace_path(target, str(self.store.workspace), True)
        artifact_id = None
        if expected_hash is not None:
            content = target.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != expected_hash or file_hash(target) != digest:
                raise ValueError("File changed before snapshot; obtain a fresh approval")
            blob = self.blobs / digest
            if not blob.exists():
                temporary = self.blobs / (identity() + ".tmp")
                try:
                    with temporary.open("xb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if os.name != "nt":
                        temporary.chmod(0o600)
                    os.replace(temporary, blob)
                finally:
                    temporary.unlink(missing_ok=True)
            if blob.is_symlink() or file_hash(blob) != digest:
                raise ValueError("Private snapshot blob is corrupt")
            artifact_id = identity()
            db.execute("INSERT INTO artifacts VALUES(?,?,?,1,?,?,?,?,?)", (
                artifact_id, action["task_id"], action["id"], digest, len(content),
                "application/octet-stream", "blobs/" + digest, timestamp()))
        snapshot_id = identity()
        db.execute("INSERT INTO snapshots(id,action_id,version,target,pre_artifact_id,pre_hash,state) VALUES(?,?,1,?,?,?,'unsealed')",
                   (snapshot_id, action["id"], str(target.relative_to(self.store.workspace)), artifact_id, expected_hash))
        return snapshot_id

    def snapshot(self, snapshot_id):
        snapshot = self.store.one("SELECT * FROM snapshots WHERE id=?", (snapshot_id,))
        if not snapshot:
            raise ValueError("Unknown snapshot")
        return snapshot

    def restore(self, snapshot_id):
        snapshot = self.snapshot(snapshot_id)
        if snapshot["state"] != "sealed":
            raise ValueError("Snapshot is not sealed or has already been restored")
        target = validate_workspace_path(snapshot["target"], str(self.store.workspace), True)
        if file_hash(target) != snapshot["post_hash"]:
            raise ValueError("File changed after the recorded operation")
        if snapshot["pre_hash"] is not None:
            artifact = self.store.one("SELECT * FROM artifacts WHERE id=?", (snapshot["pre_artifact_id"],))
            if not artifact or artifact["digest"] != snapshot["pre_hash"] or artifact["action_id"] != snapshot["action_id"]:
                raise ValueError("Missing or mismatched snapshot artifact")
            blob = self.blobs / artifact["digest"]
            if artifact["relative_path"] != "blobs/" + artifact["digest"] or blob.is_symlink():
                raise ValueError("Invalid snapshot artifact path")
            content = blob.read_bytes()
            if hashlib.sha256(content).hexdigest() != snapshot["pre_hash"]:
                raise ValueError("Snapshot backup is corrupt; target preserved")
            replace_bytes(target, content, str(self.store.workspace), snapshot["post_hash"])
        elif target.exists():
            # Absence was recorded intentionally; this deletion is separately approved.
            target.unlink()
        return {"status": "success", "snapshot_id": snapshot_id, "file_path": str(target),
                "action": "restored" if snapshot["pre_hash"] is not None else "deleted"}

    def seal(self, db, action, result):
        if action["name"] in {"write_file", "edit_file"}:
            target = validate_workspace_path(action["target"], str(self.store.workspace), True)
            db.execute("UPDATE snapshots SET post_hash=?,state='sealed',diff=? WHERE action_id=?",
                       (file_hash(target), scrubber.scrub(result.get("diff", "")), action["id"]))
        elif action["name"] == "restore_snapshot":
            import json
            db.execute("UPDATE snapshots SET state='restored' WHERE id=?", (json.loads(action["arguments"])["snapshot_id"],))

    def latest(self):
        return self.store.one("SELECT s.* FROM snapshots s JOIN actions a ON a.id=s.action_id WHERE s.state='sealed' ORDER BY a.rowid DESC LIMIT 1")
