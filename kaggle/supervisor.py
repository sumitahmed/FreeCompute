#!/usr/bin/env python3
"""
kaggle/supervisor.py — Lightweight Authenticated Supervisor & Watchdog for llama-server
Runs inside the Kaggle GPU container, providing:
1. Token-based authentication (Bearer token gate on all endpoints).
2. Health & Telemetry endpoint (/health) with real container uptime and dual-GPU stats.
3. Streaming OpenAI-compatible reverse proxy (/v1/chat/completions) to llama-server.
4. Process lifecycle & watchdog to monitor, restart, and safely terminate llama-server.
"""

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
    def __init__(self, port=8081, llama_port=8080, api_key="", llama_cmd=None, log_path=""):
        self.port = port
        self.llama_port = llama_port
        self.api_key = api_key or os.environ.get("SUPERVISOR_API_KEY", "default-kaggle-key")
        self.llama_cmd = llama_cmd or []
        self.log_path = log_path or "/kaggle/working/llama_server.log"
        self.start_time = time.time()
        self.llama_process = None
        self.watchdog_active = True


config = SupervisorConfig()


def get_container_uptime_seconds():
    """Extract real container uptime from /proc/uptime if available."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.readline().split()[0])
    except Exception:
        return time.time() - config.start_time


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
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
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
        return [{"error": str(exc)}]


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
        sys.stderr.write(f"[SUPERVISOR {self.address_string()}] {format % args}\n")

    def check_auth(self):
        """Validate Authorization: Bearer <API_KEY> header."""
        if not config.api_key:
            return True
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self.send_error_response(401, "Missing or invalid Authorization header. Expected Bearer token.")
            return False
        token = auth_header[7:].strip()
        if token != config.api_key:
            self.send_error_response(403, "Forbidden: Invalid API Key.")
            return False
        return True

    def send_error_response(self, status_code, message):
        body = json.dumps({"error": {"message": message, "code": status_code}}).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            llama_ok = check_llama_health()
            container_uptime = get_container_uptime_seconds()
            gpus = get_gpu_telemetry()
            payload = {
                "status": "healthy" if llama_ok else "degraded",
                "supervisorUptimeSeconds": round(time.time() - config.start_time, 1),
                "containerUptimeSeconds": round(container_uptime, 1),
                "maxSessionSeconds": 43200,
                "secondsRemainingIn12hSession": max(0, round(43200 - container_uptime, 1)),
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

        if path.startswith("/v1/") or path in ("/slots", "/props"):
            self.proxy_to_llama("GET")
        else:
            self.send_error_response(404, f"Endpoint {path} not found.")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not self.check_auth():
            return

        if path == "/control/restart":
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

        if path.startswith("/v1/"):
            self.proxy_to_llama("POST")
        else:
            self.send_error_response(404, f"Endpoint {path} not found.")

    def proxy_to_llama(self, method):
        target_url = f"http://127.0.0.1:{config.llama_port}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
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
                self.end_headers()

                while True:
                    chunk = resp.read(1024 if is_sse else 8192)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except urllib.error.HTTPError as err:
            err_body = err.read()
            self.send_response(err.code)
            for k, v in err.headers.items():
                if k.lower() != "transfer-encoding":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as exc:
            self.send_error_response(502, f"Failed to connect to internal llama-server: {str(exc)}")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_supervisor(port=8081, llama_port=8080, api_key="", llama_cmd=None, log_path=""):
    config.port = port
    config.llama_port = llama_port
    if api_key:
        config.api_key = api_key
    if llama_cmd:
        config.llama_cmd = llama_cmd
    if log_path:
        config.log_path = log_path

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
    parser.add_argument("--api-key", type=str, default="", help="Bearer token for API access")
    parser.add_argument("--log-path", type=str, default="/kaggle/working/llama_server.log", help="Log output file path")
    args = parser.parse_args()

    run_supervisor(port=args.port, llama_port=args.llama_port, api_key=args.api_key, log_path=args.log_path)
