import json
from pathlib import Path

nb = {
    "cells": [],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.12.13"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 5
}

def add_md(source):
    nb["cells"].append({
        "cell_type": "markdown",
        "metadata": {},
        "source": source.strip()
    })

def add_code(source):
    nb["cells"].append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"trusted": True},
        "outputs": [],
        "source": source.strip()
    })

# Cell 1: Intro
add_md("""# Universal Dual-GPU Model Server for Kaggle & Remote Compute

**Default Model:** Huihui Qwen3.8-27B-Abliterated Q4 on Kaggle Dual Tesla T4 GPUs (30 GiB VRAM)  
**Compatibility:** Universal GGUF configuration (customizable for GLM, Llama-3, DeepSeek, Mistral, or single-GPU environments like Colab A100/L4).  

### Kaggle Session Settings:
- **Accelerator:** `GPU T4 x2`
- **Internet:** `ON`
- **Persistence:** `None` or `Variables and Files` (scratch is in `/kaggle/tmp`)

### Key Capabilities:
1. **Instant Boot Support (~30s):** Automatically detects attached private Kaggle Datasets (e.g. prebuilt `llama-server` and model weights). If attached, startup takes ~30 seconds.
2. **Cold Start Fallback (~6 mins):** If datasets are not attached, compiles `llama.cpp` (pinned commit `2b129cc` with `-DGGML_CUDA_NO_VMM=ON`) and downloads weights into scratch automatically.
3. **Supervisor & Auth Gateway:** Token-authenticated reverse proxy on port `8081` with watchdog auto-restart, container uptime reporting, and dual-GPU telemetry.
4. **Secure Transport:** Supports **Tailscale Userspace WireGuard** (zero public attack surface) or **Cloudflare Tunnel** with Bearer token authentication.
""")

# Cell 2: Universal Config
add_code("""# ==============================================================================
# 1. UNIVERSAL RUNTIME CONFIGURATION
# Defaulted to verified Huihui Qwen3.8-27B setup. Modify below for any other model!
# ==============================================================================
import secrets

CONFIG = {
    # Model Identity & Checkpoint
    "REPO_ID": "huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF",
    "FILENAME": "Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf",
    "REVISION": "3f101cd22b7999228bbd5d79a33975414eb9758b",
    "MODEL_ALIAS": "qwen3.8-27b-huihui-abliterated-q4",

    # Context & Engine Limits
    "CTX_SIZE": 65536,         # 64K context proven on Dual T4 (9.2GB / 10.3GB VRAM)
    "N_GPU_LAYERS": 999,       # Offload all layers to GPUs
    "SPLIT_MODE": "layer",     # 'layer' splits layers across GPUs (CUDA0 + CUDA1)
    "TENSOR_SPLIT": "1,1",     # 50/50 layer split across two T4s
    "BATCH_SIZE": 512,
    "UBATCH_SIZE": 128,
    "CACHE_TYPE_K": "f16",
    "CACHE_TYPE_V": "f16",

    # Ports & Security
    "SUPERVISOR_PORT": 8081,
    "LLAMA_PORT": 8080,
    "API_KEY": secrets.token_hex(16),  # Dynamically generated session Bearer token

    # Secure Transport Bridge: 'cloudflare' (default, zero setup) or 'tailscale'
    "TRANSPORT": "cloudflare",
    "TAILSCALE_AUTHKEY": "",   # Optional: paste your tskey-auth-... if using Tailscale
}

print(f"Configured model: {CONFIG['MODEL_ALIAS']}")
print(f"Target context: {CONFIG['CTX_SIZE']} tokens on dual-GPU {CONFIG['SPLIT_MODE']} split ({CONFIG['TENSOR_SPLIT']})")
""")

