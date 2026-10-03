"""Build/install the CLI in isolation and verify real effects against loopback inference.

Explicit test tooling, never packaged/default product behavior. No Kaggle or GPU.
Run: python tests/runtime/cli_release_acceptance.py --output-dir <new temp directory>
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import venv
import zipfile

from cli_fixture import TOKEN, configuration, start_fixture, workspace_files

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", help="New external directory; existing data is never reset")
    args = parser.parse_args()
    root = Path(args.output_dir or tempfile.mkdtemp(prefix="fc-cli-wheel-")).resolve()
    if root.is_relative_to(REPO):
        raise ValueError("Acceptance must run outside the repository")
    root.mkdir(parents=True, exist_ok=True)
    source, environment = root / "source", root / "installed"
    if source.exists() or environment.exists():
        raise ValueError("Choose a fresh output directory; existing environments are preserved")
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO / name, source / name)
    shutil.copytree(REPO / "harness", source / "harness", ignore=shutil.ignore_patterns("experiments", "__pycache__", "*.pyc"))
    env = {k:v for k,v in os.environ.items() if not k.startswith(("FREECOMPUTE_", "HARNESS_", "RELAYFORGE_")) and k not in {"PYTHONPATH", "FC_FIXTURE_KEY"}}
    env.update(LOCALAPPDATA=str(root / "state"), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
    results, transcripts = [], []

    def record(name, **evidence):
        results.append({"case": name, "result": "passed", **evidence})
        print("PASS " + name, flush=True)

    def setup_run(command):
        process = subprocess.run(command, cwd=root, env=env, text=True, encoding="utf-8", capture_output=True, timeout=240)
        if process.returncode:
            raise RuntimeError("Package setup failed: " + process.stderr[-2000:])
        return process

    print("Building a source snapshot outside the repository...", flush=True)
    setup_run([sys.executable, "-m", "pip", "wheel", "--quiet", "--disable-pip-version-check", "--no-deps", "--no-cache-dir", "--wheel-dir", str(root / "wheels"), str(source)])
    wheel = next((root / "wheels").glob("freecompute-*.whl"))
    with zipfile.ZipFile(wheel) as bundle:
        names = bundle.namelist()
        assert not any("experiments/" in p or "apps/" in p or "harness/api/" in p or p.endswith(".env") for p in names), names
        shipped = [p for p in names if p.startswith("harness/") and p.endswith(".py")]
        expected = {str(p.relative_to(source)).replace("\\", "/") for p in (source / "harness").rglob("*.py")}
        assert set(shipped) == expected
        for name in shipped:
            assert bundle.read(name) == (source / name).read_bytes(), name
        assert "harness/config.sample.yaml" in names
    record("wheel inventory and byte comparison", python_files=len(shipped), wheel=wheel.name,
           sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
    print("Installing into a clean virtual environment...", flush=True)
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    executable = scripts / ("freecompute.exe" if os.name == "nt" else "freecompute")
    setup_run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-cache-dir", str(wheel)])
    location = setup_run([str(python), "-c", "import harness; print(harness.__file__)"]).stdout.strip()
    assert Path(location).is_relative_to(environment)
    setup_run([str(python), "-c", "import importlib.util; assert importlib.util.find_spec('openhands') is None; import harness.cli.main, harness.core.service"])
    record("clean wheel install/import without optional SDK", import_path=location)
    workspace = root / "project with spaces π"
    workspace.mkdir()
    workspace_files(workspace)
    server, thread = start_fixture(str(python))
    config = root / "config.yaml"
    config.write_text(json.dumps(configuration(workspace, f"http://127.0.0.1:{server.server_port}")), encoding="utf-8")
    (root / ".env").write_text("FC_FIXTURE_KEY=" + TOKEN + "\n", encoding="utf-8")

    def cli(name, text="/exit\n", extra=(), configured=True, expected=0, use_env=None):
        command = [str(executable)]
        if configured: command += ["--config", str(config)]
        process = subprocess.run([*command, *extra], cwd=workspace, env=use_env or env, input=text, capture_output=True,
                                 text=True, encoding="utf-8", timeout=40)
        output = process.stdout + process.stderr
        assert process.returncode == expected, (name, process.returncode, output)
        assert TOKEN not in output and "Traceback" not in output and "HIDDEN_FIXTURE_REASONING" not in output, (name, output)
        transcripts.append({"case": name, "stdout": process.stdout, "stderr": process.stderr, "exit": process.returncode})
        return output

    def db_path():
        key = hashlib.sha256(os.path.normcase(str(workspace.resolve())).encode()).hexdigest()
        return root / "state" / "FreeCompute" / "workspaces" / key / "runtime.sqlite3"

    def query(sql, params=()):
        with contextlib.closing(sqlite3.connect(db_path())) as db:
            return db.execute(sql, params).fetchall()

    try:
        assert "Local CLI" in cli("help", extra=("--help",))
        assert "FreeCompute 0.1.0" in cli("version", extra=("--version",))
        record("installed console entrypoint/help/version")
        out = cli("first run without env/config", configured=False)
        assert "No worker configured" in out and "Status     unconfigured" in out
        out = cli("invalid URL", extra=("--remote-url", "not-a-url"), configured=False, expected=1)
        assert "Configuration error" in out
        record("first-run guidance and invalid configuration")
        wrong_env = dict(env, FC_FIXTURE_KEY="SYNTHETIC_WRONG_FIXTURE_KEY")
        out = cli("wrong key", use_env=wrong_env)
        assert "Authentication failed" in out and not server.requests
        record("wrong key is actionable; no inference dispatch")
        out = cli("commands and model selection", "/help\n/help recovery\n/status\n/workers\n/models\n/model chat fixture-chat-worker\n/model code fixture-code-worker\n/skills\n/new\n/sessions\n/run-next\n/cancel\n/image\n/image-server\n/clear\n/typo\n/exit\n")
        assert "Profile   chat" in out and "Profile   code" in out and "Unknown command" in out
        assert "No active task to cancel" in out and not server.requests
        assert "No queued task currently has an eligible free worker" in out and "Recorded task outcome" not in out
        record("slash commands, explicit model/worker selection and safe unknown command")

        out = cli("read edit test", "fix calculator\ny\ny\n/diff\n/exit\n")
        assert "Reading calculator.py" in out and "Edit requested" in out and "Run command?" in out
        assert "Ran 2 tests" in out and "OK" in out and "Command exited 0" in out
        assert out.count("FIXTURE FINAL:") == 1 and "tests exited 0" in out
        assert "return a / b" in (workspace / "calculator.py").read_text()
        assert (workspace / "test-run-count.txt").read_text() == "1"
        assert len(server.requests) == 4
        assert all(TOKEN not in json.dumps(request) for request in server.requests)
        record("installed read/edit/approve/command/real-test/final/diff", model_turns=4, real_calculator_tests=2)
        sid = query("SELECT id FROM sessions ORDER BY rowid LIMIT 1")[0][0]
        receipts = query("SELECT id,state,result FROM actions ORDER BY rowid")
        count = len(server.requests)
        out = cli("restart resume and deny undo", "/sessions\n/resume " + sid[:8] + "\n/diff\n/undo\nn\n/exit\n")
        assert "Recorded task outcome: completed" in out and "Undo requested" in out and "Action REJECTED" in out
        assert len(server.requests) == count and (workspace / "test-run-count.txt").read_text() == "1"
        assert query("SELECT id,state,result FROM actions ORDER BY rowid")[:len(receipts)] == receipts
        assert "return a / b" in (workspace / "calculator.py").read_text()
        record("restart/resume: no repeated inference/effects; undo denial preserved file")
        out = cli("approve durable undo", "/undo\ny\n/exit\n")
        assert "Undo completed" in out and "return a // b" in (workspace / "calculator.py").read_text()
        assert len(server.requests) == count and (workspace / "test-run-count.txt").read_text() == "1"
        record("approved sealed snapshot undo without inference or test replay")

        out = cli("EOF approval denial", "fix calculator\n")
        assert "Action REJECTED" in out and "tests are not confirmed" in out
        assert "return a // b" in (workspace / "calculator.py").read_text()
        assert (workspace / "test-run-count.txt").read_text() == "1"
        record("EOF denies both edits and commands; no effects")
        out = cli("one-shot prompt", "", extra=("--prompt", "stream only"))
        assert out.count("STREAM_FIRST") == out.count("STREAM_LAST") == 1 and "Unicode π ✓" in out
        record("installed --prompt, Unicode and single streamed final answer")

        server.hold_stream = True
        server.completed.clear()
        process = subprocess.Popen([str(executable), "--config", str(config), "--prompt", "stream only"], cwd=workspace, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        buffer, seen = bytearray(), threading.Event()
        def read_stream():
            while True:
                value = process.stdout.read(1)
                if not value: break
                buffer.extend(value)
                if b"STREAM_FIRST" in buffer: seen.set()
        reader = threading.Thread(target=read_stream, daemon=True); reader.start()
        try:
            assert seen.wait(12) and process.poll() is None and not server.completed.is_set()
        finally:
            server.release.set()
            process.wait(20); reader.join(3)
            process.stdout.close(); process.stderr.close()
            server.hold_stream = False
        assert process.returncode == 0
        record("terminal receives visible text before remote fixture completion")

        server.health = "unhealthy"
        out = cli("offline queue", "/new\nwait until worker recovers\n/queue\n/exit\n")
        assert "unhealthy (observed at startup)" in out and "Waiting for an eligible worker" in out
        task = query("SELECT id FROM tasks WHERE prompt='wait until worker recovers'")[0][0]
        count = len(server.requests)
        cli("cancel queued work", "/cancel " + task + "\n/queue\n/exit\n")
        assert query("SELECT state FROM tasks WHERE id=?", (task,))[0][0] == "cancelled"
        assert len(server.requests) == count
        cli("new recovery queue", "/new\nrecover queued task\n/exit\n")
        server.health = "healthy"
        cli("dispatch recovered queue", "/run-next\n/queue\n/exit\n")
        assert len(server.requests) == count + 1
        assert query("SELECT state FROM tasks WHERE prompt='recover queued task'")[0][0] == "completed"
        record("offline queue persistence, queued cancellation and recovery dispatch")

        out = cli("control characters and secrets", "/new\nterminal controls\necho secret\n/exit\n")
        assert "\x1b" not in out and "\x07" not in out and "[REDACTED_SECRET]" in out
        record("terminal controls blocked and cross-chunk secret redaction")

        server.incomplete = True
        out = cli("incomplete inference", "", extra=("--prompt", "stream only"), expected=1)
        assert "Remote outcome unknown" in out and "Capacity remains held" in out
        task_id, interrupted_sid = query("SELECT id,session_id FROM tasks ORDER BY rowid DESC LIMIT 1")[0]
        count = len(server.requests)
        cli("restart unknown inference", "/resume " + interrupted_sid[:8] + "\n/queue\n/exit\n")
        assert len(server.requests) == count
        assert query("SELECT COUNT(*) FROM inference_leases WHERE state='quarantined'")[0][0] == 1
        record("interrupted stream quarantined across restart without retry")

        # Separate workspace: no held lease from the previous negative case.
        cancel_workspace = root / "cancellation workspace"
        cancel_workspace.mkdir()
        cancel_config = root / "cancel-config.yaml"
        cancel_config.write_text(json.dumps(configuration(cancel_workspace, f"http://127.0.0.1:{server.server_port}")), encoding="utf-8")
        server.incomplete = False
        server.first_chunk.clear(); server.delay = 0.04
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen([str(executable), "--config", str(cancel_config), "--prompt", "long stream"], cwd=cancel_workspace, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        try:
            assert server.first_chunk.wait(12)
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            stdout, stderr = process.communicate(timeout=20)
        except BaseException:
            process.kill(); process.communicate(); raise
        output = (stdout + stderr).decode("utf-8")
        assert "Cancellation requested" in output and "Local task stopped" in output, output
        assert "Remote cancellation unconfirmed" in output and "remote outcome: unknown" in output, output
        assert "Remote cancellation confirmed" not in output
        transcripts.append({"case": "native interrupt cancellation", "stdout": stdout.decode('utf-8'), "stderr": stderr.decode('utf-8'), "exit": process.returncode})
        record("native Windows Ctrl+Break/SIGINT: local stop confirmed, remote acknowledgement unknown", exit=process.returncode,
               signal="CTRL_BREAK_EVENT" if os.name == "nt" else "SIGINT")

        report = {"date": "2026-10-03", "mode": "deterministic loopback inference; real local effects; no GPU",
                  "checks": results, "python": str(python), "executable": str(executable), "wheel": str(wheel), "workspace": str(workspace)}
        (root / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (root / "transcripts.json").write_text(json.dumps(transcripts, indent=2), encoding="utf-8")
        print(f"PASS {len(results)} package acceptance checks. Evidence: {root / 'acceptance.json'}", flush=True)
    finally:
        server.release.set(); server.shutdown(); server.server_close(); thread.join(3)


if __name__ == "__main__":
    main()
