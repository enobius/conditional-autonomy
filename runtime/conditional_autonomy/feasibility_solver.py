"""Deterministic finite-domain solver for the Thanksgiving environment.

This module intentionally does not import the witness checker or the environment's
``evaluate_schedule`` implementation.  It builds and searches its own constraint
model so that its successful assignments can be checked by independent code.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
from typing import Any

from .feasibility_types import ActionAssignment, FeasibilityWitness
from .storage import canonical_json_bytes
from .thanksgiving import ENVIRONMENT_VERSION, ScheduledAction, utc_minute


class FeasibilitySolverError(ValueError):
    """The proposed solver problem is structurally invalid."""


class DeterministicConstraintSolver:
    """Solve the finite minute-grid scheduling CSP by deterministic backtracking."""

    _REQUIRED_DURATIONS = {
        "thanksgiving:cook-turkey": 240,
        "thanksgiving:prepare-sides": 120,
    }

    def solve(
        self, state: Mapping[str, Any], templates: Sequence[ScheduledAction]
    ) -> FeasibilityWitness | None:
        problem_hash = self._problem_hash(state, templates)
        obligations = self._obligations(state)
        template_tuple = tuple(templates)
        if not self._validate_inventory(state, template_tuple, obligations):
            return None
        domains = {
            action.action_id: self._domain(state, action, obligations[action.obligation_id])
            for action in template_tuple
        }
        if any(not domain for domain in domains.values()):
            return None

        by_id = {action.action_id: action for action in template_tuple}
        order = sorted(by_id, key=lambda action_id: (len(domains[action_id]), action_id))
        assigned: dict[str, ScheduledAction] = {}

        def search(index: int) -> tuple[ScheduledAction, ...] | None:
            if index == len(order):
                candidate = tuple(assigned[action_id] for action_id in sorted(assigned))
                return candidate if self._complete_constraints(state, candidate) else None
            action_id = order[index]
            template = by_id[action_id]
            for start in domains[action_id]:
                candidate = self._place(template, start)
                if self._partial_constraints(state, candidate, assigned):
                    assigned[action_id] = candidate
                    result = search(index + 1)
                    if result is not None:
                        return result
                    del assigned[action_id]
            return None

        solution = search(0)
        if solution is None:
            return None
        return FeasibilityWitness(
            environment_version=state.get("active_plan", {}).get(
                "environment_version", ENVIRONMENT_VERSION
            ),
            problem_hash=problem_hash,
            assignments=tuple(
                ActionAssignment(item.action_id, item.start_minute, item.end_minute)
                for item in solution
            ),
        )

    def _obligations(
        self, state: Mapping[str, Any]
    ) -> dict[str, Mapping[str, Any]]:
        raw = state.get("obligations")
        if not isinstance(raw, list):
            raise FeasibilitySolverError("state obligations must be a list")
        try:
            result = {item["obligation_id"]: item for item in raw}
        except (KeyError, TypeError) as exc:
            raise FeasibilitySolverError("state obligations are malformed") from exc
        if len(result) != len(raw):
            raise FeasibilitySolverError("duplicate obligation ID")
        return result

    def _validate_inventory(
        self,
        state: Mapping[str, Any],
        templates: tuple[ScheduledAction, ...],
        obligations: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        ids = [item.action_id for item in templates]
        if len(set(ids)) != len(ids):
            raise FeasibilitySolverError("duplicate action ID")
        counts = Counter(item.obligation_id for item in templates)
        if set(counts) != set(obligations) or any(count != 1 for count in counts.values()):
            return False
        graph_edges: set[tuple[str, str]] = set()
        for edge in state.get("dependencies", ()):
            try:
                graph_edges.add((edge["predecessor_id"], edge["successor_id"]))
            except (KeyError, TypeError) as exc:
                raise FeasibilitySolverError("dependency graph is malformed") from exc
        action_for_obligation = {item.obligation_id: item for item in templates}
        expected_edges: set[tuple[str, str]] = set()
        for obligation_id, obligation in obligations.items():
            declared = obligation.get("dependency_ids")
            if not isinstance(declared, list) or not all(
                isinstance(item, str) for item in declared
            ):
                raise FeasibilitySolverError("obligation dependencies are malformed")
            expected_edges.update((item, obligation_id) for item in declared)
            expected_actions = {
                action_for_obligation[item].action_id
                for item in declared
                if item in action_for_obligation
            }
            actual = set(action_for_obligation[obligation_id].dependencies)
            if expected_actions != actual:
                raise FeasibilitySolverError("action dependencies disagree with state")
        if graph_edges != expected_edges:
            raise FeasibilitySolverError("dependency graph disagrees with obligations")
        return True

    def _domain(
        self,
        state: Mapping[str, Any],
        action: ScheduledAction,
        obligation: Mapping[str, Any],
    ) -> range:
        try:
            lower = utc_minute(obligation["window"]["start"]["instant"])
            upper = min(
                utc_minute(obligation["window"]["end"]["instant"]),
                utc_minute(obligation["deadline"]["instant"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FeasibilitySolverError("obligation time boundary is malformed") from exc
        duration = self._REQUIRED_DURATIONS.get(
            action.action_type, action.end_minute - action.start_minute
        )
        if duration < 0:
            raise FeasibilitySolverError("action duration is negative")
        entities = state.get("entities", {})
        release_entity = {
            "thanksgiving:land-and-rent": "person:james",
            "thanksgiving:arrive-home": "person:michael",
        }.get(action.action_type)
        if release_entity is not None:
            try:
                lower = max(
                    lower,
                    utc_minute(entities[release_entity]["arrival_at"]["instant"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise FeasibilitySolverError("arrival release is malformed") from exc
        return range(lower, upper - duration + 1)

    @staticmethod
    def _place(template: ScheduledAction, start: int) -> ScheduledAction:
        duration = DeterministicConstraintSolver._REQUIRED_DURATIONS.get(
            template.action_type, template.end_minute - template.start_minute
        )
        end = start + duration
        effects = tuple(
            replace(
                effect,
                earliest_minute=end + (effect.earliest_minute - template.end_minute),
                latest_minute=end + (effect.latest_minute - template.end_minute),
            )
            for effect in template.effects
        )
        return replace(template, start_minute=start, end_minute=end, effects=effects)

    @staticmethod
    def _partial_constraints(
        state: Mapping[str, Any],
        candidate: ScheduledAction,
        assigned: Mapping[str, ScheduledAction],
    ) -> bool:
        capacities = state.get("resources", {}).get("capacities", {})
        for other in assigned.values():
            overlaps = (
                candidate.start_minute < other.end_minute
                and other.start_minute < candidate.end_minute
            )
            if not overlaps:
                continue
            for resource_id in set(candidate.resource_ids) & set(other.resource_ids):
                capacity = capacities.get(resource_id, {}).get("capacity")
                if capacity == 1:
                    return False
        combined = {**assigned, candidate.action_id: candidate}
        for action in combined.values():
            for predecessor_id in action.dependencies:
                predecessor = combined.get(predecessor_id)
                if predecessor is not None and predecessor.end_minute > action.start_minute:
                    return False
        return True

    def _complete_constraints(
        self, state: Mapping[str, Any], actions: tuple[ScheduledAction, ...]
    ) -> bool:
        by_id = {item.action_id: item for item in actions}
        if any(
            predecessor not in by_id or by_id[predecessor].end_minute > action.start_minute
            for action in actions
            for predecessor in action.dependencies
        ):
            return False
        capacities = state.get("resources", {}).get("capacities", {})
        for resource_id in sorted({item for action in actions for item in action.resource_ids}):
            capacity = capacities.get(resource_id, {}).get("capacity")
            if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
                return False
            boundaries = sorted(
                {point for action in actions if resource_id in action.resource_ids for point in (action.start_minute, action.end_minute)}
            )
            for start, end in zip(boundaries, boundaries[1:]):
                active = sum(
                    action.start_minute < end and start < action.end_minute
                    for action in actions
                    if resource_id in action.resource_ids
                )
                if active > capacity:
                    return False
        for action in actions:
            obligation = next(
                item for item in state["obligations"] if item["obligation_id"] == action.obligation_id
            )
            deadline = utc_minute(obligation["deadline"]["instant"])
            if any(
                effect.earliest_minute != effect.latest_minute
                or effect.latest_minute != action.end_minute
                or effect.latest_minute > deadline
                for effect in action.effects
            ):
                return False
        return self._supervision_holds(state, actions)

    @staticmethod
    def _supervision_holds(
        state: Mapping[str, Any], actions: tuple[ScheduledAction, ...]
    ) -> bool:
        cooking = [
            item for item in actions
            if item.action_type in {"thanksgiving:cook-turkey", "thanksgiving:prepare-sides"}
        ]
        if not cooking:
            return False
        locations = {
            entity_id: value.get("location")
            for entity_id, value in state.get("entities", {}).items()
            if isinstance(value, Mapping)
        }
        movements = sorted(
            (action.end_minute, action.action_id, effect.path[10:-9], effect.value)
            for action in actions
            for effect in action.effects
            if effect.path.startswith("/entities/")
            and effect.path.endswith("/location")
            and isinstance(effect.value, str)
        )
        boundaries = sorted(
            {point for item in cooking for point in (item.start_minute, item.end_minute)}
            | {item[0] for item in movements}
        )
        for start, end in zip(boundaries, boundaries[1:]):
            for minute, _, entity_id, location in movements:
                if minute <= start:
                    locations[entity_id] = location
            if any(item.start_minute < end and start < item.end_minute for item in cooking):
                if "HOME" not in locations.values():
                    return False
        return True

    @staticmethod
    def _problem_hash(
        state: Mapping[str, Any], templates: Sequence[ScheduledAction]
    ) -> str:
        value = {
            "state": state,
            "templates": [
                {
                    "action_id": item.action_id,
                    "action_type": item.action_type,
                    "obligation_id": item.obligation_id,
                    "start_minute": item.start_minute,
                    "end_minute": item.end_minute,
                    "resource_ids": list(item.resource_ids),
                    "dependencies": list(item.dependencies),
                    "effects": [
                        {
                            "path": effect.path,
                            "value": effect.value,
                            "earliest_minute": effect.earliest_minute,
                            "latest_minute": effect.latest_minute,
                        }
                        for effect in item.effects
                    ],
                }
                for item in sorted(templates, key=lambda action: action.action_id)
            ],
        }
        return "sha256:" + hashlib.sha256(
            canonical_json_bytes({"domain": "feasibility-problem-v1", "value": value})
        ).hexdigest()
