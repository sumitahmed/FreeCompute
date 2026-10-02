"""
harness/core/client.py — Authenticated Streaming Client to Kaggle Supervisor.
Handles Bearer auth, SSE chunk parsing, TTFT calculation, structured tool calls, and cancellation.
"""

from harness.security import scrubber, StreamRedactor
import socket
import threading
from dataclasses import replace
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional, Iterator, Callable

from harness.core.models import RemoteHealth, GpuTelemetry, StreamChunk, Message


class AuthenticationError(Exception):
    """Raised when Bearer token is rejected (401/403)."""
    pass


class RemoteBrainUnavailableError(Exception):
    """Raised when remote Kaggle server cannot be reached."""
    pass


def _interrupt_response(response):
    try:
        response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass


class CancellationToken:
    def __init__(self):
        self._requested = threading.Event()
        self.local_stop_confirmed = False
        self.remote_cancel_confirmed = False
        self._interrupt = None

    def cancel(self):
        self._requested.set()
        if self._interrupt:
            self._interrupt()

    def attach_response(self, response):
        def interrupt():
            _interrupt_response(response)
        self._interrupt = interrupt
        if self.is_cancelled:
            interrupt()

    @property
    def is_cancelled(self):
        return self._requested.is_set()

    def summary(self):
        return {"requested": self.is_cancelled, "local_stop_confirmed": self.local_stop_confirmed,
                "remote_cancel_confirmed": self.remote_cancel_confirmed,
                "remote_outcome": "unknown" if self.is_cancelled else "not_requested"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class KaggleBrainClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8081",
        api_key: str = "",
        model_alias: str = "qwen3.8-27b-huihui-abliterated-q4",
        timeout_seconds: int = 900,
    ):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Inference endpoint must use HTTP(S) without URL credentials")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        scrubber.register_secret(api_key)
        scrubber.register_secret(self.base_url)
        self.model_alias = model_alias
        self.timeout_seconds = timeout_seconds

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Kaggle-Qwen-Harness/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_health(self) -> RemoteHealth:
        """Poll the remote Kaggle supervisor /health endpoint."""
        url = f"{self.base_url}/health"
        req = urllib.request.Request(url, headers=self._get_headers(), method="GET")

        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                gpus = []
                for g in data.get("gpus", []):
                    if "error" not in g:
                        gpus.append(GpuTelemetry(
                            index=g.get("index", 0),
                            name=scrubber.scrub(g.get("name", "Tesla T4")),
                            vram_used_mib=g.get("vramUsedMiB", 0),
                            vram_total_mib=g.get("vramTotalMiB", 15360),
                            temp_c=g.get("tempC", 0),
                            utilization_pct=g.get("utilizationPct", 0),
                        ))
                return RemoteHealth(
                    status=scrubber.scrub(data.get("status", "unknown")),
                    supervisor_uptime_s=data.get("supervisorUptimeSeconds", 0.0),
                    container_uptime_s=data.get("containerUptimeSeconds", 0.0),
                    max_session_s=data.get("maxSessionSeconds", 43200.0),
                    seconds_remaining_12h=data.get("secondsRemainingIn12hSession", 43200.0),
                    gpus=gpus,
                    raw=scrubber.structured(data),
                )
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise AuthenticationError(f"Authentication failed ({exc.code}): Check your API key.")
            raise RemoteBrainUnavailableError(scrubber.scrub(f"HTTP error from Kaggle brain: {exc.code} {exc.reason}"))
        except Exception as exc:
            raise RemoteBrainUnavailableError(scrubber.scrub(f"Cannot connect to Kaggle supervisor at {self.base_url}: {exc}"))

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        cancellation_token: Optional[CancellationToken] = None,
        model: Optional[str] = None,
    ) -> Iterator[StreamChunk]:
        """
        Stream chat completions token-by-token via Server-Sent Events (SSE).
        Yields StreamChunk with real-time text and TTFT tracking.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model or self.model_alias,
            "messages": [m.to_dict() if hasattr(m, "to_dict") else m for m in messages],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        body = json.dumps(scrubber.structured(payload)).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._get_headers(), method="POST")

        start_time = time.monotonic()
        first_token_received = False
        text_redactor, reasoning_redactor = StreamRedactor(), StreamRedactor()
        deadline_timer, timed_out = None, threading.Event()
        if cancellation_token and cancellation_token.is_cancelled:
            cancellation_token.local_stop_confirmed = True
            return

        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=self.timeout_seconds) as resp:
                def expire():
                    timed_out.set()
                    _interrupt_response(resp)
                deadline_timer = threading.Timer(max(0.001, self.timeout_seconds - (time.monotonic() - start_time)), expire)
                deadline_timer.daemon = True
                deadline_timer.start()
                if cancellation_token:
                    cancellation_token.attach_response(resp)
                completed = False
                for raw_line in iter(lambda: resp.readline(1024 * 1024 + 1), b""):
                    if len(raw_line) > 1024 * 1024:
                        raise ValueError("Inference SSE line exceeded its byte limit")
                    if timed_out.is_set() or time.monotonic() - start_time > self.timeout_seconds:
                        raise TimeoutError("Inference exceeded its configured request deadline")
                    if cancellation_token and cancellation_token.is_cancelled:
                        break

                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            completed = True
                            yield StreamChunk(delta_content=text_redactor.finish(), delta_reasoning=reasoning_redactor.finish(), stream_complete=True)
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices") or [{}]
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            finish_reason = choice.get("finish_reason")
                            reasoning = delta.get("reasoning_content") or ""
                            content = delta.get("content") or ""
                            tool_calls = delta.get("tool_calls")

                            is_first = False
                            ttft_ms = None
                            if (content or reasoning or tool_calls) and not first_token_received:
                                first_token_received = True
                                is_first = True
                                ttft_ms = round((time.monotonic() - start_time) * 1000.0, 1)

                            yield StreamChunk(
                                delta_content=text_redactor.feed(content),
                                delta_reasoning=reasoning_redactor.feed(reasoning),
                                usage=scrubber.structured(data.get("usage")),
                                tool_call_deltas=tool_calls,
                                finish_reason=finish_reason,
                                is_first_token=is_first,
                                ttft_ms=ttft_ms,
                            )
                        except json.JSONDecodeError as exc:
                            raise ValueError("Malformed SSE JSON; no tools may execute") from exc
                if not completed and not (cancellation_token and cancellation_token.is_cancelled):
                    raise ValueError("Incomplete inference stream")
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise AuthenticationError(f"Authentication rejected by Kaggle supervisor: HTTP {exc.code}")
            raise RemoteBrainUnavailableError(f"Server error: {exc.code}")
        except Exception as exc:
            if cancellation_token and cancellation_token.is_cancelled:
                return
            detail = "Inference request timed out; remote completion is unconfirmed" if timed_out.is_set() else f"Connection stream failed: {exc}"
            raise RemoteBrainUnavailableError(scrubber.scrub(detail))

        finally:
            if deadline_timer:
                deadline_timer.cancel()
            if cancellation_token:
                cancellation_token._interrupt = None
                cancellation_token.local_stop_confirmed = cancellation_token.is_cancelled

    def stream_chat_completion(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        cancellation: Optional[CancellationToken] = None,
        cancellation_token: Optional[CancellationToken] = None,
        on_chunk: Optional[Callable[[StreamChunk], None]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        token = cancellation or cancellation_token
        chunks = []
        ttft_ms = 0.0
        full_content = []
        for chunk in self.stream_chat(messages=messages, tools=tools, cancellation_token=token, **kwargs):
            if chunk.is_first_token and chunk.ttft_ms is not None:
                ttft_ms = chunk.ttft_ms
            if chunk.delta_content:
                full_content.append(chunk.delta_content)
            visible_chunk = replace(chunk, tool_call_deltas=scrubber.structured(chunk.tool_call_deltas), usage=scrubber.structured(chunk.usage))
            if on_chunk:
                on_chunk(visible_chunk)
            chunks.append(visible_chunk)
            if token and token.is_cancelled:
                break
        return {
            "content": "".join(full_content),
            "ttft_ms": ttft_ms,
            "chunks": chunks,
        }
