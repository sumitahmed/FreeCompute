import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error

from harness.config import HarnessConfig
from harness.core.client import CancellationToken
from harness.core.models import StreamChunk
from harness.core.orchestrator import AgentOrchestrator
from harness.core.prompt import PromptBuilder
from harness.cli.main import handle_approval_prompt
from harness.cli.formatter import TerminalFormatter
from harness.providers.comfyui import ComfyUIProvider
from harness.security import SecretScrubber, StreamRedactor, scrubber
from harness.storage.journal import TaskJournal
from harness.storage.undo import UndoManager
from harness.telemetry.quota_ledger import QuotaLedger
from harness.telemetry.session_tracker import SessionTracker
from harness.tools.registry import ToolRegistry, ToolBroker
from harness.tools.fs import grep_search, list_dir
from harness.tools.sandbox import validate_workspace_path, SandboxSecurityViolation
from kaggle import supervisor


class SafetyBaselineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.undo = UndoManager(str(self.workspace), str(self.root / "state"))
        self.registry = ToolRegistry(str(self.workspace), undo_manager=self.undo)

    def test_missing_or_false_approval_denies_direct_and_child_writes(self):
        broker = ToolBroker(self.registry)
        child = broker.child(["write_file"])
        for callback in (None, lambda *_: False, lambda *_: "yes"):
            with self.subTest(callback=callback):
                result = child.execute("write_file", {"path": "test.txt", "content": "hello"}, approval_callback=callback)
                self.assertEqual(result["status"], "rejected")
                self.assertFalse((self.workspace / "test.txt").exists())
        self.assertEqual(len(self.undo.snapshots), 0)

    def test_child_cannot_widen_permissions(self):
        child = ToolBroker(self.registry).child(["read_file"])
        with self.assertRaises(ValueError):
            child.child(["write_file"])
        self.assertEqual(child.execute("run_command", {"command": "echo denied"})["status"], "rejected")

    def test_blank_cli_input_denies(self):
        with patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(handle_approval_prompt("write_file", {}, TerminalFormatter(False)))

    def test_approval_content_change_and_cancel_are_rechecked(self):
        target = self.workspace / "a.txt"
        target.write_text("before")
        def mutate(*_):
            target.write_text("external")
            return True
        result = self.registry.execute("write_file", {"path": "a.txt", "content": "after", "overwrite": True}, approval_callback=mutate)
        self.assertIn("error", result)
        self.assertEqual(target.read_text(), "external")
        token = CancellationToken()
        def cancel(*_):
            token.cancel()
            return True
        result = self.registry.execute("write_file", {"path": "new", "content": "after"}, approval_callback=cancel, cancellation_token=token)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.workspace / "new").exists())

    def test_argument_validation_rejects_wrong_type_extra_and_nonobject(self):
        for arguments in ({"path": 2, "content": "x"}, {"path": "x", "content": "x", "extra": True}, [], None):
            self.assertIn("error", self.registry.execute("write_file", arguments, approval_callback=lambda *_: True))

    def test_secret_variants_and_recursive_search_are_blocked(self):
        for name in (".env.local", ".ENV", "Secrets.JSON", "credentials.ini", "id_rsa.pub", "cert.PEM"):
            (self.workspace / name).write_text("needle private")
            with self.subTest(name=name), self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path(name, str(self.workspace))
        (self.workspace / "public.txt").write_text("needle public")
        self.assertEqual([m["file"] for m in grep_search("needle", workspace_root=str(self.workspace))["matches"]], ["public.txt"])
        self.assertEqual([e["name"] for e in list_dir(workspace_root=str(self.workspace))["entries"]], ["public.txt"])

    def test_symlink_read_search_and_snapshot_denied(self):
        outside = self.root / "outside.txt"
        outside.write_text("needle outside")
        link = self.workspace / "alias.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("OS does not grant symlink creation; junction test runs separately")
        with self.assertRaises(SandboxSecurityViolation):
            self.undo.record_pre_change(str(link))
        self.assertEqual(grep_search("needle", workspace_root=str(self.workspace))["total_matches"], 0)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_windows_junction_search_and_snapshot_denied(self):
        import _winapi
        outside = self.root / "external"
        outside.mkdir()
        (outside / "private.txt").write_text("needle outside")
        junction = self.workspace / "junction"
        _winapi.CreateJunction(str(outside), str(junction))
        with self.assertRaises(SandboxSecurityViolation):
            self.undo.record_pre_change(str(junction / "private.txt"))
        self.assertEqual(grep_search("needle", workspace_root=str(self.workspace))["total_matches"], 0)
        junction.rmdir()

    def test_snapshot_protected_and_outside_paths_denied(self):
        for name in (".env.local", "../outside.txt"):
            with self.assertRaises(SandboxSecurityViolation):
                self.undo.record_pre_change(name)

    def changed_file(self):
        target = self.workspace / "a.txt"
        target.write_text("before")
        snapshot = self.undo.record_pre_change("a.txt")
        target.write_text("after")
        self.undo.record_post_change(snapshot)
        return target, snapshot

    def test_uuid_snapshots_are_immutable_and_unique(self):
        target, first = self.changed_file()
        second = self.undo.record_pre_change("a.txt")
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(Path(first.backup_path).read_text(), "before")
        with self.assertRaises(Exception):
            first.snapshot_id = "changed"
        reloaded = UndoManager(str(self.workspace), str(self.root / "state"))
        self.assertEqual(reloaded.snapshots[0].pre_hash, first.pre_hash)
        self.assertIsNotNone(reloaded.snapshots[0].post_hash)

    def test_restore_requires_approval(self):
        target, _ = self.changed_file()
        self.assertEqual(self.undo.undo_last()["status"], "rejected")
        self.assertEqual(target.read_text(), "after")

    def test_missing_or_corrupt_backup_never_deletes_target(self):
        target, snapshot = self.changed_file()
        backup = Path(snapshot.backup_path)
        backup.write_text("corrupt")
        self.assertEqual(self.undo.undo_last(lambda *_: True)["status"], "error")
        backup.unlink()
        self.assertEqual(self.undo.undo_last(lambda *_: True)["status"], "error")
        self.assertEqual(target.read_text(), "after")
        self.assertEqual(len(self.undo.snapshots), 1)

    def test_conflicts_and_unsealed_snapshot_preserve_target(self):
        target, _ = self.changed_file()
        target.write_text("user edit")
        self.assertEqual(self.undo.undo_last(lambda *_: True)["status"], "error")
        self.assertEqual(target.read_text(), "user edit")
        self.undo.record_pre_change("a.txt")
        self.assertEqual(self.undo.undo_last(lambda *_: True)["status"], "error")

    def test_undo_rechecks_after_approval(self):
        target, _ = self.changed_file()
        def approval(*_):
            target.write_text("during approval")
            return True
        self.assertEqual(self.undo.undo_last(approval)["status"], "error")
        self.assertEqual(target.read_text(), "during approval")

    def test_split_registered_secrets_redacted_at_every_boundary(self):
        source = SecretScrubber()
        secret = "synthetic-only-credential-12345"
        source.register_secret(secret)
        for split in range(1, len(secret)):
            stream = StreamRedactor(source)
            emitted = stream.feed("prefix " + secret[:split]) + stream.feed(secret[split:] + " suffix ") + stream.finish()
            self.assertNotIn(secret, emitted)
            self.assertEqual(emitted, "prefix [REDACTED_SECRET] suffix ")
        scrubber.register_secret(secret)
        journal = TaskJournal(str(self.root / "journal"))
        journal.record_event("run", "test", {"arguments": secret, "reasoning": secret, "url": secret})
        journal.save_checkpoint("run", {"history": secret})
        self.assertNotIn(secret, journal.journal_file.read_text())
        self.assertNotIn(secret, journal.checkpoints_file.read_text())
        self.registry.register(__import__("harness.tools.registry", fromlist=["ToolDefinition"]).ToolDefinition("leak", "test", {"properties": {}}, lambda: {"diff": secret}, False))
        self.assertNotIn(secret, str(self.registry.execute("leak", {})))

    def test_config_precedence_dotenv_timeout_and_validation(self):
        previous = Path.cwd()
        os.chdir(self.workspace)
        try:
            Path("config.yaml").write_text("api_key: yaml-value\nrequest_timeout_seconds: 10\n")
            Path(".env").write_text("FREECOMPUTE_API_KEY=dotenv-value\nFREECOMPUTE_TIMEOUT=42\n")
            with patch.dict(os.environ, {"FREECOMPUTE_API_KEY": "canonical-value", "HARNESS_API_KEY": "legacy-value"}, clear=True):
                config = HarnessConfig.load()
                self.assertEqual(config.api_key, "canonical-value")
                self.assertEqual(config.request_timeout_seconds, 42)
                self.assertNotIn("canonical-value", repr(config))
            with patch.dict(os.environ, {"HARNESS_API_KEY": "process-value"}, clear=True):
                self.assertEqual(HarnessConfig.load().api_key, "process-value")
            for data in ({"extra": 1}, {"request_timeout_seconds": 0}, {"transport": "unknown"}, {"remote_url": "file:///secret"}):
                with self.assertRaises(ValueError):
                    HarnessConfig(**data)
            with self.assertRaises(FileNotFoundError):
                HarnessConfig.load("missing.yaml")
        finally:
            os.chdir(previous)

    def test_comfy_health_matches_model_contract_all_paths(self):
        provider = ComfyUIProvider(output_dir="out", workspace_root=str(self.workspace))
        self.assertEqual(provider.get_health().status, "unconfigured")
        provider.server_url = "http://127.0.0.1:1"
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(provider.get_health().status, "unreachable")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"devices": [{"name": "fixture", "vram_total": 1048576, "vram_free": 0}]}).encode()
        with patch("urllib.request.urlopen", return_value=response):
            health = provider.get_health()
        self.assertEqual(health.gpus[0].vram_total_mib, 1)
        self.assertEqual(health.max_session_s, 0)

    def test_quota_stopped_sessions_and_new_observation(self):
        quota = QuotaLedger(str(self.root / "quota.json"))
        quota.set_user_observed_balance(10)
        quota.start_session()
        quota.current_session_start = time.time() - 3600
        quota.stop_session()
        self.assertAlmostEqual(quota.estimated_remaining_hours, 9, places=2)
        reloaded = QuotaLedger(str(self.root / "quota.json"))
        self.assertAlmostEqual(reloaded.estimated_remaining_hours, 9, places=2)
        reloaded.set_user_observed_balance(8)
        self.assertEqual(reloaded.estimated_remaining_hours, 8)
        self.assertIn("not GPU", reloaded.get_summary()["accounting_basis"])

    def test_session_estimate_source_and_cancellation_uncertainty(self):
        tracker = SessionTracker()
        tracker.update_from_remote_health({"sessionAgeSeconds": 10, "sessionAgeSource": "supervisor_start_estimate"})
        self.assertTrue(tracker.get_summary()["is_estimate"])
        self.assertEqual(tracker.get_summary()["session_age_source"], "supervisor_start_estimate")
        token = CancellationToken()
        token.cancel()
        self.assertTrue(token.summary()["requested"])
        self.assertFalse(token.summary()["remote_cancel_confirmed"])
        self.assertEqual(token.summary()["remote_outcome"], "unknown")

    def test_supervisor_missing_blank_credentials_fail(self):
        with patch.dict(os.environ, {}, clear=True):
            for key in (None, "", " "):
                with self.assertRaises(ValueError):
                    supervisor.SupervisorConfig(api_key=key)

    def test_supervisor_health_auth_and_backend_allowlist(self):
        with patch.object(supervisor, "config", supervisor.SupervisorConfig(api_key="fixture-auth-only")), patch.object(supervisor, "check_llama_health", return_value=True), patch.object(supervisor, "get_gpu_telemetry", return_value=[]):
            server = supervisor.ThreadedHTTPServer(("127.0.0.1", 0), supervisor.SupervisorHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(base + "/health")
                self.assertEqual(denied.exception.code, 401)
                headers = {"Authorization": "Bearer fixture-auth-only"}
                with urllib.request.urlopen(urllib.request.Request(base + "/health", headers=headers)) as response:
                    data = json.load(response)
                self.assertEqual(data["sessionAgeSource"], "supervisor_start_estimate")
                self.assertNotIn("containerUptimeSeconds", data)
                for path in ("/slots", "/props", "/v1/unknown"):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(urllib.request.Request(base + path, headers=headers))
                    self.assertEqual(denied.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_malformed_and_incomplete_tool_stream_never_executes(self):
        for arguments, finish in (("{", "tool_calls"), ('{"path":"x","content":"y"}', None)):
            client = MagicMock()
            client.stream_chat.side_effect = [iter([StreamChunk(tool_call_deltas=[{"index": 0, "id": "stable", "function": {"name": "write_file", "arguments": arguments}}], finish_reason=finish)]), iter([StreamChunk(delta_content="done", finish_reason="stop")])]
            orchestrator = AgentOrchestrator(client, PromptBuilder(), self.registry, TaskJournal(str(self.root / "journal")), SessionTracker(), QuotaLedger(str(self.root / "quota.json")))
            orchestrator.run_task("fixture", on_approval_request=lambda *_: True)
            self.assertFalse((self.workspace / "x").exists())

    def test_notebook_supervisor_matches_canonical_and_auth_health(self):
        import ast
        canonical = Path("kaggle/supervisor.py").read_text(encoding="utf-8")
        checked = 0
        for path in Path("kaggle").glob("*.ipynb"):
            for cell in json.loads(path.read_text(encoding="utf-8"))["cells"]:
                source = "".join(cell.get("source", []))
                if "supervisor_script =" not in source:
                    continue
                tree = ast.parse(source)
                value = next(node.value.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "supervisor_script" for t in node.targets))
                self.assertEqual(value, canonical)
                self.assertIn("headers={'Authorization': 'Bearer ' + CONFIG['API_KEY']}", source)
                checked += 1
        self.assertEqual(checked, 2)
