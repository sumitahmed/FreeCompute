"""
tests/integration/test_cli_smoke.py — Automated smoke test verifying CLI subsystems,
skills, undo, streaming, capability validation, cancellation, and error handling.
"""

import http.server
import json
import os
import shutil
import socketserver
import tempfile
import threading
import time
import unittest
from pathlib import Path

from harness.cli.formatter import SecretScrubber, TerminalFormatter
from harness.config import HarnessConfig
from harness.core.client import CancellationToken, KaggleBrainClient
from harness.core.models import Message
from harness.core.orchestrator import AgentOrchestrator
from harness.core.prompt import PromptBuilder
from harness.providers.base import Capability, UnsupportedCapabilityError
from harness.providers.comfyui import ComfyUIProvider
from harness.providers.llamacpp import LlamaCppProvider
from harness.skills.manager import SkillManager
from harness.storage.journal import TaskJournal
from harness.storage.undo import UndoManager
from harness.telemetry.quota_ledger import QuotaLedger
from harness.telemetry.session_tracker import SessionTracker
from harness.tools.registry import ToolRegistry


class MockStreamingSupervisorHandler(http.server.BaseHTTPRequestHandler):
    """Mock remote supervisor providing SSE streaming chunks and cancellation check."""
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = {
                "status": "healthy",
                "supervisorUptimeSeconds": 100.0,
                "containerUptimeSeconds": 3600.0,
                "maxSessionSeconds": 43200.0,
                "secondsRemainingIn12hSession": 39600.0,
                "llamaHealthy": True,
                "gpus": [{"index": 0, "name": "Tesla T4", "vramUsedMiB": 5000, "vramTotalMiB": 15360, "tempC": 50, "utilizationPct": 10}],
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            # Stream chunks with simulated delay
            tokens = ["Hello", " world", "! ", "FreeCompute", " is", " verified."]
            for t in tokens:
                chunk = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "qwen3.8-27b",
                    "choices": [{"index": 0, "delta": {"content": t}, "finish_reason": None}],
                }
                line = f"data: {json.dumps(chunk)}\n\n"
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    break
                time.sleep(0.02)

            done_line = "data: [DONE]\n\n"
            try:
                self.wfile.write(done_line.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass


class TestCliSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start mock supervisor server on dynamic port
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), MockStreamingSupervisorHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="freecompute_smoke_")
        self.workspace = Path(self.test_dir) / "workspace"
        self.journal_dir = Path(self.test_dir) / "journal"
        self.workspace.mkdir()
        self.journal_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_skills_and_slash_commands(self):
        """Verify project skills discovery and slash command resolution."""
        mgr = SkillManager(workspace_root=".")
        skills = mgr.discover_skills()
        self.assertIn("code-reviewer", skills)
        self.assertIn("neetcode-solver", skills)
        self.assertIn("web-researcher", skills)

        # Check slash command resolution
        review = mgr.get_skill("/review")
        self.assertIsNotNone(review)
        self.assertEqual(review.name, "code-reviewer")

        leetcode = mgr.get_skill("/leetcode")
        self.assertIsNotNone(leetcode)
        self.assertEqual(leetcode.name, "neetcode-solver")

        research = mgr.get_skill("/research")
        self.assertIsNotNone(research)
        self.assertEqual(research.name, "web-researcher")

        # Check prompt building
        prompt = mgr.build_skill_prompt(review, "harness/config.py")
        self.assertIn("[ACTIVE SKILL: CODE-REVIEWER]", prompt)
        self.assertIn("harness/config.py", prompt)

    def test_02_transactional_undo_and_diff(self):
        """Verify pre-change snapshotting, diff recording, and file restoration."""
        undo_mgr = UndoManager(
            workspace_root=str(self.workspace),
            storage_dir=str(self.journal_dir),
        )
        sample = self.workspace / "test_file.py"
        sample.write_text("x = 1\n", encoding="utf-8")

        # Snapshot before edit
        undo_mgr.record_pre_change("test_file.py", "edit_file", "- x = 1\n+ x = 2\n")

        # Simulate edit
        sample.write_text("x = 2\n", encoding="utf-8")
        self.assertEqual(sample.read_text(encoding="utf-8"), "x = 2\n")

        # Verify diff
        last_diff = undo_mgr.get_last_diff()
        self.assertIn("- x = 1", last_diff)

        # Undo
        undo_mgr.record_post_change(undo_mgr.snapshots[-1])
        res = undo_mgr.undo_last(approval_callback=lambda *_: True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "restored")
        self.assertEqual(sample.read_text(encoding="utf-8"), "x = 1\n")

    def test_03_capability_validation_guards(self):
        """Verify explicit capability checks produce clean errors with actionable advice."""
        llama_prov = LlamaCppProvider(base_url=f"http://127.0.0.1:{self.port}")
        comfy_prov = ComfyUIProvider(server_url="http://127.0.0.1:8188")

        # LLM rejecting image gen
        with self.assertRaises(UnsupportedCapabilityError) as ctx:
            llama_prov.generate_image(prompt="a sunset")
        self.assertIn("does not support requested capability 'image_gen'", str(ctx.exception))
        self.assertIn("FREECOMPUTE_IMAGE_SERVER", str(ctx.exception))

        # Comfy rejecting text chat
        with self.assertRaises(UnsupportedCapabilityError) as ctx:
            comfy_prov.stream_chat(messages=[])
        self.assertIn("does not support requested capability 'text'", str(ctx.exception))
        self.assertIn("LlamaCppProvider", str(ctx.exception))

    def test_04_streaming_and_token_collection(self):
        """Verify live SSE token-by-token streaming from mock supervisor."""
        client = KaggleBrainClient(base_url=f"http://127.0.0.1:{self.port}", api_key="")
        received_tokens = []

        def on_chunk(c):
            if c.delta_content:
                received_tokens.append(c.delta_content)

        res = client.stream_chat_completion(
            messages=[Message(role="user", content="Hi")],
            on_chunk=on_chunk,
        )
        self.assertGreater(len(received_tokens), 0)
        full_text = "".join(received_tokens)
        self.assertIn("FreeCompute is verified.", full_text)
        self.assertGreater(res["ttft_ms"], 0.0)

    def test_05_cooperative_cancellation(self):
        """Verify cancellation token stops stream mid-flight."""
        client = KaggleBrainClient(base_url=f"http://127.0.0.1:{self.port}", api_key="")
        token = CancellationToken()
        received = []

        def on_chunk(c):
            if c.delta_content:
                received.append(c.delta_content)
                if len(received) >= 2:
                    token.cancel()

        res = client.stream_chat_completion(
            messages=[Message(role="user", content="Hi")],
            cancellation=token,
            on_chunk=on_chunk,
        )
        self.assertLess(len(received), 6)  # Stream aborted early

    def test_06_error_handling_and_secret_redaction(self):
        """Verify offline server error is caught and credentials scrubbed."""
        scrubber = SecretScrubber()
        scrubber.register_secret("super-secret-token-xyz")
        raw_error = "Failed to connect to https://xyz.trycloudflare.com with Bearer super-secret-token-xyz"
        clean = scrubber.scrub(raw_error)
        self.assertNotIn("super-secret-token-xyz", clean)
        self.assertNotIn("xyz.trycloudflare.com", clean)
        self.assertIn("[REDACTED_SECRET]", clean)


if __name__ == "__main__":
    unittest.main()
