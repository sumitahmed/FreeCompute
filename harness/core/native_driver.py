"""Proposal-only state machine. No providers, tools, permissions or durable I/O."""
from dataclasses import asdict, dataclass, field
import json
from typing import Protocol

from harness.security import scrubber


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def strict_json(raw):
    def invalid(value):
        raise ValueError("Non-finite JSON value")
    return json.loads(raw, object_pairs_hook=_object, parse_constant=invalid)


@dataclass(frozen=True)
class InferenceResponse:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str | None = None
    stream_complete: bool = False
    error: str | None = None


@dataclass(frozen=True)
class Proposal:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class DriverDecision:
    kind: str
    answer: str = ""
    proposals: tuple = ()
    detail: str = ""


@dataclass
class NativeState:
    agent_id: str
    profile_id: str
    context_epoch: int = 0
    turns: int = 0
    phase: str = "ready"
    pending: list = field(default_factory=list)
    cancellation_requested: bool = False
    local_stop_confirmed: bool = False
    remote_cancel_confirmed: bool = False
    requires_reproposal: bool = False
    version: int = 1

    def serialize(self):
        raw = asdict(self)
        clean = scrubber.structured(raw)
        clean["requires_reproposal"] = self.requires_reproposal or clean != raw
        return json.dumps(clean, sort_keys=True, ensure_ascii=False, allow_nan=False)

    @classmethod
    def recover(cls, encoded):
        data = strict_json(encoded)
        if data.get("version") != 1:
            raise ValueError("Unsupported driver state version")
        state = cls(**data)
        if not state.agent_id or not state.profile_id or state.context_epoch < 0 or state.turns < 0:
            raise ValueError("Invalid driver identity or counters")
        if state.phase not in {"ready", "pending", "completed", "failed", "malformed", "incomplete", "truncated", "cancelled", "max_turns"}:
            raise ValueError("Invalid driver phase")
        if not isinstance(state.pending, list) or bool(state.pending) != (state.phase == "pending"):
            raise ValueError("Driver phase and pending proposals disagree")
        seen = set()
        for proposal in state.pending:
            if (not isinstance(proposal, dict) or set(proposal) != {"call_id", "name", "arguments"}
                or not isinstance(proposal["call_id"], str) or not proposal["call_id"] or proposal["call_id"] in seen
                or not isinstance(proposal["name"], str) or not proposal["name"] or not isinstance(proposal["arguments"], dict)):
                raise ValueError("Invalid recovered proposal sequence")
            seen.add(proposal["call_id"])
        return state

    def change_profile(self, profile_id):
        if self.profile_id == profile_id:
            return False
        self.profile_id = profile_id
        self.context_epoch += 1
        self.pending.clear()
        self.phase = "ready"
        return True


class AgentDriver(Protocol):
    def advance(self, state: NativeState, response: InferenceResponse, max_turns: int) -> DriverDecision: ...
    def accept_results(self, state: NativeState, call_ids: list[str]) -> None: ...


class NativeAgentDriver:
    """Atomic decoding only; mutable state is supplied and owned by the core."""
    def advance(self, state, response, max_turns=15):
        if state.cancellation_requested:
            state.phase = "cancelled"
            return DriverDecision("cancelled", detail="Local stop requested; remote outcome unconfirmed")
        if state.phase != "ready" or state.pending:
            raise ValueError("Pending results must be accepted before the next inference turn")
        if state.turns >= max_turns:
            state.phase = "max_turns"
            return DriverDecision("max_turns")
        state.turns += 1
        if response.error:
            state.phase = "failed"
            return DriverDecision("failed", detail=scrubber.scrub(response.error))
        if response.finish_reason in {"length", "content_filter"}:
            state.phase = "truncated"
            return DriverDecision("truncated", detail="No proposals accepted from truncated output")
        if not response.stream_complete or response.finish_reason not in {"stop", "tool_calls"}:
            state.phase = "incomplete"
            return DriverDecision("incomplete", detail="Stream completion and finish reason must both be confirmed")
        proposals = []
        try:
            if not isinstance(response.text, str) or not isinstance(response.tool_calls, list):
                raise ValueError("Invalid normalized response")
            if response.finish_reason == "tool_calls":
                if not response.tool_calls:
                    raise ValueError("Missing complete tool calls")
                seen = set()
                for call in response.tool_calls:
                    identity = call.get("id")
                    function = call.get("function", {})
                    name = function.get("name")
                    if not isinstance(identity, str) or not identity.strip() or identity in seen:
                        raise ValueError("Tool call IDs must be nonempty and unique")
                    if not isinstance(name, str) or not name.strip() or call.get("type", "function") != "function":
                        raise ValueError("Invalid function call")
                    arguments = strict_json(function["arguments"])
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be an object")
                    if scrubber.structured(arguments) != arguments or scrubber.scrub(name) != name:
                        raise ValueError("Sensitive proposal cannot be safely checkpointed; re-propose without secrets")
                    seen.add(identity)
                    proposals.append(Proposal(identity, name, arguments))
            elif response.tool_calls or not response.text.strip():
                raise ValueError("Stop requires nonempty text and no tool calls")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            state.phase = "malformed"
            return DriverDecision("malformed", detail=scrubber.scrub(exc))
        if proposals:
            state.pending = [asdict(p) for p in proposals]
            state.phase = "pending"
            state.requires_reproposal = False
            return DriverDecision("tool_proposals", proposals=tuple(proposals))
        state.phase = "completed"
        return DriverDecision("completed", answer=scrubber.scrub(response.text))

    def accept_results(self, state, call_ids):
        if state.phase != "pending" or call_ids != [p["call_id"] for p in state.pending]:
            raise ValueError("Results must match the entire pending proposal sequence")
        state.pending.clear()
        state.phase = "ready"
