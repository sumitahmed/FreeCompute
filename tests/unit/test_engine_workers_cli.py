"""Authenticated loopback adapters, installed-compatible config and actual CLI routes."""
import base64
import http.server
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

import test_runtime_cli as legacy
from harness.config import HarnessConfig
from harness.core.engines import EngineFailure
from harness.core.service import CoreService
from harness.storage.runtime import runtime_home


REPO = Path(__file__).resolve().parents[2]
TOKEN = legacy.FIXTURE_TOKEN
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6vWQAAAAASUVORK5CYII=")


class ProtocolServer(legacy.Supervisor):
    def do_GET(self):
        if self.path.startswith("/comfy/"):
            self.send_response(200)
            self.end_headers()
            if self.path.startswith("/comfy/view"):
                self.wfile.write(PNG)
            elif self.path.startswith("/comfy/history/"):
                self.wfile.write(json.dumps({"fixture-job": {"outputs": {"13": {"images": [{"filename": "fixture.png", "type": "output", "subfolder": ""}]}}}}).encode())
            else:
                self.wfile.write(json.dumps({"devices": [{"index": 0, "name": "fixture GPU", "vram_total": 1024, "vram_free": 512}]}).encode())
            return
        if not self.authorized():
            return
        if self.path == "/v1/models":
            if self.server.redirect:
                self.send_response(302)
                self.send_header("Location", self.server.redirect)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "plain"}, {"id": "generic-fixture"}]}).encode())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/comfy/prompt":
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"prompt_id":"fixture-job"}')
            self.server.image_jobs += 1
            return
        if self.server.fail_chat_auth:
            self.send_response(401)
            self.end_headers()
            return
        if self.server.quiet or self.server.incomplete:
            if not self.authorized():
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.requests.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data:{"choices":[{"delta":{"content":"partial"},"finish_reason":"stop"}]}\n\n')
            self.wfile.flush()
            if self.server.quiet:
                self.server.release.wait(5)
            return
        if self.server.no_space:
            if not self.authorized():
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.requests.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data:{"choices":[{"delta":{"content":"compatible answer"},"finish_reason":"stop"}]}\n\ndata:[DONE]\n\n')
            return
        super().do_POST()


class EngineAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-v1-engine-cli-")
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProtocolServer)
        self.server.daemon_threads = True
        self.server.requests, self.server.image_jobs = [], 0
        self.server.quiet = self.server.incomplete = self.server.no_space = self.server.fail_chat_auth = False
        self.server.redirect, self.server.release = "", threading.Event()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        url = f"http://127.0.0.1:{self.server.server_port}"
        self.data = {"workspace_root": str(self.workspace), "journal_dir": str(self.base / "legacy"), "selected_profile": "small",
            "model_profiles": [
                {"profile_id": "small", "model": "plain", "engine": "openai-compatible", "capabilities": ["text"]},
                {"profile_id": "qwen", "model": "generic-fixture", "engine": "llama.cpp", "capabilities": ["text", "code_tools"], "resource_requirements": ["gpu0", "gpu1"]},
                {"profile_id": "image", "model": "ComfyUI-fixture", "engine": "ComfyUI", "capabilities": ["image_gen"], "resource_requirements": ["gpu0"]}],
            "workers": [
                {"worker_id": "local-small", "location": "local", "engine": "openai-compatible", "url": url + "/v1", "api_key_env": "FC_FIXTURE_TOKEN", "profiles": ["small"]},
                {"worker_id": "kaggle-qwen", "location": "kaggle", "engine": "llama.cpp", "url": url, "api_key_env": "FC_FIXTURE_TOKEN", "profiles": ["qwen"], "resource_pool": "dual-t4", "resources": ["gpu0", "gpu1"]},
                {"worker_id": "image-worker", "location": "kaggle", "engine": "ComfyUI", "url": url + "/comfy", "profiles": ["image"], "resource_pool": "dual-t4", "resources": ["gpu0"]}]}
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith(("FREECOMPUTE_", "RELAYFORGE_", "HARNESS_"))}
        self.environment.update(LOCALAPPDATA=str(self.base / "appdata"), FC_FIXTURE_TOKEN=TOKEN,
                                PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(REPO), PYTHONIOENCODING="utf-8")
        self.environment_patch = patch.dict(os.environ, self.environment, clear=True)
        self.environment_patch.start()
        self.core = None

    def tearDown(self):
        if self.core:
            self.core.close()
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.environment_patch.stop()
        self.temp.cleanup()

    def start(self):
        self.core = CoreService.from_config(HarnessConfig(**self.data))
        return self.core

    def cli(self, text):
        config = self.base / "config.json"
        config.write_text(json.dumps(self.data), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "harness.cli.main", "--config", str(config)], input=text,
            cwd=self.workspace, env=self.environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        return result.stdout

    def test_compatible_stream_model_list_auth_and_optional_sse_space(self):
        self.server.no_space = True
        core = self.start()
        result = core.run(core.submit("hello"))
        self.assertEqual(result["final_answer"], "compatible answer")
        self.assertEqual(self.server.requests[0]["model"], "plain")
        self.assertNotIn("tools", self.server.requests[0])
        adapter = core.registry.engine("local-small")
        self.assertFalse(adapter.describe()["remote_cancel_ack"])
        self.assertEqual(adapter.get_capabilities(), frozenset({"text"}))
        self.assertEqual(core.list_workers()[1]["health"], "healthy")
        self.assertNotIn(TOKEN, json.dumps(core.store.all("SELECT * FROM workers")))

    def test_auth_rejection_before_model_dispatch_does_not_claim_success(self):
        core = self.start()
        core.registry.refresh("local-small")
        self.server.fail_chat_auth = True
        result = core.run(core.submit("hello"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "idle")
        self.assertEqual(core.store.all("SELECT * FROM resource_claims"), [])

    def test_incomplete_network_stream_quarantines_worker_without_tools(self):
        self.server.incomplete = True
        core = self.start()
        result = core.run(core.submit("hello", profile_id="qwen"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["final_answer"], "")
        self.assertEqual(len(core.store.all("SELECT * FROM resource_claims")), 2)
        self.assertEqual(core.store.all("SELECT * FROM actions"), [])

    def test_timeout_interrupts_local_read_and_retains_remote_lease(self):
        self.server.quiet = True
        self.data["workers"][0]["timeout_seconds"] = 1
        core = self.start()
        start = time.monotonic()
        result = core.run(core.submit("hello"))
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        attempt = core.store.one("SELECT * FROM inference_attempts")
        self.assertIn("timed out", attempt["error"])

    def test_redirected_health_is_refused_without_sending_auth_to_target(self):
        hits = []
        class Trap(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                hits.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
        trap = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trap)
        thread = threading.Thread(target=trap.serve_forever, daemon=True)
        thread.start()
        try:
            self.server.redirect = f"http://127.0.0.1:{trap.server_port}/models"
            core = self.start()
            self.assertEqual(core.run(core.submit("hello"))["status"], "queued")
            self.assertEqual(hits, [])
            self.assertEqual(self.server.requests, [])
        finally:
            trap.shutdown()
            trap.server_close()
            thread.join(3)

    def test_comfy_adapter_generates_correlated_artifact_and_rejects_text(self):
        core = self.start()
        result = core.generate_image("fixture")
        self.assertEqual(Path(result["file_path"]).read_bytes(), PNG)
        self.assertEqual(self.server.image_jobs, 1)
        self.assertEqual(core.inference.allocation()["state"], "idle")
        self.assertEqual(core.store.all("SELECT * FROM resource_claims"), [])
        adapter = core.registry.engine("image-worker")
        self.assertFalse(adapter.describe()["streaming"])
        with self.assertRaises(EngineFailure):
            adapter.stream(None, [], [], None)

    def test_actual_cli_selects_workers_edits_tests_and_resumes_without_replay(self):
        output = self.cli("/workers\n/models\nhello\n/model qwen kaggle-qwen\n/new\nedit and test\ny\ny\n/queue\n/sessions\nexit\n")
        self.assertIn("local-small", output)
        self.assertIn("kaggle-qwen", output)
        self.assertIn("image-worker", output)
        self.assertIn("Fixture task completed", output)
        self.assertEqual((self.workspace / "cli.txt").read_text(), "verified")
        self.assertEqual([r["model"] for r in self.server.requests], ["plain", "generic-fixture", "generic-fixture"])
        db = sqlite3.connect(runtime_home(self.workspace) / "runtime.sqlite3")
        sid = db.execute("SELECT id FROM sessions WHERE profile_id='qwen'").fetchone()[0]
        receipts = db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall()
        self.assertEqual(len(receipts), 2)
        self.assertEqual(json.loads(receipts[1][2])["exit_code"], 0)
        db.close()
        count = len(self.server.requests)
        self.assertIn("Recorded task outcome: completed", self.cli("/resume " + sid + "\n/queue\nexit\n"))
        self.assertEqual(len(self.server.requests), count)
        db = sqlite3.connect(runtime_home(self.workspace) / "runtime.sqlite3")
        self.assertEqual(db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall(), receipts)
        db.close()

    def test_actual_cli_runs_preexisting_queue_after_core_restart(self):
        core = self.start()
        task_id = core.submit("hello", profile_id="qwen", worker_id="kaggle-qwen", allowed_tools=[])
        core.close()
        self.core = None
        output = self.cli("/queue\n/run-next\n/queue\nexit\n")
        self.assertIn(task_id, output)
        self.assertIn("Hello from fixture", output)
        self.assertEqual(len(self.server.requests), 1)


if __name__ == "__main__":
    unittest.main()
