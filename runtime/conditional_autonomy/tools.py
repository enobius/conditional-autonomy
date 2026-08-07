"""Capability-gated deterministic tool execution.

Every adapter invocation enters through :class:`ToolSurface`, validates the
pinned contracts, and passes the complete validator evidence through T-09's
reconciliation function.  Adapters are deliberately small and cannot mutate
canonical state directly; they return effects for later verification and
reduction by the owning runtime phase.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from threading import Lock
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .preexecution import (
    ReconciliationEvidence,
    Resolution,
    compensation_prevalidation_check,
    reconcile_decision,
)
from .storage import canonical_json_bytes


class ToolSurfaceError(RuntimeError):
    """A tool registration or execution request is malformed."""


ToolExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ToolVerifier = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]
]


REQUIRED_EXTERNAL_VALIDATORS = frozenset(
    {"current_version_check", "adapter_compatibility_check"}
)


def _adapter_contract_probe(
    tool_id: object,
    tool_version: object,
    action_types: object,
    required_capabilities: object,
) -> None:
    """Reuse pinned schemas to validate every adapter-facing identifier."""

    outcome_probe = {
        "outcome_id": "outcome:adapter-probe", "action_id": "action:adapter-probe",
        "tool_id": tool_id, "tool_version": tool_version, "status": "PENDING",
        "started_at": {"instant": "2026-01-01T00:00:00Z", "source_timezone": "UTC", "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0}},
        "completed_at": {"instant": "2026-01-01T00:00:00Z", "source_timezone": "UTC", "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0}},
        "raw_result_ref": {"ref_id": "evidence:adapter-probe", "source": "TOOL", "access_class": "EVALUATOR_ONLY", "uri": None, "content_hash": None},
        "normalized_effects": [], "verified_effects": [], "state_version_before": 0,
        "state_version_after": None, "error_code": None, "idempotency_key": "idem:adapter-probe",
    }
    validate_contract(outcome_probe, "tool-outcome.schema.json", "tool adapter")
    for index, action_type in enumerate(action_types):
        action_probe = {
            "action_id": f"action:adapter-probe:{index}", "plan_id": "plan:adapter-probe",
            "actor_id": "actor:adapter-probe", "state_version": 0,
            "action_type": action_type, "arguments": {}, "expected_preconditions": [],
            "expected_effects": [], "required_capabilities": list(required_capabilities),
            "risk_class": "LOW", "reversibility": "REVERSIBLE",
            "compensation_action": None, "postconditions": [], "audit_deadline": None,
            "evidence_refs": [], "confidence": 1.0,
            "idempotency_key": f"idem:adapter-probe:{index}",
        }
        validate_contract(action_probe, "action-proposal.schema.json", "tool adapter scope")


@dataclass(frozen=True)
class ToolAdapter:
    """One deterministic adapter and the action types it owns."""

    tool_id: str
    tool_version: str
    action_types: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    execute: ToolExecutor
    verify: ToolVerifier

    def __post_init__(self) -> None:
        if not self.tool_id or not self.tool_version:
            raise ValueError("tool ID and version must be non-empty")
        if (
            not isinstance(self.action_types, tuple)
            or not self.action_types
            or not all(isinstance(item, str) and item for item in self.action_types)
            or len(set(self.action_types)) != len(self.action_types)
        ):
            raise ValueError("tool action types must be non-empty strings")
        if (
            not isinstance(self.required_capabilities, tuple)
            or not self.required_capabilities
            or not all(
                isinstance(item, str) and item for item in self.required_capabilities
            )
            or len(set(self.required_capabilities)) != len(self.required_capabilities)
        ):
            raise ValueError("tool required capabilities must be non-empty and unique")
        if not callable(self.execute) or not callable(self.verify):
            raise ValueError("tool execute and verify hooks must be callable")
        try:
            _adapter_contract_probe(
                self.tool_id, self.tool_version, self.action_types,
                self.required_capabilities,
            )
        except ContractValidationError as exc:
            raise ValueError(str(exc)) from exc


@dataclass(frozen=True, init=False)
class Authorization:
    """Detached result of the mandatory pre-execution gate."""

    resolution: Resolution
    _action_bytes: bytes
    _decision_bytes: bytes
    _results_bytes: bytes

    def __init__(self, resolution: Resolution, action: object, decision: object, results: object) -> None:
        object.__setattr__(self, "resolution", resolution)
        object.__setattr__(self, "_action_bytes", canonical_json_bytes(action))
        object.__setattr__(self, "_decision_bytes", canonical_json_bytes(decision))
        object.__setattr__(self, "_results_bytes", canonical_json_bytes(results))

    @property
    def action(self) -> dict[str, Any]:
        return json.loads(self._action_bytes)

    @property
    def supervisor_decision(self) -> dict[str, Any]:
        return json.loads(self._decision_bytes)

    @property
    def validator_results(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(self._results_bytes))


@dataclass(frozen=True, init=False)
class ToolExecution:
    """A gated attempt; non-approved attempts never contain a tool outcome."""

    authorization: Authorization
    _outcome_bytes: bytes | None

    def __init__(self, authorization: Authorization, outcome: object | None) -> None:
        object.__setattr__(self, "authorization", authorization)
        object.__setattr__(
            self, "_outcome_bytes",
            None if outcome is None else canonical_json_bytes(outcome),
        )

    @property
    def outcome(self) -> dict[str, Any] | None:
        return None if self._outcome_bytes is None else json.loads(self._outcome_bytes)

    @property
    def executed(self) -> bool:
        return self.outcome is not None


_RESOLUTION_PRIORITY = {
    Resolution.APPROVE: 0,
    Resolution.REPAIR: 1,
    Resolution.QUERY: 2,
    Resolution.REJECT: 3,
    Resolution.ESCALATE: 4,
}


def _checked_time(value: object, description: str) -> dict[str, Any]:
    """Validate normalized time through an existing schema-bearing contract."""

    probe = {
        "outcome_id": "outcome:time-probe",
        "action_id": "action:time-probe",
        "tool_id": "tool:time-probe",
        "tool_version": "1.0",
        "status": "PENDING",
        "started_at": value,
        "completed_at": value,
        "raw_result_ref": {
            "ref_id": "evidence:time-probe",
            "source": "TOOL",
            "access_class": "EVALUATOR_ONLY",
            "uri": None,
            "content_hash": None,
        },
        "normalized_effects": [],
        "verified_effects": [],
        "state_version_before": 0,
        "state_version_after": None,
        "error_code": None,
        "idempotency_key": "idem:time-probe",
    }
    try:
        return validate_contract(probe, "tool-outcome.schema.json", description)[
            "started_at"
        ]
    except ContractValidationError as exc:
        raise ToolSurfaceError(str(exc)) from exc


def _instant(value: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(value["instant"].replace("Z", "+00:00"))


class ToolSurface:
    """The sole capability-aware dispatch boundary for registered adapters."""

    def __init__(
        self,
        adapters: Sequence[ToolAdapter],
        *,
        granted_capabilities: Sequence[str],
    ) -> None:
        capabilities = tuple(granted_capabilities)
        if (
            not all(isinstance(item, str) and item for item in capabilities)
            or len(set(capabilities)) != len(capabilities)
        ):
            raise ValueError("granted capabilities must be unique non-empty strings")
        by_action: dict[str, ToolAdapter] = {}
        for adapter in adapters:
            if not isinstance(adapter, ToolAdapter):
                raise ValueError("adapters must be ToolAdapter instances")
            for action_type in adapter.action_types:
                if action_type in by_action:
                    raise ValueError(f"duplicate tool action type {action_type!r}")
                by_action[action_type] = adapter
        self._adapters = by_action
        self._granted_capabilities = frozenset(capabilities)
        self._dispatch_count = 0
        self._claim_lock = Lock()
        self._claims: dict[str, tuple[bytes, str, ToolExecution | None]] = {}

    @property
    def dispatch_count(self) -> int:
        with self._claim_lock:
            return self._dispatch_count

    def _capability_result(
        self,
        action: Mapping[str, Any],
        timestamp: Mapping[str, Any],
        pinned_adapter_version: str | None,
    ) -> dict[str, Any]:
        adapter = self._adapters.get(action["action_type"])
        declared = set(action["required_capabilities"])
        adapter_required = set(adapter.required_capabilities) if adapter else set()
        underdeclared = sorted(adapter_required - declared)
        required = declared | adapter_required
        missing = sorted(required - self._granted_capabilities)
        failures = []
        if adapter is None:
            failures.append("NO_REGISTERED_TOOL")
        elif (
            pinned_adapter_version is not None
            and pinned_adapter_version != adapter.tool_version
        ):
            failures.append("ADAPTER_VERSION_MISMATCH")
        failures.extend(f"UNDERDECLARED:{item}" for item in underdeclared)
        failures.extend(f"MISSING:{item}" for item in missing)
        result = {
            "validator_id": "validator:tool-capability",
            "validator_version": "1.0",
            "status": "FAIL" if failures else "PASS",
            "criticality": "HARD",
            "enforceability": "PREVENTABLE",
            "constraint_ids": ["constraint:tool-capability"],
            "evidence_refs": [],
            "observed_state_version": action["state_version"],
            "uncertainty_reason": None,
            "permitted_resolution": "REJECT" if failures else "EXECUTE",
            "explanation_code": (
                "TOOL_CAPABILITY_DENIED" if failures else "CAPABILITY_GRANTED"
            ),
            "repair_hints": (
                [f"Correct tool capability requirement {item}." for item in failures]
                if failures
                else []
            ),
            "timestamp": deepcopy(timestamp),
        }
        return validate_contract(
            result, "validator-result.schema.json", "capability validator result"
        )

    @staticmethod
    def _version_result(
        action: Mapping[str, Any], current_state_version: int, timestamp: Mapping[str, Any]
    ) -> dict[str, Any]:
        current = (
            isinstance(current_state_version, int)
            and not isinstance(current_state_version, bool)
            and current_state_version >= 0
        )
        matches = current and action["state_version"] == current_state_version
        result = {
            "validator_id": "validator:tool-current-version",
            "validator_version": "1.0",
            "status": "PASS" if matches else "FAIL",
            "criticality": "HARD",
            "enforceability": "PREVENTABLE",
            "constraint_ids": ["constraint:tool-current-version"],
            "evidence_refs": [],
            "observed_state_version": max(current_state_version, 0) if current else 0,
            "uncertainty_reason": None,
            "permitted_resolution": "EXECUTE" if matches else "REPAIR",
            "explanation_code": "VERSION_CURRENT" if matches else "STALE_STATE_VERSION",
            "repair_hints": [] if matches else ["Replan against the current state version."],
            "timestamp": deepcopy(timestamp),
        }
        return validate_contract(result, "validator-result.schema.json", "version result")

    @staticmethod
    def _prevalidation_result(
        action: Mapping[str, Any], context: object, timestamp: Mapping[str, Any]
    ) -> dict[str, Any]:
        bound = isinstance(context, Mapping)
        context_action = context.get("action") if bound else None
        authorization = context.get("authorization") if bound else None
        try:
            bound = (
                bound
                and isinstance(context_action, Mapping)
                and canonical_json_bytes(context_action) == canonical_json_bytes(action)
                and isinstance(authorization, Mapping)
                and authorization.get("state_version") == action["state_version"]
                and authorization.get("plan_id") == action["plan_id"]
            )
        except (TypeError, ValueError):
            bound = False
        outcome = compensation_prevalidation_check(context) if bound else None
        passed = bound and outcome is not None and outcome.succeeded
        result = {
            "validator_id": "validator:compensation-prevalidation",
            "validator_version": "1.0",
            "status": "PASS" if passed else "FAIL",
            "criticality": "HARD",
            "enforceability": "PREVENTABLE",
            "constraint_ids": ["constraint:compensation-prevalidation"],
            "evidence_refs": [],
            "observed_state_version": action["state_version"],
            "uncertainty_reason": None,
            "permitted_resolution": "EXECUTE" if passed else "REJECT",
            "explanation_code": (
                "COMPENSATION_PREVALIDATED"
                if passed
                else "COMPENSATION_PREVALIDATION_FAILED"
            ),
            "repair_hints": (
                []
                if passed
                else list(outcome.failure_codes)
                if outcome is not None
                else ["PREVALIDATION_CONTEXT_NOT_BOUND_TO_ACTION"]
            ),
            "timestamp": deepcopy(timestamp),
        }
        return validate_contract(
            result, "validator-result.schema.json", "compensation prevalidation result"
        )

    @staticmethod
    def _external_evidence(
        action: Mapping[str, Any], validator_results: Sequence[object]
    ) -> tuple[list[ReconciliationEvidence], list[dict[str, Any]]]:
        if not isinstance(validator_results, Sequence) or isinstance(
            validator_results, (str, bytes, bytearray)
        ):
            raise ToolSurfaceError("validator_results must be a sequence")
        required = set(REQUIRED_EXTERNAL_VALIDATORS)
        if action["reversibility"] == "COMPENSATABLE":
            required.add("compensation_prevalidation_check")
        evidence: list[ReconciliationEvidence] = []
        checked_results: list[dict[str, Any]] = []
        observed_ids: list[str] = []
        for result in validator_results:
            try:
                item = ReconciliationEvidence(result)
            except ValueError as exc:
                raise ToolSurfaceError(str(exc)) from exc
            checked = item.validator_result
            validator_id = checked["validator_id"]
            observed_ids.append(validator_id)
            if checked["observed_state_version"] != action["state_version"]:
                raise ToolSurfaceError(
                    f"stale external validator evidence {validator_id!r}"
                )
            evidence.append(item)
            checked_results.append(checked)
        if len(observed_ids) != len(set(observed_ids)):
            raise ToolSurfaceError("external validator evidence contains duplicate IDs")
        if set(observed_ids) != required:
            missing = sorted(required - set(observed_ids))
            unexpected = sorted(set(observed_ids) - required)
            raise ToolSurfaceError(
                f"external validator evidence set mismatch; missing={missing}, unexpected={unexpected}"
            )
        return evidence, checked_results

    def authorize(
        self,
        action: object,
        supervisor_decision: object,
        validator_results: Sequence[object],
        *,
        timestamp: object,
        current_state_version: int,
        compensation_prevalidation: object | None = None,
        soft_risk_below_ceiling: bool | None = None,
    ) -> Authorization:
        """Validate and reconcile an attempt without invoking its adapter."""

        try:
            checked_action = validate_contract(
                action, "action-proposal.schema.json", "tool action proposal"
            )
            checked_decision = validate_contract(
                supervisor_decision,
                "supervisor-decision.schema.json",
                "tool supervisor decision",
            )
        except ContractValidationError as exc:
            raise ToolSurfaceError(str(exc)) from exc
        checked_timestamp = _checked_time(timestamp, "tool authorization timestamp")
        evidence, complete_results = self._external_evidence(
            checked_action, validator_results
        )

        capability_result = self._capability_result(
            checked_action, checked_timestamp, checked_decision["adapter_version"]
        )
        capability_evidence = ReconciliationEvidence(capability_result)
        evidence.append(capability_evidence)
        complete_results.append(capability_evidence.validator_result)
        version_result = self._version_result(
            checked_action, current_state_version, checked_timestamp
        )
        version_evidence = ReconciliationEvidence(version_result)
        evidence.append(version_evidence)
        complete_results.append(version_evidence.validator_result)
        if checked_action["reversibility"] == "COMPENSATABLE":
            prevalidation_result = self._prevalidation_result(
                checked_action, compensation_prevalidation, checked_timestamp
            )
            prevalidation_evidence = ReconciliationEvidence(prevalidation_result)
            evidence.append(prevalidation_evidence)
            complete_results.append(prevalidation_evidence.validator_result)

        supervisor = Resolution(checked_decision["decision"])
        reconciled = [
            reconcile_decision(
                supervisor,
                item,
                soft_risk_below_ceiling=soft_risk_below_ceiling,
            )
            for item in evidence
        ]
        resolution = max(reconciled or [supervisor], key=_RESOLUTION_PRIORITY.__getitem__)
        return Authorization(
            resolution,
            deepcopy(checked_action),
            deepcopy(checked_decision),
            tuple(deepcopy(complete_results)),
        )

    def invoke(
        self,
        action: object,
        supervisor_decision: object,
        validator_results: Sequence[object],
        *,
        started_at: object,
        completed_at: object,
        current_state_version: int,
        compensation_prevalidation: object | None = None,
        soft_risk_below_ceiling: bool | None = None,
    ) -> ToolExecution:
        """Authorize, execute, verify, and emit one schema-valid tool outcome."""

        try:
            retry_action = validate_contract(
                action, "action-proposal.schema.json", "tool action proposal"
            )
        except ContractValidationError as exc:
            raise ToolSurfaceError(str(exc)) from exc
        retry_bytes = canonical_json_bytes(retry_action)
        retry_key = retry_action["idempotency_key"]
        self._external_evidence(retry_action, validator_results)
        with self._claim_lock:
            prior = self._claims.get(retry_key)
            if prior is not None:
                prior_action, state, execution = prior
                if prior_action != retry_bytes:
                    raise ToolSurfaceError(
                        "idempotency key was reused for a different action"
                    )
                if state == "COMPLETED" and execution is not None:
                    return execution
                if state == "INDETERMINATE":
                    raise ToolSurfaceError(
                        "idempotency key is indeterminate; retry would risk a duplicate side effect"
                    )
                raise ToolSurfaceError("idempotency key execution is already in flight")

        authorization = self.authorize(
            action,
            supervisor_decision,
            validator_results,
            timestamp=started_at,
            current_state_version=current_state_version,
            compensation_prevalidation=compensation_prevalidation,
            soft_risk_below_ceiling=soft_risk_below_ceiling,
        )
        if authorization.resolution is not Resolution.APPROVE:
            return ToolExecution(authorization, None)

        checked_completed = _checked_time(completed_at, "tool completion timestamp")
        started = authorization.validator_results[-1]["timestamp"]
        if _instant(checked_completed) < _instant(started):
            raise ToolSurfaceError("tool completion cannot precede tool start")
        adapter = self._adapters.get(authorization.action["action_type"])
        if adapter is None:
            raise ToolSurfaceError(
                f"no adapter owns action type {authorization.action['action_type']!r}"
            )
        idempotency_key = authorization.action["idempotency_key"]
        action_bytes = canonical_json_bytes(authorization.action)
        with self._claim_lock:
            raced = self._claims.get(idempotency_key)
            if raced is not None:
                if raced[0] != action_bytes:
                    raise ToolSurfaceError("idempotency key was reused for a different action")
                if raced[1] == "COMPLETED" and raced[2] is not None:
                    return raced[2]
                raise ToolSurfaceError("idempotency key execution is already claimed")
            self._claims[idempotency_key] = (action_bytes, "IN_FLIGHT", None)
            self._dispatch_count += 1
        try:
            try:
                raw = adapter.execute(deepcopy(authorization.action))
            except Exception as exc:
                raise ToolSurfaceError(f"tool executor failed: {exc}") from exc
            if not isinstance(raw, Mapping):
                raise ToolSurfaceError("tool executor must return an object")
            normalized = raw.get("normalized_effects")
            if not isinstance(normalized, Sequence) or isinstance(
                normalized, (str, bytes, bytearray)
            ) or not all(isinstance(item, Mapping) for item in normalized):
                raise ToolSurfaceError("tool normalized_effects must be an array of objects")
            try:
                verified = adapter.verify(
                    deepcopy(authorization.action), deepcopy(list(normalized))
                )
            except Exception as exc:
                raise ToolSurfaceError(f"tool verifier failed: {exc}") from exc
            if not isinstance(verified, Sequence) or isinstance(
                verified, (str, bytes, bytearray)
            ) or not all(isinstance(item, Mapping) for item in verified):
                raise ToolSurfaceError("tool verifier must return an array of objects")
            normalized_domains = Counter(canonical_json_bytes(item) for item in normalized)
            verified_domains = Counter(canonical_json_bytes(item) for item in verified)
            expected_domains = Counter(
                canonical_json_bytes(item)
                for item in authorization.action["expected_effects"]
            )
            status = raw.get("status", "SUCCEEDED")
            if status == "SUCCEEDED" and (
                not normalized_domains
                or verified_domains != normalized_domains
                or expected_domains != normalized_domains
            ):
                raise ToolSurfaceError(
                    "successful tool requires exact non-empty declared, normalized, and verified effect coverage"
                )
            if any(verified_domains[item] > count for item, count in normalized_domains.items()):
                raise ToolSurfaceError("verified effects must be drawn from normalized effects")
            raw_result_ref = raw.get("raw_result_ref")
            state_after = raw.get("state_version_after")
            error_code = raw.get("error_code")
            if status not in {"SUCCEEDED", "FAILED"}:
                raise ToolSurfaceError("tool status must be SUCCEEDED or FAILED")
            expected_after = authorization.action["state_version"] + 1
            if status == "SUCCEEDED" and state_after != expected_after:
                raise ToolSurfaceError("successful tool must advance state version exactly once")
            if status == "FAILED" and state_after is not None:
                raise ToolSurfaceError("failed tool cannot claim a resulting state version")
            if status == "FAILED" and (not isinstance(error_code, str) or not error_code):
                raise ToolSurfaceError("failed tool requires an error code")
            if status == "SUCCEEDED" and error_code is not None:
                raise ToolSurfaceError("successful tool cannot carry an error code")
            outcome = {
                "outcome_id": f"outcome:{authorization.action['action_id']}",
                "action_id": authorization.action["action_id"],
                "tool_id": adapter.tool_id, "tool_version": adapter.tool_version,
                "status": status,
                "started_at": deepcopy(authorization.validator_results[-1]["timestamp"]),
                "completed_at": checked_completed,
                "raw_result_ref": deepcopy(raw_result_ref),
                "normalized_effects": deepcopy(list(normalized)),
                "verified_effects": deepcopy(list(verified)),
                "state_version_before": authorization.action["state_version"],
                "state_version_after": state_after, "error_code": error_code,
                "idempotency_key": authorization.action["idempotency_key"],
            }
            try:
                checked_outcome = validate_contract(
                    outcome, "tool-outcome.schema.json", "tool outcome"
                )
            except ContractValidationError as exc:
                raise ToolSurfaceError(str(exc)) from exc
            execution = ToolExecution(authorization, checked_outcome)
            with self._claim_lock:
                self._claims[idempotency_key] = (action_bytes, "COMPLETED", execution)
            return execution
        except Exception as exc:
            with self._claim_lock:
                self._claims[idempotency_key] = (action_bytes, "INDETERMINATE", None)
            if isinstance(exc, ToolSurfaceError):
                raise
            raise ToolSurfaceError(f"tool execution failed: {exc}") from exc

    def repair(
        self,
        original_action: object,
        repair_decision: object,
        validator_results: Sequence[object],
        repaired_decision: object,
        repaired_validator_results: Sequence[object],
        *,
        started_at: object,
        completed_at: object,
        current_state_version: int,
        original_compensation_prevalidation: object | None = None,
        repaired_compensation_prevalidation: object | None = None,
        soft_risk_below_ceiling: bool | None = None,
    ) -> ToolExecution:
        """Require REPAIR, validate the replacement, then re-enter every gate."""

        initial = self.authorize(
            original_action,
            repair_decision,
            validator_results,
            timestamp=started_at,
            current_state_version=current_state_version,
            compensation_prevalidation=original_compensation_prevalidation,
            soft_risk_below_ceiling=soft_risk_below_ceiling,
        )
        if initial.resolution is not Resolution.REPAIR:
            raise ToolSurfaceError("repair requires an initial REPAIR resolution")
        replacement = initial.supervisor_decision["proposed_repair"]
        if replacement is None:
            raise ToolSurfaceError("repair decision has no replacement proposal")
        return self.invoke(
            replacement,
            repaired_decision,
            repaired_validator_results,
            started_at=started_at,
            completed_at=completed_at,
            current_state_version=current_state_version,
            compensation_prevalidation=repaired_compensation_prevalidation,
            soft_risk_below_ceiling=soft_risk_below_ceiling,
        )

    def compensate(
        self,
        original_action: object,
        original_outcome: object,
        supervisor_decision: object,
        validator_results: Sequence[object],
        *,
        expected_effects: Sequence[Mapping[str, Any]],
        started_at: object,
        completed_at: object,
        current_state_version: int,
        soft_risk_below_ceiling: bool | None = None,
    ) -> ToolExecution:
        """Compile a compensation template and send it through the same gate."""

        try:
            action = validate_contract(
                original_action, "action-proposal.schema.json", "original action"
            )
            outcome = validate_contract(
                original_outcome, "tool-outcome.schema.json", "original tool outcome"
            )
        except ContractValidationError as exc:
            raise ToolSurfaceError(str(exc)) from exc
        template = action["compensation_action"]
        if action["reversibility"] != "COMPENSATABLE" or template is None:
            raise ToolSurfaceError("only COMPENSATABLE actions can be compensated")
        if outcome["action_id"] != action["action_id"]:
            raise ToolSurfaceError("original outcome does not belong to original action")
        if outcome["idempotency_key"] != action["idempotency_key"]:
            raise ToolSurfaceError("original outcome idempotency key does not match action")
        if (
            not isinstance(expected_effects, Sequence)
            or isinstance(expected_effects, (str, bytes, bytearray))
            or not expected_effects
            or not all(isinstance(item, Mapping) for item in expected_effects)
        ):
            raise ToolSurfaceError("compensation requires declared expected effects")
        try:
            checked_expected_effects = json.loads(canonical_json_bytes(expected_effects))
        except (TypeError, ValueError) as exc:
            raise ToolSurfaceError("compensation expected effects are not strict JSON") from exc
        action_bytes = canonical_json_bytes(action)
        outcome_bytes = canonical_json_bytes(outcome)
        with self._claim_lock:
            recorded = self._claims.get(action["idempotency_key"])
        if (
            recorded is None
            or recorded[0] != action_bytes
            or recorded[1] != "COMPLETED"
            or recorded[2] is None
            or canonical_json_bytes(recorded[2].authorization.action) != action_bytes
            or recorded[2].outcome is None
            or canonical_json_bytes(recorded[2].outcome) != outcome_bytes
        ):
            raise ToolSurfaceError(
                "compensation requires the exact recorded successful original execution"
            )
        original_adapter = self._adapters.get(action["action_type"])
        if (
            original_adapter is None
            or outcome["status"] != "SUCCEEDED"
            or outcome["tool_id"] != original_adapter.tool_id
            or outcome["tool_version"] != original_adapter.tool_version
            or outcome["state_version_before"] != action["state_version"]
            or outcome["state_version_after"] != action["state_version"] + 1
            or current_state_version != outcome["state_version_after"]
        ):
            raise ToolSurfaceError("original execution linkage is not valid for recovery")
        state_version = outcome["state_version_after"]
        if state_version is None:
            raise ToolSurfaceError("original outcome has no post-execution state version")
        compensation = {
            "action_id": f"compensation:{action['action_id']}",
            "plan_id": action["plan_id"],
            "actor_id": action["actor_id"],
            "state_version": state_version,
            "action_type": template["action_type"],
            "arguments": deepcopy(template["arguments"]),
            "expected_preconditions": [{"original_outcome_id": outcome["outcome_id"]}],
            "expected_effects": checked_expected_effects,
            "required_capabilities": deepcopy(template["required_capabilities"]),
            "risk_class": action["risk_class"],
            "reversibility": "REVERSIBLE",
            "compensation_action": None,
            "postconditions": [],
            "audit_deadline": None,
            "evidence_refs": deepcopy(action["evidence_refs"]),
            "confidence": action["confidence"],
            "idempotency_key": f"idem:compensation:{action['action_id']}",
        }
        return self.invoke(
            compensation,
            supervisor_decision,
            validator_results,
            started_at=started_at,
            completed_at=completed_at,
            current_state_version=current_state_version,
            soft_risk_below_ceiling=soft_risk_below_ceiling,
        )


def canonical_execution_bytes(execution: ToolExecution) -> bytes:
    """Stable serialization helper for deterministic tool-surface tests."""

    return canonical_json_bytes(
        {
            "resolution": execution.authorization.resolution.value,
            "action": execution.authorization.action,
            "supervisor_decision": execution.authorization.supervisor_decision,
            "validator_results": list(execution.authorization.validator_results),
            "outcome": execution.outcome,
        }
    )
