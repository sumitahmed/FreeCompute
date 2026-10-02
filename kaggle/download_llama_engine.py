# ==============================================================================
# 4. DOWNLOAD PINNED LLAMA.CPP CUDA ENGINE (b11206 / 2b129cc)
# Paste this entire file into executable Cell 4, after running Cells 1-3.
# ==============================================================================
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

for name in ('llama_proc', 'supervisor_proc'):
    proc = globals().get(name)
    if proc is not None and proc.poll() is None:
        raise RuntimeError('Worker already running; do not replace its engine.')

RELEASE_TAG = 'b11206'
RELEASE_COMMIT = '2b129ccfa03aea330d2d9ac4650a10de393dbe3a'
if CONFIG['LLAMA_COMMIT'] != RELEASE_COMMIT:
    raise RuntimeError('The downloadable release does not match the configured engine pin.')

# Official CUDA 12.8 x64 release, including its matching CUDA runtime libraries.
# These are release-build flags, not the historical CUDA_NO_VMM source build.
ENGINE_ASSETS = {
    'llama-b11206-bin-ubuntu-cuda-12.8-x64.tar.gz':
        'fa78d7d80b8dca117638c49fc4aa58d6b01407541804483876c27323ebb887de',
    'cudart-llama-b11206-bin-ubuntu-cuda-12.8-x64.tar.gz':
        'bcc52b864ad3edbdd18d10d8061bb84af2c085c50621d0cc19e135130cc360e8',
}
ENGINE_DIR = SCRATCH / 'engine-b11206-cuda12.8'
ENGINE_DIR.mkdir(parents=True, exist_ok=True)


def download_engine_asset(filename, expected_sha256):
    archive = ENGINE_DIR / filename
    if not archive.is_file():
        url = f'https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE_TAG}/{filename}'
        print('Downloading:', filename)
        partial = archive.with_suffix(archive.suffix + '.part')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'FreeCompute-notebook'})
            with urllib.request.urlopen(request, timeout=180) as response, partial.open('wb') as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f'Download failed for {filename}; rerun Cell 4 to retry.') from None
    digest = hashlib.sha256()
    with archive.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        archive.unlink()
        raise RuntimeError(f'SHA256 mismatch for {filename}; stop, then rerun Cell 4 to download again.')
    print('SHA256 verified:', filename)
    # Reject traversal, unsafe links and special files before extracting anything.
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if not hasattr(tarfile, 'data_filter'):
            raise RuntimeError('Python needs tarfile.data_filter support for safe extraction.')
        for member in members:
            tarfile.data_filter(member, str(ENGINE_DIR))
        bundle.extractall(ENGINE_DIR, members=members, filter='data')


for filename, checksum in ENGINE_ASSETS.items():
    download_engine_asset(filename, checksum)

SERVER_BIN = ENGINE_DIR / f'llama-{RELEASE_TAG}' / 'llama-server'
if not SERVER_BIN.is_file():
    raise RuntimeError('The verified release archive did not contain llama-server.')
SERVER_BIN.chmod(0o755)
runtime_dir = ENGINE_DIR / 'cudart-llama-b11206-bin-ubuntu-cuda-12.8-x64'
for library in ('libcudart.so.12', 'libcublas.so.12', 'libcublasLt.so.12'):
    source = runtime_dir / library
    if not source.is_file():
        raise RuntimeError(f'The verified CUDA runtime archive is missing {library}.')
    shutil.copy2(source, SERVER_BIN.parent / library)
# Cell 6 and the manifest's version probe inherit this library search path.
os.environ['LD_LIBRARY_PATH'] = str(SERVER_BIN.parent) + ':' + os.environ.get('LD_LIBRARY_PATH', '')


def probe_downloaded_engine(flag):
    try:
        result = subprocess.run([str(SERVER_BIN), flag], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Downloaded engine could not start; check Linux/CUDA runtime compatibility.') from None
    output = (result.stdout or '') + '\n' + (result.stderr or '')
    if result.returncode:
        raise RuntimeError(scrubber.scrub('Downloaded engine is incompatible with this runtime:\n' + output))
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
    'distribution': 'official GitHub CUDA 12.8 Linux x64 release',
    'release_tag': RELEASE_TAG, 'commit': RELEASE_COMMIT,
    'asset_sha256': ENGINE_ASSETS,
    'build_flags': 'upstream release defaults; GGML_CUDA_NO_VMM was not enabled',
    'cuda_devices_observed': devices.strip(),
}
print('ENGINE DOWNLOAD VERIFIED; BOTH T4 GPUs DETECTED.')
print('llama-server ready at:', SERVER_BIN)
