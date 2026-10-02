"""Small worker/profile contracts; physical scheduling is deliberately deferred."""
from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Worker:
    worker_id: str
    location: str
    engine: str
    capabilities: frozenset[str]
    health: str = "unverified"
    observed_resources: dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.version != 1 or not self.worker_id or not self.location or not self.engine:
            raise ValueError("Unsupported worker version or missing identity/location/engine")


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    worker_id: str
    model: str
    engine: str
    capabilities: frozenset[str]
    context_capacity: int = 65536
    reserved_completion: int = 2048
    max_tool_result_bytes: int = 16000
    version: int = 1

    def __post_init__(self):
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.version != 1:
            raise ValueError("Unsupported model-profile version")
        if not self.profile_id or not self.worker_id or not self.model:
            raise ValueError("Worker/model/profile identity is required")
        if self.context_capacity <= 0 or not 0 < self.reserved_completion < self.context_capacity or self.max_tool_result_bytes < 256:
            raise ValueError("Invalid declared context or completion budget")

    def to_dict(self):
        result = asdict(self)
        result["capabilities"] = sorted(self.capabilities)
        return result


class EngineAdapter(Protocol):
    def stream(self, profile, messages, tools, cancellation): ...
    def get_health(self): ...


class LlamaCppEngine:
    """Existing authenticated supervisor transport, owned only by CoreService."""
    def __init__(self, client):
        self._client = client

    def stream(self, profile, messages, tools, cancellation):
        if profile.model != self._client.model_alias:
            raise ValueError("Profile/model mismatch; attach the matching engine adapter")
        return self._client.stream_chat(messages, tools=tools, cancellation_token=cancellation,
                                        max_tokens=profile.reserved_completion)

    def get_health(self):
        return self._client.get_health()
