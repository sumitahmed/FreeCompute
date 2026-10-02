"""Offline SDK fixture process setup. Run only in the pinned optional venv."""
import contextlib
import http.server
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import uuid

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
for key in tuple(os.environ):
    if key.startswith(("LMNR_", "OTEL_", "OPENAI_", "ANTHROPIC_", "AUTOMATION_")):
        os.environ.pop(key)
sdk_home = tempfile.TemporaryDirectory(prefix="fc-foundation-sdk-")
os.environ["OH_PERSISTENCE_DIR"] = sdk_home.name
external_attempts = []
original_connect = socket.socket.connect


def loopback_connect(connection, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
        external_attempts.append(address[0])
        raise RuntimeError("Foundation fixture forbids external network")
    return original_connect(connection, address)


socket.socket.connect = loopback_connect


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        self.server.entered.set()
        if self.server.release:
            self.server.release.wait(3)
        if self.server.retry_once:
            self.server.retry_once = False
            self.send_response(500)
            self.end_headers()
            return
        if self.server.fragments is not None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for part in self.server.fragments:
                if self.server.stream_gate:
                    self.server.stream_gate.wait(3)
                data = {"choices": [{"delta": part if isinstance(part, dict) else {"content": part}}]}
                with contextlib.suppress(OSError):
                    self.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")
                    self.wfile.flush()
            if self.server.stream_done:
                with contextlib.suppress(OSError):
                    self.wfile.write(b"data: [DONE]\n\n")
            return
        if self.server.plan:
            message = self.server.plan(payload)
        elif self.server.proposal and not any(m["role"] == "tool" for m in payload["messages"]):
            tool, args = self.server.proposal
            message = {"role": "assistant", "content": self.server.thought,
                       "tool_calls": [{"id": "fixture-call-" + uuid.uuid4().hex, "type": "function", "function": {
                           "name": "fc_action", "arguments": json.dumps({"tool": tool, "arguments": args})}}]}
        else:
            message = {"role": "assistant", "content": self.server.answer}
        data = {"id": "fixture-" + uuid.uuid4().hex, "object": "chat.completion", "created": 1,
                "model": "fixture", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)


def server():
    instance = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.requests = []
    instance.retry_once = False
    instance.proposal = None
    instance.plan = None
    instance.answer = "fixture completed"
    instance.thought = "fixture proposal"
    instance.fragments = None
    instance.release = None
    instance.stream_gate = None
    instance.stream_done = True
    instance.entered = threading.Event()
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    return instance, thread
