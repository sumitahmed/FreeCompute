"""Small proposal-only interface. Callers own inference, authorization and storage."""
from dataclasses import dataclass, field, asdict
import json
import uuid
from typing import Protocol
from harness.security import scrubber


@dataclass(frozen=True)
class ActionProposal:
    call_id: str
    name: str
    arguments: dict


@dataclass
class DriverState:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    profile_id: str = "default"
    context_epoch: int = 0
    pending: list[ActionProposal] = field(default_factory=list)
    cancellation_requested: bool = False
    local_stop_confirmed: bool = False
    remote_cancel_confirmed: bool = False
    recovery_requires_reproposal: bool = False

    def serialize(self):
        # Sanitized checkpoints cannot replay redacted arguments. Recovery must
        # request fresh input and fresh approval for any such proposal.
        raw = asdict(self)
        clean = scrubber.structured(raw)
        clean["recovery_requires_reproposal"] = self.recovery_requires_reproposal or raw != clean
        return json.dumps(clean, sort_keys=True)

    @classmethod
    def recover(cls, encoded):
        data = json.loads(encoded)
        data["pending"] = [ActionProposal(**p) for p in data.get("pending", [])]
        return cls(**data)

    def change_profile(self, profile_id):
        if profile_id != self.profile_id:
            self.profile_id = profile_id
            self.context_epoch += 1
            self.pending.clear()
            return True
        return False


class AgentDriver(Protocol):
    def propose(self, state: DriverState, response: dict) -> list[ActionProposal]: ...


class ProposalDriver:
    """Reference contract adapter; deliberately has no tool/client/storage handles."""
    def propose(self, state, response):
        if state.cancellation_requested:
            return []
        if response.get("finish_reason") != "tool_calls":
            return []
        proposals = []
        identities = set()
        for call in response.get("tool_calls", []):
            identity = call.get("id")
            if not isinstance(identity, str) or not identity or identity in identities:
                raise ValueError("Complete unique call IDs required")
            identities.add(identity)
            function = call["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict) or not isinstance(function["name"], str):
                raise ValueError("Complete tool object required")
            proposals.append(ActionProposal(identity, function["name"], arguments))
        state.recovery_requires_reproposal = False
        state.pending = proposals
        return proposals
