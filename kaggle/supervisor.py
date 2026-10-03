#!/usr/bin/env python3
"""
kaggle/supervisor.py — Lightweight Authenticated Supervisor & Watchdog for llama-server
Runs inside the Kaggle GPU container, providing:
1. Token-based authentication (Bearer token gate on all endpoints).
2. Health & Telemetry endpoint (/health) with real container uptime and dual-GPU stats.
3. Streaming OpenAI-compatible reverse proxy (/v1/chat/completions) to llama-server.
4. Process lifecycle & watchdog to monitor, restart, and safely terminate llama-server.
"""

import hmac
import re
import argparse
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class SupervisorConfig:
    def __init__(self, port=8081, llama_port=8080, api_key=None, llama_cmd=None, log_path=""):
        self.port = port
        self.llama_port = llama_port
        self.api_key = os.environ.get("SUPERVISOR_API_KEY") if api_key is None else api_key
        if not self.api_key or not self.api_key.strip():
            raise ValueError("SUPERVISOR_API_KEY must be nonempty")
        self.llama_cmd = llama_cmd or []
        self.log_path = log_path or "/kaggle/working/llama_server.log"
        self.start_time = time.time()
        self.llama_process = None
        self.watchdog_active = True


config = None

def scrub(text):
    text = str(text)
    if config and config.api_key:
        text = text.replace(config.api_key, "[REDACTED_SECRET]")
    text = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED_TOKEN]", text)
    text = re.sub(r"https?://[^\s]+", "[REDACTED_URL]", text)
    return text