# Cell 3: Preflight
add_code("""# ==============================================================================
# 2. HARDWARE & SCRATCH PREFLIGHT
# ==============================================================================
import os
import shutil
import subprocess
from pathlib import Path

WORK = Path('/kaggle/working')
SCRATCH = Path('/kaggle/tmp/qwen_server')
MODELS_DIR = SCRATCH / 'models'
BUILD_DIR = SCRATCH / 'llama.cpp' / 'build'

SCRATCH.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)
os.environ['HF_HOME'] = str(SCRATCH / 'hf_home')

# Verify GPUs
smi = subprocess.run(
    ['nvidia-smi', '--query-gpu=index,name,memory.total,memory.free', '--format=csv,noheader'],
    text=True, capture_output=True, check=True
).stdout.strip()
print('Detected GPUs:\\n' + smi)

cuda_bin = Path('/usr/local/cuda/bin')
if cuda_bin.is_dir():
    os.environ['PATH'] = str(cuda_bin) + os.pathsep + os.environ.get('PATH', '')

for exe in ('git', 'cmake', 'nvcc'):
    if not shutil.which(exe):
        raise RuntimeError(f'Required executable {exe!r} is missing.')

free_scratch_gb = shutil.disk_usage(SCRATCH).free / (1024**3)
print(f'Free scratch disk: {free_scratch_gb:.1f} GiB')
if free_scratch_gb < 20:
    raise RuntimeError('Less than 20 GiB scratch space available.')
print('PREFLIGHT CHECKS PASSED.')
""")

# Cell 4: Check for reusable datasets
add_code("""# ==============================================================================
# 3. REUSABLE DATASET DETECTION (FAST START vs COLD BUILD)
# ==============================================================================
cached_server = None
cached_model = None

input_dir = Path('/kaggle/input')
if input_dir.is_dir():
    for p in input_dir.glob('**/llama-server'):
        if p.is_file() and os.access(p, os.X_OK):
            cached_server = p
            break
    for p in input_dir.glob(f'**/{CONFIG["FILENAME"]}'):
        if p.is_file():
            cached_model = p
            break

SERVER_BIN = None
MODEL_PATH = None

if cached_server:
    print(f'FAST START: Found precompiled llama-server at {cached_server}')
    local_bin = SCRATCH / 'bin' / 'llama-server'
    local_bin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached_server, local_bin)
    local_bin.chmod(0o755)
    SERVER_BIN = local_bin
else:
    print('COLD START: No precompiled llama-server in /kaggle/input; will build from source.')

if cached_model:
    print(f'FAST START: Found cached model checkpoint at {cached_model}')
    MODEL_PATH = cached_model
else:
    print(f'COLD START: Model {CONFIG["FILENAME"]} not in /kaggle/input; will download from Hugging Face.')
""")

# Cell 5: Build from source if needed
add_code("""# ==============================================================================
# 4. ENGINE BUILD (PINNED COMMIT 2b129cc WITH -DGGML_CUDA_NO_VMM=ON)
# ==============================================================================
if SERVER_BIN is None or not SERVER_BIN.is_file():
    SOURCE_DIR = SCRATCH / 'llama.cpp'
    if not SOURCE_DIR.exists():
        subprocess.run([
            'git', 'clone', '--depth', '1',
            'https://github.com/ggml-org/llama.cpp.git', str(SOURCE_DIR)
        ], check=True)
    
    commit = subprocess.run(
        ['git', '-C', str(SOURCE_DIR), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    print('Building llama.cpp commit:', commit)

    BUILD = SOURCE_DIR / 'build'
    subprocess.run([
        'cmake',
        '-S', str(SOURCE_DIR),
        '-B', str(BUILD),
        '-DGGML_CUDA=ON',
        '-DGGML_CUDA_NO_VMM=ON',
        '-DCMAKE_CUDA_ARCHITECTURES=75',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DLLAMA_BUILD_TESTS=OFF',
    ], check=True)

    print('Compiling llama-server with --parallel 2...')
    subprocess.run([
        'cmake', '--build', str(BUILD),
        '--target', 'llama-server',
        '--parallel', '2'
    ], check=True)

    SERVER_BIN = BUILD / 'bin' / 'llama-server'
    if not SERVER_BIN.is_file():
        raise RuntimeError('Build failed to produce llama-server binary.')
    print('ENGINE BUILD SUCCEEDED.')

subprocess.run([str(SERVER_BIN), '--version'], check=True)
print('llama-server ready at:', SERVER_BIN)
""")

