"""Self-contained dataset helpers embedded in both notebooks. No network on import."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess

BUILD_FLAGS = ['GGML_CUDA=ON', 'GGML_CUDA_NO_VMM=ON', 'CMAKE_CUDA_ARCHITECTURES=75',
               'CMAKE_BUILD_TYPE=Release', 'LLAMA_BUILD_TESTS=OFF']
CUDA_LIBRARIES = ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12')


def asset_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def asset_path(root, name):
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe dataset manifest path')
    path = Path(root).joinpath(*relative.parts)
    # No symlinked executables, libraries, parents or models from input datasets.
    for part in (path, *path.parents):
        if part == Path(root).parent:
            break
        if part.is_symlink():
            raise ValueError('Dataset assets must not be symlinks')
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Dataset path escapes its root')
    return path


def verify_asset_manifest(manifest_path, config):
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ValueError('Dataset manifest must not be a symlink')
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    engine = data.get('engine', {})
    if data.get('schema_version') != 1 or engine.get('commit') != config['LLAMA_COMMIT'] or engine.get('cuda_arch') != '75' or engine.get('build_flags') != BUILD_FLAGS:
        raise ValueError('Dataset engine does not match the pinned T4 build')
    libc, version = platform.libc_ver()
    required = engine.get('minimum_glibc', '')
    if libc != 'glibc' or not re.fullmatch(r'\d+\.\d+', required) or tuple(map(int, version.split('.')[:2])) < tuple(map(int, required.split('.'))):
        raise ValueError('Dataset engine requires a newer/different glibc runtime')
    if engine.get('platform') != 'Linux-x86_64':
        raise ValueError('Dataset engine platform is unsupported')
    files = engine.get('files', {})
    server = engine.get('server', '')
    if not isinstance(files, dict) or not server.startswith('engine/') or server not in files or not files:
        raise ValueError('Dataset engine manifest has no server/checksums')
    root = manifest_path.parent
    for name, digest in files.items():
        if not name.startswith('engine/') or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid engine file checksum declaration')
        path = asset_path(root, name)
        if not path.is_file() or asset_sha256(path) != digest:
            raise ValueError('Dataset engine file is missing or has changed: ' + name)
    expected = {str(p.relative_to(root)).replace('\\', '/') for p in (root / 'engine').rglob('*') if p.is_file()}
    if expected != set(files):
        raise ValueError('Dataset engine contains undeclared files')
    for library in (*CUDA_LIBRARIES, 'libggml-cuda.so'):
        if 'engine/' + library not in files:
            raise ValueError('Dataset engine is missing a required runtime library')
    model_path = None
    model = data.get('model')
    if model:
        if (model.get('repo'), model.get('revision'), model.get('filename')) == (config['REPO_ID'], config['REVISION'], config['FILENAME']):
            model_path = asset_path(root, model.get('path', ''))
            if not re.fullmatch(r'[0-9a-f]{64}', model.get('sha256', '')) or not model_path.is_file() or model_path.stat().st_size != model.get('bytes') or asset_sha256(model_path) != model['sha256']:
                raise ValueError('Dataset model checksum/size verification failed')
    return data, asset_path(root, server), model_path


def find_cached_assets(input_dir, scratch, config, report=print):
    for path in sorted(Path(input_dir).glob('**/freecompute-assets.json')):
        try:
            data, server, model = verify_asset_manifest(path, config)
            destination = Path(scratch) / 'cached-engine'
            destination.mkdir(parents=True, exist_ok=True)
            for name in data['engine']['files']:
                source = asset_path(path.parent, name)
                target = destination / source.name
                shutil.copyfile(source, target)
                if asset_sha256(target) != data['engine']['files'][name]:
                    raise ValueError('Copied engine checksum verification failed')
            copied_server = destination / server.name
            copied_server.chmod(0o755)
            report('FAST START: verified private dataset engine; no download/build.')
            return copied_server, model, dict(data['engine'], distribution='user-attached dataset; manifest/checksums verified')
        except (ValueError, OSError, TypeError, KeyError) as exc:
            report('Skipping incompatible dataset: ' + str(exc))
    return None, None, None


def build_source_engine(config, scratch, destination=None, report=print):
    source = Path(scratch) / 'llama.cpp'
    if not source.exists():
        subprocess.run(['git', 'clone', '--no-checkout', '--depth', '1', 'https://github.com/ggml-org/llama.cpp.git', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth', '1', 'origin', config['LLAMA_COMMIT']], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', config['LLAMA_COMMIT']], check=True)
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != config['LLAMA_COMMIT']:
        raise RuntimeError('Source checkout does not match the configured engine pin')
    build = source / 'build'
    subprocess.run(['cmake', '-S', str(source), '-B', str(build), *['-D' + flag for flag in BUILD_FLAGS]], check=True)
    subprocess.run(['cmake', '--build', str(build), '--target', 'llama-server', '--parallel', '2'], check=True)
    destination = Path(destination or Path(scratch) / 'source-engine')
    destination.mkdir(parents=True, exist_ok=True)
    for file in (build / 'bin').iterdir():
        if file.is_file() and (file.name == 'llama-server' or '.so' in file.name):
            shutil.copyfile(file, destination / file.name)
    for library in CUDA_LIBRARIES:
        paths = list(Path('/usr/local/cuda').glob('**/' + library))
        if not paths:
            raise RuntimeError('CUDA toolkit is missing ' + library)
        shutil.copyfile(paths[0], destination / library)
    server = destination / 'llama-server'
    if not server.is_file():
        raise RuntimeError('Pinned build did not produce llama-server')
    server.chmod(0o755)
    os.environ['LD_LIBRARY_PATH'] = str(destination) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    version = subprocess.check_output([str(server), '--version'], stderr=subprocess.STDOUT, text=True).strip()
    if not re.search(r'\b' + commit[:7] + r'[0-9a-f]*\b', version):
        raise RuntimeError('Built engine does not report the pinned version')
    provenance = {'commit': commit, 'cuda_arch': '75', 'build_flags': BUILD_FLAGS,
                  'minimum_glibc': '.'.join(platform.libc_ver()[1].split('.')[:2]), 'platform': 'Linux-x86_64',
                  'version_observed': version, 'server': 'engine/llama-server',
                  'files': {'engine/' + file.name: asset_sha256(file) for file in sorted(destination.iterdir()) if file.is_file()},
                  'distribution': 'pinned source build on this runtime'}
    report('Pinned T4 engine built; save it once as a private dataset to avoid future builds.')
    return server, provenance
