"""Engine policy stays at this boundary. Network adapters never receive tools to execute."""
from harness.core.client import AuthenticationError
from harness.security import scrubber
from harness.storage.runtime import fingerprint


class EngineFailure(RuntimeError):
    def __init__(self, message, *, remote_not_started=False, kind="transport"):
        super().__init__(scrubber.scrub(message))
        self.remote_not_started, self.kind = remote_not_started, kind


class LlamaCppEngine:
    kind = "llama.cpp"

    def __init__(self, client):
        self._client = client
        self.identity_hash = fingerprint({"engine": self.kind, "endpoint": client.base_url})

    def get_capabilities(self):
        return frozenset({"text", "code_tools"})

    def describe(self):
        return {"engine": self.kind, "capabilities": sorted(self.get_capabilities()), "streaming": True,
                "cancellation": "local_socket_only", "remote_cancel_ack": False,
                "timeout_seconds": self._client.timeout_seconds}

    def get_health(self):
        health = self._client.get_health()
        if health.status == "ok":
            from dataclasses import replace
            health = replace(health, status="healthy")
        return health

    def stream(self, profile, messages, tools, cancellation):
        if not profile.capabilities <= self.get_capabilities():
            raise EngineFailure("Profile capabilities exceed this engine", remote_not_started=True, kind="capability")
        try:
            yield from self._client.stream_chat(messages, tools=tools, cancellation_token=cancellation,
                                               max_tokens=profile.reserved_completion, model=profile.model)
        except AuthenticationError as exc:
            raise EngineFailure(exc, remote_not_started=True, kind="authentication") from None
        except Exception as exc:
            raise EngineFailure(exc) from None

    def generate(self, profile, prompt, cancellation):
        raise EngineFailure("Text engine cannot generate images", remote_not_started=True, kind="capability")


class OpenAICompatibleEngine(LlamaCppEngine):
    kind = "openai-compatible"

    def __init__(self, provider):
        super().__init__(provider.client)
        self._capabilities = frozenset(cap.value for cap in provider.get_capabilities())

    def get_capabilities(self):
        return self._capabilities


class ComfyUIEngine:
    kind = "ComfyUI"

    def __init__(self, provider):
        self.provider = provider
        self.identity_hash = fingerprint({"engine": self.kind, "endpoint": provider.server_url})

    def get_capabilities(self):
        return frozenset({"image_gen"})

    def describe(self):
        return {"engine": self.kind, "capabilities": ["image_gen"], "streaming": False,
                "cancellation": "local_wait_only", "remote_cancel_ack": False}

    def get_health(self):
        return self.provider.get_health()

    def stream(self, *args):
        raise EngineFailure("Image engine cannot run text inference", remote_not_started=True, kind="capability")

    def generate(self, profile, prompt, cancellation):
        if "image_gen" not in profile.capabilities:
            raise EngineFailure("Profile cannot generate images", remote_not_started=True, kind="capability")
        if cancellation.is_cancelled:
            raise EngineFailure("Cancelled before image dispatch", remote_not_started=True, kind="cancelled")
        try:
            return self.provider.generate_image(prompt=prompt)
        except Exception as exc:
            raise EngineFailure(exc) from None