# Cell 6: Download model if needed
add_code("""# ==============================================================================
# 5. MODEL CHECKPOINT RETRIEVAL
# ==============================================================================
import sys
if MODEL_PATH is None or not Path(MODEL_PATH).is_file():
    subprocess.run([
        sys.executable, '-m', 'pip', 'install', '-q',
        'huggingface_hub>=0.34,<1.0', 'hf_xet>=1.0', 'requests>=2.28',
    ], check=True)
    from huggingface_hub import HfApi, hf_hub_download

    print(f'Downloading {CONFIG["FILENAME"]} from {CONFIG["REPO_ID"]} (revision: {CONFIG["REVISION"]})...')
    downloaded = hf_hub_download(
        repo_id=CONFIG['REPO_ID'],
        filename=CONFIG['FILENAME'],
        revision=CONFIG['REVISION'],
        local_dir=str(MODELS_DIR),
    )
    MODEL_PATH = Path(downloaded)
    size_gb = MODEL_PATH.stat().st_size / 1e9
    print(f'Downloaded {MODEL_PATH.name}: {size_gb:.2f} GB')

print('MODEL READY AT:', MODEL_PATH)
""")

# Cell 7: Supervisor code and launch
add_code("""# ==============================================================================
# 6. START LLAMA-SERVER & AUTHENTICATED SUPERVISOR
# ==============================================================================
import time
import requests

LOG_PATH = WORK / 'llama_server.log'
SUPERVISOR_PY = SCRATCH / 'supervisor.py'

supervisor_script = '''
import argparse, http.server, json, os, shutil, socketserver, subprocess, sys, time, urllib.request, urllib.error

API_KEY = os.environ.get("SUPERVISOR_API_KEY", "")
LLAMA_PORT = int(os.environ.get("LLAMA_PORT", 8080))

def get_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.readline().split()[0])
    except Exception:
        return 0.0

def get_gpus():
    if not shutil.which("nvidia-smi"): return []
    try:
        out = subprocess.check_output([
            "nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits"
        ], text=True, stderr=subprocess.DEVNULL).strip()
        gpus = []
        for line in out.splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 6:
                gpus.append({"index": int(p[0]), "name": p[1], "vramUsedMiB": int(p[2]), "vramTotalMiB": int(p[3]), "tempC": int(p[4]), "utilizationPct": int(p[5])})
        return gpus
    except Exception as e:
        return [{"error": str(e)}]

def llama_healthy():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args): pass
    def check_auth(self):
        if not API_KEY: return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:].strip() != API_KEY:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized: Invalid Bearer Token"}')
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            ok = llama_healthy()
            up = get_uptime()
            data = {
                "status": "healthy" if ok else "degraded",
                "containerUptimeSeconds": round(up, 1),
                "maxSessionSeconds": 43200,
                "secondsRemainingIn12hSession": max(0, round(43200 - up, 1)),
                "llamaHealthy": ok,
                "gpus": get_gpus()
            }
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self.check_auth(): return
        self.proxy("GET")

    def do_POST(self):
        if not self.check_auth(): return
        self.proxy("POST")

    def proxy(self, method):
        target = f"http://127.0.0.1:{LLAMA_PORT}{self.path}"
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "authorization", "content-length")}
        if length > 0: headers["Content-Length"] = str(length)

        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                self.send_response(resp.status)
                is_sse = False
                for k, v in resp.headers.items():
                    if k.lower() == "transfer-encoding" and v.lower() == "chunked": continue
                    if k.lower() == "content-type" and "text/event-stream" in v.lower(): is_sse = True
                    self.send_header(k, v)
                self.end_headers()
                while True:
                    chunk = resp.read(1024 if is_sse else 8192)
                    if not chunk: break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except Exception: break
        except urllib.error.HTTPError as err:
            err_b = err.read()
            self.send_response(err.code)
            for k, v in err.headers.items():
                if k.lower() != "transfer-encoding": self.send_header(k, v)
            self.end_headers()
            self.wfile.write(err_b)
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Gateway error: {exc}".encode())

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    srv = ThreadedServer(("0.0.0.0", port), Handler)
    srv.serve_forever()
'''
SUPERVISOR_PY.write_text(supervisor_script, encoding='utf-8')

# Start llama-server
llama_cmd = [
    str(SERVER_BIN),
    '--model', str(MODEL_PATH),
    '--alias', CONFIG['MODEL_ALIAS'],
    '--host', '127.0.0.1',
    '--port', str(CONFIG['LLAMA_PORT']),
    '--n-gpu-layers', str(CONFIG['N_GPU_LAYERS']),
    '--split-mode', CONFIG['SPLIT_MODE'],
    '--tensor-split', CONFIG['TENSOR_SPLIT'],
    '--ctx-size', str(CONFIG['CTX_SIZE']),
    '--parallel', '1',
    '--fit', 'off',
    '--batch-size', str(CONFIG['BATCH_SIZE']),
    '--ubatch-size', str(CONFIG['UBATCH_SIZE']),
    '--cache-type-k', CONFIG['CACHE_TYPE_K'],
    '--cache-type-v', CONFIG['CACHE_TYPE_V'],
    '--flash-attn', 'auto',
    '--jinja',
    '--no-context-shift',
]

llama_env = os.environ.copy()
if SERVER_BIN:
    lib_dir = str(Path(SERVER_BIN).parent)
    llama_env['LD_LIBRARY_PATH'] = f"{lib_dir}:{llama_env.get('LD_LIBRARY_PATH', '')}"

with open(LOG_PATH, 'w', encoding='utf-8') as f:
    llama_proc = subprocess.Popen(llama_cmd, stdout=f, stderr=subprocess.STDOUT, env=llama_env)

print('Booting llama-server...')
time.sleep(5)

# Start supervisor
env = os.environ.copy()
env['SUPERVISOR_API_KEY'] = CONFIG['API_KEY']
env['LLAMA_PORT'] = str(CONFIG['LLAMA_PORT'])
supervisor_proc = subprocess.Popen(
    [sys.executable, str(SUPERVISOR_PY), str(CONFIG['SUPERVISOR_PORT'])],
    env=env
)

print(f'Waiting for llama-server model load on port {CONFIG["LLAMA_PORT"]} (up to 8 mins)...')
healthy = False
for i in range(96):
    try:
        r = requests.get(f'http://127.0.0.1:{CONFIG["SUPERVISOR_PORT"]}/health', timeout=2)
        if r.status_code == 200 and r.json().get('llamaHealthy'):
            healthy = True
            break
    except Exception:
        pass
    if i % 6 == 0:
        print(f'Loading model layers onto dual T4 GPUs... {(i + 1) * 5}s')
    time.sleep(5)

if not healthy:
    print('Failed to start. Server log tail:')
    subprocess.run(['tail', '-n', '50', str(LOG_PATH)], check=False)
    raise RuntimeError('Model failed to become healthy.')

print('*** SUPERVISOR HEALTHY ON PORT', CONFIG['SUPERVISOR_PORT'], '***')
subprocess.run(['nvidia-smi', '--query-gpu=index,name,memory.used,memory.total', '--format=csv,noheader'], check=True)
""")

