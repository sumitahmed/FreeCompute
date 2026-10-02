"""
harness/cli/formatter.py — Terminal UI formatter, Markdown printer, and Secret Scrubber for FreeCompute.
"""

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set


from harness.security import SecretScrubber, scrubber, safe_print as print


class TerminalFormatter:
    """
    Renders styled terminal messages, code blocks, diffs, and activity milestones
    using standard ANSI sequences or clean plain-text fallback.
    """

    # ANSI color codes
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"

    # Foreground
    FG_CYAN = "\033[36m"
    FG_GREEN = "\033[32m"
    FG_YELLOW = "\033[33m"
    FG_RED = "\033[31m"
    FG_BLUE = "\033[34m"
    FG_MAGENTA = "\033[35m"
    FG_WHITE = "\033[37m"
    FG_GRAY = "\033[90m"

    def __init__(self, use_colors: bool = True):
        # Disable ANSI colors if Windows console doesn't support it or if NO_COLOR is set
        if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
            self.use_colors = False
        else:
            self.use_colors = use_colors

    def _c(self, code: str, text: str) -> str:
        text = scrubber.scrub(text)
        if not self.use_colors:
            return text
        return f"{code}{text}{self.RESET}"

    def bold(self, text: str) -> str:
        return self._c(self.BOLD, text)

    def dim(self, text: str) -> str:
        return self._c(self.DIM, text)

    def cyan(self, text: str) -> str:
        return self._c(self.FG_CYAN, text)

    def green(self, text: str) -> str:
        return self._c(self.FG_GREEN, text)

    def yellow(self, text: str) -> str:
        return self._c(self.FG_YELLOW, text)

    def red(self, text: str) -> str:
        return self._c(self.FG_RED, text)

    def gray(self, text: str) -> str:
        return self._c(self.FG_GRAY, text)

    def print_banner(
        self,
        remote_url: str,
        model_alias: str,
        workspace_path: str,
        health_summary: Dict[str, Any],
        version: str = "0.1.0",
    ):
        """Render the FreeCompute startup banner."""
        scrubbed_url = scrubber.scrub(remote_url)
        print()
        print(self.cyan("=" * 76))
        print(self.bold(f"  ⚡ FREECOMPUTE — AGENT HARNESS (v{version})"))
        print(self.dim("  Local-first AI pair programmer powered by remote GPU inference"))
        print(self.cyan("=" * 76))
        print(f"  Remote Brain  : {self.bold(scrubbed_url)}")
        print(f"  Model Engine  : {self.bold(model_alias)}")
        print(f"  Workspace     : {self.dim(workspace_path)}")

        status = health_summary.get("status", "unverified")
        if status == "healthy":
            container_age = health_summary.get("container_uptime_formatted", "Unknown")
            rem_12h = health_summary.get("remaining_12h_formatted", "Unknown")
            print(f"  Remote State  : {self.green('ONLINE')} | Session age estimate: {container_age} | 12h assumption: {rem_12h}")
            gpus = health_summary.get("gpus", [])
            if gpus:
                gpu_info = ", ".join(
                    f"GPU{g.get('index', i)} {g.get('vramUsedMiB', 0)}MB/{g.get('vramTotalMiB', 0)}MB"
                    for i, g in enumerate(gpus)
                )
                print(f"  VRAM Memory   : {self.dim(gpu_info)}")
        else:
            print(f"  Remote State  : {self.yellow('STANDBY / UNVERIFIED')} (will connect on first task)")

        print(self.cyan("=" * 76))
        print(self.dim("  Commands: /status, /skills, /diff, /undo, /quota <hrs>, /help, exit"))
        print(self.cyan("-" * 76))
        print()

    def print_phase(self, phase: str, detail: str):
        """Print an authoritative agent phase change (e.g. INFERENCE, EXECUTION)."""
        clean_detail = scrubber.scrub(detail)
        tag = self.cyan(f"[{phase.upper()}]")
        print(f"● {tag} {clean_detail}")

    def print_tool_proposal(self, tool_name: str, args: Dict[str, Any]):
        """Render a clean tool proposal tag."""
        if tool_name == "edit_file":
            path = args.get("path", "")
            print(f"\n● Proposing edit to {self.bold(path)}")
        elif tool_name == "write_file":
            path = args.get("path", "")
            print(f"\n● Proposing write to {self.bold(path)}")
        elif tool_name == "run_command":
            cmd = args.get("command", "")
            print(f"\n● Proposing command: {self.bold(cmd)}")
        elif tool_name == "search_web":
            query = args.get("query", "")
            print(f"\n● Proposing web search: \"{self.bold(query)}\"")
        elif tool_name == "fetch_url":
            url = args.get("url", "")
            print(f"\n● Proposing web fetch: {self.dim(scrubber.scrub(url))}")
        else:
            print(f"\n● Proposing tool call: {self.bold(tool_name)}")

    def print_tool_result(self, tool_name: str, res: Dict[str, Any]):
        """Render tool execution output with clear visual demarcation."""
        if res.get("outcome_unknown"):
            print(f"● {self.yellow('[OUTCOME UNKNOWN]')}: {tool_name} requires reconciliation.")
        elif res.get("status") == "rejected":
            print(f"● {self.yellow('[TOOL DENIED]')}: {scrubber.scrub(res.get('message', 'Approval required'))}")
        elif res.get("status") == "reconciled":
            print(f"● {self.yellow('[RECONCILED]')}: {tool_name}: {res.get('outcome')}; explicit operator decision.")
        elif "error" in res:
            print(f"● {self.red('[TOOL ERROR]')}: {scrubber.scrub(res['error'])}")
        elif "diff" in res:
            diff_text = res["diff"]
            tag = '[RECORDED PATCH]' if res.get('receipt_replayed') else '[PATCH APPLIED]'
            print(f"● {self.green(tag)}:")
            for line in diff_text.splitlines()[:15]:
                if line.startswith("+"):
                    print(self.green(f"  {line}"))
                elif line.startswith("-"):
                    print(self.red(f"  {line}"))
                else:
                    print(self.dim(f"  {line}"))
            if len(diff_text.splitlines()) > 15:
                print(self.dim(f"  ... (+ {len(diff_text.splitlines()) - 15} more lines)"))
        elif "exit_code" in res:
            code = res["exit_code"]
            tag = self.green("[EXIT 0]") if code == 0 else self.red(f"[EXIT {code}]")
            duration = res.get('duration_ms', 0.0) / 1000 if 'duration_ms' in res else res.get('duration_seconds', 0.0)
            label = 'Recorded command result' if res.get('receipt_replayed') else 'Command finished'
            print(f"● {tag} {label} in {duration:.2f}s")
            stdout = res.get("stdout", "").strip()
            stderr = res.get("stderr", "").strip()
            if stdout:
                lines = stdout.splitlines()
                preview = lines[:8]
                for l in preview:
                    print(f"  {self.dim(scrubber.scrub(l))}")
                if len(lines) > 8:
                    print(self.dim(f"  ... ({len(lines) - 8} more stdout lines)"))
            if stderr:
                lines = stderr.splitlines()
                for l in lines[:5]:
                    print(f"  {self.yellow(scrubber.scrub(l))}")
        elif "results" in res and "count" in res:
            print(f"● {self.green('[SEARCH RESULTS]')}: Found {res['count']} results for \"{res.get('query')}\"")
            for r in res.get("results", [])[:3]:
                title = r.get("title", "")
                url = scrubber.scrub(r.get("url", ""))
                print(f"   • {self.bold(title)} — {self.dim(url)}")
        elif "chars_extracted" in res:
            print(f"● {self.green('[FETCH SUCCESS]')}: Extracted {res['chars_extracted']} characters from {scrubber.scrub(res.get('url', ''))}")
        else:
            print(f"● {self.green('[SUCCESS]')}: {tool_name} completed successfully.")

    def print_streaming_stats(self, ttft_ms: float, total_tokens: Optional[int], duration_sec: float):
        """Print inference telemetry (TTFT, tokens, speed) cleanly."""
        tokens = str(total_tokens) if total_tokens is not None else "unknown"
        stats = f"TTFT: {ttft_ms:.0f}ms | Server tokens: {tokens} | Task elapsed: {duration_sec:.1f}s"
        print(f"\n{self.dim(stats)}")
