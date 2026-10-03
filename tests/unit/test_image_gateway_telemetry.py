"""Authenticated HTTP image fixtures; no image model or GPU involved."""
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from harness.config import WorkerConnection
from harness.core.service import CoreService
from harness.providers.comfyui import ComfyUIProvider
from harness.telemetry.models import normalize
from test_workers_scheduler import FakeEngine, SMALL

KEY = 'SYNTHETIC_IMAGE_GATEWAY_CREDENTIAL'


class ImageHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        authorized = self.headers.get('Authorization') == 'Bearer ' + KEY
        self.server.probes.append((self.path, authorized))
        if not authorized:
            self.send_response(401); self.end_headers(); return
        if self.server.redirect:
            self.send_response(302); self.send_header('Location', self.server.redirect); self.end_headers(); return
        self.send_response(200); self.end_headers()
        if self.path.startswith('/history/'):
            data = {'fixture-job': {'outputs': {'9': {'images': [{'filename': 'fixture.png'}]}}}}
        elif self.path.startswith('/view'):
            self.wfile.write(b'fixture image bytes'); return
        else:
            data = self.server.stats
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        self.server.posts += 1
        self.server.auth_posts.append(self.headers.get('Authorization') == 'Bearer ' + KEY)
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"prompt_id":"fixture-job"}')


class ImageGatewayTests(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ImageHandler)
        self.server.probes, self.server.auth_posts, self.server.posts, self.server.redirect = [], [], 0, ''
        self.server.stats = {'devices': [{'name': 'fixture GPU', 'vram_total': 1024 * 1024 * 16, 'vram_free': 1024 * 1024 * 4}],
                             'system': {'ram_total': 1024, 'ram_free': 256, 'argv': ['private remote argv']}}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / 'workspace'; self.workspace.mkdir()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3); self.temp.cleanup()

    def test_auth_health_and_real_image_artifact_use_separate_credential(self):
        core = CoreService(self.workspace, FakeEngine(), SMALL, state_dir=self.workspace.parent / 'state')
        core.image_api_key = KEY
        try:
            route = core.model_info()
            result = core.connect_image_worker(self.url)
            self.assertEqual(result['status'], 'healthy')
            with patch('time.sleep'):
                image = core.generate_image('fixture')
            self.assertEqual(Path(image['file_path']).read_bytes(), b'fixture image bytes')
            self.assertEqual(self.server.auth_posts, [True])
            self.assertTrue(all(authorized for _, authorized in self.server.probes))
            self.assertEqual(core.model_info()['profile_id'], route['profile_id'])
            self.assertEqual(core.model_info()['selected_worker'], route['selected_worker'])
            rows = core.store.all('SELECT observation FROM workers')
            self.assertNotIn(KEY, str(rows))
            self.assertNotIn('private remote argv', str(rows))
        finally:
            core.close()

    def test_wrong_image_key_reports_authentication_failure(self):
        provider = ComfyUIProvider(self.url, workspace_root=str(self.workspace), api_key='SYNTHETIC_WRONG_IMAGE_KEY')
        health = provider.get_health()
        self.assertEqual(health.status, 'unreachable')
        self.assertIn('authentication failed', health.raw['error'])
        self.assertNotIn(provider.api_key, health.raw['error'])

    def test_optional_malformed_metrics_do_not_prevent_healthy_image_inference(self):
        self.server.stats = {'devices': [{'name': 'fixture GPU', 'vram_total': 16, 'vram_free': 'unknown'}], 'system': {'ram_total': 'invalid'}}
        provider = ComfyUIProvider(self.url, workspace_root=str(self.workspace), api_key=KEY)
        health = provider.get_health()
        self.assertEqual(health.status, 'healthy')
        t = normalize(health.raw)
        self.assertIsNone(t.metrics['ram_total_bytes']['value'])
        self.assertIsNone(t.gpus[0]['vram_used_mib']['value'])
        self.assertIsNone(t.gpus[0]['temperature_c']['value'])
        with patch('time.sleep'):
            image = provider.generate_image('fixture')
        self.assertTrue(Path(image['file_path']).is_file())

    def test_auth_redirect_is_not_followed(self):
        self.server.redirect = self.url + '/other-host'
        provider = ComfyUIProvider(self.url, workspace_root=str(self.workspace), api_key=KEY)
        health = provider.get_health()
        self.assertEqual(health.status, 'unreachable')
        self.assertEqual(len(self.server.probes), 1)

    def test_session_limit_and_no_deadline_configuration_conflict_rejected(self):
        with self.assertRaises(ValueError):
            WorkerConnection(worker_id='local', location='local', engine='llama.cpp', url=self.url, profiles=['text'],
                             session_has_no_deadline=True, session_limit_seconds=3600)

    def test_manifest_limit_precedes_explicit_config_but_not_runtime(self):
        raw = {'session_manifest': {'session_age_seconds': 100, 'session_limit_seconds': 1000, 'observed_at': 10000}}
        t = normalize(raw, configured_limit=500, now=10000)
        self.assertEqual(t.metrics['session_remaining_seconds']['value'], 900)
        self.assertEqual(t.metrics['session_limit_seconds']['source'], 'worker/session manifest')
        raw['telemetry'] = {'schema_version': 1, 'observed_at': 10000, 'metrics': {'session_limit_seconds': {'value': 2000, 'status': 'provider-reported', 'source': 'runtime'}}}
        t = normalize(raw, configured_limit=500, now=10000)
        self.assertEqual(t.metrics['session_limit_seconds']['value'], 2000)


if __name__ == '__main__':
    unittest.main()