def get_container_uptime_seconds():
    """Linux/kernel uptime proxy; this is not an account session start time."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.readline().split()[0])
    except Exception:
        return None


def get_gpu_telemetry():
    """Query nvidia-smi for dual Tesla T4 memory, temperature, and utilization."""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        gpus = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "vramUsedMiB": int(parts[2]),
                    "vramTotalMiB": int(parts[3]),
                    "tempC": int(parts[4]),
                    "utilizationPct": int(parts[5]),
                })
        return gpus
    except Exception as exc:
        return [{"error": scrub(exc)}]


_cpu_previous = None
_telemetry_lock = threading.Lock()


def hardware_metrics(gpus, llama_ok):
    """Optional measurements; missing tools/files never change engine readiness."""
    def item(value=None, source="not reported", status="observed"):
        return {"value": value, "status": status if value is not None else "unknown", "source": source}
    names = ('session_age_seconds', 'session_limit_seconds', 'session_remaining_seconds', 'cpu_utilization_pct',
             'ram_used_bytes', 'ram_total_bytes', 'disk_free_bytes', 'disk_total_bytes', 'model_loaded', 'active_inference_slots')
    metrics = {name: item() for name in names}
    metrics['provider'] = item(os.environ.get('FREECOMPUTE_PROVIDER', 'kaggle'), 'supervisor provider setting', 'configured')
    metrics['supervisor_uptime_seconds'] = item(max(0, time.time() - config.start_time), 'supervisor process clock')
    metrics['kernel_uptime_seconds'] = item(get_container_uptime_seconds(), '/proc/uptime; not account session age')
    metrics['cpu_count'] = item(os.cpu_count(), 'os.cpu_count; visible logical cores')
    metrics['engine_health'] = item('healthy' if llama_ok else 'unhealthy', 'llama-server /health')
    try:
        global _cpu_previous
        with _telemetry_lock:
            with open('/proc/stat') as handle:
                cpu = [int(v) for v in handle.readline().split()[1:9]]
            current = (sum(cpu), cpu[3] + cpu[4])
            if _cpu_previous and current[0] > _cpu_previous[0]:
                metrics['cpu_utilization_pct'] = item(round(100 * (1 - (current[1] - _cpu_previous[1]) / (current[0] - _cpu_previous[0])), 1), '/proc/stat delta; host/container-visible CPU')
            _cpu_previous = current
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open('/proc/meminfo') as handle:
            memory = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in handle}
        metrics['ram_total_bytes'] = item(memory['MemTotal'], '/proc/meminfo; host/container-visible RAM')
        metrics['ram_used_bytes'] = item(memory['MemTotal'] - memory['MemAvailable'], '/proc/meminfo; total minus available')
    except (OSError, ValueError, KeyError, IndexError):
        pass
    try:
        disk = shutil.disk_usage(os.path.dirname(config.log_path) or '.')
        metrics['disk_free_bytes'], metrics['disk_total_bytes'] = item(disk.free, 'filesystem containing supervisor log'), item(disk.total, 'filesystem containing supervisor log')
    except OSError:
        pass
    # Optional loopback observations do not execute local tools or make generation requests.
    for endpoint, field in (('/slots', 'active_inference_slots'), ('/v1/models', 'model_loaded')):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{config.llama_port}' + endpoint, timeout=1) as response:
                data = json.loads(response.read(65536))
            if field == 'active_inference_slots' and isinstance(data, list) and all(isinstance(s.get('is_processing'), bool) for s in data):
                metrics[field] = item(sum(s['is_processing'] for s in data), 'llama-server /slots')
            elif field == 'model_loaded':
                metrics[field] = item(', '.join(str(s['id']) for s in data['data']), 'llama-server /v1/models')
        except Exception:
            pass
    aliases = {'name': 'name', 'vram_used_mib': 'vramUsedMiB', 'vram_total_mib': 'vramTotalMiB', 'utilization_pct': 'utilizationPct', 'temperature_c': 'tempC'}
    devices = [{name: item(gpu.get(key), 'nvidia-smi') for name, key in aliases.items()} for gpu in gpus if 'error' not in gpu]
    metrics['gpu_count'] = item(len(devices) if devices else None, 'nvidia-smi')
    return {'schema_version': 1, 'observed_at': time.time(), 'metrics': metrics, 'gpus': devices}


def check_llama_health():
    """Check if the internal llama-server answers on its loopback port."""
    url = f"http://127.0.0.1:{config.llama_port}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_llama_server():
    """Launch the llama-server subprocess if a command was configured."""
    if not config.llama_cmd:
        return None
    print(f"[SUPERVISOR] Starting llama-server on port {config.llama_port}...")
    log_dir = os.path.dirname(config.log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    log_file = open(config.log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        config.llama_cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    config.llama_process = proc
    return proc


class SupervisorHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        sys.stderr.write(scrub(f"[SUPERVISOR {self.address_string()}] {format % args}") + "\n")

    def check_auth(self):
        """Validate Authorization: Bearer <API_KEY> header."""
        if config is None or not config.api_key:
            self.send_error_response(503, "Supervisor authentication is not configured")
            return False
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self.send_error_response(401, "Missing or invalid Authorization header. Expected Bearer token.")
            return False
        token = auth_header[7:].strip()
        if not hmac.compare_digest(token.encode(), config.api_key.encode()):
            self.send_error_response(403, "Forbidden: Invalid API Key.")
            return False
        return True

    def send_error_response(self, status_code, message):
        body = json.dumps({"error": {"message": scrub(message), "code": status_code}}).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            llama_ok = check_llama_health()
            gpus = get_gpu_telemetry()
            payload = {
                "status": "healthy" if llama_ok else "degraded",
                "supervisorUptimeSeconds": round(time.time() - config.start_time, 1),
                "sessionAgeSeconds": None,
                "sessionAgeSource": "supervisor_start_estimate",  # Legacy label; normalized account age stays unknown.
                "linuxUptimeSeconds": get_container_uptime_seconds(),
                "maxSessionSeconds": None,
                "secondsRemainingIn12hSession": None,
                "telemetry": hardware_metrics(gpus, llama_ok),
                "llamaServer": {
                    "healthy": llama_ok,
                    "port": config.llama_port,
                    "pid": config.llama_process.pid if config.llama_process else None,
                },
                "gpus": gpus,
            }
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200 if llama_ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self.check_auth():
            return

        if path == "/v1/models" and not parsed.query:
            self.proxy_to_llama("GET")
        else:
            self.send_error_response(404, f"Endpoint {path} not found.")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not self.check_auth():
            return

        if path == "/control/restart" and not parsed.query:
            if not config.llama_cmd:
                self.send_error_response(409, "Supervisor does not own a restart command")
                return
            if config.llama_process and config.llama_process.poll() is None:
                config.llama_process.terminate()
                try:
                    config.llama_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    config.llama_process.kill()
            start_llama_server()
            body = json.dumps({"status": "restarting", "message": "llama-server restart signal sent."}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/v1/chat/completions" and not parsed.query:
            self.proxy_to_llama("POST")
        else:
            self.send_error_response(404, f"Endpoint {path} not found.")

    def proxy_to_llama(self, method):
        target_url = f"http://127.0.0.1:{config.llama_port}{self.path}"
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if not 0 <= content_length <= 16 * 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                raise ValueError()
        except ValueError:
            self.send_error_response(400, "Invalid request body length")
            return
        body = self.rfile.read(content_length) if content_length > 0 else None

        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ("host", "authorization", "content-length"):
                headers[k] = v
        if content_length > 0:
            headers["Content-Length"] = str(content_length)

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                self.send_response(resp.status)
                is_sse = False
                for k, v in resp.headers.items():
                    if k.lower() == "transfer-encoding" and v.lower() == "chunked":
                        continue
                    if k.lower() == "content-type" and "text/event-stream" in v.lower():
                        is_sse = True
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()

                while True:
                    chunk = resp.readline() if is_sse else resp.read(8192)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except urllib.error.HTTPError as err:
            self.send_error_response(err.code, "Internal inference backend returned an error")
        except Exception:
            self.send_error_response(502, "Internal inference backend unavailable")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_supervisor(port=8081, llama_port=8080, api_key=None, llama_cmd=None, log_path=""):
    global config
    config = SupervisorConfig(port, llama_port, api_key, llama_cmd, log_path)

    if config.llama_cmd:
        start_llama_server()

    server_address = ("0.0.0.0", config.port)
    httpd = ThreadedHTTPServer(server_address, SupervisorHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if config.llama_process and config.llama_process.poll() is None:
            config.llama_process.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kaggle llama-server Authenticated Supervisor")
    parser.add_argument("--port", type=int, default=8081, help="Supervisor external port (default: 8081)")
    parser.add_argument("--llama-port", type=int, default=8080, help="Internal llama-server port (default: 8080)")
    parser.add_argument("--api-key", type=str, default=None, help="Bearer token for API access")
    parser.add_argument("--log-path", type=str, default="/kaggle/working/llama_server.log", help="Log output file path")
    args = parser.parse_args()

    run_supervisor(port=args.port, llama_port=args.llama_port, api_key=args.api_key, log_path=args.log_path)
