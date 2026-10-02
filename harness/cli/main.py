"""
harness/cli/main.py — FreeCompute Unified Interactive CLI Agent.
Provides the local-first coding harness, tool approvals, skill dispatch,
transactional undo, image generation, and Kaggle/GPU telemetry.
"""

from harness.security import safe_print as print
import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from harness.config import HarnessConfig
from harness.cli.formatter import TerminalFormatter, scrubber
from harness.core.client import AuthenticationError, RemoteBrainUnavailableError
from harness.core.models import Message
from harness.core.orchestrator import AgentOrchestrator
from harness.core.prompt import PromptBuilder
from harness.providers.base import Capability, UnsupportedCapabilityError
from harness.providers.llamacpp import LlamaCppProvider
from harness.providers.comfyui import ComfyUIProvider
from harness.skills.manager import SkillManager
from harness.storage.journal import TaskJournal
from harness.storage.undo import UndoManager
from harness.telemetry.quota_ledger import QuotaLedger
from harness.telemetry.session_tracker import SessionTracker
from harness.tools.registry import ToolRegistry


def handle_approval_prompt(tool_name: str, args: Dict[str, Any], fmt: TerminalFormatter) -> bool:
    """Prompt the user in the CLI to approve or reject sensitive tool actions."""
    print()
    print(fmt.yellow("=" * 64))
    print(fmt.bold(f"  >>> [APPROVAL REQUIRED: {tool_name.upper()}] <<<"))
    print(fmt.yellow("=" * 64))

    if tool_name == "edit_file":
        path = args.get("path", "")
        print(f"File to edit: {fmt.bold(path)}")
        old_str = args.get("old_str", "").strip()
        new_str = args.get("new_str", "").strip()
        print(fmt.dim("Proposed replacement:"))
        for line in old_str.splitlines()[:5]:
            print(fmt.red(f"  [-] {scrubber.scrub(line)}"))
        for line in new_str.splitlines()[:5]:
            print(fmt.green(f"  [+] {scrubber.scrub(line)}"))
    elif tool_name == "write_file":
        path = args.get("path", "")
        overwrite = args.get("overwrite", False)
        print(f"File to write: {fmt.bold(path)} (overwrite={overwrite})")
        content = args.get("content", "")
        lines = content.splitlines()
        print(fmt.dim(f"Content preview ({len(content)} chars, {len(lines)} lines):"))
        for line in lines[:8]:
            print(fmt.dim(f"  | {scrubber.scrub(line)}"))
        if len(lines) > 8:
            print(fmt.dim(f"  ... (+ {len(lines) - 8} more lines)"))
    elif tool_name == "run_command":
        cmd = args.get("command", "")
        cwd = args.get("cwd", ".")
        print(f"Command : {fmt.bold(cmd)}")
        print(f"Dir     : {fmt.dim(cwd)}")
    else:
        print(f"Tool: {tool_name} with arguments: {args}")

    while True:
        try:
            choice = input(fmt.bold("\nApprove this action? [y/N]: ")).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(fmt.red("\nAction rejected by user."))
            return False

        if choice in ("y", "yes"):
            print(fmt.green("Action APPROVED."))
            return True
        elif choice in ("", "n", "no"):
            print(fmt.red("Action REJECTED."))
            return False
        print("Please enter 'y' to approve or 'n' to reject.")


