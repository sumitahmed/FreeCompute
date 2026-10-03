"""Command menu, Windows-safe formatting, optional telemetry and independent routes."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from prompt_toolkit.application import create_app_session
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from harness.cli.commands import CommandRegistry
from harness.cli.formatter import TerminalFormatter, TaskPresentation, terminal_text
from harness.cli.input import CommandCompleter, TerminalInput
from harness.cli.core_client import CoreClient
from harness.cli.telemetry import lines
from harness.config import HarnessConfig
from harness.core.engines import ComfyUIEngine
from harness.core.runtime_models import ModelProfile, Worker
from harness.core.service import CoreService
from harness.providers.comfyui import ComfyUIProvider
from harness.security import SecretScrubber
from harness.skills.manager import SkillManager
from harness.telemetry.models import normalize, metric
from harness.telemetry.session_tracker import SessionTracker
from test_workers_scheduler import FakeEngine, SMALL


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'workspace'
        self.root.mkdir()
        self.core = CoreService(self.root, FakeEngine(), SMALL, state_dir=self.root.parent / 'state')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.core.close)
        self.client = CoreClient(self.core)
        self.registry = CommandRegistry(self.core.skills)

    def test_help_menu_and_bundled_skills_share_registry(self):
        names = {c.name for c in self.registry.entries()}
        self.assertTrue({'/model', '/models', '/image-model', '/connect-image', '/review', '/research', '/leetcode'} <= names)
        help_text = '\n'.join(self.registry.help_lines())
        for name in ('/review', '/research', '/model', '/connect-image'):
            self.assertIn(name, help_text)
        self.assertEqual(self.registry.canonical('/health'), '/status')

    def test_slash_filters_and_argument_completion_uses_declared_routes(self):
        completer = CommandCompleter(self.registry, self.client)
        self.assertEqual([c.text for c in completer.get_completions(Document('/mo'), None)], ['/model', '/models'])
        candidates = completer.candidates('/model ')
        self.assertEqual(candidates[0][0], 'small')
        self.assertIn('small-fixture | code_tools, text | context 65,536 declared', candidates[0][1])
        self.assertIn('local-small:', candidates[0][1])
        self.assertEqual(completer.candidates('/image-model '), [])
        self.assertTrue(completer.candidates('/skill web'))
        self.assertEqual(completer.candidates('ordinary prompt'), [])

    def test_custom_skill_palette_refresh_and_no_permission_expansion(self):
        path = self.root / 'skills' / 'local-reader'
        path.mkdir(parents=True)
        (path / 'SKILL.md').write_text('---\nname: local-reader\nslash_command: /read-local\ndescription: Read locally\nallowed_tools: [read_file]\n---\nRead the requested file.', encoding='utf-8')
        self.core.skills.discover_skills()
        self.assertIn('/read-local', {c.name for c in self.registry.entries()})
        skill = self.core.skills.get_skill('/read-local')
        self.assertEqual(self.core.skills.restrictions(skill, self.core.tools.tools, SMALL.capabilities), frozenset({'read_file'}))

    def test_menu_actual_key_events_enter_select_escape_and_multiline(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            reader = TerminalInput(self.registry, self.client, interactive=True)
            observed = {}
            def drive():
                time.sleep(.5)  # Win32 input attachment completes after run begins.
                pipe.send_text('/mo')
                time.sleep(.5)
                deadline = time.time() + 4
                while time.time() < deadline:
                    state = reader.session.default_buffer.complete_state
                    if state and len(state.completions) == 2:
                        observed['menu'] = [c.text for c in state.completions]
                        break
                    time.sleep(.01)
                observed['buffer'] = reader.session.default_buffer.text
                observed['state'] = repr(reader.session.default_buffer.complete_state)
                pipe.send_text('\x1b[B\r')  # Down selects, Enter completes without submitting.
                time.sleep(.1)
                observed['selected'] = reader.session.default_buffer.text
                pipe.send_text('\r')
                time.sleep(.5)
                pipe.close()  # Bound failures rather than leaving a prompt waiting forever.
            thread = threading.Thread(target=drive, daemon=True)
            thread.start()
            answer = reader.read()
            thread.join(3)
        self.assertEqual(observed.get('menu'), ['/model', '/models'], observed)
        self.assertEqual(observed['selected'], '/model')
        self.assertEqual(answer, '/model')

    def test_plain_prompt_has_no_ansi_fragments(self):
        reader = TerminalInput(self.registry, self.client, interactive=False)
        with patch('builtins.input', return_value='/help') as read:
            self.assertEqual(reader.read(), '/help')
        self.assertEqual(read.call_args.args[0], 'freecompute> ')

    def test_tab_escape_and_multiline_keyboard_flow(self):
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            reader = TerminalInput(self.registry, self.client, interactive=True)
            observed = {}
            def drive():
                time.sleep(.5)
                pipe.send_text('/')
                time.sleep(.3)
                observed['slash_menu'] = reader.session.default_buffer.complete_state is not None
                pipe.send_text('\x1b')
                time.sleep(.4)
                observed['dismissed'] = reader.session.default_buffer.complete_state is None
                pipe.send_text('\x15/mo\t')  # Ctrl+U replaces the line; Tab completes.
                time.sleep(.4)
                observed['tab'] = reader.session.default_buffer.text
                pipe.send_text('\x15first\x1b\rsecond\r')  # Alt+Enter inserts a newline.
                time.sleep(.5)
                pipe.close()
            thread = threading.Thread(target=drive, daemon=True)
            thread.start()
            answer = reader.read()
            thread.join(4)
        self.assertTrue(observed['slash_menu'])
        self.assertTrue(observed['dismissed'])
        self.assertEqual(observed['tab'], '/model')
        self.assertEqual(answer, 'first\nsecond')

    def test_resume_completion_uses_real_saved_session_ids(self):
        result = self.client.run_task('one')
        values = CommandCompleter(self.registry, self.client).candidates('/resume ' + result['session_id'][:8])
        self.assertEqual(values[0][0], result['session_id'])

    def test_image_selection_and_reconnect_do_not_change_text_or_tasks(self):
        text_route = self.core.model_info()
        completed = self.client.run_task('first')
        provider = ComfyUIProvider('http://127.0.0.1:9', workspace_root=str(self.root))
        image = ModelProfile('image', model='ComfyUI-default', engine='ComfyUI', capabilities=frozenset({'image_gen'}))
        worker = Worker('image-worker', 'local', 'ComfyUI', image.capabilities, resource_pool='image-host')
        self.core.attach_worker(worker, [image], ComfyUIEngine(provider))
        self.client.select_image_model('image', 'image-worker')
        with patch.object(ComfyUIProvider, 'get_health', return_value=provider.get_health()):
            result = self.client.connect_image('http://127.0.0.1:10')
        self.assertEqual(result['worker_id'], 'image-worker')
        self.assertEqual(self.core.model_info()['profile_id'], text_route['profile_id'])
        self.assertEqual(self.core.model_info()['selected_worker'], text_route['selected_worker'])
        self.assertEqual(self.core.task(completed['task_id'])['state'], 'completed')
        self.assertEqual(self.core.image_provider.server_url, 'http://127.0.0.1:10')
        self.assertEqual(len(self.core.registry.engine('local-small').calls), 1)

    def test_text_profile_rejected_by_image_selector(self):
        with self.assertRaises(ValueError):
            self.core.select_image_model('small')

    def test_invalid_image_reconnect_does_not_mutate_route(self):
        for url in ('file:///etc/passwd', 'https://user:pass@host', 'http://host:0', 'http://host\n'):
            with self.assertRaises(ValueError):
                self.core.connect_image_worker(url)
        self.assertIsNone(self.core.image_profile_id)

    def test_remote_image_requires_its_own_key(self):
        with self.assertRaisesRegex(ValueError, 'FREECOMPUTE_IMAGE_API_KEY'):
            self.core.connect_image_worker('https://images.example.invalid')
        self.assertIsNone(self.core.image_profile_id)


class FormatTests(unittest.TestCase):
    def test_nested_ansi_is_removed_as_whole_sequence(self):
        fmt = TerminalFormatter(False)
        fmt.use_colors = True
        text = fmt.bold(fmt.cyan('freecompute> '))
        self.assertNotIn('[36m', terminal_text(text))
        self.assertEqual(terminal_text(text), 'freecompute> ')

    def test_terminal_cursor_and_osc_controls_are_removed(self):
        self.assertEqual(terminal_text('a\x1b[2Jb\x1b]0;spoofed title\x07c'), 'abc')

    def test_no_color_for_redirected_stream(self):
        with patch('sys.stdout.isatty', return_value=False):
            self.assertFalse(TerminalFormatter().use_colors)

    def test_markdown_chunk_does_not_wait_for_response_completion(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            view = TaskPresentation(TerminalFormatter(False))
            view.token('# Heading\n```python\n')
            self.assertIn('# Heading', output.getvalue())
            view.token('print(1)\n```\n')
            self.assertIn('print(1)', output.getvalue())
            view.boundary()


class NormalizedTelemetryTests(unittest.TestCase):
    def sample(self, **metrics):
        return {'status': 'healthy', 'telemetry': {'schema_version': 1, 'observed_at': 10000,
                'metrics': {name: metric(v, source='fixture runtime', name=name) for name, v in metrics.items()}}}

    def test_old_supervisor_does_not_invent_twelve_hour_session(self):
        t = normalize({'supervisorUptimeSeconds': 500, 'linuxUptimeSeconds': 900, 'sessionAgeSource': 'supervisor_start_estimate',
                       'sessionAgeSeconds': 500, 'maxSessionSeconds': 43200}, provider='kaggle', now=10000)
        for name in ('session_age_seconds', 'session_limit_seconds', 'session_remaining_seconds'):
            self.assertIsNone(t.metrics[name]['value'])
        self.assertEqual(t.metrics['kernel_uptime_seconds']['value'], 900)

    def test_configured_limit_is_labeled_and_remaining_requires_session_age(self):
        t = normalize({}, configured_limit=3600, now=10000)
        self.assertEqual(t.metrics['session_limit_seconds']['status'], 'configured')
        self.assertIsNone(t.metrics['session_remaining_seconds']['value'])
        t = normalize(self.sample(session_age_seconds=3100), configured_limit=3600, now=10000)
        self.assertEqual(t.metrics['session_remaining_seconds']['value'], 500)
        self.assertEqual(t.warning(10000), '10 minutes')

    def test_runtime_limit_beats_configuration(self):
        t = normalize(self.sample(session_age_seconds=10, session_limit_seconds=7200), configured_limit=3600, now=10000)
        self.assertEqual(t.metrics['session_limit_seconds']['value'], 7200)
        self.assertEqual(t.metrics['session_remaining_seconds']['value'], 7190)

    def test_stale_sample_does_not_warn(self):
        t = normalize(self.sample(session_age_seconds=3590, session_limit_seconds=3600), now=10100)
        self.assertTrue(t.stale(10100))
        self.assertIsNone(t.warning(10100))
        self.assertIn('[STALE]', '\n'.join(lines({'telemetry': t.to_dict()}, now=10100)))

    def test_local_no_deadline_and_colab_unknown_are_not_kaggle_defaults(self):
        local = normalize({}, provider='local', no_deadline=True, now=10000)
        self.assertEqual(local.metrics['session_limit_seconds']['value'], 'none')
        colab = normalize({}, provider='colab', now=10000)
        self.assertIsNone(colab.metrics['session_limit_seconds']['value'])
        self.assertIsNone(colab.warning(10000))

    def test_partial_hardware_keeps_unknown_temperature_and_cpu(self):
        raw = {'gpus': [{'name': 'Tesla T4', 'vramTotalMiB': 15360}]}
        t = normalize(raw, now=10000)
        self.assertEqual(t.gpus[0]['vram_total_mib']['value'], 15360)
        self.assertIsNone(t.gpus[0]['temperature_c']['value'])
        self.assertIsNone(t.metrics['cpu_utilization_pct']['value'])
        self.assertIn('CPU unknown', '\n'.join(lines({'telemetry': t.to_dict()}, now=10000)))

    def test_malformed_optional_metrics_are_unknown_not_inference_failure(self):
        for malformed in (None, [], 'invalid', {'schema_version': 1, 'metrics': {'cpu_count': 'many', 'ram_used_bytes': {'value': float('nan'), 'status': 'observed'}}}):
            t = normalize({'telemetry': malformed}, now=10000)
            self.assertIsNone(t.metrics['cpu_count']['value'])
            self.assertIsNone(t.metrics['ram_used_bytes']['value'])

    def test_metric_statuses_retained_and_invalid_percent_rejected(self):
        for status in ('observed', 'provider-reported', 'configured', 'estimated', 'user-provided'):
            t = normalize({'telemetry': {'schema_version': 1, 'metrics': {'cpu_count': {'value': 8, 'status': status, 'source': 'fixture'}}}}, now=10000)
            self.assertEqual(t.metrics['cpu_count']['status'], status)
        self.assertIsNone(metric(120, name='cpu_utilization_pct')['value'])

    def test_legacy_session_tracker_has_no_default_limit(self):
        tracker = SessionTracker()
        tracker.update_from_remote_health({'containerUptimeSeconds': 100})
        self.assertIsNone(tracker.seconds_remaining_in_12h_session)
        self.assertFalse(tracker.is_warning)


if __name__ == '__main__':
    unittest.main()
