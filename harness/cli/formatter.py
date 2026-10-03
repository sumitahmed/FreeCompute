"""Compact terminal presentation. Core events and receipts are the only authority."""
import os
import re
import shutil
import sys
import time

from harness import __version__
from harness.security import SecretScrubber, scrubber, safe_print as print


def terminal_text(value):
    # Untrusted model/tool text must not move the cursor or emit terminal controls.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", scrubber.scrub(value))


class TerminalFormatter:
    BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
    FG_CYAN, FG_GREEN, FG_YELLOW, FG_RED, FG_GRAY = "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[90m"

    def __init__(self, use_colors=True):
        self.use_colors = bool(use_colors and not os.environ.get("NO_COLOR") and sys.stdout.isatty())

    def _c(self, code, text):
        text = terminal_text(text)
        return f"{code}{text}{self.RESET}" if self.use_colors else text

    def bold(self, text): return self._c(self.BOLD, text)
    def dim(self, text): return self._c(self.DIM, text)
    def cyan(self, text): return self._c(self.FG_CYAN, text)
    def green(self, text): return self._c(self.FG_GREEN, text)
    def yellow(self, text): return self._c(self.FG_YELLOW, text)
    def red(self, text): return self._c(self.FG_RED, text)
    def gray(self, text): return self._c(self.FG_GRAY, text)

    def print_banner(self, remote_url, model_alias, workspace_path, health_summary, version=__version__):
        print("\n" + self.bold(f"FreeCompute {version} · CLI coding agent"))
        print(self.dim("─" * min(72, max(20, shutil.get_terminal_size((80, 24)).columns - 1))))
        print(f"Workspace  {self.dim(workspace_path)}")
        print(f"Model      {self.bold(model_alias)}")
        print(f"Worker     {self.cyan(health_summary.get('worker', 'not configured'))}")
        status = health_summary.get("status", "unverified")
        print(f"Status     {self.green(status) if status == 'healthy' else self.yellow(status)} (observed at startup)"
              if status != "unconfigured" else "Status     unconfigured")
        if "context_capacity" in health_summary:
            print(f"Context    {health_summary['context_capacity']:,} tokens (declared; {health_summary.get('verification', 'unverified')})")
        print(self.dim("/help for commands · Ctrl+C during a task requests local cancellation\n"))

    def print_phase(self, phase, detail):
        print(self.cyan("● ") + terminal_text(detail))

    def print_tool_proposal(self, tool_name, args):
        label = args.get("path") or args.get("command") or args.get("query") or args.get("url") or tool_name
        verbs = {"read_file": "Reading", "list_dir": "Listing", "grep_search": "Searching", "edit_file": "Editing",
                 "write_file": "Writing", "run_command": "Running", "search_web": "Searching web", "fetch_url": "Fetching"}
        self.print_phase("tool", f"{verbs.get(tool_name, 'Executing')} {label}")

    def print_diff(self, text):
        for line in text.splitlines():
            style = self.green if line.startswith("+") else self.red if line.startswith("-") else self.dim
            print(style(line))

    def print_tool_result(self, tool_name, res):
        replay = "Recorded " if res.get("receipt_replayed") else ""
        if res.get("outcome_unknown"):
            print(self.yellow("Local tool outcome unknown; inspect /actions before reconciliation."))
        elif res.get("status") == "rejected":
            print(self.yellow("[TOOL DENIED] " + res.get("message", "Action was not approved")))
        elif res.get("status") == "reconciled":
            print(self.yellow(f"{tool_name}: {res.get('outcome')} (explicit operator decision)"))
        elif "error" in res:
            print(self.red("[TOOL ERROR] " + str(res["error"])))
        elif "exit_code" in res:
            code = res["exit_code"]
            elapsed = res.get("duration_ms", 0) / 1000 if "duration_ms" in res else res.get("duration_seconds", 0)
            print((self.green if code == 0 else self.red)(f"{replay}Command exited {code} · {elapsed:.2f}s"))
            for key in ("stdout", "stderr"):
                lines = res.get(key, "").strip().splitlines()
                for line in lines[:12]:
                    print(self.dim("  " + line))
                if len(lines) > 12:
                    print(self.dim(f"  … {len(lines) - 12} more {key} lines; full result is in the local receipt"))
        elif "diff" in res:
            print(self.green(f"{replay}File change applied"))
        elif tool_name == "read_file":
            print(self.dim(f"Read completed · {res.get('total_lines', res.get('lines_read', 'unknown'))} lines reported"))
        else:
            print(self.dim(f"{replay}{tool_name} completed"))

    def print_streaming_stats(self, ttft_ms, total_tokens, duration_sec):
        parts = [f"Task elapsed: {duration_sec:.1f}s"]
        if ttft_ms is not None:
            parts.append(f"Last request first chunk: {ttft_ms:.0f}ms")
        if total_tokens is not None:
            parts.append(f"Last response tokens (reported): {total_tokens}")
        print(self.dim(" · ".join(parts)))


