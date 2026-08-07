"""Thin named replay-phase adapters for the deferred-invariant register.

The adapters validate the compact invariant-corpus context and delegate all
ordering and transition semantics to the T-07 replay checks and T-04 reducer.
They are pure, deterministic, and fail closed to the register's QUARANTINE
resolution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .preexecution import InvariantDisposition, ValidationOutcome, Verdict
from .reducer import ReducerError, canonical_state_bytes, replay_events
from .replay import (
    ReplayVerificationError,
    validate_episode_trace_order,
    validate_logical_clock_order,
)
from .storage import canonical_json_bytes, with_content_hash


REPLAY_FAILURE_RESOLUTION = InvariantDisposition.QUARANTINE


def _pass(invariant_id: str, validator: str) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.PASS, None)


def _fail(invariant_id: str, validator: str, code: str) -> ValidationOutcome:
    return ValidationOutcome(
        invariant_id,
        validator,
        Verdict.FAIL,
        REPLAY_FAILURE_RESOLUTION,
        (code,),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def logical_clock_order_check(context: object) -> ValidationOutcome:
    """Adapt INV-006 corpus evidence to the T-07 clock-order primitive."""

    invariant, validator = "INV-006", "logical_clock_order_check"
    root = _mapping(context)
    events = _sequence(root.get("events")) if root else None
    if root is None or root.get("concurrency_policy") != "TOTAL_ORDER" or not events:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    checked: list[Mapping[str, Any]] = []
    for candidate in events:
        event = _mapping(candidate)
        if (
            event is None
            or set(event) != {"event_id", "logical_clock"}
            or not isinstance(event.get("event_id"), str)
            or not event.get("event_id")
            or not _integer(event.get("logical_clock"))
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        checked.append(event)
    try:
        validate_logical_clock_order(checked)
    except ReplayVerificationError:
        return _fail(invariant, validator, "LOGICAL_CLOCK_ORDER")
    return _pass(invariant, validator)


def _base_state(version: int, resources: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "episode:invariant-adapter",
        "state_version": version,
        "logical_clock": 0,
        "entities": {},
        "resources": dict(resources or {"adapter_counter": 0}),
        "obligations": [],
        "dependencies": [],
        "deadlines": [],
        "permissions": [],
        "active_plan": None,
        "completed_actions": [],
        "pending_questions": [],
        "exogenous_events": [],
        "provenance": [],
        "revision_chain": [],
    }


def _transition_event(
    event_id: str,
    logical_clock: int,
    from_version: int,
    to_version: int,
    path: str,
    value: object,
) -> dict[str, Any]:
    instant = {
        "instant": "2026-11-26T14:00:00Z",
        "source_timezone": "America/New_York",
        "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
    }
    return with_content_hash(
        {
            "event_id": event_id,
            "episode_id": "episode:invariant-adapter",
            "event_type": "STATE_TRANSITION",
            "logical_clock": logical_clock,
            "timestamp": instant,
            "source": "ENVIRONMENT",
            "access_class": "EVALUATOR_ONLY",
            "payload": {
                "operation": "SET",
                "path": path,
                "value": value,
                "from_state_version": from_version,
                "to_state_version": to_version,
            },
            "provenance": {
                "provenance_id": f"provenance:{event_id}",
                "source": "ENVIRONMENT",
                "recorded_at": instant,
                "access_class": "EVALUATOR_ONLY",
                "content_hash": "sha256:" + "a" * 64,
            },
        }
    )


def state_version_transition_check(context: object) -> ValidationOutcome:
    """Adapt INV-007 transition evidence to complete reducer events."""

    invariant, validator = "INV-007", "state_version_transition_check"
    root = _mapping(context)
    transitions = _sequence(root.get("transitions")) if root else None
    if root is None or set(root) != {"transitions"} or not transitions:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    checked: list[tuple[str, int, int]] = []
    for candidate in transitions:
        item = _mapping(candidate)
        if (
            item is None
            or set(item) != {"event_id", "from_state_version", "to_state_version"}
            or not isinstance(item.get("event_id"), str)
            or not item.get("event_id")
            or not _integer(item.get("from_state_version"))
            or not _integer(item.get("to_state_version"))
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        checked.append((item["event_id"], item["from_state_version"], item["to_state_version"]))
    initial = _base_state(checked[0][1])
    events = [
        _transition_event(event_id, index, from_version, to_version, "/resources/adapter_counter", index)
        for index, (event_id, from_version, to_version) in enumerate(checked, start=1)
    ]
    try:
        replay_events(initial, events)
    except ReducerError:
        return _fail(invariant, validator, "ILLEGAL_STATE_VERSION_TRANSITION")
    return _pass(invariant, validator)


def deterministic_replay_check(context: object) -> ValidationOutcome:
    """Adapt INV-008 compact SET evidence to the deterministic reducer."""

    invariant, validator = "INV-008", "deterministic_replay_check"
    root = _mapping(context)
    initial = _mapping(root.get("initial_state")) if root else None
    ordered = _sequence(root.get("ordered_events")) if root else None
    recorded = _mapping(root.get("recorded_state")) if root else None
    if (
        root is None
        or set(root) != {"initial_state", "ordered_events", "recorded_state"}
        or initial is None
        or recorded is None
        or not ordered
        or set(initial) != {"state_version", "resources"}
        or set(recorded) != {"state_version", "resources"}
        or not _integer(initial.get("state_version"))
        or not _integer(recorded.get("state_version"))
        or not isinstance(initial.get("resources"), Mapping)
        or not isinstance(recorded.get("resources"), Mapping)
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    try:
        # Reject non-JSON leaves and non-finite numbers before constructing
        # complete reducer contracts. This also normalizes circular mappings.
        canonical_json_bytes(root)
    except (TypeError, ValueError):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    events: list[dict[str, Any]] = []
    version = initial["state_version"]
    for index, candidate in enumerate(ordered, start=1):
        event = _mapping(candidate)
        if (
            event is None
            or set(event) != {"event_id", "logical_clock", "operation", "path", "value"}
            or not isinstance(event.get("event_id"), str)
            or not event.get("event_id")
            or not _integer(event.get("logical_clock"))
            or event.get("operation") != "SET"
            or not isinstance(event.get("path"), str)
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        try:
            events.append(
                _transition_event(
                    event["event_id"], event["logical_clock"], version, version + 1,
                    event["path"], event["value"],
                )
            )
        except (TypeError, ValueError):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        version += 1
    try:
        replayed = replay_events(_base_state(initial["state_version"], initial["resources"]), events)
    except (ReducerError, TypeError, ValueError):
        return _fail(invariant, validator, "REPLAY_FAILED")
    observed = {"state_version": replayed["state_version"], "resources": replayed["resources"]}
    try:
        recorded_matches = canonical_json_bytes(observed) == canonical_json_bytes(
            dict(recorded)
        )
    except (TypeError, ValueError):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    if not recorded_matches:
        return _fail(invariant, validator, "RECORDED_STATE_MISMATCH")
    # A second replay is an explicit determinism tripwire, still delegated to T-04.
    try:
        second = replay_events(_base_state(initial["state_version"], initial["resources"]), events)
        deterministic = canonical_state_bytes(replayed) == canonical_state_bytes(second)
    except (ReducerError, TypeError, ValueError):
        return _fail(invariant, validator, "REPLAY_FAILED")
    if not deterministic:
        return _fail(invariant, validator, "NONDETERMINISTIC_REPLAY")
    return _pass(invariant, validator)


def episode_trace_order_check(context: object) -> ValidationOutcome:
    """Adapt INV-016 compact trace evidence to the T-07 sequence primitive."""

    invariant, validator = "INV-016", "episode_trace_order_check"
    root = _mapping(context)
    steps = _sequence(root.get("steps")) if root else None
    episode_id = root.get("episode_id") if root else None
    if (
        root is None
        or set(root) != {"episode_id", "steps"}
        or not isinstance(episode_id, str)
        or not episode_id
        or not steps
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    checked: list[Mapping[str, Any]] = []
    for candidate in steps:
        step = _mapping(candidate)
        if (
            step is None
            or set(step) != {"trace_step_id", "episode_id", "step_index"}
            or not isinstance(step.get("trace_step_id"), str)
            or not step.get("trace_step_id")
            or not isinstance(step.get("episode_id"), str)
            or not step.get("episode_id")
            or not _integer(step.get("step_index"))
            or step["step_index"] < 0
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        checked.append(step)
    try:
        validate_episode_trace_order(episode_id, checked)
    except ReplayVerificationError:
        return _fail(invariant, validator, "EPISODE_TRACE_ORDER")
    return _pass(invariant, validator)


REPLAY_INVARIANT_VALIDATORS: Mapping[str, Callable[[object], ValidationOutcome]] = {
    "logical_clock_order_check": logical_clock_order_check,
    "state_version_transition_check": state_version_transition_check,
    "deterministic_replay_check": deterministic_replay_check,
    "episode_trace_order_check": episode_trace_order_check,
}
