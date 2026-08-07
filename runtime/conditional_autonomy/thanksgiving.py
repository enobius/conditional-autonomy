"""Deterministic, hand-authored Thanksgiving micro-environment.

The source scenario is REALM-Bench v2 Table 6 (P6, static).  This module is a
thesis-specific executable encoding, not copied benchmark instance data.  P9's
James flight delay is intentionally absent and belongs to T-16.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .contracts import validate_contract
from .projection import ObservationProjection, project_observation
from .reducer import reduce_event
from .storage import canonical_json_bytes, with_content_hash


ENVIRONMENT_VERSION = "thanksgiving-p6.1.0"
EPISODE_ID = "episode:thanksgiving-p6-static-001"
SOURCE_TIMEZONE = "America/New_York"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def utc_minute(instant: str) -> int:
    """Convert a normalized UTC instant to an integer minute since Unix epoch."""

    if not isinstance(instant, str):
        raise ValueError("environment instant must be a string")
    parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("environment instants must be timezone-aware UTC values")
    delta = parsed.astimezone(timezone.utc) - _EPOCH
    if delta.total_seconds() % 60:
        raise ValueError("environment time must have whole-minute precision")
    return int(delta.total_seconds() // 60)


def normalized_time(minute: int) -> dict[str, Any]:
    """Return the existing normalized-time boundary representation."""

    if not isinstance(minute, int) or isinstance(minute, bool):
        raise TypeError("minute must be an integer")
    instant = (_EPOCH + timedelta(minutes=minute)).isoformat(timespec="seconds")
    return {
        "instant": instant.replace("+00:00", "Z"),
        "source_timezone": SOURCE_TIMEZONE,
        "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
    }


def _boundary_minute(value: object) -> int:
    """Read the approved normalized boundary shape into internal UTC minutes."""

    if not isinstance(value, Mapping) or set(value) != {
        "instant",
        "source_timezone",
        "uncertainty",
    }:
        raise EnvironmentConstraintError("time boundary is not normalized")
    uncertainty = value["uncertainty"]
    if (
        value["source_timezone"] != SOURCE_TIMEZONE
        or not isinstance(uncertainty, Mapping)
        or uncertainty.get("kind") != "EXACT"
        or uncertainty.get("minus_seconds") != 0
        or uncertainty.get("plus_seconds") != 0
    ):
        raise EnvironmentConstraintError("environment boundary time must be exact")
    try:
        return utc_minute(value["instant"])
    except (TypeError, ValueError) as exc:
        raise EnvironmentConstraintError("time boundary has an invalid instant") from exc


DINNER = utc_minute("2026-11-26T23:00:00Z")  # 18:00 America/New_York
JAMES_ARRIVAL = utc_minute("2026-11-26T18:00:00Z")  # 13:00 local
EMILY_ARRIVAL = utc_minute("2026-11-26T19:30:00Z")  # 14:30 local
MICHAEL_ARRIVAL = utc_minute("2026-11-26T20:00:00Z")  # 15:00 local


class Enforceability(str, Enum):
    PREVENTABLE = "PREVENTABLE"
    PREDICTIVE = "PREDICTIVE"
    DETECTABLE = "DETECTABLE"


class Criticality(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


@dataclass(frozen=True)
class Constraint:
    constraint_id: str
    enforceability: Enforceability
    criticality: Criticality
    description: str


@dataclass(frozen=True)
class ConstraintEvaluation:
    constraint: Constraint
    passed: bool
    detail: str


@dataclass(frozen=True)
class PredictedEffect:
    path: str
    value: Any
    earliest_minute: int
    latest_minute: int


@dataclass(frozen=True)
class ScheduledAction:
    action_id: str
    action_type: str
    obligation_id: str
    start_minute: int
    end_minute: int
    resource_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    effects: tuple[PredictedEffect, ...]

    def __post_init__(self) -> None:
        if self.end_minute < self.start_minute:
            raise ValueError(f"action {self.action_id!r} ends before it starts")
        if any(
            effect.earliest_minute > effect.latest_minute for effect in self.effects
        ):
            raise ValueError(f"action {self.action_id!r} has an inverted effect bound")


@dataclass(frozen=True)
class ThanksgivingEpisode:
    initial_state: Mapping[str, Any]
    final_state: Mapping[str, Any]
    observation_projection: ObservationProjection
    actions: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    evaluations: tuple[ConstraintEvaluation, ...]
    outcome: Mapping[str, Any]

    def canonical_summary(self) -> bytes:
        """Return a process-stable summary without exposing mutable aliases."""

        return canonical_json_bytes(
            {
                "initial_state": self.initial_state,
                "final_state": self.final_state,
                "observation": self.observation_projection.observation,
                "actions": self.actions,
                "events": self.events,
                "evaluations": [
                    {
                        "constraint_id": item.constraint.constraint_id,
                        "enforceability": item.constraint.enforceability.value,
                        "criticality": item.constraint.criticality.value,
                        "passed": item.passed,
                        "detail": item.detail,
                    }
                    for item in self.evaluations
                ],
                "outcome": self.outcome,
            }
        )


class EnvironmentConstraintError(RuntimeError):
    """The proposed static schedule violates an environment constraint."""


_CONSTRAINTS = {
    "capacity": Constraint(
        "constraint:resource-capacity",
        Enforceability.PREVENTABLE,
        Criticality.HARD,
        "Half-open reservations never exceed declared resource capacity.",
    ),
    "dependencies": Constraint(
        "constraint:dependencies",
        Enforceability.PREVENTABLE,
        Criticality.HARD,
        "Every dependency completes no later than its dependent action starts.",
    ),
    "windows": Constraint(
        "constraint:time-windows",
        Enforceability.PREVENTABLE,
        Criticality.HARD,
        "Actions remain inside their windows and end by inclusive deadlines.",
    ),
    "durations": Constraint(
        "constraint:exact-duration",
        Enforceability.PREVENTABLE,
        Criticality.HARD,
        "Turkey cooks for 240 minutes and sides prepare for 120 minutes.",
    ),
    "supervision": Constraint(
        "constraint:cooking-supervision",
        Enforceability.PREVENTABLE,
        Criticality.HARD,
        "At least one family member remains home throughout cooking.",
    ),
    "prediction": Constraint(
        "constraint:predicted-completion",
        Enforceability.PREDICTIVE,
        Criticality.HARD,
        "Every deterministic latest effect remains within its obligation deadline.",
    ),
    "precision": Constraint(
        "constraint:prediction-precision",
        Enforceability.PREDICTIVE,
        Criticality.SOFT,
        "The static fixture prefers exact deterministic effect bounds.",
    ),
    "completion": Constraint(
        "constraint:verified-completion",
        Enforceability.DETECTABLE,
        Criticality.HARD,
        "Every required obligation is recorded COMPLETED after execution.",
    ),
    "dinner": Constraint(
        "constraint:dinner-ready",
        Enforceability.DETECTABLE,
        Criticality.HARD,
        "All five family members and both dishes are ready at home by 18:00.",
    ),
}


def _fact(fact_id: str, value: Any) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "value": value,
        "epistemic_status": "OBSERVED",
        "evidence_refs": [],
        "access_class": "POLICY_VISIBLE",
    }


def _obligation(
    obligation_id: str,
    label: str,
    start: int,
    deadline: int,
    dependencies: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "obligation_id": obligation_id,
        "label": label,
        "status": "PENDING",
        "window": {"start": normalized_time(start), "end": normalized_time(deadline)},
        "deadline": normalized_time(deadline),
        "dependency_ids": list(dependencies),
        "access_class": "EVALUATOR_ONLY",
    }


def initial_thanksgiving_state() -> dict[str, Any]:
    """Build the schema-valid, pre-execution state for Table 6."""

    state = {
        "schema_version": "1.0",
        "episode_id": EPISODE_ID,
        "state_version": 0,
        "logical_clock": 0,
        "entities": {
            "person:sarah": {
                "location": "HOME",
                "available_from": normalized_time(utc_minute("2026-11-26T17:00:00Z")),
                "access_class": "EVALUATOR_ONLY",
            },
            "person:james": {
                "location": "IN_FLIGHT",
                "origin": "SF",
                "arrival_location": "BOS",
                "arrival_at": normalized_time(JAMES_ARRIVAL),
                "has_vehicle": False,
                "access_class": "EVALUATOR_ONLY",
            },
            "person:emily": {
                "location": "IN_FLIGHT",
                "origin": "Chicago",
                "arrival_location": "BOS",
                "arrival_at": normalized_time(EMILY_ARRIVAL),
                "requires_pickup": True,
                "access_class": "EVALUATOR_ONLY",
            },
            "person:michael": {
                "location": "EN_ROUTE_HOME",
                "origin": "NY",
                "arrival_at": normalized_time(MICHAEL_ARRIVAL),
                "has_vehicle": True,
                "access_class": "EVALUATOR_ONLY",
            },
            "person:grandma": {
                "location": "GRANDMA_HOME",
                "health_status": "HEALTHY",
                "requires_pickup": True,
                "access_class": "EVALUATOR_ONLY",
            },
        },
        "resources": {
            "capacities": {
                "resource:oven": {"capacity": 1, "access_class": "EVALUATOR_ONLY"},
                "resource:kitchen-workstation": {
                    "capacity": 1,
                    "access_class": "EVALUATOR_ONLY",
                },
                "vehicle:rental-james": {
                    "capacity": 1,
                    "status": "UNAVAILABLE",
                    "location": "BOS",
                    "access_class": "EVALUATOR_ONLY",
                },
            },
            "food": {
                "turkey": {"status": "RAW", "access_class": "EVALUATOR_ONLY"},
                "sides": {
                    "status": "NOT_STARTED",
                    "access_class": "EVALUATOR_ONLY",
                },
            },
            "projection_facts": {
                "dinner_deadline": _fact(
                    "fact:dinner-deadline", normalized_time(DINNER)
                ),
                "cooking_requirements": _fact(
                    "fact:cooking-requirements",
                    {
                        "turkey_minutes": 240,
                        "sides_minutes": 120,
                        "continuous_home_supervision": True,
                    },
                ),
                "travel_times": _fact(
                    "fact:travel-times",
                    {
                        "HOME-BOS": 60,
                        "BOS-GRANDMA_HOME": 60,
                        "HOME-GRANDMA_HOME": 30,
                    },
                ),
            },
        },
        "obligations": [
            _obligation("obligation:james-rental", "James rents a car after landing", JAMES_ARRIVAL, DINNER),
            _obligation(
                "obligation:airport-grandma-pickup",
                "Pick up Emily and Grandma and return home",
                EMILY_ARRIVAL,
                DINNER,
                ("obligation:james-rental",),
            ),
            _obligation("obligation:michael-home", "Michael arrives home", MICHAEL_ARRIVAL, DINNER),
            _obligation(
                "obligation:turkey-ready",
                "Cook turkey for four hours",
                utc_minute("2026-11-26T19:00:00Z"),
                DINNER,
            ),
            _obligation(
                "obligation:sides-ready",
                "Prepare side dishes for two hours",
                utc_minute("2026-11-26T19:00:00Z"),
                DINNER,
            ),
        ],
        "dependencies": [
            {
                "predecessor_id": "obligation:james-rental",
                "successor_id": "obligation:airport-grandma-pickup",
                "access_class": "EVALUATOR_ONLY",
            }
        ],
        "deadlines": [
            {
                "deadline_id": "deadline:dinner",
                "at": normalized_time(DINNER),
                "inclusive": True,
                "access_class": "EVALUATOR_ONLY",
            }
        ],
        "permissions": [],
        "active_plan": {
            "plan_id": "plan:thanksgiving-p6-static",
            "environment_version": ENVIRONMENT_VERSION,
            "access_class": "EVALUATOR_ONLY",
        },
        "completed_actions": [],
        "pending_questions": [],
        "exogenous_events": [],
        "provenance": [],
        "revision_chain": [],
    }
    return validate_contract(state, "canonical-state.schema.json", "Thanksgiving state")


def thanksgiving_actions() -> tuple[ScheduledAction, ...]:
    """Return the fixed feasible P6 schedule; no P9 disruption is included."""

    return (
        ScheduledAction(
            "action:james-land-and-rent",
            "thanksgiving:land-and-rent",
            "obligation:james-rental",
            JAMES_ARRIVAL,
            JAMES_ARRIVAL,
            (),
            (),
            (
                PredictedEffect("/entities/person:james/location", "BOS", JAMES_ARRIVAL, JAMES_ARRIVAL),
                PredictedEffect("/entities/person:james/has_vehicle", True, JAMES_ARRIVAL, JAMES_ARRIVAL),
                PredictedEffect(
                    "/resources/capacities/vehicle:rental-james/status",
                    "AVAILABLE",
                    JAMES_ARRIVAL,
                    JAMES_ARRIVAL,
                ),
            ),
        ),
        ScheduledAction(
            "action:cook-turkey",
            "thanksgiving:cook-turkey",
            "obligation:turkey-ready",
            utc_minute("2026-11-26T19:00:00Z"),
            DINNER,
            ("resource:oven",),
            (),
            (PredictedEffect("/resources/food/turkey/status", "READY", DINNER, DINNER),),
        ),
        ScheduledAction(
            "action:michael-arrive",
            "thanksgiving:arrive-home",
            "obligation:michael-home",
            MICHAEL_ARRIVAL,
            MICHAEL_ARRIVAL,
            (),
            (),
            (PredictedEffect("/entities/person:michael/location", "HOME", MICHAEL_ARRIVAL, MICHAEL_ARRIVAL),),
        ),
        ScheduledAction(
            "action:airport-grandma-pickup",
            "thanksgiving:airport-grandma-pickup",
            "obligation:airport-grandma-pickup",
            EMILY_ARRIVAL,
            utc_minute("2026-11-26T21:00:00Z"),
            ("vehicle:rental-james",),
            ("action:james-land-and-rent",),
            (
                PredictedEffect("/entities/person:james/location", "HOME", utc_minute("2026-11-26T21:00:00Z"), utc_minute("2026-11-26T21:00:00Z")),
                PredictedEffect("/entities/person:emily/location", "HOME", utc_minute("2026-11-26T21:00:00Z"), utc_minute("2026-11-26T21:00:00Z")),
                PredictedEffect("/entities/person:grandma/location", "HOME", utc_minute("2026-11-26T21:00:00Z"), utc_minute("2026-11-26T21:00:00Z")),
                PredictedEffect("/resources/capacities/vehicle:rental-james/location", "HOME", utc_minute("2026-11-26T21:00:00Z"), utc_minute("2026-11-26T21:00:00Z")),
            ),
        ),
        ScheduledAction(
            "action:prepare-sides",
            "thanksgiving:prepare-sides",
            "obligation:sides-ready",
            utc_minute("2026-11-26T21:00:00Z"),
            DINNER,
            ("resource:kitchen-workstation",),
            (),
            (PredictedEffect("/resources/food/sides/status", "READY", DINNER, DINNER),),
        ),
    )


def _obligations_by_id(state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["obligation_id"]: item for item in state["obligations"]}


def _supervision_failures(
    state: Mapping[str, Any], actions: Sequence[ScheduledAction]
) -> list[str]:
    """Check every half-open cooking segment after applying scheduled movements."""

    cooking = [
        action
        for action in actions
        if action.action_type
        in {"thanksgiving:cook-turkey", "thanksgiving:prepare-sides"}
    ]
    if not cooking:
        return ["cooking actions are missing"]
    locations = {
        entity_id: entity["location"]
        for entity_id, entity in state["entities"].items()
        if isinstance(entity, Mapping) and isinstance(entity.get("location"), str)
    }
    movements: list[tuple[int, str, str, str]] = []
    prefix = "/entities/"
    suffix = "/location"
    for action in actions:
        for effect in action.effects:
            if effect.path.startswith(prefix) and effect.path.endswith(suffix):
                entity_id = effect.path[len(prefix) : -len(suffix)]
                if isinstance(effect.value, str):
                    movements.append(
                        (action.end_minute, action.action_id, entity_id, effect.value)
                    )
    movements.sort()
    boundaries = sorted(
        {
            minute
            for action in cooking
            for minute in (action.start_minute, action.end_minute)
        }
        | {minute for minute, _, _, _ in movements}
    )
    failures: list[str] = []
    movement_index = 0
    for start, end in zip(boundaries, boundaries[1:]):
        while movement_index < len(movements) and movements[movement_index][0] <= start:
            _, _, entity_id, location = movements[movement_index]
            locations[entity_id] = location
            movement_index += 1
        cooking_active = any(
            action.start_minute < end and start < action.end_minute
            for action in cooking
        )
        if cooking_active and "HOME" not in locations.values():
            failures.append(f"no family member HOME during [{start},{end})")
    return failures


def evaluate_schedule(
    state: Mapping[str, Any], actions: Sequence[ScheduledAction]
) -> tuple[ConstraintEvaluation, ...]:
    """Evaluate preventable and predictive constraints without side effects."""

    checked = validate_contract(state, "canonical-state.schema.json", "Thanksgiving state")
    obligation_counts = Counter(
        item["obligation_id"] for item in checked["obligations"]
    )
    obligations = _obligations_by_id(checked)
    actions_by_id = {action.action_id: action for action in actions}
    actions_by_obligation: dict[str, list[ScheduledAction]] = {}
    for action in actions:
        actions_by_obligation.setdefault(action.obligation_id, []).append(action)

    capacity_failures: list[str] = []
    capacities = checked["resources"]["capacities"]
    for resource_id in sorted({item for action in actions for item in action.resource_ids}):
        capacity = capacities.get(resource_id, {}).get("capacity")
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            capacity_failures.append(f"{resource_id}: missing positive capacity")
            continue
        boundaries = sorted(
            {
                minute
                for action in actions
                if resource_id in action.resource_ids
                for minute in (action.start_minute, action.end_minute)
            }
        )
        for start, end in zip(boundaries, boundaries[1:]):
            if start == end:
                continue
            active = sum(
                1
                for action in actions
                if resource_id in action.resource_ids
                and action.start_minute < end
                and start < action.end_minute
            )
            if active > capacity:
                capacity_failures.append(f"{resource_id}: {active}>{capacity} at {start}")

    dependency_failures: list[str] = []
    duplicate_action_ids = sorted(
        action_id
        for action_id, count in Counter(action.action_id for action in actions).items()
        if count > 1
    )
    dependency_failures.extend(
        f"duplicate action ID {action_id}" for action_id in duplicate_action_ids
    )
    dependency_failures.extend(
        f"duplicate obligation ID {obligation_id}"
        for obligation_id, count in sorted(obligation_counts.items())
        if count > 1
    )
    root_predecessors: dict[str, set[str]] = {}
    for edge in checked["dependencies"]:
        predecessor_id = edge.get("predecessor_id")
        successor_id = edge.get("successor_id")
        if not isinstance(predecessor_id, str) or not isinstance(successor_id, str):
            dependency_failures.append("malformed state dependency edge")
            continue
        root_predecessors.setdefault(successor_id, set()).add(predecessor_id)
    for obligation_id, obligation in obligations.items():
        declared = obligation.get("dependency_ids")
        if not isinstance(declared, list) or any(
            not isinstance(item, str) for item in declared
        ):
            dependency_failures.append(
                f"{obligation_id}: malformed obligation dependencies"
            )
            continue
        expected_obligations = set(declared)
        if root_predecessors.get(obligation_id, set()) != expected_obligations:
            dependency_failures.append(
                f"{obligation_id}: obligation and state dependencies disagree"
            )
        dependent_actions = actions_by_obligation.get(obligation_id, [])
        if len(dependent_actions) != 1:
            dependency_failures.append(
                f"{obligation_id}: expected exactly one scheduled action"
            )
            continue
        expected_action_ids: set[str] = set()
        for predecessor_obligation_id in expected_obligations:
            predecessor_actions = actions_by_obligation.get(
                predecessor_obligation_id, []
            )
            if len(predecessor_actions) != 1:
                dependency_failures.append(
                    f"{obligation_id}: unresolved predecessor obligation "
                    f"{predecessor_obligation_id}"
                )
                continue
            expected_action_ids.add(predecessor_actions[0].action_id)
        dependent = dependent_actions[0]
        if len(set(dependent.dependencies)) != len(dependent.dependencies):
            dependency_failures.append(
                f"{dependent.action_id}: duplicate action dependency"
            )
        if set(dependent.dependencies) != expected_action_ids:
            dependency_failures.append(
                f"{dependent.action_id}: action dependencies disagree with state"
            )
    for action in actions:
        for predecessor_id in action.dependencies:
            predecessor = actions_by_id.get(predecessor_id)
            if predecessor is None or predecessor.end_minute > action.start_minute:
                dependency_failures.append(
                    f"{action.action_id}: unsatisfied {predecessor_id}"
                )

    window_failures: list[str] = []
    duration_failures: list[str] = []
    prediction_failures: list[str] = []
    for action in actions:
        obligation = obligations.get(action.obligation_id)
        if obligation is None:
            window_failures.append(f"{action.action_id}: missing obligation")
            continue
        window = obligation["window"]
        try:
            window_start = _boundary_minute(window["start"])
            window_end = _boundary_minute(window["end"])
            deadline = _boundary_minute(obligation["deadline"])
        except (KeyError, TypeError, EnvironmentConstraintError) as exc:
            window_failures.append(f"{action.action_id}: malformed time boundary")
            continue
        if action.start_minute < window_start or action.end_minute > window_end:
            window_failures.append(f"{action.action_id}: outside obligation window")
        if action.end_minute > deadline:  # equality is valid: deadlines are inclusive
            window_failures.append(f"{action.action_id}: misses inclusive deadline")
        for effect in action.effects:
            if effect.latest_minute > deadline:
                prediction_failures.append(
                    f"{action.action_id}: predicted effect misses deadline"
                )
            if not (
                effect.earliest_minute
                == effect.latest_minute
                == action.end_minute
            ):
                prediction_failures.append(
                    f"{action.action_id}: effect timing differs from transition time"
                )

    required_durations = {
        "thanksgiving:cook-turkey": 240,
        "thanksgiving:prepare-sides": 120,
    }
    for action_type, required_minutes in required_durations.items():
        matching = [action for action in actions if action.action_type == action_type]
        if len(matching) != 1:
            duration_failures.append(
                f"{action_type}: expected exactly one scheduled action"
            )
        elif matching[0].end_minute - matching[0].start_minute != required_minutes:
            duration_failures.append(
                f"{matching[0].action_id}: duration must be {required_minutes} minutes"
            )

    supervision_failures = _supervision_failures(checked, actions)
    precision_ok = all(
        effect.earliest_minute == effect.latest_minute
        for action in actions
        for effect in action.effects
    )

    def result(key: str, failures: Sequence[str]) -> ConstraintEvaluation:
        return ConstraintEvaluation(
            _CONSTRAINTS[key],
            not failures,
            "PASS" if not failures else "; ".join(failures),
        )

    return (
        result("capacity", capacity_failures),
        result("dependencies", dependency_failures),
        result("windows", window_failures),
        result("durations", duration_failures),
        result("supervision", supervision_failures),
        result("prediction", prediction_failures),
        result("precision", () if precision_ok else ("effect bound is not exact",)),
    )


def _action_proposal(action: ScheduledAction, state_version: int) -> dict[str, Any]:
    proposal = {
        "action_id": action.action_id,
        "plan_id": "plan:thanksgiving-p6-static",
        "actor_id": "actor:environment",
        "state_version": state_version,
        "action_type": action.action_type,
        "arguments": {
            "start_at": normalized_time(action.start_minute),
            "end_at": normalized_time(action.end_minute),
            "resource_ids": list(action.resource_ids),
        },
        "expected_preconditions": [
            {"dependency_action_id": dependency} for dependency in action.dependencies
        ],
        "expected_effects": [
            {
                "path": effect.path,
                "value": deepcopy(effect.value),
                "earliest_at": normalized_time(effect.earliest_minute),
                "latest_at": normalized_time(effect.latest_minute),
            }
            for effect in action.effects
        ],
        "required_capabilities": ["capability:environment-transition"],
        "risk_class": "MODERATE",
        "reversibility": (
            "IRREVERSIBLE"
            if action.action_type
            in {"thanksgiving:cook-turkey", "thanksgiving:prepare-sides"}
            else "REVERSIBLE"
        ),
        "compensation_action": None,
        "postconditions": [{"obligation_id": action.obligation_id, "status": "COMPLETED"}],
        "audit_deadline": None,
        "evidence_refs": [],
        "confidence": 1.0,
        "idempotency_key": f"idem:{action.action_id}",
    }
    return validate_contract(proposal, "action-proposal.schema.json", "Thanksgiving action")


def _transition_event(
    state: Mapping[str, Any], action: ScheduledAction, path: str, value: Any, ordinal: int
) -> dict[str, Any]:
    event_id = f"event:{action.action_id.removeprefix('action:')}:{ordinal}"
    to_version = state["state_version"] + 1
    clock = state["logical_clock"] + 1
    provenance = with_content_hash(
        {
            "provenance_id": f"provenance:{event_id}",
            "source": "ENVIRONMENT",
            "recorded_at": normalized_time(action.end_minute),
            "access_class": "EVALUATOR_ONLY",
        }
    )
    event = {
        "event_id": event_id,
        "episode_id": EPISODE_ID,
        "event_type": "STATE_TRANSITION",
        "logical_clock": clock,
        "timestamp": normalized_time(action.end_minute),
        "source": "ENVIRONMENT",
        "access_class": "EVALUATOR_ONLY",
        "payload": {
            "operation": "SET",
            "path": path,
            "value": deepcopy(value),
            "from_state_version": state["state_version"],
            "to_state_version": to_version,
        },
        "provenance": provenance,
    }
    return with_content_hash(event)


def _completed_obligations(
    state: Mapping[str, Any], obligation_id: str
) -> list[dict[str, Any]]:
    obligations = deepcopy(state["obligations"])
    for obligation in obligations:
        if obligation["obligation_id"] == obligation_id:
            obligation["status"] = "COMPLETED"
            return obligations
    raise EnvironmentConstraintError(f"unknown obligation {obligation_id!r}")


def _detectable_evaluations(state: Mapping[str, Any]) -> tuple[ConstraintEvaluation, ...]:
    obligations_complete = all(
        item["status"] == "COMPLETED" for item in state["obligations"]
    )
    people_home = all(
        state["entities"][person]["location"] == "HOME"
        for person in (
            "person:sarah",
            "person:james",
            "person:emily",
            "person:michael",
            "person:grandma",
        )
    )
    food_ready = all(
        state["resources"]["food"][dish]["status"] == "READY"
        for dish in ("turkey", "sides")
    )
    return (
        ConstraintEvaluation(
            _CONSTRAINTS["completion"],
            obligations_complete,
            "PASS" if obligations_complete else "required obligations remain incomplete",
        ),
        ConstraintEvaluation(
            _CONSTRAINTS["dinner"],
            people_home and food_ready,
            "PASS" if people_home and food_ready else "family or food is not ready",
        ),
    )


def run_thanksgiving_episode() -> ThanksgivingEpisode:
    """Execute the deterministic static P6 episode through ordered T-04 events."""

    initial = initial_thanksgiving_state()
    scheduled = thanksgiving_actions()
    preflight = evaluate_schedule(initial, scheduled)
    failures = [item for item in preflight if not item.passed]
    if failures:
        raise EnvironmentConstraintError(
            "; ".join(f"{item.constraint.constraint_id}: {item.detail}" for item in failures)
        )

    observation = project_observation(
        initial,
        observation_id="observation:thanksgiving-p6-initial",
        actor_id="actor:planner",
        source_paths=(
            "/resources/projection_facts/dinner_deadline",
            "/resources/projection_facts/cooking_requirements",
            "/resources/projection_facts/travel_times",
        ),
        goal_refs=("goal:thanksgiving-dinner",),
        generated_at=normalized_time(utc_minute("2026-11-26T17:00:00Z")),
        context_budget_tokens=2048,
    )

    state: dict[str, Any] = deepcopy(initial)
    proposals: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for action in sorted(
        scheduled, key=lambda item: (item.end_minute, item.start_minute, item.action_id)
    ):
        proposals.append(_action_proposal(action, state["state_version"]))
        ordinal = 0
        for effect in action.effects:
            ordinal += 1
            event = _transition_event(state, action, effect.path, effect.value, ordinal)
            state = reduce_event(state, event)
            events.append(event)
        ordinal += 1
        event = _transition_event(
            state,
            action,
            "/obligations",
            _completed_obligations(state, action.obligation_id),
            ordinal,
        )
        state = reduce_event(state, event)
        events.append(event)
        ordinal += 1
        event = _transition_event(
            state,
            action,
            "/completed_actions",
            [*state["completed_actions"], action.action_id],
            ordinal,
        )
        state = reduce_event(state, event)
        events.append(event)

    detectable = _detectable_evaluations(state)
    evaluations = (*preflight, *detectable)
    passed = sum(item.passed for item in evaluations)
    hard_failures = sum(
        not item.passed and item.constraint.criticality is Criticality.HARD
        for item in evaluations
    )
    outcome = validate_contract(
        {
            "goal_success": all(item.passed for item in detectable),
            "constraint_score": passed / len(evaluations),
            "hard_violation_count": hard_failures,
            "optimality_gap": None,
            "recovery_success": None,
            "execution_cost": 0.0,
            "latency": 0.0,
            "token_count": 0,
            "tool_calls": 0,
            "user_interventions": 0,
            "clarification_total": 0,
            "clarification_necessary": 0,
            "clarification_unnecessary": 0,
            "clarification_insufficient": 0,
            "clarification_repeated": 0,
            "clarification_incorrect_scope": 0,
            "evaluator_disagreement": 0.0,
        },
        "outcome-vector.schema.json",
        "Thanksgiving outcome",
    )
    return ThanksgivingEpisode(
        initial_state=deepcopy(initial),
        final_state=deepcopy(state),
        observation_projection=observation,
        actions=tuple(deepcopy(proposals)),
        events=tuple(deepcopy(events)),
        evaluations=evaluations,
        outcome=deepcopy(outcome),
    )
