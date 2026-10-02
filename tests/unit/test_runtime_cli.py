"""Real CLI processes through authenticated loopback SSE, plus event presentation."""
import http.server
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from harness.cli.core_client import CoreClient
from harness.core.runtime_models import ModelProfile
from harness.core.service import CoreService
from harness.core.models import StreamChunk
from harness.storage.runtime import runtime_home


REPO = Path(__file__).resolve().parents[2]
FIXTURE_TOKEN = "CLI_SYNTHETIC_CREDENTIAL_ABCDE"


class Supervisor(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def authorized(self):
        if self.headers.get("Authorization") != "Bearer " + FIXTURE_TOKEN:
            self.send_response(401)
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if self.authorized():
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "supervisorUptimeSeconds": 1,
                "containerUptimeSeconds": 10, "llamaHealthy": True, "gpus": []}).encode())

    def do_POST(self):
        if not self.authorized():
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        last = payload["messages"][-1]
        if last["role"] == "tool":
            delta, finish = {"content": "Fixture task completed."}, "stop"
        elif last["content"] == "hello":
            delta, finish = {"content": "Hello from fixture."}, "stop"
        else:
            command = f'"{sys.executable}" -c "from pathlib import Path; assert Path(\'cli.txt\').read_text() == \'verified\'"'
            delta = {"tool_calls": [{"index": 0, "id": "cli-write", "type": "function",
                     "function": {"name": "write_file", "arguments": json.dumps({"path": "cli.txt", "content": "verified", "overwrite": True})}},
                    {"index": 1, "id": "cli-test", "type": "function",
                     "function": {"name": "run_command", "arguments": json.dumps({"command": command})}}]}
            finish = "tool_calls"
        chunk = {"choices": [{"delta": delta, "finish_reason": finish}], "usage": {"completion_tokens": 10}}
        self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
        self.wfile.flush()


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-runtime-cli-")
        self.directory = Path(self.temp.name)
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Supervisor)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith(("FREECOMPUTE_", "RELAYFORGE_", "HARNESS_"))}
        self.environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(REPO),
            LOCALAPPDATA=str(self.directory / "appdata"),
            FREECOMPUTE_REMOTE_URL=f"http://127.0.0.1:{self.server.server_port}",
            FREECOMPUTE_API_KEY=FIXTURE_TOKEN, FREECOMPUTE_MODEL_ALIAS="generic-fixture",
            FREECOMPUTE_JOURNAL_DIR=str(self.directory / "legacy-ledger"))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    def cli(self, text):
        result = subprocess.run([sys.executable, "-m", "harness.cli.main", "--workspace", str(self.workspace)],
            input=text, cwd=self.workspace, env=self.environment, text=True, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(FIXTURE_TOKEN, result.stdout + result.stderr)
        return result.stdout

    def db(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"LOCALAPPDATA": self.environment["LOCALAPPDATA"]}):
            return sqlite3.connect(runtime_home(self.workspace) / "runtime.sqlite3")

    def test_actual_cli_edit_test_sessions_resume_and_unchanged_receipts(self):
        output = self.cli("edit and test\ny\ny\n/sessions\n/actions\n/skills\n/diff\n/model\nexit\n")
        self.assertIn("Fixture task completed", output)
        self.assertNotIn("[Thinking]", output)
        self.assertEqual((self.workspace / "cli.txt").read_text(), "verified")
        db = self.db()
        sid, task_id = db.execute("SELECT id,current_task_id FROM sessions ORDER BY rowid LIMIT 1").fetchone()
        before = db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall()
        self.assertEqual(len(before), 2)
        self.assertEqual(json.loads(before[1][2])["exit_code"], 0)
        db.close()
        request_count = len(self.server.requests)
        output = self.cli("/resume " + sid + "\n/sessions\nexit\n")
        self.assertIn("Recorded task outcome: completed", output)
        self.assertEqual(len(self.server.requests), request_count)
        db = self.db()
        self.assertEqual(db.execute("SELECT id,state,result FROM actions ORDER BY rowid").fetchall(), before)
        self.assertEqual(db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()[0], "completed")
        db.close()

    def test_actual_cli_denial_no_effect_and_normal_text(self):
        output = self.cli("edit and test\nn\nn\nhello\nexit\n")
        self.assertIn("Action REJECTED", output)
        self.assertIn("[TOOL DENIED]", output)
        self.assertNotIn("write_file completed successfully", output)
        self.assertIn("Hello from fixture", output)
        self.assertFalse((self.workspace / "cli.txt").exists())
        db = self.db()
        self.assertEqual(db.execute("SELECT DISTINCT state FROM actions").fetchall(), [("denied",)])
        db.close()

    def test_event_adapter_forwards_actual_reasoning_and_survives_bad_renderer(self):
        class Engine:
            def stream(self, *args):
                yield StreamChunk(delta_content="answer", delta_reasoning="server supplied reasoning", finish_reason="stop")
                yield StreamChunk(stream_complete=True)
        profile = ModelProfile("p", "w", "fixture", "fixture", frozenset({"text", "code_tools"}))
        core = CoreService(self.workspace, Engine(), profile, state_dir=self.directory / "state", system_prompt="system")
        try:
            core.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("renderer failed")))
            client = CoreClient(core)
            text, reasoning = [], []
            result = client.run_task("hello", on_token=text.append, on_reasoning=reasoning.append)
            self.assertEqual(result["status"], "completed")
            self.assertEqual("".join(text), "answer")
            self.assertEqual("".join(reasoning), "server supplied reasoning")
        finally:
            core.close()


if __name__ == "__main__":
    unittest.main()
