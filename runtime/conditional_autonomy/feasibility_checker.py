"""Independent verification of feasibility witnesses.

The checker does not import the solver.  It reconstructs the proposed schedule,
binds it to the complete input, then delegates semantic evaluation to the
pre-existing T-14 environment constraints.  Release-time checks are repeated
here directly because they are ledger facts introduced outside that evaluator.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from typing import Any

from .feasibility_types import ActionAssignment, FeasibilityWitness
from .storage import canonical_json_bytes
from .thanksgiving import ScheduledAction, evaluate_schedule, utc_minute


@dataclass(frozen=True)
class WitnessCheck:
    accepted: bool
    failures: tuple[str, ...]
    schedule: tuple[ScheduledAction, ...] | None


@dataclass(frozen=True)
class IndependentSearch:
    """Result of the checker's exhaustive decision path."""

    feasible: bool
    witness: FeasibilityWitness | None
    complete_assignments_examined: int


class IndependentWitnessChecker:
    """Validate solver output without invoking or sharing the solver model."""

    def check(
        self,
        state: Mapping[str, Any],
        templates: Sequence[ScheduledAction],
        witness: FeasibilityWitness,
    ) -> WitnessCheck:
        failures: list[str] = []
        template_tuple = tuple(templates)
        template_by_id = {item.action_id: item for item in template_tuple}
        assignment_by_id = {item.action_id: item for item in witness.assignments}
        if len(template_by_id) != len(template_tuple):
            failures.append("problem contains duplicate action IDs")
        if len(assignment_by_id) != len(witness.assignments):
            failures.append("witness contains duplicate action IDs")
        if set(assignment_by_id) != set(template_by_id):
            failures.append("witness action inventory differs from problem")
        actual_version = state.get("active_plan", {}).get("environment_version")
        if witness.environment_version != actual_version:
            failures.append("witness environment version differs from state")
        if witness.problem_hash != self._independent_problem_hash(state, template_tuple):
            failures.append("witness is not bound to the supplied problem")
        if failures:
            return WitnessCheck(False, tuple(failures), None)

        schedule: list[ScheduledAction] = []
        for action_id in sorted(template_by_id):
            template = template_by_id[action_id]
            assignment = assignment_by_id[action_id]
            if assignment.end_minute < assignment.start_minute:
                failures.append(f"{action_id}: negative duration")
                continue
            original_duration = template.end_minute - template.start_minute
            expected_duration = {
                "thanksgiving:cook-turkey": 240,
                "thanksgiving:prepare-sides": 120,
            }.get(template.action_type, original_duration)
            if assignment.end_minute - assignment.start_minute != expected_duration:
                failures.append(f"{action_id}: witness changed action duration")
                continue
            shifted_effects = tuple(
                replace(
                    effect,
                    earliest_minute=assignment.end_minute
                    + effect.earliest_minute
                    - template.end_minute,
                    latest_minute=assignment.end_minute
                    + effect.latest_minute
                    - template.end_minute,
                )
                for effect in template.effects
            )
            schedule.append(
                replace(
                    template,
                    start_minute=assignment.start_minute,
                    end_minute=assignment.end_minute,
                    effects=shifted_effects,
                )
            )
        if failures:
            return WitnessCheck(False, tuple(failures), None)

        checked_schedule = tuple(schedule)
        for evaluation in evaluate_schedule(state, checked_schedule):
            if not evaluation.passed and evaluation.constraint.criticality.value == "HARD":
                failures.append(
                    f"{evaluation.constraint.constraint_id}: {evaluation.detail}"
                )
        self._check_arrival_releases(state, checked_schedule, failures)
        return WitnessCheck(not failures, tuple(failures), checked_schedule)

    def prove_or_find(
        self,
        state: Mapping[str, Any],
        templates: Sequence[ScheduledAction],
    ) -> IndependentSearch:
        """Independently find a checked witness or exhaust the finite domains.

        This is deliberately a second implementation, not a call into the solver.
        It uses independently extracted domains and pruning, and only counts a
        complete assignment as feasible after ``check`` accepts it through T-14.
        """

        template_tuple = tuple(templates)
        if len({item.action_id for item in template_tuple}) != len(template_tuple):
            raise ValueError("problem contains duplicate action IDs")
        raw_obligations = state.get("obligations")
        if not isinstance(raw_obligations, list):
            raise ValueError("state obligations must be a list")
        try:
            obligations = {item["obligation_id"]: item for item in raw_obligations}
        except (KeyError, TypeError) as exc:
            raise ValueError("state obligations are malformed") from exc
        if len(obligations) != len(raw_obligations):
            raise ValueError("state contains duplicate obligation IDs")
        counts = Counter(item.obligation_id for item in template_tuple)
        if set(counts) != set(obligations) or any(value != 1 for value in counts.values()):
            # Missing or repeated fulfillment cannot satisfy the T-14 inventory
            # constraint; there are no scheduling assignments to enumerate.
            return IndependentSearch(False, None, 0)

        domains: dict[str, tuple[ActionAssignment, ...]] = {}
        for template in template_tuple:
            obligation = obligations[template.obligation_id]
            try:
                first = utc_minute(obligation["window"]["start"]["instant"])
                last = min(
                    utc_minute(obligation["window"]["end"]["instant"]),
                    utc_minute(obligation["deadline"]["instant"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("obligation time boundary is malformed") from exc
            duration = {
                "thanksgiving:cook-turkey": 240,
                "thanksgiving:prepare-sides": 120,
            }.get(template.action_type, template.end_minute - template.start_minute)
            if duration < 0:
                raise ValueError("action duration is negative")
            release_entity = {
                "thanksgiving:land-and-rent": "person:james",
                "thanksgiving:arrive-home": "person:michael",
            }.get(template.action_type)
            if release_entity is not None:
                try:
                    first = max(
                        first,
                        utc_minute(
                            state["entities"][release_entity]["arrival_at"]["instant"]
                        ),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("arrival release is malformed") from exc
            domains[template.action_id] = tuple(
                ActionAssignment(template.action_id, start, start + duration)
                for start in range(first, last - duration + 1)
            )
        if any(not values for values in domains.values()):
            return IndependentSearch(False, None, 0)

        templates_by_id = {item.action_id: item for item in template_tuple}
        order = sorted(domains, key=lambda action_id: (len(domains[action_id]), action_id))
        chosen: dict[str, ActionAssignment] = {}
        examined = 0
        problem_hash = self._independent_problem_hash(state, template_tuple)

        def compatible(candidate: ActionAssignment) -> bool:
            template = templates_by_id[candidate.action_id]
            capacities = state.get("resources", {}).get("capacities", {})
            for other_id, other in chosen.items():
                other_template = templates_by_id[other_id]
                overlap = (
                    candidate.start_minute < other.end_minute
                    and other.start_minute < candidate.end_minute
                )
                if overlap:
                    for resource_id in set(template.resource_ids) & set(
                        other_template.resource_ids
                    ):
                        if capacities.get(resource_id, {}).get("capacity") == 1:
                            return False
            together = {**chosen, candidate.action_id: candidate}
            for action_id, assignment in together.items():
                for predecessor_id in templates_by_id[action_id].dependencies:
                    predecessor = together.get(predecessor_id)
                    if (
                        predecessor is not None
                        and predecessor.end_minute > assignment.start_minute
                    ):
                        return False
            return True

        def search(index: int) -> FeasibilityWitness | None:
            nonlocal examined
            if index == len(order):
                examined += 1
                witness = FeasibilityWitness(
                    environment_version=state.get("active_plan", {}).get(
                        "environment_version"
                    ),
                    problem_hash=problem_hash,
                    assignments=tuple(chosen[action_id] for action_id in sorted(chosen)),
                )
                return witness if self.check(state, template_tuple, witness).accepted else None
            action_id = order[index]
            for candidate in domains[action_id]:
                if compatible(candidate):
                    chosen[action_id] = candidate
                    result = search(index + 1)
                    if result is not None:
                        return result
                    del chosen[action_id]
            return None

        witness = search(0)
        return IndependentSearch(witness is not None, witness, examined)

    @staticmethod
    def _check_arrival_releases(
        state: Mapping[str, Any],
        schedule: tuple[ScheduledAction, ...],
        failures: list[str],
    ) -> None:
        entities = state.get("entities", {})
        releases = {
            "thanksgiving:land-and-rent": "person:james",
            "thanksgiving:arrive-home": "person:michael",
        }
        counts = Counter(item.action_type for item in schedule)
        for action_type, entity_id in releases.items():
            if counts[action_type] != 1:
                failures.append(f"{action_type}: expected exactly one action")
                continue
            action = next(item for item in schedule if item.action_type == action_type)
            try:
                release = utc_minute(entities[entity_id]["arrival_at"]["instant"])
            except (KeyError, TypeError, ValueError):
                failures.append(f"{entity_id}: malformed arrival release")
                continue
            if action.start_minute < release:
                failures.append(f"{action.action_id}: starts before ledger arrival")

    @staticmethod
    def _independent_problem_hash(
        state: Mapping[str, Any], templates: Sequence[ScheduledAction]
    ) -> str:
        # Kept local on purpose: checker and solver must bind the same bytes without
        # sharing an executable extraction helper.
        encoded_templates = []
        for item in sorted(templates, key=lambda action: action.action_id):
            encoded_templates.append(
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
            )
        payload = canonical_json_bytes(
            {
                "domain": "feasibility-problem-v1",
                "value": {"state": state, "templates": encoded_templates},
            }
        )
        return "sha256:" + hashlib.sha256(payload).hexdigest()
