"""Regression checks for bugs reproduced during the final CLI product pass."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from harness.cli.formatter import TerminalFormatter
from harness.cli.main import handle_approval_prompt
from harness.config import HarnessConfig
from harness.core.engine_config import configured_engines
from harness.storage.runtime import runtime_home

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cli_product_fixture", REPO / "tests/runtime/cli_fixture.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ConfigAndApprovalTests(unittest.TestCase):
    def test_broken_or_missing_approval_input_denies(self):
        for error in (EOFError(), OSError("input closed"), KeyboardInterrupt()):
            with patch("builtins.input", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(handle_approval_prompt("edit_file", {"path": "a.py", "old_str": "old", "new_str": "new"}, TerminalFormatter(False)))

    def test_single_line_diff_keeps_addition_and_deletion_on_separate_lines(self):
        output = io.StringIO()
        with patch("builtins.input", return_value="n"), contextlib.redirect_stdout(output):
            handle_approval_prompt("edit_file", {"path": "a.py", "old_str": "    return a // b", "new_str": "    return a / b"}, TerminalFormatter(False))
        self.assertIn("-    return a // b\n+    return a / b\n", output.getvalue())

    def test_worker_key_uses_config_side_env_and_process_precedence_without_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "worker.yaml"
            path.write_text("{}", encoding="utf-8")
            (root / ".env").write_text("CUSTOM_WORKER_KEY=dotenv-fixture\nFREECOMPUTE_API_KEY=dotenv-key\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {}, clear=True):
                    config = HarnessConfig.load(path)
                    self.assertEqual(config.resolve_api_key("CUSTOM_WORKER_KEY"), "dotenv-fixture")
                    self.assertNotIn("dotenv-fixture", config.model_dump_json())
                    with patch.dict(os.environ, {"CUSTOM_WORKER_KEY": "process-fixture"}):
                        self.assertEqual(config.resolve_api_key("CUSTOM_WORKER_KEY"), "process-fixture")
            finally:
                os.chdir(previous)

    def test_malformed_yaml_does_not_echo_a_private_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text('api_key: [SYNTHETIC_PRIVATE_YAML\n', encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                HarnessConfig.load(path)
            self.assertNotIn("SYNTHETIC_PRIVATE_YAML", str(caught.exception))
            self.assertIn("Invalid YAML", str(caught.exception))

    def test_invalid_ports_and_uncredentialed_remote_text_workers_are_rejected(self):
        for url in ("http://localhost:abc", "http://localhost:0"):
            with self.assertRaises(ValueError): HarnessConfig(remote_url=url)
        with self.assertRaisesRegex(ValueError, "bearer key"):
            configured_engines(HarnessConfig(remote_url="https://worker.example.invalid"), ".")

    def test_config_side_then_cwd_env_then_process_preserve_alias_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir, cwd = root / "configuration", root / "working directory"
            config_dir.mkdir(); cwd.mkdir()
            path = config_dir / "config.yaml"
            path.write_text("api_key: yaml-fixture\n", encoding="utf-8")
            (config_dir / ".env").write_text("FREECOMPUTE_API_KEY=config-env-fixture\n", encoding="utf-8")
            (cwd / ".env").write_text("HARNESS_API_KEY=cwd-env-fixture\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(HarnessConfig.load(path).api_key, "cwd-env-fixture")
                with patch.dict(os.environ, {"RELAYFORGE_API_KEY": "process-env-fixture"}, clear=True):
                    self.assertEqual(HarnessConfig.load(path).api_key, "process-env-fixture")
            finally:
                os.chdir(previous)

    def test_secret_scan_reports_locations_without_disclosing_matched_content(self):
        scan_spec = importlib.util.spec_from_file_location("cli_secret_scan", REPO / "tests/security_scan.py")
        scanner = importlib.util.module_from_spec(scan_spec)
        scan_spec.loader.exec_module(scanner)
        with tempfile.TemporaryDirectory() as directory:
            fake = "A" * 32
            (Path(directory) / "bad.txt").write_text("Bearer " + fake, encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(scanner.run_audit(directory), 1)
            self.assertIn("bad.txt:1", output.getvalue())
            self.assertNotIn(fake, output.getvalue())


class CliProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-cli-product-")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace with spaces π"
        self.workspace.mkdir()
        fixture.workspace_files(self.workspace)
        self.server, self.thread = fixture.start_fixture()
        self.config = self.root / "config.yaml"
        self.config.write_text(json.dumps(fixture.configuration(self.workspace, f"http://127.0.0.1:{self.server.server_port}")), encoding="utf-8")
        (self.root / ".env").write_text("FC_FIXTURE_KEY=" + fixture.TOKEN + "\n", encoding="utf-8")
        self.environment = {k:v for k,v in os.environ.items() if not k.startswith(("FREECOMPUTE_", "HARNESS_", "RELAYFORGE_")) and k != "FC_FIXTURE_KEY"}
        self.environment.update(PYTHONPATH=str(REPO), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1", LOCALAPPDATA=str(self.root / "state"))

    def tearDown(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    def cli(self, text="/exit\n", args=(), configured=True, code=0):
        command = [sys.executable, "-m", "harness.cli.main"]
        if configured: command += ["--config", str(self.config)]
        result = subprocess.run([*command, *args], cwd=self.workspace, env=self.environment, input=text, text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn(fixture.TOKEN, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        return result

    def db(self):
        with patch.dict(os.environ, self.environment, clear=True):
            return sqlite3.connect(runtime_home(self.workspace) / "runtime.sqlite3")

    def test_read_edit_command_flow_streams_once_and_never_displays_reasoning_or_json(self):
        out = self.cli("fix calculator\ny\ny\n/diff\n/exit\n").stdout
        self.assertIn("Reading calculator.py", out)
        self.assertIn("Edit requested", out)
        self.assertIn("Run command?", out)
        self.assertIn("Ran 2 tests", out)
        self.assertEqual(out.count("FIXTURE FINAL:"), 1)
        self.assertNotIn("HIDDEN_FIXTURE_REASONING", out)
        self.assertNotIn('"tool_calls"', out)
        self.assertIn("return a / b", (self.workspace / "calculator.py").read_text())
        self.assertEqual(len(self.server.requests), 4)
        self.assertIn("total_lines", self.server.requests[1]["messages"][-1]["content"])

    def test_agent_prompt_is_executed_instead_of_ignored(self):
        out = self.cli("", args=("--prompt", "stream only")).stdout
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(out.count("STREAM_FIRST"), 1)
        self.assertEqual(out.count("STREAM_LAST"), 1)

    def test_unhealthy_status_and_selected_profile_are_truthful(self):
        self.server.health = "unhealthy"
        out = self.cli().stdout
        self.assertIn("fixture-code", out)
        self.assertIn("unhealthy (observed at startup)", out)
        self.assertNotIn("ONLINE", out)

    def test_wrong_key_is_actionable_and_does_not_dispatch(self):
        self.environment["FC_FIXTURE_KEY"] = "SYNTHETIC_WRONG_FIXTURE_KEY"
        result = self.cli()
        self.assertIn("Authentication failed", result.stderr)
        self.assertNotIn("healthy (observed at startup)", result.stdout)
        self.assertEqual(self.server.requests, [])

    def test_unknown_slash_commands_do_not_become_model_tasks(self):
        out = self.cli("/typo\n/imagezzz\n/help\n/help recovery\n/exit\n")
        self.assertIn("Unknown command", out.stderr)
        self.assertIn("/reconcile-inference", out.stdout)
        self.assertEqual(self.server.requests, [])

    def test_empty_queue_does_not_claim_a_recorded_task_receipt(self):
        out = self.cli("/run-next\n/exit\n").stdout
        self.assertNotIn("Recorded task outcome", out)
        self.assertIn("No queued task currently has an eligible free worker", out)
        self.assertEqual(self.server.requests, [])

    def test_no_config_guidance_invalid_url_and_ignored_registry_flags(self):
        out = self.cli(configured=False).stdout
        self.assertIn("No worker configured", out)
        self.assertIn("Status     unconfigured", out)
        self.cli(args=("--remote-url", "not-a-url"), configured=False, code=1)
        out = self.cli(args=("--engine", "llama.cpp"), code=1)
        self.assertIn("single-worker flags", out.stderr)

    def fresh_worker(self):
        server, thread = fixture.start_fixture()
        def close():
            server.release.set()
            server.shutdown()
            server.server_close()
            thread.join(3)
        self.addCleanup(close)
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_fresh_cli_url_overrides_stale_registry_url_with_dotenv_key(self):
        self.server.health_http_status = 530
        fresh, url = self.fresh_worker()
        saved = self.config.read_bytes()
        out = self.cli(args=("--remote-url", url))
        self.assertIn("healthy (observed at startup)", out.stdout)
        self.assertEqual(self.server.probes, [])
        self.assertIn({"path": "/health", "authenticated": True}, fresh.probes)
        self.assertEqual(self.config.read_bytes(), saved)
        self.assertEqual(fresh.requests, [])

    def test_url_override_targets_flag_selected_compatible_worker(self):
        fresh, url = self.fresh_worker()
        out = self.cli(args=("--profile", "chat", "--worker", "fixture-chat-worker", "--remote-url", url + "/v1"))
        self.assertIn("fixture-chat", out.stdout)
        self.assertIn("healthy (observed at startup)", out.stdout)
        self.assertIn({"path": "/v1/models", "authenticated": True}, fresh.probes)
        self.assertEqual(self.server.probes, [])

    def test_connect_replaces_expired_endpoint_and_continues_in_same_cli(self):
        self.server.health_http_status = 530
        fresh, url = self.fresh_worker()
        saved = self.config.read_bytes()
        out = self.cli("/connect " + url + "\n/status\n/workers\n/models\n/model\nstream only\n/exit\n")
        self.assertIn("saved tunnel URL may have expired", out.stdout)
        self.assertIn("Connected: fixture-code-worker", out.stdout)
        self.assertIn("Advertised models: fixture-code, fixture-chat", out.stdout)
        self.assertIn("Endpoint changed for this run only", out.stdout)
        self.assertIn("STREAM_LAST", out.stdout)
        self.assertEqual(len(fresh.requests), 1)
        self.assertEqual(self.server.requests, [])
        self.assertIn({"path": "/health", "authenticated": True}, fresh.probes)
        self.assertIn({"path": "/v1/models", "authenticated": True}, fresh.probes)
        self.assertEqual(self.config.read_bytes(), saved)
        with contextlib.closing(self.db()) as db:
            self.assertNotIn(url, str(db.execute("SELECT declaration FROM workers").fetchall()))

    def test_expired_startup_is_nonfatal_and_help_still_works(self):
        self.server.health_http_status = 530
        out = self.cli("/help\n/sessions\n/exit\n")
        self.assertIn("unreachable (observed at startup)", out.stdout)
        self.assertIn("CLI remains usable", out.stdout)
        self.assertIn("/connect <URL>", out.stdout)
        self.assertEqual(self.server.requests, [])

    def test_connect_invalid_urls_fail_cleanly_and_keep_existing_endpoint(self):
        out = self.cli("/connect not-a-url\n/connect http://localhost:bad\n/connect\n/model\nstream only\n/exit\n")
        self.assertIn("Worker endpoint must be HTTP(S)", out.stderr)
        self.assertIn("invalid port", out.stderr)
        self.assertIn("Usage: /connect", out.stderr)
        self.assertIn("STREAM_LAST", out.stdout)
        self.assertEqual(len(self.server.requests), 1)

    def test_connect_wrong_key_reports_authentication_and_never_prints_key(self):
        fresh, url = self.fresh_worker()
        wrong = "SYNTHETIC_WRONG_RECONNECT_KEY"
        self.environment["FC_FIXTURE_KEY"] = wrong
        out = self.cli("/connect " + url + "\n/help\n/exit\n")
        self.assertIn("Authentication failed", out.stderr)
        self.assertNotIn(wrong, out.stdout + out.stderr)
        self.assertNotIn("Connected:", out.stdout)
        self.assertIn({"path": "/health", "authenticated": False}, fresh.probes)
        self.assertEqual(fresh.requests, [])

    def test_connect_valid_but_expired_url_is_nonfatal_without_dispatch(self):
        self.server.health_http_status = 530
        url = f"http://127.0.0.1:{self.server.server_port}"
        out = self.cli("/connect " + url + "\n/help\n/sessions\n/exit\n")
        self.assertIn("unreachable", out.stdout)
        self.assertIn("saved tunnel URL may have expired", out.stdout)
        self.assertNotIn("Connected:", out.stdout)
        self.assertEqual(self.server.requests, [])

    def test_connect_and_resume_preserve_completed_receipts_without_replay(self):
        self.cli("fix calculator\ny\ny\n/exit\n")
        with contextlib.closing(self.db()) as db:
            sid = db.execute("SELECT id FROM sessions ORDER BY rowid LIMIT 1").fetchone()[0]
            receipts = db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall()
        fresh, url = self.fresh_worker()
        count = len(self.server.requests)
        out = self.cli("/connect " + url + "\n/resume " + sid + "\n/queue\n/exit\n")
        self.assertIn("Recorded task outcome: completed", out.stdout)
        self.assertEqual(len(self.server.requests), count)
        self.assertEqual(fresh.requests, [])
        self.assertEqual((self.workspace / "test-run-count.txt").read_text(), "1")
        self.assertIn("return a / b", (self.workspace / "calculator.py").read_text())
        with contextlib.closing(self.db()) as db:
            self.assertEqual(db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall(), receipts)

    def test_connect_keeps_unknown_lease_fenced_and_does_not_resubmit(self):
        self.server.incomplete = True
        self.cli("", args=("--prompt", "stream only"), code=1)
        fresh, url = self.fresh_worker()
        out = self.cli("/connect " + url + "\n/queue\n/help\n/exit\n")
        self.assertIn("Resolve worker leases", out.stderr)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(fresh.requests, [])
        self.assertEqual(fresh.probes, [])
        with contextlib.closing(self.db()) as db:
            self.assertEqual(db.execute("SELECT state FROM inference_leases").fetchone()[0], "quarantined")

    def test_connect_legacy_route_reuses_freecompute_key_without_registry(self):
        fresh, url = self.fresh_worker()
        self.environment.update(FREECOMPUTE_API_KEY=fixture.TOKEN, FREECOMPUTE_MODEL_ALIAS="fixture-code")
        out = self.cli("/connect " + url + "\nstream only\n/exit\n", configured=False)
        self.assertIn("Connected: supervisor-text", out.stdout)
        self.assertIn("STREAM_LAST", out.stdout)
        self.assertEqual(len(fresh.requests), 1)
        self.assertTrue(all(p["authenticated"] for p in fresh.probes))

    def test_eof_denies_effects_and_resume_prefix_reuses_completed_receipts(self):
        out = self.cli("fix calculator\n").stdout
        self.assertIn("Action REJECTED", out)
        self.assertNotIn("test-run-count.txt", [p.name for p in self.workspace.iterdir()])
        self.assertIn("return a // b", (self.workspace / "calculator.py").read_text())
        with contextlib.closing(self.db()) as db:
            sid = db.execute("SELECT id FROM sessions ORDER BY rowid LIMIT 1").fetchone()[0]
            before = db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall()
        count = len(self.server.requests)
        self.assertIn("Recorded task outcome: completed", self.cli("/resume " + sid[:8] + "\n/exit\n").stdout)
        self.assertEqual(len(self.server.requests), count)
        with contextlib.closing(self.db()) as db:
            self.assertEqual(db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall(), before)

    def test_terminal_controls_and_split_secret_are_not_emitted(self):
        out = self.cli("terminal controls\necho secret\n/exit\n").stdout
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertNotIn(fixture.TOKEN, out)
        self.assertIn("[REDACTED_SECRET]", out)

    def test_undo_conflict_keeps_the_cli_running_and_preserves_external_edit(self):
        self.cli("fix calculator\ny\ny\n/exit\n")
        target = self.workspace / "calculator.py"
        target.write_text("external change", encoding="utf-8")
        out = self.cli("/undo\n/model\n/exit\n")
        self.assertIn("Undo stopped", out.stdout)
        self.assertIn("Profile   code", out.stdout)
        self.assertEqual(target.read_text(), "external change")

    def test_incomplete_stream_is_unknown_and_restart_does_not_redispatch(self):
        self.server.incomplete = True
        out = self.cli("", args=("--prompt", "stream only"), code=1).stdout
        self.assertIn("Remote outcome unknown", out)
        self.assertIn("Capacity remains held", out)
        with contextlib.closing(self.db()) as db:
            sid = db.execute("SELECT id FROM sessions ORDER BY rowid LIMIT 1").fetchone()[0]
            self.assertEqual(db.execute("SELECT state FROM inference_leases").fetchone()[0], "quarantined")
        self.cli("/resume " + sid + "\n/queue\n/exit\n")
        self.assertEqual(len(self.server.requests), 1)

    def test_stream_reaches_terminal_before_inference_completion(self):
        self.server.hold_stream = True
        process = subprocess.Popen([sys.executable, "-m", "harness.cli.main", "--config", str(self.config), "--prompt", "stream only"], cwd=self.workspace,
                                   env=self.environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, observed = bytearray(), threading.Event()
        def read():
            while True:
                byte = process.stdout.read(1)
                if not byte: break
                output.extend(byte)
                if b"STREAM_FIRST" in output: observed.set()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            self.assertTrue(observed.wait(10))
            self.assertIsNone(process.poll())
            self.assertFalse(self.server.completed.is_set())
        finally:
            self.server.release.set()
            process.wait(15)
            reader.join(3)
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