def print_status_telemetry(client: Any, session_tracker: SessionTracker, quota_ledger: QuotaLedger, fmt: TerminalFormatter):
    """Fetch and display remote telemetry and quota honestly."""
    try:
        h = client.get_health()
        session_tracker.update_from_remote_health(h.raw)
        st = session_tracker.get_summary()
        qt = quota_ledger.get_summary()
        print("\n" + fmt.cyan("--- REMOTE RUNTIME & QUOTA TELEMETRY ---"))
        print(f"Status           : {fmt.green(h.status.upper()) if h.status == 'healthy' else fmt.red(h.status.upper())}")
        print(f"Connected Uptime : {st['connected_uptime_formatted']}")
        print(f"Session Age Est  : {st['container_uptime_formatted']} (source: {st['session_age_source']})")
        print(f"12h Assumption   : {st['remaining_12h_formatted']}")
        print(f"Weekly Quota Est : {qt['estimated_remaining_hours']}h remaining (last observed: {qt['last_observed_hours']}h)")
        if h.gpus:
            print("GPU Allocations  :")
            for g in h.gpus:
                pct = g.utilization_pct
                print(f"  • CUDA{g.index} ({g.name}): {g.vram_used_mib} / {g.vram_total_mib} MiB ({g.temp_c}°C, util: {pct}%)")
        print(fmt.cyan("-" * 40))
    except Exception as exc:
        print(fmt.red(f"Telemetry query error: {scrubber.scrub(str(exc))}"))


