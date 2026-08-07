"""Pure pre-execution invariant checks and deterministic reconciliation.

The three validators implement only the pre-execution slice of the deferred-
invariant register. They return immutable outcomes and never perform I/O or
mutate their inputs. ``reconcile_decision`` encodes Specification section 3.1.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .storage import canonical_json_bytes


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Resolution(str, Enum):
    APPROVE = "APPROVE"
    REPAIR = "REPAIR"
    QUERY = "QUERY"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class InvariantDisposition(str, Enum):
    """Registered failure behavior, separate from supervisor decisions."""

    REJECT = "REJECT"
    REPAIR = "REPAIR"
    ESCALATE = "ESCALATE"
    QUARANTINE = "QUARANTINE"


class ValidatorStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class Criticality(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


@dataclass(frozen=True)
class ValidationOutcome:
    """A registered invariant verdict with no implicit failure behavior."""

    invariant_id: str
    validator: str
    verdict: Verdict
    failure_resolution: InvariantDisposition | None
    failure_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict is Verdict.PASS:
            if self.failure_resolution is not None or self.failure_codes:
                raise ValueError("PASS cannot carry failure metadata")
        elif (
            not isinstance(self.failure_resolution, InvariantDisposition)
            or not self.failure_codes
        ):
            raise ValueError("FAIL requires an invariant disposition and failure code")

    @property
    def succeeded(self) -> bool:
        return self.verdict is Verdict.PASS


@dataclass(frozen=True, init=False)
class ReconciliationEvidence:
    """Immutable evidence derived from one complete validator result."""

    _canonical_bytes: bytes = field(repr=False)
    _criticality: Criticality
    _status: ValidatorStatus
    _permitted_resolution: str

    def __init__(self, validator_result: object) -> None:
        if (
            isinstance(validator_result, Mapping)
            and isinstance(
                validator_result.get("permitted_resolution"), InvariantDisposition
            )
        ):
            raise ValueError(
                "validator-result permitted_resolution cannot be an invariant disposition"
            )
        try:
            checked = validate_contract(
                validator_result,
                "validator-result.schema.json",
                "validator result",
            )
        except ContractValidationError as exc:
            raise ValueError(str(exc)) from exc
        object.__setattr__(self, "_canonical_bytes", canonical_json_bytes(checked))
        object.__setattr__(self, "_criticality", Criticality(checked["criticality"]))
        object.__setattr__(self, "_status", ValidatorStatus(checked["status"]))
        object.__setattr__(self, "_permitted_resolution", checked["permitted_resolution"])

    @property
    def validator_result(self) -> dict[str, Any]:
        """Return a detached copy of the complete validated contract."""

        return json.loads(self._canonical_bytes)

    @property
    def criticality(self) -> Criticality:
        return self._criticality

    @property
    def status(self) -> ValidatorStatus:
        return self._status

    @property
    def permitted_resolution(self) -> str:
        return self._permitted_resolution

    @classmethod
    def from_validator_result(cls, result: object) -> ReconciliationEvidence:
        """Project the policy fields from a validator-result-shaped mapping."""

        return cls(result)  # type: ignore[arg-type]


def _pass(invariant_id: str, validator: str) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.PASS, None)


def _fail(
    invariant_id: str,
    validator: str,
    disposition: InvariantDisposition,
    *codes: str,
) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.FAIL, disposition, tuple(codes))


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def compensation_prevalidation_check(context: object) -> ValidationOutcome:
    """Enforce INV-001 for COMPENSATABLE actions."""

    invariant, validator = "INV-001", "compensation_prevalidation_check"
    root = _mapping(context)
    action = _mapping(root.get("action")) if root else None
    authorization = _mapping(root.get("authorization")) if root else None
    records = _sequence(root.get("prevalidations")) if root else None
    if action is None or authorization is None or records is None:
        return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")
    reversibility = action.get("reversibility")
    if reversibility not in {"REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE"}:
        return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")
    if reversibility != "COMPENSATABLE":
        return _pass(invariant, validator)

    compensation_action = _mapping(action.get("compensation_action"))
    prevalidation_id = (
        compensation_action.get("prevalidation_id")
        if compensation_action is not None
        else None
    )
    action_id = action.get("action_id")
    authorized_at = authorization.get("authorized_at_logical_clock")
    required_capabilities = (
        _sequence(compensation_action.get("required_capabilities"))
        if compensation_action is not None
        else None
    )
    if (
        "compensation_prevalidation_id" in action
        or not isinstance(action_id, str) or not action_id
        or not isinstance(prevalidation_id, str) or not prevalidation_id
        or not _integer(authorized_at)
        or compensation_action is None
        or not isinstance(compensation_action.get("action_type"), str)
        or not compensation_action.get("action_type")
        or not isinstance(compensation_action.get("arguments"), Mapping)
        or required_capabilities is None or not required_capabilities
        or not all(isinstance(item, str) and item for item in required_capabilities)
        or len(set(required_capabilities)) != len(required_capabilities)
    ):
        return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")

    normalized_records: list[tuple[str, str, str, int]] = []
    for candidate in records:
        record = _mapping(candidate)
        if (
            record is None
            or not isinstance(record.get("prevalidation_id"), str)
            or not isinstance(record.get("action_id"), str)
            or record.get("status") not in {"PASS", "FAIL", "UNKNOWN"}
            or not _integer(record.get("logical_clock"))
        ):
            return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")
        normalized_records.append(
            (
                record["prevalidation_id"],
                record["action_id"],
                record["status"],
                record["logical_clock"],
            )
        )

    matched = False
    for record_id, record_action_id, status, clock in normalized_records:
        if record_id == prevalidation_id and record_action_id == action_id:
            matched = True
            if status == "PASS" and clock < authorized_at:
                return _pass(invariant, validator)
    code = "PREVALIDATION_NOT_BEFORE_AUTHORIZATION" if matched else "PREVALIDATION_NOT_FOUND"
    return _fail(invariant, validator, InvariantDisposition.REJECT, code)


def current_version_check(context: object) -> ValidationOutcome:
    """Enforce INV-004 across authorization and current executable state."""

    invariant, validator = "INV-004", "current_version_check"
    root = _mapping(context)
    authorization = _mapping(root.get("authorization")) if root else None
    current = _mapping(root.get("current")) if root else None
    if authorization is None or current is None:
        return _fail(invariant, validator, InvariantDisposition.REPAIR, "MALFORMED_CONTEXT")
    fields = ("state_version", "plan_id", "plan_version")
    if any(field not in authorization or field not in current for field in fields):
        return _fail(invariant, validator, InvariantDisposition.REPAIR, "MALFORMED_CONTEXT")
    for source in (authorization, current):
        if (
            not _integer(source["state_version"])
            or not isinstance(source["plan_id"], str) or not source["plan_id"]
            or not _integer(source["plan_version"])
        ):
            return _fail(invariant, validator, InvariantDisposition.REPAIR, "MALFORMED_CONTEXT")
    mismatches = tuple(
        f"STALE_{field.upper()}" for field in fields if authorization[field] != current[field]
    )
    if mismatches:
        return _fail(invariant, validator, InvariantDisposition.REPAIR, *mismatches)
    return _pass(invariant, validator)


def adapter_compatibility_check(context: object) -> ValidationOutcome:
    """Enforce INV-012 for model hash, target modules, and runtime version."""

    invariant, validator = "INV-012", "adapter_compatibility_check"
    root = _mapping(context)
    adapter = _mapping(root.get("adapter")) if root else None
    runtime = _mapping(root.get("runtime")) if root else None
    if adapter is None or runtime is None:
        return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")
    targets = _sequence(adapter.get("target_modules"))
    available = _sequence(runtime.get("available_modules"))
    incompatibilities = _sequence(adapter.get("incompatibilities"))
    required_strings = (
        adapter.get("base_model_hash"), runtime.get("base_model_hash"),
        runtime.get("runtime_version"),
    )
    if (
        targets is None or not targets or available is None or incompatibilities is None
        or not all(isinstance(value, str) and value for value in required_strings)
        or not all(isinstance(value, str) and value for value in (*targets, *available, *incompatibilities))
    ):
        return _fail(invariant, validator, InvariantDisposition.REJECT, "MALFORMED_CONTEXT")
    failures: list[str] = []
    if adapter["base_model_hash"] != runtime["base_model_hash"]:
        failures.append("BASE_MODEL_HASH_MISMATCH")
    if not set(targets).issubset(set(available)):
        failures.append("TARGET_MODULE_UNAVAILABLE")
    if runtime["runtime_version"] in incompatibilities:
        failures.append("RUNTIME_INCOMPATIBLE")
    if failures:
        return _fail(invariant, validator, InvariantDisposition.REJECT, *failures)
    return _pass(invariant, validator)


def reconcile_decision(
    supervisor_decision: Resolution | str,
    evidence: ReconciliationEvidence,
    *,
    soft_risk_below_ceiling: bool | None = None,
) -> Resolution:
    """Resolve supervisor recommendation and evidence without silent coercion."""

    if not isinstance(evidence, ReconciliationEvidence):
        raise ValueError("reconciliation requires a complete schema-valid validator result")
    if isinstance(supervisor_decision, InvariantDisposition):
        raise ValueError("unknown supervisor decision")
    try:
        supervisor = Resolution(supervisor_decision)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown supervisor decision") from exc
    if supervisor is Resolution.REJECT:
        return Resolution.REJECT
    if supervisor is Resolution.ESCALATE:
        return Resolution.ESCALATE
    if supervisor is Resolution.QUERY:
        return Resolution.QUERY
    if supervisor is Resolution.REPAIR:
        if evidence.permitted_resolution == "REJECT":
            return Resolution.REJECT
        if evidence.permitted_resolution == "ESCALATE":
            return Resolution.ESCALATE
        return Resolution.REPAIR
    if evidence.status is ValidatorStatus.PASS:
        return Resolution.APPROVE
    if evidence.criticality is Criticality.HARD:
        hard_resolutions = {
            "REPAIR": Resolution.REPAIR, "REJECT": Resolution.REJECT,
            "QUERY": Resolution.QUERY, "ESCALATE": Resolution.ESCALATE,
        }
        try:
            return hard_resolutions[evidence.permitted_resolution]
        except KeyError as exc:
            raise ValueError("HARD FAIL/UNKNOWN evidence cannot permit execution") from exc
    if soft_risk_below_ceiling is None:
        raise ValueError("SOFT FAIL/UNKNOWN requires an explicit residual-risk decision")
    if not isinstance(soft_risk_below_ceiling, bool):
        raise ValueError("soft_risk_below_ceiling must be boolean")
    if not soft_risk_below_ceiling:
        return Resolution.ESCALATE
    soft_resolutions = {
        "EXECUTE": Resolution.APPROVE, "REPAIR": Resolution.REPAIR,
        "QUERY": Resolution.QUERY, "REJECT": Resolution.REJECT,
        "ESCALATE": Resolution.ESCALATE,
    }
    return soft_resolutions[evidence.permitted_resolution]
