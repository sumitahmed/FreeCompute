"""Explicit loopback-only test inference. Not shipped in the FreeCompute package."""
import http.server
import json
import os
import sys
import threading
import time

TOKEN = "FC_SYNTHETIC_CLI_FIXTURE_CREDENTIAL"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def authorized(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401)
            self.end_headers()
            return False
        return True

    def do_GET(self):
        allowed = self.authorized()
        self.server.probes.append({"path": self.path, "authenticated": allowed})
        if not allowed:
            return
        if self.path == "/health" and self.server.health_http_status != 200:
            self.send_response(self.server.health_http_status)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        value = ({"data": [{"id": model} for model in self.server.models]} if self.path.endswith("models")
                 else {"status": self.server.health, "gpus": [], "source": "loopback fixture, no GPU"})
        self.wfile.write(json.dumps(value).encode())

    def event(self, delta, finish=None):
        value = {"choices": [{"delta": delta, "finish_reason": finish}]}
        self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
        self.wfile.flush()

    def do_POST(self):
        if not self.authorized():
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(request)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            last_user = max(i for i, m in enumerate(request["messages"]) if m["role"] == "user")
            prompt = request["messages"][last_user]["content"].lower()
            results = [json.loads(m["content"]) for m in request["messages"][last_user + 1:] if m["role"] == "tool"]
            self.event({"reasoning_content": "HIDDEN_FIXTURE_REASONING must never appear in terminal output"})
            if "local command probe" in prompt:
                commands = [
                    'powershell -NoProfile -Command "Get-Date -Format o"' if os.name == 'nt'
                    else f'"{self.server.tool_python}" -c "print(format(7, \'d\'))"',
                    f'"{self.server.tool_python}" -c "import sys; print(format(7, \'d\')); sys.stderr.write(\'diagnostic\\n\'); sys.exit(7)"',
                ]
                if len(results) < len(commands):
                    self.event({"tool_calls": [{"index": 0, "id": "command-probe-" + str(len(results)), "type": "function",
                                "function": {"name": "run_command", "arguments": json.dumps({"command": commands[len(results)]})}}]}, "tool_calls")
                else:
                    assert [r.get('exit_code') for r in results] == [0, 7], results
                    assert all(r.get('owned_process_exit_confirmed') for r in results), results
                    assert 'diagnostic' in results[1]['stderr'], results
                    self.event({"content": "FIXTURE COMMAND FINAL: both local command outcomes are definitive."}, "stop")
            elif "fix calculator" in prompt:
                stages = [("read_file", {"path": "calculator.py"}),
                          ("edit_file", {"path": "calculator.py", "old_str": "return a // b", "new_str": "return a / b"}),
                          ("run_command", {"command": f'"{self.server.tool_python}" -m unittest -v test_calculator', "timeout_seconds": 30})]
                if len(results) < len(stages):
                    name, args = stages[len(results)]
                    self.event({"content": "FIXTURE proposal: " + name + ". "})
                    self.event({"tool_calls": [{"index": 0, "id": "fixture-step-" + str(len(results)), "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls")
                else:
                    success = results[1].get("status") == "applied" and results[2].get("exit_code") == 0
                    text = ("FIXTURE FINAL: true division applied; real local tests exited 0. " if success else
                            "FIXTURE FINAL: an action was denied or failed; tests are not confirmed. ")
                    for word in text.split(" "):
                        self.event({"content": word + " "})
                        time.sleep(self.server.delay)
                    self.event({}, "stop")
            else:
                if "long stream" in prompt:
                    words = ["LONG_STREAM_ACTIVE "] + ["still generating " for _ in range(300)]
                elif "echo secret" in prompt:
                    words = ["Secret ", TOKEN[:12], TOKEN[12:] + " must be redacted. "]
                elif "terminal controls" in prompt:
                    words = ["Safe text ", "\x1b[2J\x07 ", "continued "]
                else:
                    words = ["STREAM_FIRST ", "Unicode π ✓ ", "STREAM_LAST "]
                for index, word in enumerate(words):
                    self.event({"content": word})
                    self.server.first_chunk.set()
                    if index == 0 and self.server.hold_stream:
                        self.server.release.wait(10)
                    time.sleep(self.server.delay)
                self.event({}, "stop")
            if not self.server.incomplete:
                self.wfile.write(b'data: {"choices": [], "usage": {"completion_tokens": 12}}\n\ndata: [DONE]\n\n')
                self.wfile.flush()
                self.server.completed.set()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.server.connection_closed.set()


def start_fixture(python=None):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.requests, server.health, server.delay = [], "healthy", 0.015
    server.probes, server.health_http_status, server.models = [], 200, ["fixture-code", "fixture-chat"]
    server.tool_python = python or sys.executable
    server.hold_stream = server.incomplete = False
    server.first_chunk, server.release, server.completed, server.connection_closed = (threading.Event() for _ in range(4))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def workspace_files(workspace):
    # Caller creates only disposable workspaces; existing projects are never reset.
    (workspace / "calculator.py").write_text("def divide(a, b):\n    return a // b\n", encoding="utf-8")
    (workspace / "test_calculator.py").write_text(
        "import unittest\nfrom pathlib import Path\nfrom calculator import divide\n"
        "counter = Path('test-run-count.txt')\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
        "class CalculatorTests(unittest.TestCase):\n"
        "    def test_fraction(self): self.assertEqual(divide(7, 2), 3.5)\n"
        "    def test_whole(self): self.assertEqual(divide(8, 2), 4)\n", encoding="utf-8")


def configuration(workspace, url):
    return {"workspace_root": str(workspace), "journal_dir": str(workspace.parent / "legacy ledger"),
            "selected_profile": "code", "selected_worker": "fixture-code-worker",
            "model_profiles": [
                {"profile_id": "code", "model": "fixture-code", "engine": "llama.cpp", "capabilities": ["text", "code_tools"],
                 "resource_requirements": ["slot"], "verification": "fixture-tested"},
                {"profile_id": "chat", "model": "fixture-chat", "engine": "openai-compatible", "capabilities": ["text"], "verification": "fixture-tested"}],
            "workers": [
                {"worker_id": "fixture-code-worker", "location": "local", "engine": "llama.cpp", "url": url,
                 "api_key_env": "FC_FIXTURE_KEY", "profiles": ["code"], "concurrency_limit": 1, "resource_pool": "fixture-machine", "resources": ["slot"]},
                {"worker_id": "fixture-chat-worker", "location": "local", "engine": "openai-compatible", "url": url + "/v1",
                 "api_key_env": "FC_FIXTURE_KEY", "profiles": ["chat"], "resource_pool": "fixture-machine", "resources": ["slot"]}]}
