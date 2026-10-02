"""Generic, explicit context accounting. No model-family prompt mutations."""
from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class ContextBudget:
    profile_id: str
    capacity: int
    reserved_completion: int
    system_prefix: int
    tool_prefix: int
    history: int
    selected_context: int
    tool_results: int
    method: str = "utf8-bytes-plus-framing estimate (not verified tokenizer counts)"

    @property
    def input_total(self):
        return self.system_prefix + self.tool_prefix + self.history + self.selected_context + self.tool_results

    @property
    def fits(self):
        return self.input_total + self.reserved_completion <= self.capacity

    def to_dict(self):
        return dict(asdict(self), input_total=self.input_total, fits=self.fits)


def estimate(value):
    if not value:
        return 0
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")) + 16


def budget_context(profile, system, tools, history, selected_context=None):
    ordinary = [m for m in history if m.get("role") != "tool"]
    results = [m for m in history if m.get("role") == "tool"]
    return ContextBudget(profile.profile_id, profile.context_capacity, profile.reserved_completion,
                         estimate(system), estimate(tools), estimate(ordinary),
                         estimate(selected_context), estimate(results))
