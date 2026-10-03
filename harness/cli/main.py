"""FreeCompute CLI. Core owns inference, tools, approvals and durable recovery."""
import argparse
import difflib
import os
from pathlib import Path
import signal
import sys
import traceback

from pydantic import ValidationError

from harness import __version__
from harness.cli.core_client import CoreClient
from harness.cli.commands import CommandRegistry
from harness.cli.input import TerminalInput
from harness.cli.formatter import TerminalFormatter, TaskPresentation, terminal_text
from harness.config import HarnessConfig
from harness.core.service import CoreService
from harness.security import safe_print as print, scrubber


def handle_approval_prompt(tool_name, args, fmt):
    """Only an explicit y/yes approves. EOF, cancellation and broken input deny."""
    print()
    if tool_name == "edit_file":
        print(fmt.bold("Edit requested"))
        path = args.get("path", "")
        print(fmt.bold(path))
        diff = "".join(difflib.unified_diff(
            [line + "\n" for line in args.get("old_str", "").splitlines()], [line + "\n" for line in args.get("new_str", "").splitlines()],
            fromfile="a/" + path, tofile="b/" + path))
        fmt.print_diff(diff)
    elif tool_name == "write_file":
        print(fmt.bold("Write requested"))
        print(fmt.bold(args.get("path", "")))
        print(f"Overwrite existing file: {args.get('overwrite', False)}")
        lines = args.get("content", "").splitlines()
        for line in lines[:40]:
            print(fmt.dim("+ " + line))
        if len(lines) > 40:
            print(fmt.yellow(f"Preview truncated: {len(lines) - 40} more lines in this write"))
    elif tool_name == "run_command":
        print(fmt.bold("Run command?"))
        print(fmt.bold(args.get("command", "")))
        print(fmt.dim("cwd: " + str(args.get("cwd", "."))))
        print(fmt.dim("Approved commands run with your local user privileges."))
    elif tool_name in {"restore_snapshot", "restore_legacy_snapshot"}:
        print(fmt.bold("Undo requested"))
        print(fmt.bold(args.get("path", "")))
        print(args.get("operation", "Restore the recorded snapshot"))
        fmt.print_diff(args.get("diff", ""))
        print(fmt.dim("Core will recheck the current file and sealed snapshot hashes."))
    else:
        print(fmt.bold("Approval required: " + tool_name))
        for name, value in args.items():
            print(fmt.dim(f"{name}: {value}"))
    while True:
        try:
            choice = input(fmt.bold("Approve? [y/N] ")).strip().lower()
        except (EOFError, OSError, KeyboardInterrupt):
            print(fmt.yellow("\nAction REJECTED. No approval input received."))
            return False
        if choice in {"y", "yes"}:
            print(fmt.green("Action APPROVED."))
            return True
        if choice in {"", "n", "no"}:
            print(fmt.yellow("Action REJECTED."))
            return False
        print("Enter y to approve, or Enter/n to deny.")


def _error(exc, fmt, debug=False):
    if isinstance(exc, ValidationError):
        details = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False)[:3]]
        message = "Configuration error\n" + "\n".join(details)
    elif isinstance(exc, FileNotFoundError):
        message = "File/configuration not found. Check the --config and --workspace paths."
    elif isinstance(exc, PermissionError):
        message = "Access denied. Check local file permissions."
    else:
        message = str(exc)
        if "authenticat" in message.lower() or "unauthorized" in message.lower():
            message = "Authentication failed. Check the configured FreeCompute worker key."
        elif "context" in message.lower() and ("exceed" in message.lower() or "budget" in message.lower()):
            message = "Context limit reached. Use /new or reduce the request/context."
        elif any(word in message.lower() for word in ("cannot connect", "connection refused", "timed out", "winerror 10061")):
            message = "Worker unavailable. Check the endpoint and confirm the selected worker is running."
    print(fmt.red(message or "FreeCompute could not complete this operation."), file=sys.stderr)
    if debug:
        print(terminal_text(traceback.format_exc()), file=sys.stderr)


