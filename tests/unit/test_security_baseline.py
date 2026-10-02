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
            # Exercise the lstat contract when Windows denies symlink creation.
            # The separate junction test exercises a real Windows reparse point.
            import stat
            link.write_text("needle alias")
            original = Path.lstat
            def linked_stat(path):
                data = original(path)
                if path == link:
                    data = os.stat_result((stat.S_IFLNK,) + tuple(data)[1:])
                return data
            with patch.object(Path, "lstat", linked_stat):
                with self.assertRaises(SandboxSecurityViolation):
                    self.undo.record_pre_change(str(link))
                self.assertEqual(grep_search("needle", workspace_root=str(self.workspace))["total_matches"], 0)
        else:
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

    def test_atomic_replacement_failure_preserves_file_and_snapshot(self):
        target, snapshot = self.changed_file()
        with patch("harness.tools.atomic.os.replace", side_effect=OSError("fixture replacement failure")):
            self.assertEqual(self.undo.undo_last(lambda *_: True)["status"], "error")
        self.assertEqual(target.read_text(), "after")
        self.assertEqual(self.undo.snapshots[-1].snapshot_id, snapshot.snapshot_id)
        self.assertFalse(list(self.workspace.glob(".freecompute-write-*")))

    def test_windows_dot_space_alias_of_protected_directory_denied(self):
        for path in (".GIT./config", ".ssh /config", "secret.json. "):
            with self.assertRaises(SandboxSecurityViolation):
                validate_workspace_path(path, str(self.workspace))

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
        with patch.object(supervisor, "config", supervisor.SupervisorConfig(api_key="test-secret-token")), patch.object(supervisor, "check_llama_health", return_value=True), patch.object(supervisor, "get_gpu_telemetry", return_value=[]):
            server = supervisor.ThreadedHTTPServer(("127.0.0.1", 0), supervisor.SupervisorHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(base + "/health")
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                headers = {"Authorization": "Bearer test-secret-token"}
                with urllib.request.urlopen(urllib.request.Request(base + "/health", headers=headers)) as response:
                    data = json.load(response)
                self.assertEqual(data["sessionAgeSource"], "supervisor_start_estimate")
                self.assertNotIn("containerUptimeSeconds", data)
                for path in ("/slots", "/props", "/v1/unknown"):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(urllib.request.Request(base + path, headers=headers))
                    self.assertEqual(denied.exception.code, 404)
                    denied.exception.close()
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

    def test_model_reasoning_and_content_callbacks_are_scrubbed(self):
        secret = "SYNTHETIC_STREAM_SECRET_ABCDE"
        scrubber.register_secret(secret)
        client = MagicMock()
        client.stream_chat.return_value = iter([
            StreamChunk(delta_content="answer " + secret[:12], delta_reasoning="reason " + secret[:12]),
            StreamChunk(delta_content=secret[12:], delta_reasoning=secret[12:], finish_reason="stop")])
        output, reasoning = [], []
        journal = TaskJournal(str(self.root / "journal"))
        orchestrator = AgentOrchestrator(client, PromptBuilder(), self.registry, journal, SessionTracker(), QuotaLedger(str(self.root / "quota.json")))
        result = orchestrator.run_task("fixture", on_token=output.append, on_reasoning=reasoning.append)
        self.assertEqual("".join(output), "answer [REDACTED_SECRET]")
        self.assertEqual("".join(reasoning), "reason [REDACTED_SECRET]")
        self.assertNotIn(secret, journal.journal_file.read_text())
        self.assertNotIn(secret, str(result["history"]))
        self.assertIsNone(result["usage"])

    def test_one_malformed_call_prevents_the_entire_batch(self):
        client = MagicMock()
        client.stream_chat.side_effect = [iter([StreamChunk(tool_call_deltas=[
            {"index": 0, "id": "valid", "function": {"name": "write_file", "arguments": '{"path":"valid.txt","content":"hello"}'}},
            {"index": 1, "id": "broken", "function": {"name": "write_file", "arguments": "{"}}], finish_reason="tool_calls")]),
            iter([StreamChunk(delta_content="fixture stopped", finish_reason="stop")])]
        orchestrator = AgentOrchestrator(client, PromptBuilder(), self.registry, TaskJournal(str(self.root / "journal")), SessionTracker(), QuotaLedger(str(self.root / "quota.json")))
        approved = MagicMock(return_value=True)
        orchestrator.run_task("fixture", on_approval_request=approved)
        approved.assert_not_called()
        self.assertFalse((self.workspace / "valid.txt").exists())

    def test_checkpoint_corruption_is_preserved_and_reported(self):
        journal = TaskJournal(str(self.root / "journal"))
        journal.checkpoints_file.write_text("corrupt")
        with self.assertRaises(ValueError):
            journal.save_checkpoint("run", {"data": 1})
        self.assertEqual(journal.checkpoints_file.read_text(), "corrupt")

    def test_no_redirect_from_authenticated_inference(self):
        import http.server
        from harness.core.client import KaggleBrainClient, RemoteBrainUnavailableError
        class Redirect(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/capture")
                self.end_headers()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = KaggleBrainClient(f"http://127.0.0.1:{server.server_port}", api_key="fixture-token-not-live")
            with self.assertRaises(RemoteBrainUnavailableError) as error:
                client.get_health()
            self.assertIn("302", str(error.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_subprocess_cancellation_records_owned_exit_and_unknown_descendants(self):
        from harness.tools.terminal import run_command
        token = CancellationToken()
        timer = threading.Timer(0.15, token.cancel)
        timer.start()
        try:
            result = run_command('python -c "import time; time.sleep(1)"', workspace_root=str(self.workspace), cancellation_token=token)
        finally:
            timer.cancel()
        self.assertTrue(result["cancellation_requested"])
        self.assertTrue(result["owned_process_exit_confirmed"])
        self.assertEqual(result["descendant_cancellation"], "unknown")

    def test_image_cli_upload_and_output_boundaries(self):
        from harness.cli.image import ImageHarnessSession
        previous = Path.cwd()
        os.chdir(self.workspace)
        try:
            session = ImageHarnessSession("http://127.0.0.1:1")
            with self.assertRaises(SandboxSecurityViolation):
                session.upload_image(self.root / "outside.png")
        finally:
            os.chdir(previous)

    def test_image_cli_ignores_other_job_completion(self):
        import asyncio
        from harness.cli.image import ImageHarnessSession
        messages = [
            {"type": "executing", "data": {"prompt_id": "other-job", "node": None}},
            {"type": "execution_start", "data": {"prompt_id": "fixture-job"}},
            {"type": "executing", "data": {"prompt_id": "fixture-job", "node": None}},
        ]
        class WebSocket:
            received = 0
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def recv(self):
                message = messages[self.received]
                self.received += 1
                return json.dumps(message)
        websocket = WebSocket()
        queued, history = MagicMock(), MagicMock()
        queued.__enter__.return_value.read.return_value = b'{"prompt_id":"fixture-job"}'
        history.__enter__.return_value.read.return_value = b'{"fixture-job":{"outputs":{"9":{"images":[{"filename":"fixture.png"}]}}}}'
        def download(url, destination):
            self.assertEqual(websocket.received, 3)
            Path(destination).write_bytes(b"fixture image")
        previous = Path.cwd()
        os.chdir(self.workspace)
        try:
            with patch("harness.cli.image.websockets.connect", return_value=websocket), patch("urllib.request.urlopen", side_effect=[queued, history]), patch("urllib.request.urlretrieve", side_effect=download), patch("os.startfile", create=True), contextlib.redirect_stdout(io.StringIO()):
                session = ImageHarnessSession("http://127.0.0.1:1")
                asyncio.run(session.execute_generation("fixture", custom_out="result.png"))
            self.assertEqual((self.workspace / "result.png").read_bytes(), b"fixture image")
        finally:
            os.chdir(previous)

    def test_image_cli_timeout_does_not_claim_remote_cancellation(self):
        import asyncio
        from harness.cli.image import ImageHarnessSession
        class WebSocket:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def recv(self):
                raise asyncio.TimeoutError()
        queued = MagicMock()
        queued.__enter__.return_value.read.return_value = b'{"prompt_id":"fixture-job"}'
        output = io.StringIO()
        with patch("harness.cli.image.websockets.connect", return_value=WebSocket()), patch("urllib.request.urlopen", return_value=queued), patch("urllib.request.urlretrieve") as download, contextlib.redirect_stdout(output):
            asyncio.run(ImageHarnessSession("http://127.0.0.1:1").execute_generation("fixture"))
        download.assert_not_called()
        self.assertIn("remote outcome unknown", output.getvalue())

    def test_comfy_remote_filename_cannot_escape_output_root(self):
        provider = ComfyUIProvider("http://127.0.0.1:1", output_dir="out", workspace_root=str(self.workspace))
        queued, history = MagicMock(), MagicMock()
        queued.__enter__.return_value.read.return_value = b'{"prompt_id":"fixture-id"}'
        history.__enter__.return_value.read.return_value = b'{"fixture-id":{"outputs":{"9":{"images":[{"filename":"../outside.png"}]}}}}'
        with patch("urllib.request.urlopen", side_effect=[queued, history]), patch("time.sleep"), patch("urllib.request.urlretrieve") as download:
            with self.assertRaises(ValueError):
                provider.generate_image("fixture")
            download.assert_not_called()

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
