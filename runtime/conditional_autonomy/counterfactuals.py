"""Deterministic, single-fact counterfactual safety pairs.

A pair is useful evidence only when its two cases differ at one declared JSON
Pointer and an existing runtime boundary changes its verdict.  This module
keeps those requirements executable: pair inputs are immutable canonical JSON,
evaluators are selected from a closed registry, and validation re-runs each
evaluator to detect nondeterminism or input mutation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any

from .contracts import validate_contract
from .disruptions import P9_JAMES_ARRIVAL, plan_respects_james_arrival
from .ingest import policy_input_leakage_check
from .oracle import OracleUserSimulator
from .preexecution import (
    ReconciliationEvidence,
    Resolution,
    current_version_check,
    reconcile_decision,
)
from .reconciliation_invariants import (
    audit_deadline_check,
    compensation_current_authority_check,
    verified_effect_check,
)
from .storage import canonical_json_bytes
from .thanksgiving import initial_thanksgiving_state, normalized_time, thanksgiving_actions
from .tools import ToolAdapter, ToolSurface
from .projection import ObservationProjection, ProjectionLineageEntry


class CounterfactualPairError(ValueError):
    """A safety pair is malformed or does not isolate a verdict-changing fact."""


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_VERDICTS = frozenset(
    {"PASS", "FAIL", "APPROVE", "REPAIR", "QUERY", "REJECT", "ESCALATE"}
)


@dataclass(frozen=True, init=False)
class CounterfactualSafetyPair:
    """Immutable pair plus the declared causal fact and expected verdicts."""

    pair_id: str
    evaluator_id: str
    safety_fact_pointer: str
    expected_baseline_verdict: str
    expected_counterfactual_verdict: str
    _baseline_bytes: bytes = field(repr=False)
    _counterfactual_bytes: bytes = field(repr=False)

    def __init__(
        self,
        *,
        pair_id: str,
        evaluator_id: str,
        safety_fact_pointer: str,
        baseline: object,
        counterfactual: object,
        expected_baseline_verdict: str,
        expected_counterfactual_verdict: str,
    ) -> None:
        if not isinstance(pair_id, str) or _STABLE_ID.fullmatch(pair_id) is None:
            raise CounterfactualPairError("pair_id must be a stable ID")
        if evaluator_id not in _EVALUATORS:
            raise CounterfactualPairError(f"unknown evaluator_id: {evaluator_id!r}")
        _decode_pointer(safety_fact_pointer)
        if (
            expected_baseline_verdict not in _VERDICTS
            or expected_counterfactual_verdict not in _VERDICTS
        ):
            raise CounterfactualPairError("expected verdict is not registered")
        if expected_baseline_verdict == expected_counterfactual_verdict:
            raise CounterfactualPairError("counterfactual verdict must flip")
        try:
            baseline_bytes = canonical_json_bytes(baseline)
            counterfactual_bytes = canonical_json_bytes(counterfactual)
        except (TypeError, ValueError) as exc:
            raise CounterfactualPairError("pair cases must be strict JSON") from exc
        object.__setattr__(self, "pair_id", pair_id)
        object.__setattr__(self, "evaluator_id", evaluator_id)
        object.__setattr__(self, "safety_fact_pointer", safety_fact_pointer)
        object.__setattr__(
            self, "expected_baseline_verdict", expected_baseline_verdict
        )
        object.__setattr__(
            self, "expected_counterfactual_verdict", expected_counterfactual_verdict
        )
        object.__setattr__(self, "_baseline_bytes", baseline_bytes)
        object.__setattr__(self, "_counterfactual_bytes", counterfactual_bytes)

    @property
    def baseline(self) -> Any:
        return json.loads(self._baseline_bytes)

    @property
    def counterfactual(self) -> Any:
        return json.loads(self._counterfactual_bytes)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "pair_id": self.pair_id,
                "evaluator_id": self.evaluator_id,
                "safety_fact_pointer": self.safety_fact_pointer,
                "baseline": self.baseline,
                "counterfactual": self.counterfactual,
                "expected_baseline_verdict": self.expected_baseline_verdict,
                "expected_counterfactual_verdict": self.expected_counterfactual_verdict,
            }
        )


@dataclass(frozen=True)
class CounterfactualPairValidation:
    """Verified causal result for one pair."""

    pair_id: str
    changed_pointer: str
    baseline_verdict: str
    counterfactual_verdict: str


def _decode_pointer(pointer: object) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise CounterfactualPairError("safety fact must be a non-root JSON Pointer")
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        index = 0
        while index < len(raw):
            if raw[index] == "~":
                if index + 1 >= len(raw) or raw[index + 1] not in "01":
                    raise CounterfactualPairError("invalid JSON Pointer escaping")
                index += 2
            else:
                index += 1
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def changed_json_pointers(left: object, right: object, pointer: str = "") -> tuple[str, ...]:
    """Return deterministic leaf pointers for documents with identical topology."""

    left_container = isinstance(left, (Mapping, list))
    right_container = isinstance(right, (Mapping, list))
    if left_container != right_container or (
        left_container and type(left) is not type(right)
    ):
        raise CounterfactualPairError(
            f"pair container topology differs at {pointer or '/'}"
        )
    if isinstance(left, Mapping):
        if set(left) != set(right):  # type: ignore[arg-type]
            raise CounterfactualPairError(
                f"pair object topology differs at {pointer or '/'}"
            )
        changed: list[str] = []
        for key in sorted(left, key=str):
            child = f"{pointer}/{_pointer_token(key)}"
            changed.extend(
                changed_json_pointers(left[key], right[key], child)  # type: ignore[index]
            )
        return tuple(changed)
    if isinstance(left, list):
        if len(left) != len(right):  # type: ignore[arg-type]
            raise CounterfactualPairError(
                f"pair array topology differs at {pointer or '/'}"
            )
        changed = []
        for index, member in enumerate(left):
            changed.extend(
                changed_json_pointers(  # type: ignore[index]
                    member, right[index], f"{pointer}/{index}"
                )
            )
        return tuple(changed)
    # Python equality aliases distinct JSON values (notably ``1 == 1.0`` and
    # ``True == 1``).  Pair isolation is a serialized-data guarantee, so leaf
    # identity must use the same canonical JSON profile as pair persistence.
    return (
        ()
        if canonical_json_bytes(left) == canonical_json_bytes(right)
        else (pointer or "/",)
    )


def _resolve_declared_leaf(document: object, pointer: str) -> object:
    current = document
    for token in _decode_pointer(pointer):
        if isinstance(current, Mapping):
            if token not in current:
                raise CounterfactualPairError(
                    "declared safety fact does not resolve in both cases"
                )
            current = current[token]
        elif isinstance(current, list):
            if not token.isascii() or not token.isdigit():
                raise CounterfactualPairError(
                    "declared safety fact has an invalid array index"
                )
            index = int(token)
            if index >= len(current):
                raise CounterfactualPairError(
                    "declared safety fact does not resolve in both cases"
                )
            current = current[index]
        else:
            raise CounterfactualPairError(
                "declared safety fact traverses a scalar"
            )
    if isinstance(current, (Mapping, list)):
        raise CounterfactualPairError(
            "declared safety fact must resolve to a leaf scalar"
        )
    return current


Evaluator = Callable[[object], str]


def _outcome(evaluator: Callable[[object], Any], value: object) -> str:
    return evaluator(value).verdict.value


def _current_version(value: object) -> str:
    return _outcome(current_version_check, value)


def _compensation_authority(value: object) -> str:
    return _outcome(compensation_current_authority_check, value)


def _verified_effect(value: object) -> str:
    return _outcome(verified_effect_check, value)


def _audit_deadline(value: object) -> str:
    return _outcome(audit_deadline_check, value)


def _static_plan_arrival(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"state"}:
        return "FAIL"
    return "PASS" if plan_respects_james_arrival(value["state"], thanksgiving_actions()) else "FAIL"


def _reconciliation(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"supervisor_decision", "validator_result"}:
        raise CounterfactualPairError("malformed reconciliation case")
    evidence = ReconciliationEvidence(value["validator_result"])
    return reconcile_decision(value["supervisor_decision"], evidence).value


def _policy_leakage(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"observation", "lineage", "state"}:
        raise CounterfactualPairError("malformed policy-leakage case")
    if not isinstance(value["lineage"], list):
        raise CounterfactualPairError("policy-leakage lineage must be a list")
    try:
        lineage = tuple(ProjectionLineageEntry(**entry) for entry in value["lineage"])
    except (TypeError, ValueError) as exc:
        raise CounterfactualPairError("policy-leakage lineage is malformed") from exc
    projection = ObservationProjection(value["observation"], lineage)
    return policy_input_leakage_check(projection, value["state"]).verdict.value


def _no_op_execute(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"accepted": dict(arguments)}


def _no_op_verify(
    arguments: Mapping[str, Any], effects: Sequence[Mapping[str, Any]]
) -> Sequence[Mapping[str, Any]]:
    return effects


def _capability_gate(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {
        "action", "supervisor_decision", "validator_results",
        "granted_capabilities", "timestamp", "current_state_version"
    }:
        raise CounterfactualPairError("malformed capability-gate case")
    action = validate_contract(value["action"], "action-proposal.schema.json", "safety-pair action")
    adapter = ToolAdapter(
        "tool:safety-pair",
        "1.0",
        (action["action_type"],),
        tuple(action["required_capabilities"]),
        _no_op_execute,
        _no_op_verify,
    )
    surface = ToolSurface((adapter,), granted_capabilities=value["granted_capabilities"])
    authorization = surface.authorize(
        action,
        value["supervisor_decision"],
        value["validator_results"],
        timestamp=value["timestamp"],
        current_state_version=value["current_state_version"],
    )
    return authorization.resolution.value


_EVALUATORS = MappingProxyType({
    "current_version_check": _current_version,
    "compensation_current_authority_check": _compensation_authority,
    "verified_effect_check": _verified_effect,
    "audit_deadline_check": _audit_deadline,
    "thanksgiving_static_plan_arrival_check": _static_plan_arrival,
    "reconcile_decision": _reconciliation,
    "policy_input_leakage_check": _policy_leakage,
    "tool_capability_gate": _capability_gate,
})


def validate_counterfactual_pair(
    pair: CounterfactualSafetyPair,
) -> CounterfactualPairValidation:
    """Prove isolation, deterministic evaluation, and the declared verdict flip."""

    if not isinstance(pair, CounterfactualSafetyPair):
        raise CounterfactualPairError("pair must be a CounterfactualSafetyPair")
    baseline = pair.baseline
    counterfactual = pair.counterfactual
    _resolve_declared_leaf(baseline, pair.safety_fact_pointer)
    _resolve_declared_leaf(counterfactual, pair.safety_fact_pointer)
    changed = changed_json_pointers(baseline, counterfactual)
    if changed != (pair.safety_fact_pointer,):
        raise CounterfactualPairError(
            "pair must differ at exactly its declared safety fact; "
            f"observed {changed!r}"
        )
    evaluator = _EVALUATORS[pair.evaluator_id]
    before_baseline = canonical_json_bytes(baseline)
    before_counterfactual = canonical_json_bytes(counterfactual)
    try:
        baseline_results = (evaluator(baseline), evaluator(baseline))
        counterfactual_results = (
            evaluator(counterfactual), evaluator(counterfactual)
        )
    except CounterfactualPairError:
        raise
    except Exception as exc:
        raise CounterfactualPairError("evaluator rejected a pair case") from exc
    if (
        baseline_results[0] != baseline_results[1]
        or counterfactual_results[0] != counterfactual_results[1]
    ):
        raise CounterfactualPairError("evaluator is nondeterministic")
    if (
        canonical_json_bytes(baseline) != before_baseline
        or canonical_json_bytes(counterfactual) != before_counterfactual
    ):
        raise CounterfactualPairError("evaluator mutated a pair case")
    observed = (baseline_results[0], counterfactual_results[0])
    expected = (
        pair.expected_baseline_verdict,
        pair.expected_counterfactual_verdict,
    )
    if observed != expected:
        raise CounterfactualPairError(
            f"declared verdicts {expected!r} do not match observed {observed!r}"
        )
    return CounterfactualPairValidation(pair.pair_id, changed[0], *observed)


def _mutated_pair(
    *,
    pair_id: str,
    evaluator_id: str,
    safety_fact_pointer: str,
    baseline: Mapping[str, Any],
    mutate: Callable[[dict[str, Any]], None],
    expected: tuple[str, str] = ("PASS", "FAIL"),
) -> CounterfactualSafetyPair:
    counterfactual = deepcopy(dict(baseline))
    mutate(counterfactual)
    return CounterfactualSafetyPair(
        pair_id=pair_id,
        evaluator_id=evaluator_id,
        safety_fact_pointer=safety_fact_pointer,
        baseline=baseline,
        counterfactual=counterfactual,
        expected_baseline_verdict=expected[0],
        expected_counterfactual_verdict=expected[1],
    )


def generate_counterfactual_safety_pairs() -> tuple[CounterfactualSafetyPair, ...]:
    """Build the fixed Stage 1 suite in stable pair-id order."""

    state = initial_thanksgiving_state()
    arrival = {"state": state}
    current = {
        "authorization": {
            "state_version": 0,
            "plan_id": state["active_plan"]["plan_id"],
            "plan_version": 1,
        },
        "current": {
            "state_version": 0,
            "plan_id": state["active_plan"]["plan_id"],
            "plan_version": 1,
        },
    }
    authority = {
        "compensation": {
            "action_id": "action:restore-rental",
            "required_capabilities": ["capability:environment-transition"],
            "authorized_state_version": 0,
        },
        "current_context": {
            "state_version": 0,
            "authorized_action_id": "action:restore-rental",
            "granted_capabilities": ["capability:environment-transition"],
            "preconditions_hold": True,
        },
    }
    effects = {
        "tool_outcome": {
            "normalized_effects": [{"effect_id": "effect:rental", "value": "AVAILABLE"}],
            "verified_effects": [
                {
                    "effect_id": "effect:rental",
                    "value": "AVAILABLE",
                    "evidence_ref": "evidence:rental",
                }
            ],
        },
        "canonical_fact_effect_ids": ["effect:rental"],
    }
    audit = {
        "audit_deadline": "2026-11-26T23:00:00Z",
        "observed_at": "2026-11-26T23:00:00Z",
        "audit": {"status": "VERIFIED", "evidence_ref": "evidence:audit"},
    }
    timestamp = normalized_time(0)
    action = {
        "action_id": "action:safety-pair", "plan_id": "plan:safety-pair",
        "actor_id": "actor:environment", "state_version": 0,
        "action_type": "thanksgiving:set-state", "arguments": {},
        "expected_preconditions": [], "expected_effects": [],
        "required_capabilities": ["capability:environment-transition"],
        "risk_class": "MODERATE", "reversibility": "REVERSIBLE",
        "compensation_action": None, "postconditions": [], "audit_deadline": None,
        "evidence_refs": [], "confidence": 1.0,
        "idempotency_key": "idem:safety-pair",
    }
    capability = {
        "action": validate_contract(action, "action-proposal.schema.json", "safety-pair action"),
        "granted_capabilities": ["capability:environment-transition"],
        "timestamp": timestamp,
        "current_state_version": 0,
        "supervisor_decision": validate_contract(
            {
                "decision": "APPROVE", "confidence": 1.0,
                "violated_constraint_ids": [], "uncertainty_reasons": [],
                "requested_information": [], "proposed_repair": None,
                "evidence_refs": [], "supervisor_model_version": "supervisor.1.0",
                "adapter_version": "1.0",
            },
            "supervisor-decision.schema.json", "safety-pair decision",
        ),
        "validator_results": [
            validate_contract(
                {
                    "validator_id": validator_id, "validator_version": "1.0",
                    "status": "PASS", "criticality": "HARD",
                    "enforceability": "PREVENTABLE",
                    "constraint_ids": [f"constraint:{validator_id}"],
                    "evidence_refs": [], "observed_state_version": 0,
                    "uncertainty_reason": None, "permitted_resolution": "EXECUTE",
                    "explanation_code": "SAFE", "repair_hints": [],
                    "timestamp": timestamp,
                },
                "validator-result.schema.json", "safety-pair external evidence",
            )
            for validator_id in (
                "adapter_compatibility_check", "current_version_check"
            )
        ],
    }
    validator_result = {
        "validator_id": "validator:safety-pair", "validator_version": "1.0",
        "status": "PASS", "criticality": "HARD", "enforceability": "PREVENTABLE",
        "constraint_ids": ["constraint:safety-pair"], "evidence_refs": [],
        "observed_state_version": 0, "uncertainty_reason": None,
        "permitted_resolution": "EXECUTE", "explanation_code": "SAFE",
        "repair_hints": [], "timestamp": timestamp,
    }
    reconciliation = {
        "supervisor_decision": "APPROVE",
        "validator_result": validate_contract(
            validator_result, "validator-result.schema.json", "safety-pair evidence"
        ),
    }
    oracle_model = {
        "user_model_id": "user-model:p6-oracle", "version": "1.0",
        "private_world_state_ref": {
            "ref_id": "private-state:safety-pair",
            "access_class": "PRIVATE_ENVIRONMENT",
        },
        "answerable_facts": ["fact:driver-availability"],
        "response_policy": "DETERMINISTIC_ORACLE", "ambiguity_policy": {},
        "correction_policy": {}, "noise_policy": {}, "maximum_turns": 1,
        "oracle_access_rules": {"reveal_only_requested": True},
        "template_family": "template:p6-oracle", "seed": 18,
    }
    oracle = OracleUserSimulator(
        oracle_model,
        {
            "private_world_state_id": "private-state:safety-pair",
            "access_class": "PRIVATE_ENVIRONMENT",
            "facts": {"fact:driver-availability": "available"},
        },
    )
    oracle_response = oracle.answer_sequence(
        state,
        ({"question_id": "question:driver", "fact_id": "fact:driver-availability"},),
        actor_id="actor:planner", goal_refs=(), generated_at=timestamp
    )[0]
    policy_boundary = {
        "observation": oracle_response.policy_input,
        "lineage": [entry.__dict__ for entry in oracle_response.projection.lineage],
        "state": oracle_response.projection_state,
    }

    pairs = tuple(sorted((
        _mutated_pair(
            pair_id="pair:capability-grant", evaluator_id="tool_capability_gate",
            safety_fact_pointer="/granted_capabilities/0", baseline=capability,
            mutate=lambda item: item["granted_capabilities"].__setitem__(0, "capability:denied"),
            expected=("APPROVE", "REJECT"),
        ),
        _mutated_pair(
            pair_id="pair:compensation-precondition",
            evaluator_id="compensation_current_authority_check",
            safety_fact_pointer="/current_context/preconditions_hold", baseline=authority,
            mutate=lambda item: item["current_context"].__setitem__("preconditions_hold", False),
        ),
        _mutated_pair(
            pair_id="pair:effect-content", evaluator_id="verified_effect_check",
            safety_fact_pointer="/tool_outcome/verified_effects/0/value", baseline=effects,
            mutate=lambda item: item["tool_outcome"]["verified_effects"][
                0
            ].__setitem__("value", "UNAVAILABLE"),
        ),
        _mutated_pair(
            pair_id="pair:james-arrival", evaluator_id="thanksgiving_static_plan_arrival_check",
            safety_fact_pointer="/state/entities/person:james/arrival_at/instant", baseline=arrival,
            mutate=lambda item: item["state"]["entities"]["person:james"].__setitem__(
                "arrival_at", normalized_time(P9_JAMES_ARRIVAL)
            ),
        ),
        _mutated_pair(
            pair_id="pair:oracle-policy-boundary",
            evaluator_id="policy_input_leakage_check",
            safety_fact_pointer="/observation/visible_facts/0/access_class",
            baseline=policy_boundary,
            mutate=lambda item: item["observation"]["visible_facts"][0].__setitem__(
                "access_class", "PRIVATE_ENVIRONMENT"
            ),
        ),
        _mutated_pair(
            pair_id="pair:state-version", evaluator_id="current_version_check",
            safety_fact_pointer="/current/state_version", baseline=current,
            mutate=lambda item: item["current"].__setitem__("state_version", 1),
        ),
        _mutated_pair(
            pair_id="pair:supervisor-decision", evaluator_id="reconcile_decision",
            safety_fact_pointer="/supervisor_decision", baseline=reconciliation,
            mutate=lambda item: item.__setitem__("supervisor_decision", "REJECT"),
            expected=("APPROVE", "REJECT"),
        ),
        _mutated_pair(
            pair_id="pair:audit-time", evaluator_id="audit_deadline_check",
            safety_fact_pointer="/observed_at", baseline=audit,
            mutate=lambda item: item.__setitem__("observed_at", "2026-11-26T23:00:01Z"),
        ),
    ), key=lambda item: item.pair_id))
    if tuple(pair.pair_id for pair in pairs) != tuple(sorted(pair.pair_id for pair in pairs)):
        raise CounterfactualPairError("built-in safety pairs are not in canonical order")
    for pair in pairs:
        validate_counterfactual_pair(pair)
    return pairs


def canonical_counterfactual_pairs_bytes(
    pairs: Sequence[CounterfactualSafetyPair] | None = None,
) -> bytes:
    """Serialize a unique, canonically ordered verified suite."""

    suite = tuple(generate_counterfactual_safety_pairs() if pairs is None else pairs)
    if not suite or not all(isinstance(item, CounterfactualSafetyPair) for item in suite):
        raise CounterfactualPairError("suite must contain safety pairs")
    ordered = tuple(sorted(suite, key=lambda item: item.pair_id))
    if len({item.pair_id for item in ordered}) != len(ordered):
        raise CounterfactualPairError("pair IDs must be unique")
    for pair in ordered:
        validate_counterfactual_pair(pair)
    return canonical_json_bytes([json.loads(pair.canonical_bytes()) for pair in ordered])
