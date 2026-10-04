"""
harness/tools/terminal.py — Sandboxed Local Command Runner.
Executes shell commands (tests, builds, git status) under the workspace root with timeout.
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

from harness.security import scrubber
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
    cancellation_token=None,
) -> Dict[str, Any]:
    """
    Run a terminal command securely within the workspace.
    Captures stdout, stderr, return code, and execution time.
    """
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        # Match the format utility, not harmless -Format flags or format() calls.
        matched = (re.search(r"(?<![\w-])format(?:\.com|\.exe)?(?=\s|$|[\"'/&|;])", cmd_lower)
                   if blocked == "format" else blocked in cmd_lower)
        if matched:
            raise SandboxSecurityViolation(f"Blocked hazardous command pattern: '{blocked}'")

    working_dir = validate_workspace_path(cwd or ".", workspace_root)
    if not working_dir.is_dir():
        raise NotADirectoryError(f"Working directory does not exist: '{working_dir}'")

    start_time = time.monotonic()
    if cancellation_token and cancellation_token.is_cancelled:
        return {"status": "rejected", "message": "Cancellation requested before subprocess start"}
    with subprocess.Popen(command, cwd=str(working_dir), shell=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, errors="replace") as process:
        timed_out = False
        requested = False
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                requested = bool(cancellation_token and cancellation_token.is_cancelled)
                timed_out = time.monotonic() - start_time >= timeout_seconds
                if requested or timed_out:
                    process.kill()
                    # A descendant can retain pipe handles. Never wait indefinitely
                    # or claim killing the shell confirmed the entire process tree.
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        stdout, stderr = "", "Output pipes still held by descendants"
                        process.stdout.close()
                        process.stderr.close()
                    process.wait(timeout=1)
                    break
        return scrubber.structured({"command": command, "cwd": str(working_dir.relative_to(Path(workspace_root).resolve())),
                "exit_code": -1 if timed_out else process.returncode, "stdout": stdout[-8000:],
                "stderr": f"Command timed out after {timeout_seconds} seconds." if timed_out else stderr[-8000:],
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1), "timed_out": timed_out,
                "cancellation_requested": requested, "owned_process_exit_confirmed": process.poll() is not None,
                "descendant_cancellation": "unknown" if requested or timed_out else "not_requested"})
