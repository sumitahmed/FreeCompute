"""
harness/providers/base.py — Abstract provider contracts and capability model for FreeCompute.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from harness.core.models import Message, RemoteHealth, StreamChunk


class Capability(str, Enum):
    TEXT = "text"
    CODE_TOOLS = "code_tools"
    IMAGE_UNDERSTANDING = "image_understanding"
    IMAGE_GEN = "image_gen"
    VIDEO_UNDERSTANDING = "video_understanding"
    VIDEO_GEN = "video_gen"


class UnsupportedCapabilityError(Exception):
    """
    Raised when a requested modality or operation is not supported by the active
    model engine or backend hardware.
    """

    def __init__(self, requested: Capability, provider_name: str, guidance: str = ""):
        self.requested = requested
        self.provider_name = provider_name
        self.guidance = guidance
        msg = f"Provider '{provider_name}' does not support requested capability '{requested.value}'."
        if guidance:
            msg += f" {guidance}"
        super().__init__(msg)


class BaseProvider(ABC):
    """Abstract base class for all inference backends in FreeCompute."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_capabilities(self) -> Set[Capability]:
        """Return the set of capabilities supported by this provider."""
        raise NotImplementedError

    def has_capability(self, cap: Capability) -> bool:
        """Check if this provider supports a specific capability."""
        return cap in self.get_capabilities()

    def assert_capability(self, cap: Capability, guidance: str = ""):
        """Raise UnsupportedCapabilityError if this provider lacks the capability."""
        if not self.has_capability(cap):
            raise UnsupportedCapabilityError(requested=cap, provider_name=self.name, guidance=guidance)

    @abstractmethod
    def get_health(self) -> RemoteHealth:
        """Query remote backend health, uptime, and GPU telemetry."""
        raise NotImplementedError

    @abstractmethod
    def stream_chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        cancellation: Optional[Any] = None,
        on_chunk: Optional[Callable[[StreamChunk], None]] = None,
    ) -> Dict[str, Any]:
        """Stream conversational chat completions with optional tool calls."""
        raise NotImplementedError

    def generate_image(
        self,
        prompt: str,
        width: int = 768,
        height: int = 768,
        steps: int = 8,
        cfg: float = 3.5,
        seed: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate an image from a prompt."""
        self.assert_capability(
            Capability.IMAGE_GEN,
            guidance="To generate images, configure a ComfyUI endpoint with FREECOMPUTE_IMAGE_SERVER.",
        )
        raise NotImplementedError