def _has_worker(config):
    return bool(config.workers or config.api_key or "remote_url" in config.model_fields_set)


def _setup_guidance():
    print("No worker configured. Set FREECOMPUTE_API_KEY in .env, then launch with")
    print('freecompute --remote-url "https://YOUR-KAGGLE-URL" or use /connect <URL>.')
    print("A worker config is also supported. Run /help for commands.")


def _connection_problem(error, worker, fmt):
    if "authenticat" in error.lower() or "unauthorized" in error.lower():
        _error(ValueError(error), fmt)
    else:
        print(fmt.yellow(f"Worker {worker} unreachable."))
        print("The endpoint may be offline or the saved tunnel URL may have expired.")
    print("Paste the fresh URL with: /connect https://YOUR-KAGGLE-URL")
    print(fmt.dim("The CLI remains usable; no task was submitted by this health check."))


def _startup(config, client, fmt):
    info = client.model_info()
    summary = {"status": "unconfigured", "context_capacity": info["context_capacity"], "verification": info["verification"]}
    if _has_worker(config):
        health = client.get_health()
        summary["status"] = health.status
        from harness.telemetry.models import normalize
        telemetry = normalize(health.raw)
        names = [str(g['name']['value']) for g in telemetry.gpus if g['name']['value']]
        summary['compute'] = f"{telemetry.metrics['provider']['value'] or 'unknown provider'} | " + (', '.join(names) + ' (observed)' if names else 'hardware unknown')
        if health.raw.get("error"):
            _connection_problem(health.raw["error"], info["selected_worker"] or "selected worker", fmt)
    summary["worker"] = info["selected_worker"] or "any eligible: " + ", ".join(w["worker_id"] for w in info["eligible_workers"])
    image = client.image_model_info()
    if image and client.server_url:
        rows = client._core.list_workers()
        row = next((w for w in rows if w['worker_id'] == image['selected_worker']), {})
        summary['image'] = image['model'] + " | " + row.get('location', 'unknown') + " | " + row.get('health', 'unverified')
    fmt.print_banner(config.remote_url, info["model"], str(Path(config.workspace_root).resolve()), summary)
    if not _has_worker(config):
        _setup_guidance()


def print_status_telemetry(client, session_tracker, quota_ledger, fmt):
    """Only health payload values are observations; timers/quota remain estimates."""
    try:
        health = client.get_health()
        info = client.model_info()
        print(f"Worker {info['selected_worker'] or 'any eligible'} | model {info['model']} (configured) | engine {info['engine']}")
        print(f"Worker status: {fmt.green(health.status) if health.status == 'healthy' else fmt.yellow(health.status)} (observed now)")
        if health.raw.get("error"):
            _connection_problem(health.raw["error"], client.model_info()["selected_worker"] or "selected worker", fmt)
        from harness.cli.telemetry import lines
        for line in lines(health.raw):
            print(terminal_text(line))
        quota = quota_ledger.get_summary()
        if quota['last_observed_hours'] is None:
            print("Weekly quota: unknown; account dashboard is not queried.")
        else:
            print(f"Weekly quota: {quota['last_observed_hours']}h (user-provided, as of {quota['observed_as_of']}; may be stale)")
        print(f"Logged local task wall time: {quota['local_task_wall_time_hours']}h (estimated; separate from provider billing)")
        return health.status == "healthy"
    except Exception as exc:
        _error(exc, fmt)
        return False


def _show_model(client, fmt):
    info = client.model_info()
    print(f"Model     {fmt.bold(info['model'])}")
    print(f"Profile   {info['profile_id']}")
    print(f"Engine    {info['engine']}")
    print(f"Worker    {info['selected_worker'] or 'any eligible worker'}")
    for worker in info["eligible_workers"]:
        print(f"          {worker['worker_id']} · {worker['location']} · {worker['health']}")
    print(f"Context   {info['context_capacity']:,} tokens (declared)")
    print(f"Reserve   {info['reserved_completion']:,} tokens")
    print(f"Evidence  {info['verification']} (configured label, not fresh certification)")
    print(f"Capacity  {info['allocation']['state']}")


