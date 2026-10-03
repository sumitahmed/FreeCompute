"""
tests/security_scan.py — Comprehensive Gitleaks-equivalent secret scanner for FreeCompute.
Scans source files, notebooks (cells & outputs), config templates, and proposed commits.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Security pattern definitions matching standard Gitleaks rules
RULES = [
    ("Private Key", re.compile(r"-----BEGIN (?:RSA|OPENSSH|DSA|EC|PGP)?\s*PRIVATE KEY-----", re.IGNORECASE)),
    ("AWS Access Key", re.compile(r"(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}")),
    ("GitHub Personal Token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    ("Tailscale Auth Key", re.compile(r"tskey-auth-[A-Za-z0-9_\-]+")),
    ("HuggingFace User Token", re.compile(r"hf_[A-Za-z0-9]{34,}")),
    ("Slack Token", re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}")),
    ("Discord Webhook", re.compile(r"https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_\-]+")),
    ("Hardcoded Bearer Secret", re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]{16,})", re.IGNORECASE)),
    ("Hardcoded Default API Key", re.compile(r"sk-kaggle-qwen-local-ai")),
    ("Legacy Ephemeral Tunnel", re.compile(r"scientists-microphone-campus-select\.trycloudflare\.com")),
    ("Live Tunnel Leak", re.compile(r"https://[a-z0-9\-]{10,}\.trycloudflare\.com")),
]

# Patterns explicitly permitted (e.g. documentation placeholders, regex patterns)
ALLOWLIST_PATTERNS = [
    re.compile(r"Bearer\s+<TOKEN>", re.IGNORECASE),
    re.compile(r"Bearer\s+\[REDACTED", re.IGNORECASE),
    re.compile(r"your-secure-bearer-token-here"),
    re.compile(r"your-session-api-key-from-kaggle"),
    re.compile(r"your-generated-bearer-token"),
    re.compile(r"test-secret-token"),
    re.compile(r"test-key"),
    re.compile(r"https?://\[tunnel\]\.trycloudflare\.com"),
    re.compile(r"https://xxxx\.trycloudflare\.com"),
    re.compile(r"https://your-tunnel-url\.trycloudflare\.com"),
    re.compile(r"https?://\[a-zA-Z0-9\-\]\+\\\.trycloudflare\\\.com"),
    re.compile(r"https?://\[a-zA-Z0-9\-\]\+\.trycloudflare\.com"),
    re.compile(r"tskey-auth-\.\.\."),
    re.compile(r"\[REDACTED_SECRET\]"),
    re.compile(r"\[REDACTED_TOKEN\]"),
    re.compile(r"\[REDACTED_TAILSCALE_KEY\]"),
    re.compile(r"\[REDACTED_SECRET_KEY\]"),
    re.compile(r"super-secret-token-xyz"),
    re.compile(r"your-custom-secret-key"),
    re.compile(r"https://xyz\.trycloudflare\.com"),
]

EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", ".qwen_harness", "output"}


def is_allowed(line: str) -> bool:
    return any(p.search(line) for p in ALLOWLIST_PATTERNS)


def scan_file(file_path: Path) -> List[Tuple[str, int, str, str]]:
    """Scan a text file or notebook and return list of (rule_name, line_num, line_preview, reason)."""
    findings = []
    
    if file_path.suffix.lower() == ".ipynb":
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                nb = json.load(f)
            cells = nb.get("cells", [])
            for c_idx, cell in enumerate(cells):
                cell_type = cell.get("cell_type", "code")
                # 1. Scan cell source
                sources = cell.get("source", [])
                if isinstance(sources, str):
                    sources = sources.splitlines()
                for l_idx, line in enumerate(sources):
                    if is_allowed(line):
                        continue
                    for rule_name, pattern in RULES:
                        if pattern.search(line):
                            findings.append((rule_name, l_idx + 1, line.strip()[:100], f"Cell {c_idx} source"))
                
                # 2. Scan cell outputs
                outputs = cell.get("outputs", [])
                for o_idx, out in enumerate(outputs):
                    # Check text/plain or stream text
                    text_blocks = []
                    if "text" in out:
                        t = out["text"]
                        text_blocks.extend(t if isinstance(t, list) else [t])
                    if "data" in out and "text/plain" in out["data"]:
                        t = out["data"]["text/plain"]
                        text_blocks.extend(t if isinstance(t, list) else [t])
                    
                    for l_idx, line in enumerate(text_blocks):
                        if is_allowed(line):
                            continue
                        for rule_name, pattern in RULES:
                            if pattern.search(line):
                                findings.append((rule_name, l_idx + 1, line.strip()[:100], f"Cell {c_idx} output {o_idx}"))
        except Exception as exc:
            findings.append(("JSON_PARSE_ERROR", 0, str(exc), "Failed to parse notebook JSON"))
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    if is_allowed(line):
                        continue
                    for rule_name, pattern in RULES:
                        if pattern.search(line):
                            findings.append((rule_name, line_num, line.strip()[:100], "Source text"))
        except Exception:
            pass

    return findings


def run_audit(root_dir: str = ".") -> int:
    print("=" * 72)
    print("  FREECOMPUTE DEEP SECURITY AUDIT & SECRET SCANNER")
    print("=" * 72)
    root = Path(root_dir).resolve()
    all_findings = []
    total_files_scanned = 0

    # Inspect releasable files, not ignored private .env/state or generated GUI caches.
    try:
        inventory = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                   capture_output=True, check=True)
        paths = [root / p for p in inventory.stdout.decode("utf-8").split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS | {"node_modules", "dist", "build"}]
            paths.extend(Path(dirpath) / f for f in filenames if not f.startswith(".env") and f != "config.yaml")
    for p in paths:
        if p.name == "security_scan.py" or not p.is_file() or p.is_symlink():
            continue
        total_files_scanned += 1
        for rule, line_num, line, reason in scan_file(p):
            all_findings.append((p.relative_to(root), rule, line_num, line, reason))

    print(f"Scanned {total_files_scanned} files across repository.")
    print("-" * 72)

    if not all_findings:
        print("[SUCCESS] ZERO SECRETS FOUND. All files clean and safe for release.")
        print("=" * 72)
        return 0

    print(f"[ALERT] FOUND {len(all_findings)} POTENTIAL SECRET LEAKS:")
    for path, rule, line_num, line, reason in all_findings:
        # Reporting a suspected leak must not itself disclose the matched credential.
        print(f"  • {path}:{line_num} [{rule}] ({reason}) [matched content omitted]")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    code = run_audit()
    sys.exit(code)
