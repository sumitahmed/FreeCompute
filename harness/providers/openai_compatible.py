"""Chat Completions transport with authenticated model-list health, no SDK."""
import json
import urllib.error
import urllib.request

from harness.core.client import AuthenticationError, KaggleBrainClient, _NoRedirect
from harness.core.models import RemoteHealth
from harness.providers.llamacpp import LlamaCppProvider
from harness.providers.base import Capability
from harness.security import scrubber


class OpenAICompatibleClient(KaggleBrainClient):
    def get_health(self):
        request = urllib.request.Request(self.base_url + "/v1/models", headers=self._get_headers())
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=min(10, self.timeout_seconds)) as response:
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError("Model-list response exceeded its byte limit")
                data = json.loads(body)
            models = data.get("data")
            if not isinstance(models, list) or any(not isinstance(m, dict) or not isinstance(m.get("id"), str) for m in models):
                raise ValueError("Invalid compatible model-list response")
            return RemoteHealth("healthy", 0, 0, 0, 0, raw=scrubber.structured({"models": [m["id"] for m in models], "telemetry_available": False}))
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise AuthenticationError("Compatible endpoint rejected authentication") from None
            raise RuntimeError("Compatible health returned HTTP " + str(exc.code)) from None
        except Exception as exc:
            raise RuntimeError(scrubber.scrub(exc)) from None


class OpenAICompatibleProvider(LlamaCppProvider):
    def __init__(self, base_url, api_key="", model_alias="", timeout_seconds=900, *, code_tools=False):
        # /v1 is accepted at the end of a configured API base URL.
        base_url = base_url.rstrip("/").removesuffix("/v1")
        super().__init__(base_url, api_key, model_alias, timeout_seconds)
        self.client = OpenAICompatibleClient(base_url, api_key, model_alias, timeout_seconds)
        self.name = "OpenAI-compatible inference"
        self.code_tools = bool(code_tools)

    def get_capabilities(self):
        return {Capability.TEXT, Capability.CODE_TOOLS} if self.code_tools else {Capability.TEXT}
