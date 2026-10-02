"""Versioned model declarations and worker identities, independent of adapters."""
from dataclasses import asdict, dataclass, field
import re
from typing import Protocol


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("Identifiers must be 1..128 letters, digits, dots, colons, dashes or underscores")
    return value


@dataclass(frozen=True)
class Worker:
    worker_id: str
    location: str
    engine: str
    capabilities: frozenset[str]
    health: str = "unverified"
    observed_resources: dict = field(default_factory=dict)
    version: int = 1
    concurrency_limit: int = 1
    resource_pool: str = ""
    resources: frozenset[str] = frozenset()
    last_seen: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "resources", frozenset(self.resources))
        if self.version != 1 or not self.worker_id or not self.location or not self.engine:
            raise ValueError("Unsupported worker version or missing identity/location/engine")
        identifier(self.worker_id)
        identifier(self.resource_pool or self.worker_id)
        for resource in self.resources:
            identifier(resource)
        if type(self.concurrency_limit) is not int or not 1 <= self.concurrency_limit <= 64:
            raise ValueError("Worker concurrency must be an integer in 1..64")

    def to_dict(self):
        result = asdict(self)
        result["capabilities"], result["resources"] = sorted(self.capabilities), sorted(self.resources)
        return result


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    worker_id: str = ""  # Preserved positional API; only a legacy route hint.
    model: str = ""
    engine: str = ""
    capabilities: frozenset[str] = frozenset()
    context_capacity: int = 65536
    reserved_completion: int = 2048
    max_tool_result_bytes: int = 16000
    version: int = 1
    engine_requirements: frozenset[str] = frozenset()
    resource_requirements: frozenset[str] = frozenset()
    tokenizer: str | None = None
    template: str | None = None
    verification: str = "declared"

    def __post_init__(self):
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "engine_requirements", frozenset(self.engine_requirements or {self.engine}))
        object.__setattr__(self, "resource_requirements", frozenset(self.resource_requirements))
        if self.version != 1:
            raise ValueError("Unsupported model-profile version")
        if not self.profile_id or not self.model or not all(self.engine_requirements):
            raise ValueError("Model/profile identity and engine requirements are required")
        identifier(self.profile_id)
        if self.worker_id:
            identifier(self.worker_id)
        for resource in self.resource_requirements:
            identifier(resource)
        if any(type(v) is not int for v in (self.context_capacity, self.reserved_completion, self.max_tool_result_bytes)) or self.context_capacity <= 0 or not 0 < self.reserved_completion < self.context_capacity or self.max_tool_result_bytes < 256:
            raise ValueError("Invalid declared context or completion budget")
        if self.verification not in {"declared", "unverified", "fixture-tested", "verified"}:
            raise ValueError("Unknown profile verification status")

    def to_dict(self):
        result = asdict(self)
        result["capabilities"] = sorted(self.capabilities)
        result["engine_requirements"] = sorted(self.engine_requirements)
        result["resource_requirements"] = sorted(self.resource_requirements)
        return result


class EngineAdapter(Protocol):
    def stream(self, profile, messages, tools, cancellation): ...
    def get_health(self): ...
    def get_capabilities(self): ...
    def describe(self): ...
    def generate(self, profile, prompt, cancellation): ...


# Preserve the Stage 3 import without exposing engine policy in the core.
from harness.core.engines import LlamaCppEngine
