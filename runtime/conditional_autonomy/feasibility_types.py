"""Data-only contracts shared by the feasibility solver and witness checker."""

from __future__ import annotations

from dataclasses import dataclass

from .storage import canonical_json_bytes


@dataclass(frozen=True, order=True)
class ActionAssignment:
    """One solver decision, expressed without executable constraint logic."""

    action_id: str
    start_minute: int
    end_minute: int


@dataclass(frozen=True)
class FeasibilityWitness:
    """A deterministic, content-bound schedule witness."""

    environment_version: str
    problem_hash: str
    assignments: tuple[ActionAssignment, ...]

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "environment_version": self.environment_version,
                "problem_hash": self.problem_hash,
                "assignments": [
                    {
                        "action_id": item.action_id,
                        "start_minute": item.start_minute,
                        "end_minute": item.end_minute,
                    }
                    for item in self.assignments
                ],
            }
        )


@dataclass(frozen=True)
class FeasibilityDecision:
    """The externally visible, independently checked oracle decision."""

    feasible: bool
    witness: FeasibilityWitness | None
    reason: str
