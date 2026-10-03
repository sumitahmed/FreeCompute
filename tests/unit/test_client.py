"""
tests/unit/test_client.py — Unit tests for authenticated client, SSE parsing, TTFT, and cancellation.
"""

import http.server
import json
import socketserver
import threading
import time
import unittest

from harness.core.client import KaggleBrainClient, AuthenticationError, CancellationToken


class MockSupervisorHandler(http.server.BaseHTTPRequestHandler):
    VALID_API_KEY = "test-secret-token"

    def log_message(self, format, *args):
        pass

    def check_auth(self):
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {self.VALID_API_KEY}":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized"}')
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            if not self.check_auth():
                return
            data = {
                "status": "healthy",
                "supervisorUptimeSeconds": 150.0,
                "containerUptimeSeconds": 3600.0,
                "maxSessionSeconds": 43200.0,
                "secondsRemainingIn12hSession": 39600.0,
                "gpus": [
                    {
                        "index": 0,
                        "name": "Tesla T4",
                        "vramUsedMiB": 9187,
                        "vramTotalMiB": 15360,
                        "tempC": 56,
                        "utilizationPct": 15,
                    },
                    {
                        "index": 1,
                        "name": "Tesla T4",
                        "vramUsedMiB": 10305,
                        "vramTotalMiB": 15360,
                        "tempC": 59,
                        "utilizationPct": 18,
                    },
                ],
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            if not self.check_auth():
                return
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            tokens = ["def ", "add", "(a, ", "b):", "\n    ", "return ", "a + b"]
            for tok in tokens:
                chunk = {
                    "choices": [
                        {
                            "delta": {"content": tok},
                            "index": 0,
                            "finish_reason": None,
                        }
                    ]
                }
                try:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    break
                time.sleep(0.01)

            try:
                if payload.get("stream_options", {}).get("include_usage"):
                    usage = {"choices": [], "usage": {"prompt_tokens": 14, "completion_tokens": 7, "total_tokens": 21}}
                    self.wfile.write(f"data: {json.dumps(usage)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass


class TestKaggleBrainClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), MockSupervisorHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_health_authenticated(self):
        client = KaggleBrainClient(
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="test-secret-token",
        )
        health = client.get_health()
        self.assertEqual(health.status, "healthy")
        self.assertEqual(health.container_uptime_s, 3600.0)
        self.assertEqual(len(health.gpus), 2)
        self.assertEqual(health.gpus[0].vram_used_mib, 9187)
        self.assertEqual(health.gpus[1].vram_used_mib, 10305)

    def test_get_health_unauthorized_negative_test(self):
        bad_client = KaggleBrainClient(
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="invalid-key-123",
        )
        with self.assertRaises(AuthenticationError):
            bad_client.get_health()

    def test_stream_chat_token_by_token(self):
        client = KaggleBrainClient(
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="test-secret-token",
        )
        messages = [{"role": "user", "content": "Write add"}]
        chunks = list(client.stream_chat(messages))

        self.assertGreater(len(chunks), 0)
        self.assertTrue(chunks[0].is_first_token)
        self.assertIsNotNone(chunks[0].ttft_ms)
        self.assertGreater(chunks[0].ttft_ms, 0.0)

        full_text = "".join(c.delta_content for c in chunks)
        self.assertEqual(full_text, "def add(a, b):\n    return a + b")

    def test_stream_chat_cancellation(self):
        client = KaggleBrainClient(
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="test-secret-token",
        )
        token = CancellationToken()
        messages = [{"role": "user", "content": "Write add"}]

        collected = []
        for i, chunk in enumerate(client.stream_chat(messages, cancellation_token=token)):
            collected.append(chunk.delta_content)
            if i == 1:
                token.cancel()

        self.assertLess(len(collected), 5)

    def test_stream_requests_usage_and_accepts_empty_choices_usage_chunk(self):
        client = KaggleBrainClient(
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="test-secret-token",
        )
        chunks = list(client.stream_chat([{"role": "user", "content": "Write add"}]))
        usage = [chunk.usage for chunk in chunks if chunk.usage is not None]
        self.assertEqual(usage, [{"prompt_tokens": 14, "completion_tokens": 7, "total_tokens": 21}])
        self.assertTrue(chunks[-1].stream_complete)


if __name__ == "__main__":
    unittest.main()
