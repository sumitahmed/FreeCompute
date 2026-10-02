"""Execute notebook control paths with local fakes; never start a GPU or tunnel."""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class KaggleNotebookAcceptanceTests(unittest.TestCase):
    def setUp(self):
        path = Path('kaggle/freecompute_dual_gpu_server.ipynb')
        self.notebook = json.loads(path.read_text(encoding='utf-8'))
        self.cells = [''.join(c['source']) for c in self.notebook['cells']]
        self.output = io.StringIO()
        self.bearer, self.tailkey = 'fixture-bearer', 'fixture-tailkey'

    def configuration(self):
        secrets = { 'FREECOMPUTE_API_KEY': self.bearer, 'TAILSCALE_AUTHKEY': self.tailkey }
        module = types.ModuleType('kaggle_secrets')
        module.UserSecretsClient = lambda: types.SimpleNamespace(get_secret=secrets.__getitem__)
        state = {}
        with patch.dict(sys.modules, kaggle_secrets=module), contextlib.redirect_stdout(self.output):
            exec(self.cells[1], state)
        return state

    def test_wrappers_compile_and_match_canonical_supervisor_and_scrubber(self):
        other = Path('kaggle/universal_dual_gpu_server.ipynb')
        self.assertEqual(self.notebook, json.loads(other.read_text(encoding='utf-8')))
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
        self.assertEqual(cfg['TRANSPORT'], 'tailscale')
        self.assertFalse(cfg['USE_DATASET_CACHE'])
        with contextlib.redirect_stdout(self.output):
            state['print'](self.bearer, self.tailkey)
        self.assertNotIn(self.bearer, self.output.getvalue())
        self.assertNotIn(self.tailkey, self.output.getvalue())

    def test_build_fetches_and_checks_out_pin_before_cmake(self):
        state = self.configuration()
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            binary = scratch / 'llama.cpp/build/bin/llama-server'
            binary.parent.mkdir(parents=True)
            binary.touch()
            state.update(SCRATCH=scratch, SERVER_BIN=None, subprocess=subprocess)
            commit = state['CONFIG']['LLAMA_COMMIT']
            with patch.object(subprocess, 'run', return_value=types.SimpleNamespace(stdout=commit)) as run, \
                 patch.object(subprocess, 'check_output', return_value='7.5\n'), \
                 contextlib.redirect_stdout(self.output):
                exec(self.cells[4], state)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][-5:], ['fetch', '--depth', '1', 'origin', commit])
            self.assertEqual(commands[1][-3:], ['checkout', '--detach', commit])
            self.assertEqual(commands[2][-2:], ['rev-parse', 'HEAD'])
            self.assertEqual(commands[3][0], 'cmake')

    def test_transport_forwards_tcp_and_removes_key_file_without_exposing_it(self):
        state = self.configuration()
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
        state = self.configuration()
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
                         MODEL_PATH=model_path, llama_cmd=['fixture-server', '--parallel', '1'])
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
