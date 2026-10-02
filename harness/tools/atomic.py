"""Atomic replacement with a final sandbox and content-conflict check.

This is a trusted-host guard, not isolation from concurrent hostile processes.
"""
import hashlib
import os
from pathlib import Path
import tempfile
from harness.tools.sandbox import validate_workspace_path


def content_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def replace_bytes(path, content, workspace_root, expected_hash):
    path = validate_workspace_path(str(path), workspace_root, True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".freecompute-write-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_workspace_path(str(path), workspace_root, True)
        if content_hash(path) != expected_hash or path.exists() and not path.is_file():
            raise ValueError("File changed before atomic replacement")
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
