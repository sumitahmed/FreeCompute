"""Trusted dataset integrity and download fallback without GPU execution."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fc_assets', Path('kaggle/assets.py'))
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)
PIN = '2b129ccfa03aea330d2d9ac4650a10de393dbe3a'
CONFIG = {'LLAMA_COMMIT': PIN, 'REPO_ID': 'fixture/repo', 'REVISION': 'fixture-pin', 'FILENAME': 'model.gguf'}


class FastAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dataset = self.root / 'input' / 'private-assets'
        engine = self.dataset / 'engine'
        engine.mkdir(parents=True)
        for name in ['llama-server', 'libggml-cuda.so', *assets.CUDA_LIBRARIES]:
            (engine / name).write_bytes(('fixture ' + name).encode())
        model = self.dataset / CONFIG['FILENAME']
        model.write_bytes(b'fixture GGUF')
        self.manifest = {'schema_version': 1, 'engine': {'commit': PIN, 'cuda_arch': '75', 'build_flags': assets.BUILD_FLAGS,
            'minimum_glibc': '2.35', 'platform': 'Linux-x86_64', 'server': 'engine/llama-server',
            'files': {'engine/' + p.name: assets.asset_sha256(p) for p in engine.iterdir()}},
            'model': {'repo': CONFIG['REPO_ID'], 'revision': CONFIG['REVISION'], 'filename': CONFIG['FILENAME'],
                      'path': CONFIG['FILENAME'], 'bytes': model.stat().st_size, 'sha256': assets.asset_sha256(model)}}
        self.path = self.dataset / 'freecompute-assets.json'
        self.save()
        libc = patch('platform.libc_ver', return_value=('glibc', '2.35'))
        libc.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(libc.stop)

    def save(self):
        self.path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_verified_engine_and_model_are_reused_without_network_or_build(self):
        with patch('subprocess.run') as run, patch('urllib.request.urlopen') as download:
            server, model, provenance = assets.find_cached_assets(self.root / 'input', self.root / 'scratch', CONFIG, report=lambda _: None)
        run.assert_not_called(); download.assert_not_called()
        self.assertEqual(server.parent, self.root / 'scratch' / 'cached-engine')
        self.assertTrue(server.is_file())
        self.assertEqual(model, self.dataset / CONFIG['FILENAME'])
        self.assertEqual(provenance['commit'], PIN)
        for library in assets.CUDA_LIBRARIES:
            self.assertTrue((server.parent / library).is_file())

    def test_corrupt_engine_or_model_rejected(self):
        for name in ('engine/llama-server', CONFIG['FILENAME']):
            file = self.dataset / name
            original = file.read_bytes()
            file.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                assets.verify_asset_manifest(self.path, CONFIG)
            file.write_bytes(original)

    def test_mismatched_commit_build_arch_and_flags_rejected(self):
        for field, value in (('commit', 'other'), ('cuda_arch', '80'), ('build_flags', ['GGML_CUDA=ON'])):
            old = self.manifest['engine'][field]
            self.manifest['engine'][field] = value
            self.save()
            with self.assertRaises(ValueError): assets.verify_asset_manifest(self.path, CONFIG)
            self.manifest['engine'][field] = old

    def test_missing_library_and_undeclared_file_rejected(self):
        file = self.dataset / 'engine' / assets.CUDA_LIBRARIES[0]
        file.unlink()
        with self.assertRaises(ValueError): assets.verify_asset_manifest(self.path, CONFIG)
        file.write_bytes(('fixture ' + file.name).encode())
        (file.parent / 'unlisted.so').write_bytes(b'not listed')
        with self.assertRaises(ValueError): assets.verify_asset_manifest(self.path, CONFIG)

    def test_path_traversal_absolute_and_nested_library_declarations_rejected(self):
        for name in ('../outside', '/tmp/engine', 'C:/engine', 'engine/../../outside', 'engine/subdir/llama-server'):
            with self.assertRaises(ValueError):
                assets.asset_path(self.dataset, name) if name != 'engine/subdir/llama-server' else self._nested()

    def _nested(self):
        self.manifest['engine']['files']['engine/subdir/llama-server'] = '0' * 64
        self.save()
        return assets.verify_asset_manifest(self.path, CONFIG)

    def test_incompatible_glibc_not_executed(self):
        with patch('platform.libc_ver', return_value=('glibc', '2.34')), patch('subprocess.run') as run:
            self.assertEqual(assets.find_cached_assets(self.root / 'input', self.root / 'scratch', CONFIG, report=lambda _: None), (None, None, None))
        run.assert_not_called()

    def test_engine_only_dataset_is_supported(self):
        self.manifest['model'] = None
        self.save()
        data, server, model = assets.verify_asset_manifest(self.path, CONFIG)
        self.assertIsNone(model)
        self.assertEqual(data['engine']['commit'], PIN)

    def test_cell_four_cached_engine_still_checks_version_and_both_gpus(self):
        server, _, provenance = assets.find_cached_assets(self.root / 'input', self.root / 'scratch', CONFIG, report=lambda _: None)
        state = dict(CONFIG=CONFIG, SCRATCH=self.root / 'scratch', cached_server=server, cached_engine_provenance=provenance,
                     scrubber=types.SimpleNamespace(scrub=str))
        results = [types.SimpleNamespace(returncode=0, stderr='', stdout=v) for v in ('commit 2b129cc', 'CUDA0: Tesla T4\nCUDA1: Tesla T4')]
        with patch('urllib.request.urlopen') as download, patch('subprocess.run', side_effect=results) as run, \
             patch.dict('os.environ'), contextlib.redirect_stdout(io.StringIO()):
            exec(Path('kaggle/download_llama_engine.py').read_text(encoding='utf-8'), state)
        download.assert_not_called()
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ['--version', '--list-devices'])

    def test_expired_artifact_falls_back_only_to_pinned_source(self):
        server = self.dataset / 'engine' / 'llama-server'
        calls = []
        def build(config, scratch, report):
            calls.append(config['LLAMA_COMMIT'])
            return server, self.manifest['engine']
        state = dict(CONFIG=CONFIG, SCRATCH=self.root / 'scratch', build_source_engine=build, scrubber=types.SimpleNamespace(scrub=str))
        results = [types.SimpleNamespace(returncode=0, stderr='', stdout=v) for v in ('commit 2b129cc', 'CUDA0: Tesla T4\nCUDA1: Tesla T4')]
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('expired')), patch('subprocess.run', side_effect=results), \
             patch.dict('os.environ'), contextlib.redirect_stdout(io.StringIO()):
            exec(Path('kaggle/download_llama_engine.py').read_text(encoding='utf-8'), state)
        self.assertEqual(calls, [PIN])

    def test_builder_and_server_embed_current_helpers_and_no_saved_outputs(self):
        helper = Path('kaggle/assets.py').read_text(encoding='utf-8')
        for filename, cell in (('dataset_builder.ipynb', 2), ('freecompute_dual_gpu_server.ipynb', 3)):
            n = json.loads((Path('kaggle') / filename).read_text(encoding='utf-8'))
            self.assertIn(helper, ''.join(n['cells'][cell]['source']))
            for c in n['cells']:
                if c['cell_type'] == 'code':
                    compile(''.join(c['source']), filename, 'exec')
                    self.assertEqual(c['outputs'], [])
        self.assertIn('MANUAL SHUTDOWN', ''.join(json.loads(Path('kaggle/freecompute_dual_gpu_server.ipynb').read_text(encoding='utf-8'))['cells'][9]['source']))


if __name__ == '__main__':
    unittest.main()
