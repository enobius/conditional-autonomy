"""Pure reconciliation-phase deferred-invariant validators.

These adapters consume the compact, already-integrated T-10 fixture contexts.
They do not execute tools, mutate canonical state, read clocks, or collapse the
register's phase-specific ESCALATE and REPAIR dispositions into supervisor
decision vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import re
from typing import Any, Callable

from .preexecution import InvariantDisposition, ValidationOutcome, Verdict


RECONCILIATION_FAILURE_RESOLUTIONS = {
    "INV-002": InvariantDisposition.ESCALATE,
    "INV-009": InvariantDisposition.REPAIR,
    "INV-010": InvariantDisposition.ESCALATE,
}


def _pass(invariant_id: str, validator: str) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.PASS, None)


def _fail(
    invariant_id: str, validator: str, *codes: str
) -> ValidationOutcome:
    return ValidationOutcome(
        invariant_id,
        validator,
        Verdict.FAIL,
        RECONCILIATION_FAILURE_RESOLUTIONS[invariant_id],
        tuple(codes),
    )


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
_UTC_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


def _stable_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 160
        and bool(_STABLE_ID.fullmatch(value))
    )


def compensation_current_authority_check(context: object) -> ValidationOutcome:
    """Enforce INV-002 immediately before a compensation recovery begins."""

    invariant, validator = "INV-002", "compensation_current_authority_check"
    root = _mapping(context)
    compensation = _mapping(root.get("compensation")) if root else None
    current = _mapping(root.get("current_context")) if root else None
    if (
        root is None
        or set(root) != {"compensation", "current_context"}
        or compensation is None
        or set(compensation)
        != {"action_id", "required_capabilities", "authorized_state_version"}
        or current is None
        or set(current)
        != {
            "state_version",
            "authorized_action_id",
            "granted_capabilities",
            "preconditions_hold",
        }
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    required = _sequence(compensation.get("required_capabilities"))
    granted = _sequence(current.get("granted_capabilities"))
    if (
        not _stable_id(compensation.get("action_id"))
        or required is None
        or not required
        or not all(_stable_id(item) for item in required)
        or len(set(required)) != len(required)
        or not _integer(compensation.get("authorized_state_version"))
        or not _integer(current.get("state_version"))
        or not _stable_id(current.get("authorized_action_id"))
        or granted is None
        or not all(_stable_id(item) for item in granted)
        or len(set(granted)) != len(granted)
        or not isinstance(current.get("preconditions_hold"), bool)
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    codes: list[str] = []
    if compensation["authorized_state_version"] != current["state_version"]:
        codes.append("STALE_STATE_VERSION")
    if compensation["action_id"] != current["authorized_action_id"]:
        codes.append("STALE_ACTION_AUTHORITY")
    missing = sorted(set(required) - set(granted))
    codes.extend(f"MISSING_CAPABILITY:{capability}" for capability in missing)
    if not current["preconditions_hold"]:
        codes.append("PRECONDITION_FAILED")
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


def _effect_records(
    effects: Sequence[Any], *, require_evidence: bool
) -> tuple[dict[str, bytes], str | None]:
    from .storage import canonical_json_bytes

    records: dict[str, bytes] = {}
    for candidate in effects:
        effect = _mapping(candidate)
        if (
            effect is None
            or not _stable_id(effect.get("effect_id"))
            or (
                require_evidence
                and (
                    not _stable_id(effect.get("evidence_ref"))
                )
            )
            or (not require_evidence and "evidence_ref" in effect)
        ):
            return {}, "MALFORMED_CONTEXT"
        effect_id = effect["effect_id"]
        if effect_id in records:
            return {}, "MALFORMED_CONTEXT"
        identity = dict(effect)
        identity.pop("evidence_ref", None)
        try:
            records[effect_id] = canonical_json_bytes(identity)
        except (TypeError, ValueError):
            return {}, "MALFORMED_CONTEXT"
    return records, None


def verified_effect_check(context: object) -> ValidationOutcome:
    """Enforce INV-009 without promoting or otherwise mutating any fact."""

    invariant, validator = "INV-009", "verified_effect_check"
    root = _mapping(context)
    outcome = _mapping(root.get("tool_outcome")) if root else None
    canonical = _sequence(root.get("canonical_fact_effect_ids")) if root else None
    if (
        root is None
        or set(root) != {"tool_outcome", "canonical_fact_effect_ids"}
        or outcome is None
        or set(outcome) != {"normalized_effects", "verified_effects"}
        or canonical is None
        or not all(_stable_id(item) for item in canonical)
        or len(set(canonical)) != len(canonical)
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    normalized = _sequence(outcome.get("normalized_effects"))
    verified = _sequence(outcome.get("verified_effects"))
    if normalized is None or verified is None:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    normalized_records, normalized_error = _effect_records(
        normalized, require_evidence=False
    )
    verified_records, verified_error = _effect_records(verified, require_evidence=True)
    if normalized_error or verified_error:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    normalized_set = set(normalized_records)
    verified_set = set(verified_records)
    codes: list[str] = []
    orphaned = sorted(verified_set - normalized_set)
    codes.extend(f"VERIFIED_EFFECT_NOT_NORMALIZED:{item}" for item in orphaned)
    contradictory = sorted(
        effect_id
        for effect_id in normalized_set & verified_set
        if normalized_records[effect_id] != verified_records[effect_id]
    )
    codes.extend(
        f"VERIFIED_EFFECT_CONTENT_MISMATCH:{item}" for item in contradictory
    )
    unverified = sorted(set(canonical) - verified_set)
    codes.extend(f"CANONICAL_FACT_UNVERIFIED:{item}" for item in unverified)
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not _UTC_INSTANT.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed


def audit_deadline_check(context: object) -> ValidationOutcome:
    """Enforce INV-010 against supplied clock and independent audit state."""

    invariant, validator = "INV-010", "audit_deadline_check"
    root = _mapping(context)
    audit = _mapping(root.get("audit")) if root else None
    deadline = _instant(root.get("audit_deadline")) if root else None
    observed = _instant(root.get("observed_at")) if root else None
    if (
        root is None
        or set(root) != {"audit_deadline", "observed_at", "audit"}
        or audit is None
        or set(audit) != {"status", "evidence_ref"}
        or deadline is None
        or observed is None
        or audit.get("status") not in {"VERIFIED", "MISSING", "UNVERIFIABLE"}
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    status = audit["status"]
    evidence_ref = audit["evidence_ref"]
    if status == "VERIFIED":
        if not _stable_id(evidence_ref):
            return _fail(invariant, validator, "AUDIT_UNVERIFIABLE")
    elif evidence_ref is not None:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")

    codes: list[str] = []
    if observed > deadline:
        codes.append("AUDIT_DEADLINE_MISSED")
    if status == "MISSING":
        codes.append("AUDIT_MISSING")
    elif status == "UNVERIFIABLE":
        codes.append("AUDIT_UNVERIFIABLE")
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


ReconciliationValidator = Callable[[object], ValidationOutcome]

RECONCILIATION_INVARIANT_VALIDATORS: dict[str, ReconciliationValidator] = {
    "compensation_current_authority_check": compensation_current_authority_check,
    "verified_effect_check": verified_effect_check,
    "audit_deadline_check": audit_deadline_check,
}
