"""
harness/providers/llamacpp.py — Provider implementation for llama.cpp / supervisor backends.
"""

from typing import Any, Callable, Dict, List, Optional, Set

from harness.core.client import KaggleBrainClient
from harness.core.models import Message, RemoteHealth, StreamChunk
from harness.providers.base import BaseProvider, Capability


class LlamaCppProvider(BaseProvider):
    """
    Provider for llama-server / llama.cpp backends mediated through the
    authenticated Kaggle supervisor proxy.
    Supported capabilities: TEXT, CODE_TOOLS.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8081",
        api_key: str = "",
        model_alias: str = "qwen3.8-27b-huihui-abliterated-q4",
        timeout_seconds: int = 900,
    ):
        super().__init__(name=f"llama.cpp ({model_alias})")
        self.model_alias = model_alias
        self.client = KaggleBrainClient(
            base_url=base_url,
            api_key=api_key,
            model_alias=model_alias,
            timeout_seconds=timeout_seconds,
        )

    def get_capabilities(self) -> Set[Capability]:
        return {Capability.TEXT, Capability.CODE_TOOLS}

    def get_health(self) -> RemoteHealth:
        return self.client.get_health()

    def stream_chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        cancellation: Optional[Any] = None,
        on_chunk: Optional[Callable[[StreamChunk], None]] = None,
    ) -> Dict[str, Any]:
        self.assert_capability(Capability.TEXT)
        return self.client.stream_chat_completion(
            messages=messages,
            tools=tools,
            cancellation=cancellation,
            on_chunk=on_chunk,
        )

    def generate_image(self, *args, **kwargs) -> Dict[str, Any]:
        self.assert_capability(
            Capability.IMAGE_GEN,
            guidance=(
                f"Active model '{self.model_alias}' is an autoregressive LLM optimized for text and coding. "
                "For image generation, use the /image command or configure a ComfyUI endpoint with "
                "FREECOMPUTE_IMAGE_SERVER."
            ),
        )