def run_interactive_repl(
    config: HarnessConfig,
    client: Any,
    orchestrator: AgentOrchestrator,
    undo_mgr: UndoManager,
    skills_mgr: SkillManager,
    session_tracker: SessionTracker,
    quota_ledger: QuotaLedger,
    comfy_prov: ComfyUIProvider,
    fmt: TerminalFormatter,
):
    """Main interactive REPL loop."""
    # Preflight health check
    health_summary = {"status": "unverified"}
    try:
        health_resp = client.get_health()
        session_tracker.update_from_remote_health(health_resp.raw)
        health_summary = session_tracker.get_summary()
        health_summary["status"] = "healthy"
        health_summary["gpus"] = [g.dict() if hasattr(g, "dict") else vars(g) for g in health_resp.gpus]
    except AuthenticationError as e:
        print(fmt.red(f"\n[AUTHENTICATION ERROR] {e}"))
        print(fmt.yellow("Verify that FREECOMPUTE_API_KEY matches the key printed by your Kaggle supervisor."))
    except RemoteBrainUnavailableError as e:
        print(fmt.yellow(f"\n[REMOTE STANDBY] Remote GPU endpoint not reachable yet ({e})."))
        print(fmt.dim("Start your Kaggle/remote server notebook and verify the URL.\n"))
    except Exception as e:
        print(fmt.dim(f"\n[PREFLIGHT NOTE] {e}\n"))

    fmt.print_banner(
        remote_url=config.remote_url,
        model_alias=config.model_alias,
        workspace_path=str(Path(config.workspace_root).resolve()),
        health_summary=health_summary,
    )

    history: List[Message] = []

    while True:
        try:
            prompt_label = fmt.bold(fmt.cyan("freecompute> "))
            user_input = input(prompt_label).strip()
        except (KeyboardInterrupt, EOFError):
            print(fmt.dim("\nExiting FreeCompute. Remember to Stop Session in Kaggle to preserve GPU quota!"))
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        # Built-in Slash Commands
        if cmd in ("exit", "quit", "/exit", "/quit"):
            print(fmt.dim("Session ended. Remember to Stop Session on Kaggle when done."))
            break

        if cmd in ("/status", "/health"):
            print_status_telemetry(client, session_tracker, quota_ledger, fmt)
            continue

        if cmd.startswith("/quota"):
            parts = user_input.split()
            if len(parts) == 2:
                try:
                    hrs = float(parts[1])
                    quota_ledger.set_user_observed_balance(hrs)
                    print(fmt.green(f"Updated user-observed weekly quota to {hrs:.1f} hours."))
                except ValueError:
                    print(fmt.red("Usage: /quota <hours_float> (e.g. /quota 24.5)"))
            else:
                qt = quota_ledger.get_summary()
                print(f"Weekly quota estimate: {qt['estimated_remaining_hours']}h remaining (observed: {qt['last_observed_hours']}h)")
            continue

        if cmd == "/diff":
            last_diff = undo_mgr.get_last_diff()
            if last_diff:
                print(fmt.cyan("\n--- MOST RECENT FILE MODIFICATION ---"))
                for line in last_diff.splitlines():
                    if line.startswith("+"):
                        print(fmt.green(line))
                    elif line.startswith("-"):
                        print(fmt.red(line))
                    else:
                        print(fmt.dim(line))
                print(fmt.cyan("-" * 37))
            else:
                print("No recent file modifications recorded in this session.")
            continue

        if cmd == "/undo":
            res = undo_mgr.undo_last(approval_callback=lambda name, args: handle_approval_prompt(name, args, fmt))
            if res.get("status") == "success":
                action = res.get("action", "restored")
                path = res.get("file_path", "")
                print(fmt.green(f"Successfully {action} file: {path}"))
            elif res.get("status") == "empty":
                print(fmt.yellow("No recorded file changes available to undo."))
            else:
                print(fmt.red(f"Undo failed: {res.get('error')}"))
            continue

        if cmd in ("/skills", "/skills list"):
            print(fmt.cyan("\n" + skills_mgr.format_skills_list() + "\n"))
            continue

        if cmd == "/model":
            print(fmt.cyan("\n--- ACTIVE MODEL CONFIGURATION ---"))
            print(f"Model Alias     : {config.model_alias}")
            print(f"Max Context     : {config.max_context_tokens} tokens")
            print(f"Remote Endpoint : {scrubber.scrub(config.remote_url)}")
            print(f"Image Server    : {scrubber.scrub(config.image_server_url) or 'Not configured'}")
            print(f"Transport Mode  : {config.transport}")
            print(fmt.cyan("-" * 34))
            continue

        if cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        if cmd == "/help":
            print(fmt.bold("\nFREECOMPUTE COMMAND REFERENCE:"))
            print("  /status          Display Kaggle container uptime, 12h cap, and GPU VRAM")
            print("  /quota <hours>   Set user-observed weekly GPU quota from Kaggle dashboard")
            print("  /skills          List all discovered skills and slash commands")
            print("  /diff            Inspect the unified diff from the last file modification")
            print("  /undo            Revert the last file write or edit made by the agent")
            print("  /image <prompt>  Generate an image via ComfyUI (requires image server)")
            print("  /image-server    Set or view ComfyUI image server URL")
            print("  /model           Show active model engine, context window, and endpoint")
            print("  /clear           Clear the terminal console")
            print("  exit / quit      Exit the CLI")
            print(fmt.dim("  <any prompt>     Execute coding task with sandboxed tools and approval gates\n"))
            continue

        # Check for image server configuration
        if cmd.startswith("/image-server"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                new_url = parts[1].strip()
                comfy_prov.server_url = new_url.rstrip("/")
                scrubber.register_secret(comfy_prov.server_url)
                print(fmt.green(f"ComfyUI image server updated to: {scrubber.scrub(comfy_prov.server_url)}"))
            else:
                current = comfy_prov.server_url or "Not configured"
                print(fmt.cyan(f"Current image server: {scrubber.scrub(current)}"))
                print(fmt.yellow("Usage: /image-server <URL> (e.g. /image-server https://xxxx.trycloudflare.com)"))
            continue

        # Check for image generation request
        if cmd.startswith("/image"):
            prompt_text = user_input[6:].strip()
            if not prompt_text:
                print(fmt.yellow("Usage: /image <prompt description>"))
                continue
            if not comfy_prov.server_url:
                print(fmt.red("\n[CAPABILITY ERROR] ComfyUI image server is not configured."))
                print(fmt.yellow("To enable image generation:"))
                print("  1. Launch the ComfyUI notebook on Kaggle/Colab (e.g. qwen_image_2_1_kaggle.ipynb).")
                print("  2. Set FREECOMPUTE_IMAGE_SERVER in your .env or pass --image-server <URL>.")
                continue
            print(fmt.cyan(f"\n● [IMAGE GEN] Submitting prompt: \"{prompt_text}\""))
            try:
                res = comfy_prov.generate_image(prompt=prompt_text)
                print(fmt.green(f"● [IMAGE SAVED] Generated image downloaded to: {res['file_path']}"))
                # Try opening on Windows
                if os.name == "nt":
                    try:
                        os.startfile(res['file_path'])
                    except Exception:
                        pass
            except Exception as exc:
                print(fmt.red(f"● [IMAGE ERROR] {scrubber.scrub(str(exc))}"))
            continue

        # Check if the user invoked a registered skill
        target_prompt = user_input
        first_token = user_input.split()[0].lower()
        active_skill = skills_mgr.get_skill(first_token)
        if active_skill:
            skill_args = user_input[len(first_token):].strip()
            target_prompt = skills_mgr.build_skill_prompt(active_skill, skill_args)
            print(fmt.cyan(f"● [SKILL ACTIVATED] Executing '{active_skill.name}' workflow..."))

        # Execute coding / reasoning task
        print()
        fmt.print_phase("TASK", target_prompt[:120] + ("..." if len(target_prompt) > 120 else ""))

        in_thinking = False
        first_token_time: Optional[float] = None
        turn_start_time = time.time()
        token_count = 0

        def on_phase(phase: str, detail: str):
            nonlocal in_thinking
            if in_thinking:
                in_thinking = False
                sys.stdout.write("\n")
                sys.stdout.flush()
            fmt.print_phase(phase, detail)

        def on_reasoning(tok: str):
            nonlocal in_thinking, first_token_time
            if first_token_time is None:
                first_token_time = time.time()
            if not in_thinking:
                in_thinking = True
                sys.stdout.write("\n" + fmt.dim("💭 [Thinking] "))
                sys.stdout.flush()
            sys.stdout.write(tok)
            sys.stdout.flush()

        def on_token(tok: str):
            nonlocal in_thinking, first_token_time, token_count
            token_count += 1
            if first_token_time is None:
                first_token_time = time.time()
            if in_thinking:
                in_thinking = False
                sys.stdout.write("\n\n")
                sys.stdout.flush()
            sys.stdout.write(tok)
            sys.stdout.flush()

        def on_tool_proposed(name: str, args: Dict[str, Any]):
            nonlocal in_thinking
            if in_thinking:
                in_thinking = False
                sys.stdout.write("\n")
                sys.stdout.flush()
            fmt.print_tool_proposal(name, args)

        def on_tool_executed(name: str, res: Dict[str, Any]):
            fmt.print_tool_result(name, res)

        def approval_callback(name: str, args: Dict[str, Any]) -> bool:
            return handle_approval_prompt(name, args, fmt)

        try:
            result = orchestrator.run_task(
                user_prompt=target_prompt,
                conversation_history=history,
                on_token=on_token,
                on_reasoning=on_reasoning,
                on_phase_change=on_phase,
                on_tool_proposed=on_tool_proposed,
                on_approval_request=approval_callback,
                on_tool_executed=on_tool_executed,
            )
            history = result["history"]

            # Display truthful speed and latency telemetry
            duration = time.time() - turn_start_time
            ttft_ms = ((first_token_time - turn_start_time) * 1000.0) if first_token_time else 0.0
            if token_count > 0:
                fmt.print_streaming_stats(ttft_ms=result.get("ttft_ms") or ttft_ms, total_tokens=(result.get("usage") or {}).get("completion_tokens"), duration_sec=duration)
            print()

        except KeyboardInterrupt:
            orchestrator.cancellation_token.cancel()
            print(fmt.yellow("\n[STOP REQUESTED] Local loop interrupted; remote inference outcome unknown."))
        except UnsupportedCapabilityError as exc:
            print(fmt.red(f"\n[CAPABILITY ERROR] {exc}"))
        except Exception as exc:
            clean_err = scrubber.scrub(str(exc))
            print(fmt.red(f"\n[ERROR] Task execution failed: {type(exc).__name__}: {clean_err}"))


def _main():
    parser = argparse.ArgumentParser(
        prog="freecompute",
        description="FreeCompute: Local-first AI agent harness powered by remote GPU inference.",
    )
    parser.add_argument("subcommand", nargs="?", default="agent", choices=["agent", "image", "status"], help="Subcommand to run")
    parser.add_argument("--remote-url", type=str, default="", nargs="?", const="", help="Remote Kaggle supervisor URL")
    parser.add_argument("--api-key", type=str, default="", nargs="?", const="", help="Bearer token for Kaggle supervisor")
    parser.add_argument("--image-server", type=str, default="", nargs="?", const="", help="Remote ComfyUI image server URL")
    parser.add_argument("--workspace", type=str, default="", nargs="?", const="", help="Local workspace directory")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--observe-quota", type=float, default=None, help="Set user-observed quota balance (hours)")
    parser.add_argument("--prompt", type=str, default="", help="Prompt for direct image or task execution")
    args = parser.parse_args()

    scrubber.register_secret(args.api_key)
    config = HarnessConfig.load(args.config)
    if args.remote_url:
        config.remote_url = args.remote_url
    if args.api_key:
        config.api_key = args.api_key
    if args.image_server:
        config.image_server_url = args.image_server
    if args.workspace:
        config.workspace_root = args.workspace

    workspace_root = str(Path(config.workspace_root).resolve())

    # Configure secret redaction
    scrubber.register_secret(config.api_key)
    scrubber.register_secret(config.remote_url)
    scrubber.register_secret(config.image_server_url)

    # Initialize subsystems
    fmt = TerminalFormatter()
    session_tracker = SessionTracker()
    quota_ledger = QuotaLedger(storage_path=str(Path(config.journal_dir) / "quota_ledger.json"))
    journal = TaskJournal(journal_dir=config.journal_dir)
    undo_mgr = UndoManager(workspace_root=workspace_root, storage_dir=config.journal_dir)
    skills_mgr = SkillManager(workspace_root=workspace_root)
    prompt_builder = PromptBuilder()
    tool_registry = ToolRegistry(workspace_root=workspace_root, undo_manager=undo_mgr)

    # Model providers
    llama_prov = LlamaCppProvider(
        base_url=config.remote_url,
        api_key=config.api_key,
        model_alias=config.model_alias,
        timeout_seconds=config.request_timeout_seconds,
    )
    comfy_prov = ComfyUIProvider(server_url=config.image_server_url, workspace_root=workspace_root)

    if args.observe_quota is not None:
        quota_ledger.set_user_observed_balance(args.observe_quota)
        print(f"[QUOTA] Set user-observed balance to {args.observe_quota:.1f} hours.")

    # Direct CLI subcommands
    if args.subcommand == "status":
        print_status_telemetry(llama_prov.client, session_tracker, quota_ledger, fmt)
        return

    if args.subcommand == "image":
        prompt_text = args.prompt
        if not prompt_text:
            prompt_text = input("Enter image generation prompt: ").strip()
        if not prompt_text:
            print("No prompt provided. Exiting.")
            return
        if not comfy_prov.server_url:
            print(fmt.red("Error: ComfyUI server URL not configured. Pass --image-server or set FREECOMPUTE_IMAGE_SERVER."))
            return
        print(f"Generating image for: \"{prompt_text}\"...")
        res = comfy_prov.generate_image(prompt=prompt_text)
        print(fmt.green(f"Image saved to: {res['file_path']}"))
        return

    # Default interactive REPL
    orchestrator = AgentOrchestrator(
        client=llama_prov.client,
        prompt_builder=prompt_builder,
        tool_registry=tool_registry,
        journal=journal,
        session_tracker=session_tracker,
        quota_ledger=quota_ledger,
        undo_manager=undo_mgr,
    )

    run_interactive_repl(
        config=config,
        client=llama_prov.client,
        orchestrator=orchestrator,
        undo_mgr=undo_mgr,
        skills_mgr=skills_mgr,
        session_tracker=session_tracker,
        quota_ledger=quota_ledger,
        comfy_prov=comfy_prov,
        fmt=fmt,
    )


def main():
    try:
        _main()
    except Exception as exc:
        print(f"FreeCompute error: {scrubber.scrub(exc)}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
