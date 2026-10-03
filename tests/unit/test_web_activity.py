"""Local HTTP fixtures exercise real web parsing through durable Core tool cycles."""
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

from harness.core.models import StreamChunk
from harness.core.service import CoreService
from harness.tools import web
from test_workers_scheduler import FakeEngine, SMALL


class WebFixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        data = (b'<a class="result__a" href="https://example.org/page">Fixture title</a><a class="result__snippet">Fixture snippet</a>'
                if self.path == '/search' else b'<h1>Fixture page</h1><p>Actual HTTP fixture content.</p><script>omit_me()</script>')
        self.wfile.write(data)


class WebEngine(FakeEngine):
    def stream(self, profile, messages, tools, cancellation):
        self.calls.append(messages)
        results = [m for m in messages if m['role'] == 'tool']
        if len(results) < 2:
            name, args = ('search_web', {'query': 'fixture search'}) if not results else ('fetch_url', {'url': 'https://example.org/page'})
            yield StreamChunk(tool_call_deltas=[{'index': 0, 'id': 'web-' + str(len(results)), 'function': {'name': name, 'arguments': json.dumps(args)}}], finish_reason='tool_calls')
        else:
            yield StreamChunk(delta_content='Fixture research finished.', finish_reason='stop')
        yield StreamChunk(stream_complete=True)


class WebActivityTests(unittest.TestCase):
    def test_local_web_tools_produce_events_and_results_return_to_model(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), WebFixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def fixture_transport(request, timeout):
            path = '/search' if 'duckduckgo' in request.full_url else '/page'
            return urllib.request.urlopen(base + path, timeout=timeout)
        try:
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / 'workspace'; workspace.mkdir()
                engine = WebEngine()
                core = CoreService(workspace, engine, SMALL, state_dir=Path(directory) / 'state')
                events = []
                core.subscribe(events.append)
                try:
                    with patch.object(web, '_open', side_effect=fixture_transport):
                        result = core.run(core.submit('research fixture', allowed_tools=['search_web', 'fetch_url']))
                    self.assertEqual(result['status'], 'completed')
                    self.assertEqual(len(engine.calls), 3)
                    actions = [e['payload']['tool'] for e in events if e['kind'] == 'tool.execution_intent']
                    self.assertEqual(actions, ['search_web', 'fetch_url'])
                    returned = [json.loads(m['content']) for m in engine.calls[-1] if m['role'] == 'tool']
                    self.assertEqual(returned[0]['results'][0]['title'], 'Fixture title')
                    self.assertIn('Actual HTTP fixture content', returned[1]['content'])
                    self.assertNotIn('omit_me', returned[1]['content'])
                finally:
                    core.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def test_private_and_non_http_urls_fail_cleanly(self):
        for url in ('http://127.0.0.1/', 'http://[::1]/', 'http://169.254.169.254/', 'http://10.0.0.1/', 'file:///etc/passwd', 'https://user:pass@example.org/'):
            with self.assertRaises(ValueError): web.validate_public_url(url)

    def test_redirect_to_private_host_is_blocked(self):
        with self.assertRaises(ValueError):
            web.PublicRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/')

    def test_web_response_size_is_bounded(self):
        with self.assertRaises(ValueError): web._read(io.BytesIO(b'x' * (web.MAX_WEB_BYTES + 1)))


if __name__ == '__main__':
    unittest.main()