def _help(recovery=False, registry=None):
    for line in (registry or CommandRegistry()).help_lines(recovery):
        print(terminal_text(line))
    print("Enter sends; Alt+Enter adds a line. Arrows navigate menus/history; Tab completes; Escape dismisses.")
    print("File changes and commands require explicit approval.")


def _run_task(client, fmt, prompt=None, resume=None, next_task=False, skill=None):
    presentation = TaskPresentation(fmt, client.model_info()['model'])
    resolver = lambda name, args: handle_approval_prompt(name, args, fmt)
    callbacks = dict(on_token=presentation.token, on_phase_change=presentation.phase,
                     on_tool_proposed=presentation.proposed, on_tool_executed=presentation.executed,
                     on_approval_request=lambda n, a: presentation.approval(n, a, resolver))
    # Reasoning events remain in Core; they are never terminal content.
    from harness.cli.live import LiveTelemetry
    try:
        with LiveTelemetry(client, presentation):
            if resume:
                result = client.resume(resume, **callbacks)
            elif next_task:
                result = client.run_next(**callbacks)
            else:
                result = client.run_task(prompt, skill=skill, **callbacks)
    finally:
        presentation.boundary()
    presentation.finish(result)
    return result


def _image(client, prompt, fmt):
    if not prompt:
        raise ValueError("Usage: /image <prompt>")
    if not client.server_url:
        raise ValueError("Image worker unconfigured. Set FREECOMPUTE_IMAGE_SERVER or configure a ComfyUI worker.")
    result = client.generate_image(prompt)
    if result.get("file_path"):
        print(fmt.green("Image saved: " + result["file_path"]))
    else:
        print(fmt.yellow(f"Image task {result.get('task_id')}: {result.get('status')}"))
    return result


