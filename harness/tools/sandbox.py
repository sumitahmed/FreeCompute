"""
harness/tools/sandbox.py — Security guardrails and path sandboxing for local tools.
Prevents directory traversal, symlink escapes, and unauthorized access to system/secret paths.
"""

import os
from pathlib import Path
from typing import Set


class SandboxSecurityViolation(Exception):
    """Raised when an operation attempts to breach workspace boundaries."""
    pass


# Sensitive file patterns and directories to protect
FORBIDDEN_DIR_NAMES = {".git", ".ssh", ".aws", ".kaggle"}
FORBIDDEN_EXTENSIONS = {".pem", ".key", ".pfx", ".p12"}
FORBIDDEN_FILENAMES = {".env", "id_rsa", "id_ed25519", "credentials", "secrets.yaml"}


def validate_workspace_path(
    target_path: str,
    workspace_root: str = ".",
    allow_write_to_new_file: bool = False,
) -> Path:
    """
    Validate that target_path resolves safely within workspace_root.
    Returns the resolved Path if safe, or raises SandboxSecurityViolation.
    """
    root = Path(workspace_root).resolve()
    target = Path(target_path)

    # If relative, anchor to workspace root
    if not target.is_absolute():
        resolved_target = (root / target).resolve()
    else:
        resolved_target = target.resolve()

    # 1. Path Traversal Check: Target MUST start with workspace root
    try:
        resolved_target.relative_to(root)
    except ValueError:
        raise SandboxSecurityViolation(
            f"Path traversal detected! '{target_path}' resolves to '{resolved_target}', "
            f"which is outside approved workspace '{root}'."
        )

    # 2. Check for forbidden directory traversal (e.g. .git internal objects)
    for part in resolved_target.parts:
        if part in FORBIDDEN_DIR_NAMES and part != root.name:
            raise SandboxSecurityViolation(
                f"Access denied: Path '{target_path}' touches protected directory '{part}'."
            )

    # 3. Check for protected secret files
    if resolved_target.name in FORBIDDEN_FILENAMES:
        raise SandboxSecurityViolation(
            f"Access denied: '{resolved_target.name}' is a protected credentials file."
        )

    if resolved_target.suffix.lower() in FORBIDDEN_EXTENSIONS:
        raise SandboxSecurityViolation(
            f"Access denied: Files with extension '{resolved_target.suffix}' are protected."
        )

    return resolved_target