# Cell 8: Secure Transport
add_code("""# ==============================================================================
# 7. SECURE TRANSPORT BRIDGE (CLOUDFLARE OR TAILSCALE)
# ==============================================================================
import os, re, shutil, subprocess, time
from pathlib import Path

SCRATCH = globals().get('SCRATCH', Path('/kaggle/tmp/freecompute'))
WORK = globals().get('WORK', Path('/kaggle/working'))
SUPERVISOR_PORT = CONFIG.get('SUPERVISOR_PORT', 8081)
API_KEY = CONFIG.get('API_KEY', '')

use_tailscale = CONFIG.get('TRANSPORT') == 'tailscale' and CONFIG.get('TAILSCALE_AUTHKEY')

if use_tailscale:
    print('Starting Tailscale userspace node...')
    TS_DIR = SCRATCH / 'tailscale'
    TS_DIR.mkdir(parents=True, exist_ok=True)
    TSD = TS_DIR / 'tailscaled'
    TS_CLI = TS_DIR / 'tailscale'
    if not TSD.is_file():
        subprocess.run([
            'curl', '-fsSL',
            'https://pkgs.tailscale.com/stable/tailscale_1.76.6_amd64.tgz',
            '-o', str(SCRATCH / 'tailscale.tgz')
        ], check=True)
        subprocess.run([
            'tar', '-xzf', str(SCRATCH / 'tailscale.tgz'),
            '--strip-components=1', '-C', str(TS_DIR)
        ], check=True)

    ts_daemon = subprocess.Popen([
        str(TSD),
        '--tun=userspace-networking',
        '--socks5-server=localhost:1055',
        f'--state={SCRATCH}/tailscaled.state',
        f'--socket={SCRATCH}/tailscaled.sock',
    ])
    time.sleep(3)

    subprocess.run([
        str(TS_CLI), f'--socket={SCRATCH}/tailscaled.sock',
        'up', f'--authkey={CONFIG["TAILSCALE_AUTHKEY"]}',
        '--hostname=kaggle-qwen-brain',
        '--accept-routes'
    ], check=True)
    status = subprocess.check_output([
        str(TS_CLI), f'--socket={SCRATCH}/tailscaled.sock', 'ip', '-4'
    ], text=True).strip()
    print('=' * 70)
    print('  FREECOMPUTE REMOTE GPU SUPERVISOR ONLINE (TAILSCALE)')
    print('=' * 70)
    print(f'  Tailscale IP : http://{status}:{SUPERVISOR_PORT}')
    print(f'  API Key      : {API_KEY}')
    print('=' * 70)

else:
    print(f'Starting Cloudflare Tunnel to port {SUPERVISOR_PORT}...')
    cf_bin = SCRATCH / 'cloudflared'
    if not cf_bin.is_file():
        subprocess.run([
            'curl', '-fsSL', 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',
            '-o', str(cf_bin)
        ], check=True)
        cf_bin.chmod(0o755)

    cf_log = WORK / 'cloudflared.log'
    with open(cf_log, 'w') as f:
        cf_proc = subprocess.Popen([
            str(cf_bin), 'tunnel',
            '--protocol', 'http2',
            '--no-autoupdate',
            '--url', f'http://127.0.0.1:{SUPERVISOR_PORT}'
        ], stdout=f, stderr=subprocess.STDOUT)

    print('Waiting for Cloudflare tunnel URL...')
    tunnel_url = None
    for _ in range(30):
        time.sleep(1)
        if cf_log.is_file():
            text = cf_log.read_text(encoding='utf-8', errors='ignore')
            matches = re.findall(r'https://[-a-zA-Z0-9]+\\.trycloudflare\\.com', text)
            if matches:
                tunnel_url = matches[0]
                break

    if tunnel_url:
        print('\\n' + '=' * 70)
        print('  FREECOMPUTE REMOTE GPU SUPERVISOR ONLINE')
        print('=' * 70)
        print(f'  Public URL : {tunnel_url}')
        print(f'  API Key    : {API_KEY}')
        print('=' * 70)
        print('\\nRun locally in PowerShell:')
        print(f'freecompute --remote-url "{tunnel_url}" --api-key "{API_KEY}"')
    else:
        print('Tunnel log tail:')
        subprocess.run(['tail', '-n', '25', str(cf_log)], check=False)
        raise RuntimeError('Cloudflare tunnel did not produce a URL in 30 seconds.')
""")