def run_interactive_repl(config, client, orchestrator, undo_mgr, skills_mgr, session_tracker, quota_ledger, comfy_prov, fmt, *, debug=False):
    _startup(config, client, fmt)
    registry = CommandRegistry(skills_mgr)
    reader = TerminalInput(registry, client)
    while True:
        try:
            text = reader.read().strip()
        except KeyboardInterrupt:
            print("\nInput cleared. Use /exit or Ctrl+D to leave FreeCompute.")
            continue
        except (EOFError, OSError):
            print("\nLocal state saved. Remote GPU sessions must be stopped separately.")
            return 0
        if not text:
            continue
        command, _, arguments = text.partition(" ")
        command, arguments = registry.canonical(command.lower()), arguments.strip()
        try:
            if command in {"exit", "quit", "/exit", "/quit"}:
                print("Local state saved. Remote GPU sessions must be stopped separately.")
                return 0
            if command == "/help":
                if arguments not in {"", "recovery"}: raise ValueError("Usage: /help [recovery]")
                _help(arguments == "recovery", registry)
            elif command in {"/status", "/health"}:
                print_status_telemetry(client, session_tracker, quota_ledger, fmt)
            elif command == "/connect":
                if not arguments or len(arguments.split()) != 1:
                    raise ValueError("Usage: /connect https://YOUR-KAGGLE-URL")
                result = client.connect(arguments)
                if not config.workers:
                    config.remote_url = arguments
                if result["status"] == "healthy":
                    print(fmt.green(f"Connected: {result['worker_id']} · healthy (observed now)"))
                    print("Advertised models: " + ", ".join(result["models"]))
                    print("Endpoint changed for this run only. Continue with your next prompt.")
                elif result["status"] == "unreachable":
                    _connection_problem(result["error"], result["worker_id"], fmt)
                else:
                    _error(ValueError(result["error"] or "Worker is not ready"), fmt)
                _show_model(client, fmt)
            elif command == "/workers":
                for worker in client.workers():
                    print(fmt.bold(worker['worker_id']) + f" · {worker['location']} · {worker['engine']} · {worker['health']}")
                    print(fmt.dim(f"  held {worker['active_or_quarantined']}/{worker['concurrency_limit']} slots (declared); last healthy {worker['last_seen'] or 'never observed'}"))
                    from harness.cli.telemetry import lines
                    for line in lines(worker['observed_resources'], compact=True):
                        print(terminal_text("  " + line))
                    if worker['observed_resources'].get('error'):
                        _error(ValueError(worker['observed_resources']['error']), fmt)
                    if worker['observed_resources'].get('models') is not None:
                        print("  advertised models (observed): " + ", ".join(worker['observed_resources']['models']))
            elif command == "/models":
                for model in client.models():
                    print(f"{model['profile_id']} · {fmt.bold(model['model'])} · {model['context_capacity']:,} tokens declared · {model['verification']}")
                    print(fmt.dim(f"  capabilities: {', '.join(model['capabilities'])}; workers: {', '.join(model['workers'])}"))
            elif command == "/model":
                if not arguments:
                    _list_routes(client, fmt, "text")
                    arguments = reader.choose(command, client.models()) or ""
                if arguments:
                    parts = arguments.split()
                    if len(parts) not in {1, 2}: raise ValueError("Usage: /model [profile-id] [worker-id]")
                    client.select_model(*parts)
                    print("Route selected for new tasks. Existing queued tasks keep their original route.")
                _show_model(client, fmt)
            elif command == "/image-model":
                if not arguments:
                    _list_routes(client, fmt, "image_gen")
                    arguments = reader.choose(command, [p for p in client.models() if "image_gen" in p["capabilities"]]) or ""
                if arguments:
                    parts = arguments.split()
                    if len(parts) not in {1, 2}: raise ValueError("Usage: /image-model [profile] [worker]")
                    client.select_image_model(*parts)
                info = client.image_model_info()
                print("Image route: " + (info['model'] + " | " + str(info['selected_worker']) if info else "none; use /connect-image <URL> for the supported ComfyUI workflow"))
            elif command == "/queue":
                rows = client.queue()
                if not rows: print("Queue empty.")
                for row in rows:
                    print(f"{row['task_id']} · {row['state']} · profile {row['profile_id']} · worker {row['requested_worker'] or 'any eligible'}")
                    if row['waiting_reason']: print(fmt.dim("  " + row['waiting_reason']))
            elif command == "/sessions":
                rows = client.list_sessions()
                if not rows: print("No saved sessions in this workspace. Enter a task to create one.")
                for row in rows:
                    print(f"{row['id']} · {row['status']} · {row['updated_at']}")
            elif command == "/new":
                if arguments: raise ValueError("Usage: /new")
                client.new_session()
                print("The next prompt will start a new session.")
            elif command == "/resume":
                if not arguments or len(arguments.split()) != 1: raise ValueError("Usage: /resume <session-id>")
                _run_task(client, fmt, resume=arguments)
            elif command == "/run-next":
                _run_task(client, fmt, next_task=True)
            elif command == "/cancel":
                if len(arguments.split()) > 1: raise ValueError("Usage: /cancel [task-id]")
                result = client.cancel(arguments or None)
                if result is None:
                    print("No active task to cancel. Use /queue for queued task IDs.")
                else:
                    print(f"Cancellation state: {result['status']}; remote cancellation remains unconfirmed.")
            elif command == "/diff":
                diff = undo_mgr.get_last_diff()
                if diff: fmt.print_diff(diff)
                else: print("No recorded file changes in this workspace.")
            elif command == "/undo":
                result = undo_mgr.undo_last(lambda n, a: handle_approval_prompt(n, a, fmt))
                if result.get("status") == "success":
                    print(fmt.green(f"Undo completed: {result.get('file_path', '')}"))
                elif result.get("status") == "empty":
                    print("No recorded file changes available to undo.")
                else:
                    print(fmt.yellow("Undo stopped: " + str(result.get('error') or result.get('message') or result.get('status'))))
            elif command == "/skills":
                if arguments not in {"", "list"}: raise ValueError("Usage: /skills")
                skills_mgr.discover_skills()
                for skill in skills_mgr.skills.values():
                    print(f"{skill.slash_command} | {skill.name} ({skill.scope})\n  {skill.description}")
                for diagnostic in skills_mgr.diagnostics:
                    print(fmt.yellow(diagnostic))
            elif command == "/skill":
                if not arguments:
                    for skill in skills_mgr.skills.values():
                        print(f"{skill.name} | {skill.slash_command} | {skill.description}")
                    arguments = reader.choose(command, list(skills_mgr.skills.values())) or ""
                if arguments:
                    name, _, request = arguments.partition(" ")
                    skill = skills_mgr.get_skill(name)
                    if not skill: raise ValueError("Unknown skill. Use /skills.")
                    _run_task(client, fmt, prompt=request or "Execute the skill workflow in the workspace.", skill=skill)
            elif command == "/actions":
                for action in client.actions():
                    print(f"{action['id']} · {action['name']} · {action['state']} · {action['target'] or ''}")
                    print(fmt.dim(f"  current={action['current_hash']} pre={action['pre_hash']} post={action['post_hash']}"))
            elif command == "/reconcile-inference":
                if len(arguments.split()) > 1: raise ValueError("Usage: /reconcile-inference [lease-id]")
                print(client.reconcile_inference(lambda n, a: handle_approval_prompt(n, a, fmt), arguments or None))
            elif command == "/reconcile":
                parts = arguments.split()
                if len(parts) not in {2, 3}: raise ValueError("Usage: /reconcile <action-id> <completed|not_executed> [sha256|absent]")
                witness = parts[2] if len(parts) == 3 and parts[2] != "absent" else None
                print(client.reconcile(parts[0], parts[1], witness, lambda n, a: handle_approval_prompt(n, a, fmt)))
            elif command == "/quota":
                if arguments: quota_ledger.set_user_observed_balance(float(arguments))
                print(quota_ledger.get_summary())
            elif command == "/connect-image":
                if not arguments or len(arguments.split()) != 1: raise ValueError("Usage: /connect-image <URL>")
                result = client.connect_image(arguments)
                print(f"Image worker {result['worker_id']}: {result['status']} (observed now); endpoint changed for this run only")
                if result.get('error'): _error(ValueError(result['error']), fmt)
            elif command == "/image":
                _image(comfy_prov, arguments, fmt)
            elif command == "/clear":
                if sys.stdout.isatty(): os.system("cls" if os.name == "nt" else "clear")
            else:
                skill = skills_mgr.get_skill(command)
                if command.startswith("/") and not skill:
                    raise ValueError("Unknown command. Use /help; no model request was sent.")
                if not _has_worker(config):
                    _setup_guidance()
                    continue
                prompt = arguments or "Execute the skill workflow in the workspace." if skill else text
                if skill: print(fmt.cyan("Skill: " + skill.name))
                _run_task(client, fmt, prompt=prompt, skill=skill)
        except KeyboardInterrupt:
            client.cancellation_token.cancel()
            print(fmt.yellow("Local operation interrupted. External outcomes remain unconfirmed; inspect /queue and /actions."))
        except Exception as exc:
            _error(exc, fmt, debug)


