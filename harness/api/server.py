"""Small versioned HTTP/SSE adapter; never a public listener or tool executor."""
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import mimetypes
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from harness.api.runtime import Conflict, LocalRuntime
from harness.security import scrubber, safe_print

PREFIX = "/api/v1"
COOKIE = "freecompute_session"
MAX_BODY = 256 * 1024


class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def string(value, field, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


class APIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, core, *, port=8741, host="127.0.0.1", token=None, origins=(), static_dir=None, simulated=False):
        if host != "127.0.0.1":
            raise ValueError("The local API binds only to 127.0.0.1; public listeners are unsupported")
        self.token = token or secrets.token_urlsafe(32)
        if len(self.token) < 24:
            raise ValueError("Local API token must have at least 24 characters")
        scrubber.register_secret(self.token)
        self.auth_lock, self.auth = threading.Lock(), {}
        self.stream_slots = threading.BoundedSemaphore(8)
        self.runtime = LocalRuntime(core, simulated=simulated)
        self.static_dir = Path(static_dir).resolve() if static_dir else None
        super().__init__((host, port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"
        self.allowed_origins = {self.origin}
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.path or parsed.query or parsed.fragment or parsed.username or not parsed.port:
                self.server_close()
                raise ValueError("Additional GUI origins must be explicit loopback HTTP origins")
            self.allowed_origins.add(origin)
        self.http_thread = threading.Thread(target=self.serve_forever, name="freecompute-http", daemon=True)

    @property
    def core(self):
        return self.runtime.core

    def start(self):
        self.runtime.start()
        self.http_thread.start()
        return self

    def handle_error(self, _request, _address):
        safe_print("Local API connection ended unexpectedly; Core work remains independent.")

    def close(self):
        self.shutdown()
        self.runtime.close()
        self.server_close()
        self.http_thread.join(5)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, _format, *args):
        # No URL, header, body or credential logging at the transport boundary.
        pass

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        self._json({"error": {"code": "http_error", "message": "Unsupported or malformed HTTP request"}}, code)

    def _guard(self):
        expected = {f"127.0.0.1:{self.server.server_address[1]}", f"localhost:{self.server.server_address[1]}"}
        if self.headers.get("Host") not in expected:
            raise APIError(403, "host_rejected", "Use the loopback API address; this Host is not allowed")
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.allowed_origins:
            raise APIError(403, "origin_rejected", "This browser origin is not allowed")
        if not origin and self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "origin_rejected", "Cross-site requests are not allowed")

    def _auth(self):
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer ") and hmac.compare_digest(header[7:], self.server.token):
            return None  # CLI bearer auth is not ambient browser auth.
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            session_id = cookie[COOKIE].value if COOKIE in cookie else ""
        except Exception:
            session_id = ""
        with self.server.auth_lock:
            session = self.server.auth.get(session_id)
            if session and session["expires"] > time.monotonic():
                return dict(session, id=session_id)
            self.server.auth.pop(session_id, None)
        raise APIError(401, "authentication_required", "Connect with this service's local API token; remote worker keys are different")

    def _csrf(self, session):
        if session is not None and (self.headers.get("Origin") not in self.server.allowed_origins
                                    or not hmac.compare_digest(self.headers.get("X-FreeCompute-CSRF", ""), session["csrf"])):
            raise APIError(403, "csrf_rejected", "Refresh the authenticated GUI before sending this command")

    def _headers(self, content_type):
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        origin = self.headers.get("Origin")
        if origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _json(self, value, status=200, cookie=None):
        data = json.dumps(scrubber.structured(value), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _body(self, allowed, required=()):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "invalid_body", "Chunked command bodies are unsupported")
        if self.headers.get_content_type() != "application/json":
            raise APIError(415, "invalid_body", "Commands require application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "invalid_body", "Invalid body length") from None
        if not 0 < length <= MAX_BODY:
            raise APIError(413, "invalid_body", "Command body must be 1..262144 bytes")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = value
            return result
        try:
            value = json.loads(self.rfile.read(length), object_pairs_hook=pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        except (ValueError, UnicodeError):
            raise APIError(400, "invalid_body", "A valid JSON object is required") from None
        if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
            raise APIError(400, "invalid_body", "Missing or unsupported command fields")
        return value

    def do_OPTIONS(self):
        self._handle("OPTIONS")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        try:
            self._guard()
            parsed = urlsplit(self.path)
            path = parsed.path
            if method == "OPTIONS":
                self.send_response(204)
                self._headers("text/plain")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-FreeCompute-CSRF, Last-Event-ID")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if method == "GET" and path == "/healthz":
                self._json({"status": "listening", "api_version": 1})
                return
            if method == "GET" and not path.startswith("/api/"):
                self._static(path)
                return
            if method == "POST" and path == PREFIX + "/auth/session":
                body = self._body({"token"}, {"token"})
                token = string(body["token"], "token")
                if not hmac.compare_digest(token, self.server.token):
                    raise APIError(401, "authentication_required", "Local API token was rejected")
                session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with self.server.auth_lock:
                    now = time.monotonic()
                    self.server.auth = {k: v for k, v in self.server.auth.items() if v["expires"] > now}
                    if len(self.server.auth) >= 32:
                        raise APIError(429, "session_limit", "Too many browser sessions; restart the local API to revoke them")
                    self.server.auth[session_id] = {"csrf": csrf, "expires": now + 12 * 3600}
                self._json({"authenticated": True, "csrf": csrf}, cookie=f"{COOKIE}={session_id}; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=43200")
                return
            session = self._auth()
            if method == "POST":
                self._csrf(session)
            if path == PREFIX + "/auth/session" and method == "GET":
                self._json({"authenticated": True, "csrf": session["csrf"] if session else None})
            elif method == "POST" and path == PREFIX + "/auth/logout":
                self._body(set())
                if session:
                    with self.server.auth_lock:
                        self.server.auth.pop(session["id"], None)
                self._json({"authenticated": False}, cookie=f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=0")
            elif method == "GET":
                self._get(path, parse_qs(parsed.query), session)
            else:
                self._post(path)
        except APIError as exc:
            self.close_connection = True
            self._json({"error": {"code": exc.code, "message": exc.message}}, exc.status)
        except Conflict as exc:
            self.close_connection = True
            self._json({"error": {"code": "state_conflict", "message": scrubber.scrub(exc)}}, 409)
        except ValueError as exc:
            self.close_connection = True
            self._json({"error": {"code": "invalid_command", "message": scrubber.scrub(exc)}}, 400)
        except (ConnectionError, TimeoutError):
            self.close_connection = True  # Detaching a renderer never cancels Core work.
        except Exception:
            self.close_connection = True
            self._json({"error": {"code": "internal_error", "message": "Local API failed; inspect Core task events before retrying"}}, 500)

    def _get(self, path, query, session):
        core, views = self.server.core, self.server.core.views
        if path == PREFIX + "/status":
            value = {"api_version": 1, "simulated": self.server.runtime.simulated, "workspace": str(core.store.workspace),
                     "default_profile": core.profile.profile_id, "default_worker": core.selected_worker,
                     "active_task_id": core._running_task_id, "runtime_error": self.server.runtime.last_error}
        elif path == PREFIX + "/sessions":
            value = views.sessions()
        elif path == PREFIX + "/tasks":
            value = views.tasks(query.get("session_id", [None])[0])
        elif path == PREFIX + "/workers":
            value = core.list_workers()
        elif path == PREFIX + "/profiles":
            value = core.list_models()
        elif path == PREFIX + "/queue":
            value = {"jobs": views.queue(), "leases": views.leases(), "active_task_id": core._running_task_id}
        elif path == PREFIX + "/actions":
            value = views.actions(query.get("task_id", [None])[0])
        elif path == PREFIX + "/approvals":
            value = views.approvals(query.get("session_id", [None])[0])
        elif match := re.fullmatch(PREFIX + r"/sessions/([a-zA-Z0-9-]+)/events", path):
            after = int(query.get("after", [self.headers.get("Last-Event-ID", "0")])[0])
            events = views.events(match[1], after)
            if "text/event-stream" in self.headers.get("Accept", ""):
                self._stream(match[1], after, session)
                return
            value = {"events": events, "cursor": events[-1]["sequence"] if events else after, "has_more": len(events) == 200}
        elif match := re.fullmatch(PREFIX + r"/sessions/([a-zA-Z0-9-]+)", path):
            value = views.session(match[1])
        elif match := re.fullmatch(PREFIX + r"/tasks/([a-zA-Z0-9-]+)", path):
            value = views.task(match[1])
        else:
            raise APIError(404, "not_found", "Unknown API query")
        self._json(value)

    def _post(self, path):
        core, runtime = self.server.core, self.server.runtime
        status = 200
        if path == PREFIX + "/sessions":
            body = self._body({"profile_id"})
            session_id = core.create_session(string(body.get("profile_id"), "profile_id", optional=True))
            value, status = core.views.session(session_id), 201
        elif path == PREFIX + "/tasks":
            body = self._body({"prompt", "session_id", "request_id", "profile_id", "worker_id", "max_turns"}, {"prompt", "session_id", "request_id"})
            for name in ("prompt", "session_id", "request_id", "profile_id", "worker_id"):
                if name in body:
                    string(body[name], name, optional=name in {"profile_id", "worker_id"})
            task_id = core.submit(**body)
            runtime.wake()
            value, status = core.views.task(task_id), 202
        elif match := re.fullmatch(PREFIX + r"/tasks/([a-zA-Z0-9-]+)/(cancel|resume)", path):
            self._body(set())
            value = runtime.cancel(match[1]) if match[2] == "cancel" else runtime.resume(match[1])
            status = 202
        elif match := re.fullmatch(PREFIX + r"/approvals/([a-zA-Z0-9-]+)/decision", path):
            body = self._body({"decision", "action_revision", "task_revision", "arguments_hash", "target_hash"}, {"decision", "action_revision", "task_revision", "arguments_hash", "target_hash"})
            value, status = runtime.decide(match[1], body), 202
        elif path == PREFIX + "/defaults":
            body = self._body({"profile_id", "worker_id"}, {"profile_id"})
            core.select_model(string(body["profile_id"], "profile_id"), string(body.get("worker_id"), "worker_id", optional=True))
            value = {"profile_id": core.profile.profile_id, "worker_id": core.selected_worker}
        elif path == PREFIX + "/workers/refresh":
            self._body(set())
            value = core.list_workers(refresh=True)
            runtime.wake()
        elif path in {PREFIX + "/reconcile/inference", PREFIX + "/reconcile/action"}:
            inference = path.endswith("inference")
            body = self._body({"lease_id", "confirmed_idle"} if inference else {"action_id", "outcome", "expected_hash", "confirmed"})
            if not runtime.operation.acquire(blocking=False):
                raise Conflict("Finish or cancel the active local task before reconciliation")
            try:
                if inference:
                    if body.get("confirmed_idle") is not True:
                        raise ValueError("Explicit remote idle observation is required; health is insufficient")
                    value = core.inference.reconcile_idle(lambda *_: True, string(body.get("lease_id"), "lease_id"))
                else:
                    if body.get("confirmed") is not True:
                        raise ValueError("Explicit tool outcome confirmation is required")
                    value = core.tool_broker.reconcile(string(body.get("action_id"), "action_id"),
                              string(body.get("outcome"), "outcome"), string(body.get("expected_hash"), "expected_hash", optional=True), lambda *_: True)
            finally:
                runtime.operation.release()
            runtime.wake()
        elif path == PREFIX + "/demo/worker" and runtime.simulated:
            body = self._body({"connected"}, {"connected"})
            if type(body["connected"]) is not bool:
                raise ValueError("connected must be true or false")
            for engine in set(core.registry.engines.values()):
                engine.connected = body["connected"]
            value = core.list_workers(refresh=True)
            runtime.wake()
        else:
            raise APIError(404, "not_found", "Unknown API command")
        self._json(value, status)

    def _stream(self, session_id, after, session):
        if not self.server.stream_slots.acquire(blocking=False):
            raise APIError(429, "stream_limit", "Eight event connections are already open; close an unused tab")
        try:
            self.connection.settimeout(5)  # Slow viewers cannot hold the Core or unbounded buffers.
            self.send_response(200)
            self._headers("text/event-stream; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            while not self.server.runtime.stop.is_set():
                if session:
                    with self.server.auth_lock:
                        current = self.server.auth.get(session["id"])
                        if not current or current["expires"] <= time.monotonic():
                            break
                events = self.server.core.views.events(session_id, after)
                for event in events:
                    data = json.dumps(scrubber.structured(event), ensure_ascii=False)
                    self.wfile.write(f"id: {event['sequence']}\nevent: core\ndata: {data}\n\n".encode("utf-8"))
                    after = event["sequence"]
                self.wfile.write(b"event: heartbeat\ndata: {}\n\n")
                self.wfile.flush()
                if len(events) < 200:
                    with self.server.runtime.changed:
                        self.server.runtime.changed.wait(1)
        except (ConnectionError, TimeoutError):
            pass
        finally:
            self.server.stream_slots.release()

    def _static(self, path):
        root = self.server.static_dir
        if not root or not (root / "index.html").is_file():
            raise APIError(503, "gui_not_built", "Build apps/gui with npm run build, then open the local API URL")
        target = (root / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(root):
            raise APIError(403, "path_rejected", "Static path is outside the GUI build")
        if target.is_dir() or not target.exists() and not target.suffix:
            target = root / "index.html"
        if not target.is_file():
            raise APIError(404, "not_found", "GUI asset not found")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self._headers(content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
