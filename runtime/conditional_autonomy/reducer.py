"""Deterministic reduction of schema-valid events into canonical state.

T-04 deliberately exposes one transition operation.  A transition event's
``payload`` is exactly::

    {
        "operation": "SET",
        "path": "/resources/chairs",
        "value": 6,
        "from_state_version": 0,
        "to_state_version": 1
    }

``SET`` replaces an existing object member.  It never creates paths, changes
reducer-owned metadata, or accepts a value equal to the current value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .storage import canonical_content_hash, canonical_json_bytes


class ReducerError(RuntimeError):
    """Base class for fail-closed reducer errors."""


class SchemaValidationError(ContractValidationError, ReducerError):
    """A reducer input or output violates its named runtime contract."""


class IllegalTransitionError(ReducerError):
    """A schema-valid event does not describe a legal state transition."""


_PAYLOAD_FIELDS = frozenset(
    {"operation", "path", "value", "from_state_version", "to_state_version"}
)
_REDUCER_OWNED_FIELDS = frozenset(
    {"schema_version", "episode_id", "state_version", "logical_clock", "revision_chain"}
)


def _validate_reducer_contract(
    instance: object, schema_name: str, description: str
) -> dict[str, Any]:
    """Translate shared contract failures into the established reducer API."""

    try:
        return validate_contract(instance, schema_name, description)
    except ContractValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def _decode_pointer(path: Any) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise IllegalTransitionError("SET path must be a non-root JSON Pointer")
    tokens = path[1:].split("/")
    decoded: list[str] = []
    for token in tokens:
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in "01":
                    raise IllegalTransitionError("SET path contains invalid JSON Pointer escaping")
                index += 2
            else:
                index += 1
        decoded.append(token.replace("~1", "/").replace("~0", "~"))
    if not decoded[0] or decoded[0] in _REDUCER_OWNED_FIELDS:
        raise IllegalTransitionError("SET path targets reducer-owned or invalid state metadata")
    return decoded


def _apply_set(state: dict[str, Any], path: Any, value: Any) -> None:
    tokens = _decode_pointer(path)
    parent: Any = state
    for token in tokens[:-1]:
        if not isinstance(parent, dict) or token not in parent:
            raise IllegalTransitionError(f"SET path does not exist: {path!r}")
        parent = parent[token]
    leaf = tokens[-1]
    if not isinstance(parent, dict) or leaf not in parent:
        raise IllegalTransitionError(f"SET path does not name an existing object member: {path!r}")
    if canonical_json_bytes(parent[leaf]) == canonical_json_bytes(value):
        raise IllegalTransitionError(
            "SET must change the addressed value; no-op transitions are illegal"
        )
    parent[leaf] = deepcopy(value)


def reduce_event(state: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one event without mutating either input."""

    current = _validate_reducer_contract(state, "canonical-state.schema.json", "canonical state")
    checked_event = _validate_reducer_contract(event, "event.schema.json", "event")
    event_id = checked_event["event_id"]

    if checked_event["event_type"] != "STATE_TRANSITION":
        raise IllegalTransitionError(
            f"event {event_id!r} must have event_type 'STATE_TRANSITION'"
        )
    declared_hash = checked_event["content_hash"].removeprefix("sha256:").lower()
    actual_hash = canonical_content_hash(checked_event).removeprefix("sha256:").lower()
    if declared_hash != actual_hash:
        # INV-015 owns ingest and ledger integrity.  This check is defense in
        # depth for callers that submit events directly to the reducer.
        raise IllegalTransitionError(f"event {event_id!r} content_hash is invalid")
    if checked_event["episode_id"] != current["episode_id"]:
        raise IllegalTransitionError(f"event {event_id!r} belongs to a different episode")
    if checked_event["logical_clock"] <= current["logical_clock"]:
        raise IllegalTransitionError(
            f"event {event_id!r} logical clock must be strictly greater than the current clock"
        )

    payload = checked_event["payload"]
    if set(payload) != _PAYLOAD_FIELDS:
        raise IllegalTransitionError(
            f"event {event_id!r} payload must contain exactly {sorted(_PAYLOAD_FIELDS)}"
        )
    if payload["operation"] != "SET":
        raise IllegalTransitionError(f"event {event_id!r} has unsupported operation")
    from_version = payload["from_state_version"]
    to_version = payload["to_state_version"]
    if (
        not isinstance(from_version, int)
        or isinstance(from_version, bool)
        or not isinstance(to_version, int)
        or isinstance(to_version, bool)
    ):
        raise IllegalTransitionError(f"event {event_id!r} state versions must be integers")
    if from_version != current["state_version"]:
        raise IllegalTransitionError(
            f"event {event_id!r} expected state version {from_version}, "
            f"current version is {current['state_version']}"
        )
    if to_version != from_version + 1:
        raise IllegalTransitionError(
            f"event {event_id!r} must advance state_version exactly once"
        )
    if event_id in current["revision_chain"]:
        raise IllegalTransitionError(
            f"event {event_id!r} already appears in the state revision chain"
        )

    successor = deepcopy(current)
    _apply_set(successor, payload["path"], payload["value"])
    successor["state_version"] = to_version
    successor["logical_clock"] = checked_event["logical_clock"]
    successor["revision_chain"].append(event_id)
    try:
        return _validate_reducer_contract(successor, "canonical-state.schema.json", "reduced canonical state")
    except SchemaValidationError as exc:
        raise IllegalTransitionError(f"event {event_id!r} produces invalid state: {exc}") from exc


def replay_events(
    initial_state: Mapping[str, Any], events: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Replay events in their supplied ledger order."""

    state = _validate_reducer_contract(initial_state, "canonical-state.schema.json", "canonical state")
    for event in events:
        state = reduce_event(state, event)
    return state


def canonical_state_bytes(state: Mapping[str, Any]) -> bytes:
    """Validate and serialize a canonical state to deterministic UTF-8 bytes."""

    return canonical_json_bytes(
        _validate_reducer_contract(state, "canonical-state.schema.json", "canonical state")
    )
