"""
harness/core/models.py — Data classes and models for the coding harness.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FunctionCall:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    type: str = "function"
    function: Optional[FunctionCall] = None


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            calls = []
            for tc in self.tool_calls:
                call_dict: Dict[str, Any] = {"id": tc.id, "type": tc.type}
                if tc.function:
                    call_dict["function"] = {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                calls.append(call_dict)
            d["tool_calls"] = calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class StreamChunk:
    delta_content: str = ""
    delta_reasoning: str = ""
    tool_call_deltas: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    is_first_token: bool = False
    ttft_ms: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None
    stream_complete: bool = False


@dataclass
class GpuTelemetry:
    index: int
    name: str
    vram_used_mib: int
    vram_total_mib: int
    temp_c: int
    utilization_pct: int


@dataclass
class RemoteHealth:
    status: str
    supervisor_uptime_s: float
    container_uptime_s: float
    max_session_s: float
    seconds_remaining_12h: float
    gpus: List[GpuTelemetry] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
