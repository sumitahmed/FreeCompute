# ==============================================================================
# 4. VERIFIED CACHED / DOWNLOAD / PINNED SOURCE T4 ENGINE
# Paste into executable Cell 4 after Cells 1-3.
# ==============================================================================
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

for name in ('llama_proc', 'supervisor_proc'):
    proc = globals().get(name)
    if proc is not None and proc.poll() is None:
        raise RuntimeError('Worker already running; do not replace its engine.')

RELEASE_COMMIT = '2b129ccfa03aea330d2d9ac4650a10de393dbe3a'
if CONFIG['LLAMA_COMMIT'] != RELEASE_COMMIT:
    raise RuntimeError('Downloaded engine does not match the configured acceptance pin.')
libc_name, libc_version = platform.libc_ver()
if libc_name != 'glibc' or tuple(int(part) for part in libc_version.split('.')[:2]) < (2, 35):
    raise RuntimeError(f'This Ubuntu 22.04 engine needs glibc >= 2.35; observed {libc_name} {libc_version}.')

ARTIFACT_NAME = 'kaggle-llama-b11206-sm75-ubuntu22'
ARTIFACT_RUN = 37052624160
ARTIFACT_ID = 11247636682
ARTIFACT_ZIP_SHA256 = '71487cea2572f9cd694f542b46598c612040d54c0199465eeaaef4aaff75b50a'
ENGINE_TAR_SHA256 = 'c84d19cd871094f5a3cba730680bc23e969c667c5122aa408c4b7f38989ae0c0'
ENGINE_DIR = SCRATCH / 'engine-b11206-sm75-ubuntu22'
ENGINE_DIR.mkdir(parents=True, exist_ok=True)
artifact_zip = ENGINE_DIR / (ARTIFACT_NAME + '.zip')


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def obtain_verified_artifact():
    if not artifact_zip.is_file():
        url = f'https://nightly.link/sumitahmed/FreeCompute/actions/artifacts/{ARTIFACT_ID}.zip'
        partial = artifact_zip.with_suffix('.zip.part')
        print('Downloading the pinned Ubuntu 22.04 T4 engine artifact...')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'FreeCompute-notebook'})
            with urllib.request.urlopen(request, timeout=180) as response, partial.open('wb') as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            partial.replace(artifact_zip)
        except Exception:
            partial.unlink(missing_ok=True)
            raise ConnectionError('Compatible engine artifact download unavailable; using pinned source fallback.') from None
    if sha256_file(artifact_zip) != ARTIFACT_ZIP_SHA256:
        artifact_zip.unlink()
        raise RuntimeError('Engine artifact ZIP SHA256 mismatch. Stop; do not load the engine.')
    print('Verified artifact ZIP SHA256.')
    
    tar_name = ARTIFACT_NAME + '.tar.gz'
    engine_tar = ENGINE_DIR / tar_name
    with zipfile.ZipFile(artifact_zip) as bundle:
        if set(bundle.namelist()) != {tar_name, 'engine.sha256'}:
            raise RuntimeError('Engine artifact ZIP has unexpected contents.')
        checksum_text = bundle.read('engine.sha256').decode('ascii').strip()
        if checksum_text != f'{ENGINE_TAR_SHA256}  {tar_name}':
            raise RuntimeError('Engine artifact manifest did not match the pinned tar checksum.')
        with bundle.open(tar_name) as source, engine_tar.open('wb') as out:
            shutil.copyfileobj(source, out, length=1024 * 1024)
    if sha256_file(engine_tar) != ENGINE_TAR_SHA256:
        engine_tar.unlink()
        raise RuntimeError('Engine tar SHA256 mismatch. Stop; do not load the engine.')
    print('Verified engine tar SHA256.')
    
    with tarfile.open(engine_tar, 'r:gz') as bundle:
        if not hasattr(tarfile, 'data_filter'):
            raise RuntimeError('Python needs tarfile.data_filter support for safe extraction.')
        members = bundle.getmembers()
        if not members or any(not (item.name.startswith('engine/') or
                                   (item.name == 'engine' and item.isdir())) for item in members):
            raise RuntimeError('Engine tar has unexpected paths.')
        for member in members:
            tarfile.data_filter(member, str(ENGINE_DIR))
        bundle.extractall(ENGINE_DIR, members=members, filter='data')
    
    SERVER_BIN = ENGINE_DIR / 'engine' / 'llama-server'
    if not SERVER_BIN.is_file():
        raise RuntimeError('Verified engine tar did not contain llama-server.')
    SERVER_BIN.chmod(0o755)
    for library in ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12'):
        if not (SERVER_BIN.parent / library).is_file():
            raise RuntimeError(f'Verified engine tar is missing {library}.')
    os.environ['LD_LIBRARY_PATH'] = str(SERVER_BIN.parent) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    
    return SERVER_BIN

cached = globals().get('cached_server')
if cached:
    SERVER_BIN = Path(cached)
    os.environ['LD_LIBRARY_PATH'] = str(SERVER_BIN.parent) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    distribution = 'user-attached verified dataset'
else:
    try:
        SERVER_BIN = obtain_verified_artifact()
        distribution = 'verified historical GitHub Actions artifact'
    except ConnectionError:
        builder = globals().get('build_source_engine')
        if builder is None:
            raise RuntimeError('Run Cell 3 first to enable the pinned source fallback.') from None
        print('Artifact unavailable. Building the pinned T4 source once; use a private dataset for future sessions.')
        SERVER_BIN, cached_engine_provenance = builder(CONFIG, SCRATCH, report=print)
        distribution = 'pinned source build'


def probe_downloaded_engine(flag):
    try:
        result = subprocess.run([str(SERVER_BIN), flag], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Downloaded engine could not start on this Kaggle runtime.') from None
    output = (result.stdout or '') + '\n' + (result.stderr or '')
    if result.returncode:
        raise RuntimeError(scrubber.scrub('Downloaded engine failed its runtime check:\n' + output))
    print(output.strip())
    return output


version = probe_downloaded_engine('--version')
if not re.search(r'\b' + RELEASE_COMMIT[:7] + r'[0-9a-f]*\b', version):
    raise RuntimeError('Downloaded engine version does not report the pinned commit.')
devices = probe_downloaded_engine('--list-devices')
for index in (0, 1):
    if not re.search(rf'^\s*CUDA{index}:.*T4', devices, re.MULTILINE):
        raise RuntimeError('Downloaded engine did not detect both T4 GPUs; stop before model loading.')

ENGINE_PROVENANCE = {
    'distribution': distribution,
    'build_run': ARTIFACT_RUN, 'commit': RELEASE_COMMIT,
    'artifact_zip_sha256': ARTIFACT_ZIP_SHA256,
    'engine_tar_sha256': ENGINE_TAR_SHA256,
    'build_flags': 'GGML_CUDA=ON; GGML_CUDA_NO_VMM=ON; CUDA_ARCHITECTURES=75',
    'cuda_devices_observed': devices.strip(),
}
if globals().get('cached_engine_provenance'):
    ENGINE_PROVENANCE.update(cached_engine_provenance)
    ENGINE_PROVENANCE['cuda_devices_observed'] = devices.strip()
print('ENGINE DOWNLOAD VERIFIED; BOTH T4 GPUs DETECTED.')
print('llama-server ready at:', SERVER_BIN)