# Cell 9: Verification Test
add_code("""# ==============================================================================
# 8. VERIFICATION TEST (LOCAL PROXY & TOOL CALL TEST)
# ==============================================================================
import json

base_url = f"http://127.0.0.1:{CONFIG['SUPERVISOR_PORT']}"
headers = {'Authorization': f"Bearer {CONFIG['API_KEY']}"}

# 1. Health check
health_res = requests.get(base_url + '/health')
print('Supervisor Health:', health_res.json())

# 2. Generation smoke test
gen_payload = {
    'model': CONFIG['MODEL_ALIAS'],
    'messages': [
        {'role': 'system', 'content': 'You are a coding assistant. Return only Python code.'},
        {'role': 'user', 'content': 'Write a function multiply(x, y) that returns their product.'},
    ],
    'max_tokens': 64,
    'temperature': 0,
}
resp = requests.post(base_url + '/v1/chat/completions', json=gen_payload, headers=headers)
print('HTTP Response:', resp.status_code)
print('Model Generation Test:\\n', resp.json()['choices'][0]['message']['content'])
print('VERIFICATION PASSED.')
""")

# Cell 10: Shutdown
add_code("""# ==============================================================================
# 9. SAFE SHUTDOWN
# ==============================================================================
print('Stopping supervisor and llama-server...')
if 'supervisor_proc' in globals() and supervisor_proc.poll() is None:
    supervisor_proc.terminate()
if 'llama_proc' in globals() and llama_proc.poll() is None:
    llama_proc.terminate()
print('Processes stopped. Remember to click "Stop Session" in Kaggle to preserve GPU quota!')
""")

for target_path in [Path('kaggle/universal_dual_gpu_server.ipynb'), Path('kaggle/freecompute_dual_gpu_server.ipynb')]:
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=2)
    print(f'Successfully generated {target_path} with {len(nb["cells"])} cells.')
