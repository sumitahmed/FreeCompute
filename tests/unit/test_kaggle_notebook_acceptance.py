"""Execute notebook control paths with local fakes; never start a GPU or tunnel."""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
import urllib.request
from unittest.mock import Mock, patch


class KaggleNotebookAcceptanceTests(unittest.TestCase):
    def setUp(self):
        path = Path('kaggle/freecompute_dual_gpu_server.ipynb')
        self.notebook = json.loads(path.read_text(encoding='utf-8'))
        self.cells = [''.join(c['source']) for c in self.notebook['cells']]
        self.output = io.StringIO()
        self.bearer, self.tailkey = 'fixture-bearer', 'fixture-tailkey'
        libc = patch('platform.libc_ver', return_value=('glibc', '2.39'))
        libc.start()
        self.addCleanup(libc.stop)

    def configuration(self, transport='cloudflare'):
        secrets = { 'FREECOMPUTE_API_KEY': self.bearer, 'TAILSCALE_AUTHKEY': self.tailkey }
        module = types.ModuleType('kaggle_secrets')
        module.UserSecretsClient = lambda: types.SimpleNamespace(get_secret=secrets.__getitem__)
        state = {}
        with patch.dict(sys.modules, kaggle_secrets=module), contextlib.redirect_stdout(self.output):
            exec(self.cells[1].replace("TRANSPORT = 'cloudflare'", f"TRANSPORT = '{transport}'"), state)
        return state

    def test_wrappers_compile_and_match_canonical_supervisor_and_scrubber(self):
        other = Path('kaggle/universal_dual_gpu_server.ipynb')
        self.assertEqual(self.notebook, json.loads(other.read_text(encoding='utf-8')))
        self.assertEqual(self.cells[4], Path('kaggle/download_llama_engine.py').read_text(encoding='utf-8'))
        for cell in self.notebook['cells']:
            if cell['cell_type'] == 'code':
                compile(''.join(cell['source']), 'notebook', 'exec')
                self.assertEqual(cell['outputs'], [])
                self.assertIsNone(cell['execution_count'])
        tree = ast.parse(self.cells[6])
        embedded = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'supervisor_script' for t in n.targets))
        self.assertEqual(embedded, Path('kaggle/supervisor.py').read_text(encoding='utf-8'))
        source_tree = ast.parse(Path('harness/security.py').read_text(encoding='utf-8'))
        canonical = next(n for n in source_tree.body if isinstance(n, ast.ClassDef) and n.name == 'SecretScrubber')
        embedded_class = next(n for n in ast.parse(self.cells[1]).body if isinstance(n, ast.ClassDef))
        self.assertEqual(ast.dump(canonical), ast.dump(embedded_class))

    def test_configuration_preserves_profile_and_does_not_print_secrets(self):
        state = self.configuration()
        cfg = state['CONFIG']
        self.assertEqual(cfg['CTX_SIZE'], 65536)
        self.assertEqual(cfg['REVISION'], '3f101cd22b7999228bbd5d79a33975414eb9758b')
        self.assertEqual((cfg['SPLIT_MODE'], cfg['TENSOR_SPLIT'], cfg['CACHE_TYPE_K'], cfg['CACHE_TYPE_V']),
                         ('layer', '1,1', 'f16', 'f16'))
        self.assertEqual(cfg['TRANSPORT'], 'cloudflare')
        self.assertEqual(cfg['TAILSCALE_AUTHKEY'], '')
        self.assertFalse(cfg['USE_DATASET_CACHE'])
        with contextlib.redirect_stdout(self.output):
            state['print'](self.bearer)
        self.assertNotIn(self.bearer, self.output.getvalue())

    def test_tailscale_mode_registers_its_optional_secret(self):
        state = self.configuration('tailscale')
        with contextlib.redirect_stdout(self.output):
            state['print'](self.tailkey)
        self.assertNotIn(self.tailkey, self.output.getvalue())

    def engine_archives(self, unsafe=False):
        archives = []
        contents = [
            {'llama-b11206/llama-server': b'fixture binary',
             'llama-b11206/libggml-cuda.so': b'fixture backend'},
            {f'cudart-llama-b11206-bin-ubuntu-cuda-12.8-x64/{name}': b'fixture CUDA library'
             for name in ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12')},
        ]
        if unsafe:
            contents[0]['../../outside-engine'] = b'unsafe'
        for files in contents:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w:gz') as bundle:
                for name, data in files.items():
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), 0o755
                    bundle.addfile(info, io.BytesIO(data))
            archives.append(buffer.getvalue())
        code = self.cells[4]
        for production_digest, data in zip((
                'fa78d7d80b8dca117638c49fc4aa58d6b01407541804483876c27323ebb887de',
                'bcc52b864ad3edbdd18d10d8061bb84af2c085c50621d0cc19e135130cc360e8'), archives):
            self.assertIn(production_digest, code)
            code = code.replace(production_digest, hashlib.sha256(data).hexdigest())
        return code, archives

    def test_download_verifies_archives_libraries_pin_and_both_gpus(self):
        state = self.configuration()
        code, archives = self.engine_archives()
        with tempfile.TemporaryDirectory() as directory:
            state.update(SCRATCH=Path(directory), SERVER_BIN=None)
            responses = [types.SimpleNamespace(returncode=0, stdout=text, stderr='') for text in (
                'version: 11206 (2b129ccfa)', 'CUDA0: Tesla T4\nCUDA1: Tesla T4')]
            with patch.object(urllib.request, 'urlopen', side_effect=[io.BytesIO(a) for a in archives]) as download, \
                 patch.object(subprocess, 'run', side_effect=responses * 2) as run, \
                 patch.dict('os.environ'), \
                 contextlib.redirect_stdout(self.output):
                exec(code, state)
                exec(code, state)  # Verified cache avoids repeat downloads.
            self.assertEqual(download.call_count, 2)
            for call in download.call_args_list:
                self.assertIn('/releases/download/b11206/', call.args[0].full_url)
                self.assertIn('cuda-12.8-x64.tar.gz', call.args[0].full_url)
            self.assertEqual([c.args[0][-1] for c in run.call_args_list],
                             ['--version', '--list-devices'] * 2)
            self.assertTrue((state['SERVER_BIN'].parent / 'libcublas.so.12').is_file())
            self.assertEqual(state['ENGINE_PROVENANCE']['commit'], state['CONFIG']['LLAMA_COMMIT'])

    def test_download_rejects_corrupt_archive_before_extraction_or_execution(self):
        state = self.configuration()
        code, archives = self.engine_archives()
        with tempfile.TemporaryDirectory() as directory:
            state['SCRATCH'] = Path(directory)
            with patch.object(urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt')), \
                 patch.object(subprocess, 'run') as run, contextlib.redirect_stdout(self.output):
                with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
                    exec(code, state)
            run.assert_not_called()
            self.assertFalse((state['ENGINE_DIR'] / 'llama-b11206').exists())

    def test_download_rejects_tar_path_traversal(self):
        state = self.configuration()
        code, archives = self.engine_archives(unsafe=True)
        with tempfile.TemporaryDirectory() as directory:
            state['SCRATCH'] = Path(directory)
            with patch.object(urllib.request, 'urlopen', return_value=io.BytesIO(archives[0])), \
                 patch.object(subprocess, 'run') as run, contextlib.redirect_stdout(self.output):
                with self.assertRaises(tarfile.FilterError):
                    exec(code, state)
            run.assert_not_called()
            self.assertFalse((Path(directory).parent / 'outside-engine').exists())
            self.assertFalse((state['ENGINE_DIR'] / 'llama-b11206').exists())

    def test_download_rejects_wrong_version_cpu_fallback_and_runtime_failure(self):
        code, archives = self.engine_archives()
        cases = [
            ([('version: 11207 (abcdef0)', 0)], 'pinned commit'),
            ([('version: 11206 (2b129ccfa)', 0), ('CPU: fixture', 0)], 'both T4'),
            ([('missing library ' + self.bearer, 1)], 'incompatible'),
        ]
        for outputs, error_text in cases:
            with self.subTest(error=error_text), tempfile.TemporaryDirectory() as directory:
                state = self.configuration()
                state['SCRATCH'] = Path(directory)
                results = [types.SimpleNamespace(stdout=text, stderr='', returncode=rc) for text, rc in outputs]
                with patch.object(urllib.request, 'urlopen', side_effect=[io.BytesIO(a) for a in archives]), \
                     patch.object(subprocess, 'run', side_effect=results), patch.dict('os.environ'), \
                     contextlib.redirect_stdout(self.output):
                    with self.assertRaisesRegex(RuntimeError, error_text) as error:
                        exec(code, state)
                self.assertNotIn(self.bearer, str(error.exception))

    def test_download_rejects_changed_pin_or_running_worker(self):
        state = self.configuration()
        state['CONFIG']['LLAMA_COMMIT'] = 'different'
        with self.assertRaisesRegex(RuntimeError, 'configured engine pin'):
            exec(self.cells[4], state)
        state['llama_proc'] = types.SimpleNamespace(poll=lambda: None)
        with self.assertRaisesRegex(RuntimeError, 'already running'):
            exec(self.cells[4], state)

    def test_download_checks_glibc_before_network_use(self):
        state = self.configuration()
        with patch('platform.libc_ver', return_value=('glibc', '2.35')), \
             patch.object(urllib.request, 'urlopen') as download:
            with self.assertRaisesRegex(RuntimeError, 'glibc >= 2.38'):
                exec(self.cells[4], state)
        download.assert_not_called()

    def test_transport_forwards_tcp_and_removes_key_file_without_exposing_it(self):
        state = self.configuration('tailscale')
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            (scratch / 'tailscale').mkdir()
            for name in ('tailscaled', 'tailscale'):
                (scratch / 'tailscale' / name).touch()
            (scratch / 'tailscaled.sock').touch()
            state.update(SCRATCH=scratch, supervisor_proc=process, llama_proc=process)
            commands = []
            def run(cmd, **kwargs):
                commands.append(cmd)
                if 'up' in cmd:
                    self.assertEqual((scratch / 'tailscale-auth.key').read_text(), self.tailkey)
                return types.SimpleNamespace(returncode=0, stdout='100.64.0.1' if 'ip' in cmd else '', stderr='')
            with patch.object(subprocess, 'run', side_effect=run), \
                 patch.object(subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(self.output):
                exec(self.cells[7], state)
            self.assertEqual(commands[-1][-4:], ['serve', '--bg', '--tcp=8081', 'tcp://127.0.0.1:8081'])
            self.assertFalse((scratch / 'tailscale-auth.key').exists())
            self.assertEqual(state['remote_url'], 'http://100.64.0.1:8081')
            self.assertNotIn(self.tailkey, repr(commands))
            self.assertNotIn(self.bearer, self.output.getvalue())
            self.assertNotIn(self.tailkey, self.output.getvalue())

    def test_transport_failure_scrubs_error_and_cleans_up(self):
        state = self.configuration('tailscale')
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            (scratch / 'tailscale').mkdir()
            for name in ('tailscaled', 'tailscale'):
                (scratch / 'tailscale' / name).touch()
            (scratch / 'tailscaled.sock').touch()
            state.update(SCRATCH=scratch, supervisor_proc=process, llama_proc=process)
            with patch.object(subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=1, stdout='', stderr='denied ' + self.tailkey)), \
                 patch.object(subprocess, 'Popen', return_value=process):
                with self.assertRaises(RuntimeError) as error:
                    exec(self.cells[7], state)
            self.assertNotIn(self.tailkey, str(error.exception))
            self.assertFalse((scratch / 'tailscale-auth.key').exists())
            process.terminate.assert_called_once()

    def test_cloudflare_uses_bearer_only_and_reports_url(self):
        state = self.configuration()
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            (scratch / 'cloudflared').touch()
            state.update(SCRATCH=scratch, supervisor_proc=process, llama_proc=process)
            tunnel = 'https://' + 'example-acceptance' + '.trycloudflare.com'
            process.stdout = io.StringIO('Started at ' + tunnel + '\n')
            def start(cmd, **kwargs):
                self.assertIn('--protocol', cmd)
                return process
            with patch.object(subprocess, 'Popen', side_effect=start), \
                 patch.object(subprocess, 'run') as run, contextlib.redirect_stdout(self.output):
                exec(self.cells[7], state)
            run.assert_not_called()
            self.assertEqual(state['remote_url'], tunnel)
            self.assertIn(tunnel, self.output.getvalue())
            self.assertNotIn(self.bearer, self.output.getvalue())
            self.assertNotIn(self.tailkey, self.output.getvalue())
            self.assertFalse((scratch / 'cloudflared.log').exists())

    def test_readiness_authenticates_and_never_generates(self):
        state = self.configuration()
        requests = Mock()
        health = Mock()
        health.json.return_value = {'status': 'healthy', 'llamaServer': {'healthy': True}, 'gpus': []}
        models = Mock()
        models.json.return_value = {'data': [{'id': state['CONFIG']['MODEL_ALIAS']}]}
        requests.get.side_effect = [health, models]
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / 'model.gguf'
            model_path.touch()
            state.update(requests=requests, subprocess=subprocess, SERVER_BIN=Path('fixture-server'),
                         MODEL_PATH=model_path, llama_cmd=['fixture-server', '--parallel', '1'],
                         ENGINE_PROVENANCE={'distribution': 'fixture'})
            with patch.object(subprocess, 'check_output', return_value='fixture-version'), \
                 contextlib.redirect_stdout(self.output):
                exec(self.cells[8], state)
            for call in requests.get.call_args_list:
                self.assertEqual(call.kwargs['headers'], {'Authorization': 'Bearer ' + self.bearer})
                self.assertEqual(call.kwargs['timeout'], 10)
            requests.post.assert_not_called()
            self.assertIn('WORKER READY FOR LOCAL ACCEPTANCE', self.output.getvalue())

    def test_readiness_rejects_degraded_worker(self):
        state = self.configuration()
        requests = Mock()
        requests.get.return_value.json.return_value = {'status': 'degraded', 'llamaServer': {'healthy': False}}
        state['requests'] = requests
        with self.assertRaisesRegex(RuntimeError, 'not healthy'):
            exec(self.cells[8], state)
        self.assertEqual(requests.get.call_count, 1)

    def test_running_startup_and_default_shutdown_are_safe(self):
        state = self.configuration()
        process = Mock()
        process.poll.return_value = None
        state['llama_proc'] = process
        with patch.dict(sys.modules, requests=Mock()):
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                exec(self.cells[6], state)
        with contextlib.redirect_stdout(self.output):
            exec(self.cells[9], state)
        process.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
