"""
harness/tools/terminal.py — Sandboxed Local Command Runner.
Executes shell commands (tests, builds, git status) under the workspace root with timeout.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

from harness.tools.sandbox import validate_workspace_path, SandboxSecurityViolation

# Commands that are blocked outright for basic system safety
BLOCKED_COMMANDS = {
    "format", "del /f /s /q c:", "rmdir /s /q c:", "shutdown", "reboot",
    ":(){ :|:& };:", "dd if=", "mkfs"
}


def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 60,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """
    Run a terminal command securely within the workspace.
    Captures stdout, stderr, return code, and execution time.
    """
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            raise SandboxSecurityViolation(f"Blocked hazardous command pattern: '{blocked}'")

    working_dir = validate_workspace_path(cwd or ".", workspace_root)
    if not working_dir.is_dir():
        raise NotADirectoryError(f"Working directory does not exist: '{working_dir}'")

    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(working_dir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            errors="replace",
        )
        duration_ms = round((time.monotonic() - start_time) * 1000.0, 1)

        return {
            "command": command,
            "cwd": str(working_dir.relative_to(Path(workspace_root).resolve())),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:] if len(proc.stdout) > 8000 else proc.stdout,
            "stderr": proc.stderr[-8000:] if len(proc.stderr) > 8000 else proc.stderr,
            "duration_ms": duration_ms,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000.0, 1)
        return {
            "command": command,
            "cwd": str(working_dir.relative_to(Path(workspace_root).resolve())),
            "exit_code": -1,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": f"Command timed out after {timeout_seconds} seconds.",
            "duration_ms": duration_ms,
            "timed_out": True,
        }
