"""Pure promotion-phase deferred-invariant validators.

The adapters consume the compact evidence contexts registered for INV-011 and
INV-013.  They are deterministic, do not mutate their inputs, and fail closed
to the register's QUARANTINE disposition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, Callable

from .preexecution import InvariantDisposition, ValidationOutcome, Verdict


PROMOTION_FAILURE_RESOLUTIONS = {
    "INV-011": InvariantDisposition.QUARANTINE,
    "INV-013": InvariantDisposition.QUARANTINE,
}

PROHIBITED_SPLIT_DIMENSIONS = frozenset(
    {
        "seed",
        "template_family",
        "constraint_graph_hash",
        "disruption_composition_hash",
    }
)
# A tuple keeps deterministic reporting order distinct from the public set used
# to verify that fixture evidence declares the complete promotion policy.
PROMOTION_DIMENSIONS = tuple(sorted(PROHIBITED_SPLIT_DIMENSIONS))

_SPLITS = frozenset(
    {"TRAIN", "DEVELOPMENT", "TEST", "TRANSFER", "PROTECTED_REGRESSION"}
)
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")


def _pass(invariant_id: str, validator: str) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.PASS, None)


def _fail(
    invariant_id: str, validator: str, *codes: str
) -> ValidationOutcome:
    return ValidationOutcome(
        invariant_id,
        validator,
        Verdict.FAIL,
        PROMOTION_FAILURE_RESOLUTIONS[invariant_id],
        tuple(codes),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _stable_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 160
        and bool(_STABLE_ID.fullmatch(value))
    )


def clarification_counter_reconciliation(context: object) -> ValidationOutcome:
    """Reconcile recorded clarification totals with classified trace events."""

    invariant, validator = "INV-011", "clarification_counter_reconciliation"
    root = _mapping(context)
    events = _sequence(root.get("classified_events")) if root else None
    counters = _mapping(root.get("recorded_counters")) if root else None
    if (
        root is None
        or set(root) != {"classified_events", "recorded_counters"}
        or events is None
        or counters is None
        or set(counters) != {"queries", "user_responses"}
        or not _nonnegative_integer(counters.get("queries"))
        or not _nonnegative_integer(counters.get("user_responses"))
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    observed = {"QUERY": 0, "USER_RESPONSE": 0}
    event_ids: set[str] = set()
    for candidate in events:
        event = _mapping(candidate)
        if (
            event is None
            or set(event) != {"event_id", "classification"}
            or not _stable_id(event.get("event_id"))
            or not _stable_id(event.get("classification"))
            or event["event_id"] in event_ids
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        event_ids.add(event["event_id"])
        if event["classification"] in observed:
            observed[event["classification"]] += 1

    codes: list[str] = []
    if counters["queries"] != observed["QUERY"]:
        codes.append("QUERY_COUNT_MISMATCH")
    if counters["user_responses"] != observed["USER_RESPONSE"]:
        codes.append("USER_RESPONSE_COUNT_MISMATCH")
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


def split_leakage_check(context: object) -> ValidationOutcome:
    """Reject prohibited values reused by manifests assigned to different splits."""

    invariant, validator = "INV-013", "split_leakage_check"
    root = _mapping(context)
    dimensions = _sequence(root.get("prohibited_dimensions")) if root else None
    manifests = _sequence(root.get("manifests")) if root else None
    if (
        root is None
        or set(root) != {"prohibited_dimensions", "manifests"}
        or dimensions is None
        or manifests is None
        or not manifests
        or not all(isinstance(item, str) for item in dimensions)
        or len(dimensions) != len(set(dimensions))
        or set(dimensions) != PROHIBITED_SPLIT_DIMENSIONS
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    manifest_fields = {"instance_id", "split", *PROHIBITED_SPLIT_DIMENSIONS}
    instance_ids: set[str] = set()
    values_by_dimension: dict[str, dict[object, set[str]]] = {
        dimension: {} for dimension in sorted(PROHIBITED_SPLIT_DIMENSIONS)
    }
    for candidate in manifests:
        manifest = _mapping(candidate)
        if manifest is None or set(manifest) != manifest_fields:
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        instance_id = manifest.get("instance_id")
        split = manifest.get("split")
        seed = manifest.get("seed")
        if (
            not _stable_id(instance_id)
            or instance_id in instance_ids
            or not isinstance(split, str)
            or split not in _SPLITS
            or not isinstance(seed, int)
            or isinstance(seed, bool)
            or not all(
                _stable_id(manifest.get(dimension))
                for dimension in PROHIBITED_SPLIT_DIMENSIONS - {"seed"}
            )
        ):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        instance_ids.add(instance_id)
        for dimension in PROHIBITED_SPLIT_DIMENSIONS:
            value = manifest[dimension]
            values_by_dimension[dimension].setdefault(value, set()).add(split)

    codes = [
        f"CROSS_SPLIT_REUSE:{dimension}"
        for dimension in sorted(PROMOTION_DIMENSIONS)
        if any(
            len(splits) > 1
            for splits in values_by_dimension[dimension].values()
        )
    ]
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)

PromotionValidator = Callable[[object], ValidationOutcome]

PROMOTION_INVARIANT_VALIDATORS: dict[str, PromotionValidator] = {
    "clarification_counter_reconciliation": clarification_counter_reconciliation,
    "split_leakage_check": split_leakage_check,
}