class TaskPresentation:
    """Keep streamed text separate from activity; never render reasoning or tool JSON."""
    def __init__(self, fmt):
        self.fmt, self.started = fmt, time.monotonic()
        self.line_open, self.text_seen, self.first_text = False, False, None
        self.proposals, self.terminal_detail = {}, ""

    def boundary(self):
        if self.line_open:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.line_open = False

    def token(self, text):
        clean = terminal_text(text)
        if not clean:
            return
        if self.first_text is None:
            self.first_text = time.monotonic() - self.started
        self.text_seen = True
        sys.stdout.write(clean)
        sys.stdout.flush()
        self.line_open = not clean.endswith("\n")

    def proposed(self, name, args):
        self.proposals[name] = args

    def phase(self, phase, detail):
        if phase in {"started", "queued", "waiting_approval"}:
            return
        self.boundary()
        if phase == "requesting_model":
            self.fmt.print_phase(phase, f"Waiting for model · {detail}")
        elif phase == "executing_tool":
            self.fmt.print_tool_proposal(detail, self.proposals.get(detail, {}))
        elif phase in {"waiting", "recovering"}:
            self.fmt.print_phase(phase, detail)
        else:
            self.terminal_detail = detail

    def executed(self, name, result):
        self.boundary()
        self.fmt.print_tool_result(name, result)

    def approval(self, name, args, resolver):
        self.boundary()
        return resolver(name, args)

    def finish(self, result):
        self.boundary()
        status = result["status"]
        detail = self.terminal_detail or result.get("detail", "")
        if detail.startswith("Recorded task outcome:"):
            print(self.fmt.dim(detail))
        elif status == "completed":
            print(self.fmt.green("✓ Task completed"))
        elif status == "context_overflow":
            print(self.fmt.yellow("Context limit reached. Use /new or reduce the request/context."))
        elif status in {"queued", "waiting"}:
            print(self.fmt.yellow("Waiting for an eligible worker. Inspect /queue and /workers; retry with /run-next."))
        elif "authenticat" in detail.lower() or "unauthorized" in detail.lower():
            print(self.fmt.red("Authentication failed. Check the configured FreeCompute worker key."))
        else:
            print(self.fmt.yellow(f"Task {status}: {detail}"))
        cancel = result.get("cancellation") or {}
        if cancel.get("requested"):
            print(self.fmt.yellow("Cancellation requested"))
            if cancel.get("local_stop_confirmed"):
                print("Local task stopped")
            if cancel.get("remote_cancel_confirmed"):
                print("Remote cancellation confirmed")
            else:
                print("Remote cancellation unconfirmed; remote outcome: " + cancel.get("remote_outcome", "unknown"))
        if (result.get('allocation') or {}).get('state') == 'quarantined':
            print(self.fmt.yellow("Remote outcome unknown. Capacity remains held until explicit idle reconciliation."))
        if status in {"paused", "outcome_unknown", "incomplete"} or (result.get('allocation') or {}).get('state') == 'quarantined':
            print(self.fmt.dim("Inspect /queue and /actions. /help recovery explains explicit reconciliation."))
        self.fmt.print_streaming_stats(result.get("ttft_ms"), (result.get("usage") or {}).get("completion_tokens"), time.monotonic() - self.started)
        if result.get("session_id"):
            print(self.fmt.dim(f"Session {result['session_id'][:8]} · use /sessions, then /resume <id> after reopening"))
        print()