def _list_routes(client, fmt, capability):
    workers = {w['worker_id']: w for w in client._core.list_workers()}
    routes = [p for p in client.models() if capability in p['capabilities']]
    if not routes:
        print("No configured " + capability + " route. " + ("Use /connect-image <URL>." if capability == "image_gen" else "Configure a text worker."))
    for profile in routes:
        context = f"{profile['context_capacity']:,} context declared" if capability == 'text' else 'configured image workflow'
        print(fmt.bold(profile['profile_id']) + f" | {profile['model']} | {', '.join(profile['capabilities'])} | {context}")
        for identity in profile['workers']:
            row = workers.get(identity, {})
            print(f"  {identity} | {row.get('location', 'unknown')} | {row.get('engine', 'unknown')} | health {row.get('health', 'unknown')}")
            from harness.telemetry.models import normalize
            for gpu in normalize(row.get('observed_resources', {})).gpus:
                from harness.cli.telemetry import value
                print("    " + value(gpu['name']) + " | VRAM " + value(gpu['vram_used_mib'], unit=' MiB') + '/' + value(gpu['vram_total_mib'], unit=' MiB'))


def _main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="freecompute", description="Local CLI coding agent with approval-gated tools and configurable inference workers.")
    parser.add_argument("--version", action="version", version="FreeCompute " + __version__)
    parser.add_argument("subcommand", nargs="?", default="agent", choices=["agent", "image", "status"])
    parser.add_argument("--config", help="Worker YAML configuration; .env beside it is also loaded")
    parser.add_argument("--workspace", default="", help="Local project directory (supports spaces and Unicode)")
    parser.add_argument("--remote-url", default="", help="Temporary URL override for the selected text worker; beats the saved config URL")
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)  # Compatibility; prefer private .env/process env.
    parser.add_argument("--image-server", default="", help="Existing legacy ComfyUI endpoint")
    parser.add_argument("--engine", choices=["llama.cpp", "openai-compatible"], help="Legacy single-worker protocol")
    parser.add_argument("--profile", default="", help="Configured model profile ID")
    parser.add_argument("--worker", default="", help="Configured worker ID")
    parser.add_argument("--prompt", default="", help="Run one task, with interactive approvals; nonzero exit if not completed")
    parser.add_argument("--observe-quota", type=float, help="User-observed provider GPU quota in hours")
    parser.add_argument("--debug", action="store_true", help="Include scrubbed error tracebacks; never display model reasoning")
    args = parser.parse_args()
    scrubber.register_secret(args.api_key)
    config = HarnessConfig.load(args.config)
    if config.workers and (args.api_key or args.engine):
        raise ValueError("--api-key and --engine are single-worker flags. Update workers[].api_key_env/engine in the registry config instead.")
    for name, value in (("api_key", args.api_key), ("image_server_url", args.image_server),
                        ("workspace_root", args.workspace), ("engine", args.engine), ("selected_profile", args.profile), ("selected_worker", args.worker)):
        if value: setattr(config, name, value)
    if args.remote_url:
        try:
            config.override_remote_url(args.remote_url)
        except ValueError as exc:
            raise ValueError("Configuration error: " + str(exc)) from None
    for value in (config.api_key, config.remote_url, config.image_server_url): scrubber.register_secret(value)
    workspace = Path(config.workspace_root).resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace directory does not exist. Create it first or pass --workspace <existing-project>.")
    fmt = TerminalFormatter()
    core = CoreService.from_config(config)
    try:
        client = CoreClient(core)
        if args.observe_quota is not None: core.quota.set_user_observed_balance(args.observe_quota)
        if args.subcommand == "status":
            if not _has_worker(config):
                _setup_guidance()
                return 1
            return 0 if print_status_telemetry(client, core.session_tracker, core.quota, fmt) else 1
        if args.subcommand == "image":
            prompt = args.prompt or input("Image prompt: ").strip()
            return 0 if _image(client, prompt, fmt).get("file_path") else 1
        if args.prompt:
            _startup(config, client, fmt)
            if not _has_worker(config): return 1
            result = _run_task(client, fmt, prompt=args.prompt)
            return 0 if result["status"] == "completed" else 1
        return run_interactive_repl(config, client, client, client, core.skills, core.session_tracker, core.quota, client, fmt, debug=args.debug)
    finally:
        core.close()


def _interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main():
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, _interrupt)
    try:
        return _main()
    except KeyboardInterrupt:
        print("Stopped locally. Remote inference/effect outcomes remain unconfirmed.", file=sys.stderr)
        return 130
    except (EOFError, OSError) as exc:
        _error(exc, TerminalFormatter(False), "--debug" in sys.argv)
        return 1
    except Exception as exc:
        _error(exc, TerminalFormatter(False), "--debug" in sys.argv)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
