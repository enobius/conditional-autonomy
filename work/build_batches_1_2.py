"""Generate the reviewed Workstream 1A Batch 1 and Batch 2 artifacts.

The v0.1 package is intentionally not imported.  Field names come from the
v1.1.2 formalization and the approved Workstream 1A amendments.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "architecture" / "schemas" / "v1.0"
META = "https://json-schema.org/draft/2020-12/schema"
BASE = "https://thesis.local/schemas/v1.0/"

POLICY = ["POLICY_VISIBLE"]
CONTROL = ["SUPERVISOR_VISIBLE", "VALIDATOR_VISIBLE", "EVALUATOR_ONLY"]
EXECUTION = ["POLICY_VISIBLE", "SUPERVISOR_VISIBLE", "VALIDATOR_VISIBLE", "EVALUATOR_ONLY"]
EVALUATION = ["EVALUATOR_ONLY"]
PRIVATE = ["PRIVATE_ENVIRONMENT"]


def annotated(definition: dict, access: list[str]) -> dict:
    return {**definition, "x-access-class": access}


def ref(name: str, access: list[str]) -> dict:
    return annotated({"$ref": f"common.defs.schema.json#/$defs/{name}"}, access)


def string(access: list[str], **keywords) -> dict:
    return annotated({"type": "string", **keywords}, access)


def integer(access: list[str], **keywords) -> dict:
    return annotated({"type": "integer", **keywords}, access)


def number(access: list[str], **keywords) -> dict:
    return annotated({"type": "number", **keywords}, access)


def boolean(access: list[str]) -> dict:
    return annotated({"type": "boolean"}, access)


def array(items: dict, access: list[str], **keywords) -> dict:
    return annotated({"type": "array", "items": items, **keywords}, access)


def object_value(access: list[str], *, nullable: bool = False) -> dict:
    kind = ["object", "null"] if nullable else "object"
    return annotated({"type": kind}, access)


def schema(name: str, title: str, required: list[str], properties: dict, **keywords) -> dict:
    result = {
        "$schema": META,
        "$id": f"{BASE}{name}.schema.json",
        "title": title,
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }
    result.update(keywords)
    return result


def probability(access: list[str]) -> dict:
    return number(access, minimum=0, maximum=1)


def count(access: list[str]) -> dict:
    return integer(access, minimum=0)


def nullable_version(access: list[str]) -> dict:
    return annotated(
        {
            "oneOf": [
                {"$ref": "common.defs.schema.json#/$defs/versionIdentifier"},
                {"type": "null"},
            ]
        },
        access,
    )


def normalized_time(access: list[str], *, nullable: bool = False) -> dict:
    variants = [{"$ref": "common.defs.schema.json#/$defs/normalizedTime"}]
    if nullable:
        variants.append({"type": "null"})
    return annotated(variants[0] if len(variants) == 1 else {"oneOf": variants}, access)


def stable_id_array(access: list[str], **keywords) -> dict:
    return array(
        {"$ref": "common.defs.schema.json#/$defs/stableId"},
        access,
        **keywords,
    )


def evidence_array(access: list[str]) -> dict:
    return array(
        {"$ref": "common.defs.schema.json#/$defs/evidenceRef"},
        access,
    )


validator_result = schema(
    "validator-result",
    "Validator Result",
    [
        "validator_id",
        "validator_version",
        "status",
        "criticality",
        "enforceability",
        "constraint_ids",
        "evidence_refs",
        "observed_state_version",
        "uncertainty_reason",
        "permitted_resolution",
        "explanation_code",
        "repair_hints",
        "timestamp",
    ],
    {
        "validator_id": ref("stableId", CONTROL),
        "validator_version": ref("versionIdentifier", CONTROL),
        "status": ref("validatorStatus", CONTROL),
        "criticality": ref("criticality", CONTROL),
        "enforceability": ref("enforceability", CONTROL),
        "constraint_ids": stable_id_array(CONTROL, minItems=1, uniqueItems=True),
        "evidence_refs": evidence_array(CONTROL),
        "observed_state_version": integer(CONTROL, minimum=0),
        "uncertainty_reason": annotated({"type": ["string", "null"]}, CONTROL),
        "permitted_resolution": annotated(
            {"enum": ["EXECUTE", "REPAIR", "QUERY", "REJECT", "ESCALATE"]},
            CONTROL,
        ),
        "explanation_code": ref("stableId", CONTROL),
        "repair_hints": array({"type": "string", "minLength": 1}, CONTROL, uniqueItems=True),
        "timestamp": normalized_time(CONTROL),
    },
    allOf=[
        {
            "if": {
                "properties": {
                    "criticality": {"const": "HARD"},
                    "status": {"const": "UNKNOWN"},
                },
                "required": ["criticality", "status"],
            },
            "then": {
                "properties": {
                    "permitted_resolution": {"enum": ["QUERY", "ESCALATE"]},
                    "uncertainty_reason": {"type": "string", "minLength": 1},
                }
            },
        },
        {
            "if": {
                "properties": {"status": {"const": "PASS"}},
                "required": ["status"],
            },
            "then": {
                "properties": {
                    "permitted_resolution": {"const": "EXECUTE"},
                    "uncertainty_reason": {"type": "null"},
                }
            },
        },
    ],
)


supervisor_decision = schema(
    "supervisor-decision",
    "Supervisor Decision",
    [
        "decision",
        "confidence",
        "violated_constraint_ids",
        "uncertainty_reasons",
        "requested_information",
        "proposed_repair",
        "evidence_refs",
        "supervisor_model_version",
        "adapter_version",
    ],
    {
        "decision": ref("decision", CONTROL),
        "confidence": probability(CONTROL),
        "violated_constraint_ids": stable_id_array(CONTROL, uniqueItems=True),
        "uncertainty_reasons": array({"type": "string", "minLength": 1}, CONTROL),
        "requested_information": array({"type": "string", "minLength": 1}, CONTROL),
        "proposed_repair": object_value(CONTROL, nullable=True),
        "evidence_refs": evidence_array(CONTROL),
        "supervisor_model_version": ref("versionIdentifier", CONTROL),
        "adapter_version": nullable_version(CONTROL),
    },
    allOf=[
        {
            "if": {
                "properties": {"decision": {"const": "QUERY"}},
                "required": ["decision"],
            },
            "then": {
                "properties": {"requested_information": {"minItems": 1}}
            },
        },
        {
            "if": {
                "properties": {"decision": {"const": "REPAIR"}},
                "required": ["decision"],
            },
            "then": {
                "properties": {"proposed_repair": {"type": "object"}}
            },
        },
    ],
)


tool_outcome = schema(
    "tool-outcome",
    "Tool Outcome",
    [
        "outcome_id",
        "action_id",
        "tool_id",
        "tool_version",
        "status",
        "started_at",
        "completed_at",
        "raw_result_ref",
        "normalized_effects",
        "verified_effects",
        "state_version_before",
        "state_version_after",
        "error_code",
        "idempotency_key",
    ],
    {
        "outcome_id": ref("stableId", CONTROL),
        "action_id": ref("stableId", CONTROL),
        "tool_id": ref("stableId", CONTROL),
        "tool_version": ref("versionIdentifier", CONTROL),
        "status": ref("stableId", CONTROL),
        "started_at": normalized_time(CONTROL),
        "completed_at": normalized_time(CONTROL),
        "raw_result_ref": ref("evidenceRef", ["VALIDATOR_VISIBLE", "EVALUATOR_ONLY"]),
        "normalized_effects": array({"type": "object"}, CONTROL),
        "verified_effects": array({"type": "object"}, CONTROL),
        "state_version_before": integer(CONTROL, minimum=0),
        "state_version_after": annotated({"type": ["integer", "null"], "minimum": 0}, CONTROL),
        "error_code": annotated({"type": ["string", "null"]}, CONTROL),
        "idempotency_key": ref("stableId", CONTROL),
    },
)


outcome_vector = schema(
    "outcome-vector",
    "Outcome Vector",
    [
        "goal_success",
        "constraint_score",
        "hard_violation_count",
        "optimality_gap",
        "recovery_success",
        "execution_cost",
        "latency",
        "token_count",
        "tool_calls",
        "user_interventions",
        "clarification_total",
        "clarification_necessary",
        "clarification_unnecessary",
        "clarification_insufficient",
        "clarification_repeated",
        "clarification_incorrect_scope",
        "evaluator_disagreement",
    ],
    {
        "goal_success": boolean(EVALUATION),
        "constraint_score": number(EVALUATION, minimum=0, maximum=1),
        "hard_violation_count": count(EVALUATION),
        "optimality_gap": annotated({"type": ["number", "null"], "minimum": 0}, EVALUATION),
        "recovery_success": annotated({"type": ["boolean", "null"]}, EVALUATION),
        "execution_cost": number(EVALUATION, minimum=0),
        "latency": number(EVALUATION, minimum=0),
        "token_count": count(EVALUATION),
        "tool_calls": count(EVALUATION),
        "user_interventions": count(EVALUATION),
        "clarification_total": count(EVALUATION),
        "clarification_necessary": count(EVALUATION),
        "clarification_unnecessary": count(EVALUATION),
        "clarification_insufficient": count(EVALUATION),
        "clarification_repeated": count(EVALUATION),
        "clarification_incorrect_scope": count(EVALUATION),
        "evaluator_disagreement": number(EVALUATION, minimum=0, maximum=1),
    },
)


private_ref = annotated(
    {
        "type": "object",
        "required": ["ref_id", "access_class"],
        "properties": {
            "ref_id": ref("stableId", PRIVATE),
            "access_class": annotated({"const": "PRIVATE_ENVIRONMENT"}, PRIVATE),
        },
        "additionalProperties": False,
    },
    PRIVATE,
)

user_model = schema(
    "user-model",
    "User Model",
    [
        "user_model_id",
        "version",
        "private_world_state_ref",
        "answerable_facts",
        "response_policy",
        "ambiguity_policy",
        "correction_policy",
        "noise_policy",
        "maximum_turns",
        "oracle_access_rules",
        "template_family",
        "seed",
    ],
    {
        "user_model_id": ref("stableId", EVALUATION),
        "version": ref("versionIdentifier", EVALUATION),
        "private_world_state_ref": private_ref,
        "answerable_facts": stable_id_array(EVALUATION, uniqueItems=True),
        "response_policy": ref("stableId", EVALUATION),
        "ambiguity_policy": object_value(EVALUATION),
        "correction_policy": object_value(EVALUATION),
        "noise_policy": object_value(EVALUATION),
        "maximum_turns": integer(EVALUATION, minimum=0),
        "oracle_access_rules": object_value(EVALUATION),
        "template_family": ref("stableId", EVALUATION),
        "seed": integer(EVALUATION),
    },
)


instance_manifest = schema(
    "instance-manifest",
    "Instance Manifest",
    [
        "generator_id",
        "generator_version",
        "scenario_family",
        "seed",
        "difficulty_parameters",
        "constraint_graph_hash",
        "entity_graph_hash",
        "disruption_schedule_hash",
        "user_model_version",
        "source_dataset_lineage",
        "feasibility_oracle_version",
        "split_assignment",
    ],
    {
        "generator_id": ref("stableId", EVALUATION),
        "generator_version": ref("versionIdentifier", EVALUATION),
        "scenario_family": ref("stableId", EVALUATION),
        "seed": integer(EVALUATION),
        "difficulty_parameters": object_value(EVALUATION),
        "constraint_graph_hash": ref("contentHash", EVALUATION),
        "entity_graph_hash": ref("contentHash", EVALUATION),
        "disruption_schedule_hash": ref("contentHash", EVALUATION),
        "user_model_version": ref("versionIdentifier", EVALUATION),
        "source_dataset_lineage": stable_id_array(EVALUATION, minItems=1, uniqueItems=True),
        "feasibility_oracle_version": ref("versionIdentifier", EVALUATION),
        "split_assignment": annotated(
            {
                "enum": [
                    "TRAIN",
                    "DEVELOPMENT",
                    "TEST",
                    "TRANSFER",
                    "PROTECTED_REGRESSION",
                ]
            },
            EVALUATION,
        ),
    },
)


adapter_manifest = schema(
    "adapter-manifest",
    "Adapter Manifest",
    [
        "adapter_id",
        "base_model_hash",
        "training_data_version",
        "domain",
        "capability_scope",
        "rank",
        "target_modules",
        "router_features",
        "eval_report",
        "known_failures",
        "incompatibilities",
        "fallback_adapter",
        "status",
    ],
    {
        "adapter_id": ref("stableId", EVALUATION),
        "base_model_hash": ref("contentHash", EVALUATION),
        "training_data_version": ref("versionIdentifier", EVALUATION),
        "domain": ref("stableId", EVALUATION),
        "capability_scope": stable_id_array(EVALUATION, minItems=1, uniqueItems=True),
        "rank": integer(EVALUATION, minimum=1),
        "target_modules": stable_id_array(EVALUATION, minItems=1, uniqueItems=True),
        "router_features": stable_id_array(EVALUATION, uniqueItems=True),
        "eval_report": ref("evidenceRef", EVALUATION),
        "known_failures": stable_id_array(EVALUATION, uniqueItems=True),
        "incompatibilities": stable_id_array(EVALUATION, uniqueItems=True),
        "fallback_adapter": annotated(
            {
                "oneOf": [
                    {"$ref": "common.defs.schema.json#/$defs/stableId"},
                    {"type": "null"},
                ]
            },
            EVALUATION,
        ),
        "status": ref("stableId", EVALUATION),
    },
)


event = schema(
    "event",
    "Event",
    [
        "event_id",
        "episode_id",
        "event_type",
        "logical_clock",
        "timestamp",
        "source",
        "access_class",
        "payload",
        "provenance",
        "content_hash",
    ],
    {
        "event_id": ref("stableId", CONTROL),
        "episode_id": ref("stableId", CONTROL),
        "event_type": ref("stableId", CONTROL),
        "logical_clock": integer(CONTROL, minimum=0),
        "timestamp": normalized_time(CONTROL),
        "source": ref("provenanceSource", CONTROL),
        "access_class": ref("accessClass", CONTROL),
        "payload": object_value(CONTROL),
        "provenance": ref("provenance", CONTROL),
        "content_hash": ref("contentHash", ["VALIDATOR_VISIBLE", "EVALUATOR_ONLY"]),
        "supersedes_event_id": annotated(
            {
                "oneOf": [
                    {"$ref": "common.defs.schema.json#/$defs/stableId"},
                    {"type": "null"},
                ]
            },
            CONTROL,
        ),
    },
)


compensation_template = annotated(
    {
        "oneOf": [
            {"type": "null"},
            {
                "type": "object",
                "required": ["action_type", "arguments", "required_capabilities", "prevalidation_id"],
                "properties": {
                    "action_type": ref("stableId", EXECUTION),
                    "arguments": object_value(EXECUTION),
                    "required_capabilities": stable_id_array(
                        EXECUTION, minItems=1, uniqueItems=True
                    ),
                    "prevalidation_id": ref("stableId", CONTROL),
                },
                "additionalProperties": False,
            },
        ]
    },
    EXECUTION,
)

action_proposal = schema(
    "action-proposal",
    "Action Proposal",
    [
        "action_id",
        "plan_id",
        "actor_id",
        "state_version",
        "action_type",
        "arguments",
        "expected_preconditions",
        "expected_effects",
        "required_capabilities",
        "risk_class",
        "reversibility",
        "compensation_action",
        "postconditions",
        "audit_deadline",
        "evidence_refs",
        "confidence",
        "idempotency_key",
    ],
    {
        "action_id": ref("stableId", EXECUTION),
        "plan_id": ref("stableId", EXECUTION),
        "actor_id": ref("stableId", EXECUTION),
        "state_version": integer(EXECUTION, minimum=0),
        "action_type": ref("stableId", EXECUTION),
        "arguments": object_value(EXECUTION),
        "expected_preconditions": array({"type": "object"}, EXECUTION),
        "expected_effects": array({"type": "object"}, EXECUTION),
        "required_capabilities": stable_id_array(EXECUTION, minItems=1, uniqueItems=True),
        "risk_class": annotated(
            {"enum": ["LOW", "MODERATE", "HIGH", "CRITICAL"]}, EXECUTION
        ),
        "reversibility": ref("reversibility", EXECUTION),
        "compensation_action": compensation_template,
        "postconditions": array({"type": "object"}, EXECUTION),
        "audit_deadline": normalized_time(EXECUTION, nullable=True),
        "evidence_refs": evidence_array(EXECUTION),
        "confidence": probability(EXECUTION),
        "idempotency_key": ref("stableId", EXECUTION),
    },
    allOf=[
        {
            "if": {
                "properties": {"reversibility": {"const": "COMPENSATABLE"}},
                "required": ["reversibility"],
            },
            "then": {
                "properties": {
                    "compensation_action": {"type": "object"},
                    "audit_deadline": {
                        "$ref": "common.defs.schema.json#/$defs/normalizedTime"
                    },
                }
            },
        },
        {
            "if": {
                "properties": {"reversibility": {"const": "IRREVERSIBLE"}},
                "required": ["reversibility"],
            },
            "then": {
                "properties": {
                    "compensation_action": {"type": "null"}
                }
            },
        },
    ],
)


canonical_state = schema(
    "canonical-state",
    "Canonical State",
    [
        "schema_version",
        "episode_id",
        "state_version",
        "logical_clock",
        "entities",
        "resources",
        "obligations",
        "dependencies",
        "deadlines",
        "permissions",
        "active_plan",
        "completed_actions",
        "pending_questions",
        "exogenous_events",
        "provenance",
        "revision_chain",
    ],
    {
        "schema_version": ref("versionIdentifier", EVALUATION),
        "episode_id": ref("stableId", EVALUATION),
        "state_version": integer(EVALUATION, minimum=0),
        "logical_clock": integer(EVALUATION, minimum=0),
        "entities": object_value(EVALUATION),
        "resources": object_value(EVALUATION),
        "obligations": array({"type": "object"}, EVALUATION),
        "dependencies": array({"type": "object"}, EVALUATION),
        "deadlines": array({"type": "object"}, EVALUATION),
        "permissions": array({"type": "object"}, EVALUATION),
        "active_plan": object_value(EVALUATION, nullable=True),
        "completed_actions": stable_id_array(EVALUATION, uniqueItems=True),
        "pending_questions": array({"type": "object"}, EVALUATION),
        "exogenous_events": stable_id_array(EVALUATION, uniqueItems=True),
        "provenance": evidence_array(EVALUATION),
        "revision_chain": stable_id_array(EVALUATION, uniqueItems=True),
    },
)


policy_evidence_ref = {
    "type": "object",
    "required": ["ref_id", "source", "access_class"],
    "properties": {
        "ref_id": ref("stableId", POLICY),
        "source": ref("provenanceSource", POLICY),
        "access_class": annotated({"const": "POLICY_VISIBLE"}, POLICY),
        "uri": annotated({"type": ["string", "null"]}, POLICY),
        "content_hash": annotated(
            {
                "oneOf": [
                    {"$ref": "common.defs.schema.json#/$defs/contentHash"},
                    {"type": "null"},
                ]
            },
            POLICY,
        ),
    },
    "additionalProperties": False,
}

visible_fact = {
    "type": "object",
    "required": ["fact_id", "value", "epistemic_status", "evidence_refs", "access_class"],
    "properties": {
        "fact_id": ref("stableId", POLICY),
        "value": annotated({}, POLICY),
        "epistemic_status": ref("epistemicStatus", POLICY),
        "evidence_refs": array(policy_evidence_ref, POLICY),
        "access_class": annotated({"const": "POLICY_VISIBLE"}, POLICY),
    },
    "additionalProperties": False,
}

access_scoped_observation = schema(
    "access-scoped-observation",
    "Access-Scoped Observation",
    [
        "observation_id",
        "episode_id",
        "state_version",
        "actor_id",
        "access_class",
        "visible_facts",
        "goal_refs",
        "generated_at",
    ],
    {
        "observation_id": ref("stableId", POLICY),
        "episode_id": ref("stableId", POLICY),
        "state_version": integer(POLICY, minimum=0),
        "actor_id": ref("stableId", POLICY),
        "access_class": annotated({"const": "POLICY_VISIBLE"}, POLICY),
        "visible_facts": array(visible_fact, POLICY),
        "goal_refs": stable_id_array(POLICY, uniqueItems=True),
        "generated_at": normalized_time(POLICY),
        "context_budget_tokens": integer(POLICY, minimum=1),
    },
)


SCHEMAS = {
    "validator-result": validator_result,
    "supervisor-decision": supervisor_decision,
    "tool-outcome": tool_outcome,
    "outcome-vector": outcome_vector,
    "user-model": user_model,
    "instance-manifest": instance_manifest,
    "adapter-manifest": adapter_manifest,
    "event": event,
    "action-proposal": action_proposal,
    "canonical-state": canonical_state,
    "access-scoped-observation": access_scoped_observation,
}


def exact_time(instant: str = "2026-11-26T14:00:00Z") -> dict:
    return {
        "instant": instant,
        "source_timezone": "America/New_York",
        "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
    }


def evidence(ref_id: str = "evidence:1", source: str = "TOOL") -> dict:
    return {
        "ref_id": ref_id,
        "source": source,
        "access_class": "EVALUATOR_ONLY",
        "uri": None,
        "content_hash": None,
    }


def provenance() -> dict:
    return {
        "provenance_id": "provenance:1",
        "source": "ENVIRONMENT",
        "recorded_at": exact_time(),
        "access_class": "EVALUATOR_ONLY",
        "content_hash": "sha256:" + "a" * 64,
    }


VALID = {
    "validator-result": {
        "validator_id": "validator:capability",
        "validator_version": "1.0",
        "status": "UNKNOWN",
        "criticality": "HARD",
        "enforceability": "PREVENTABLE",
        "constraint_ids": ["constraint:capability"],
        "evidence_refs": [],
        "observed_state_version": 3,
        "uncertainty_reason": "Capability grant is not present in the observation.",
        "permitted_resolution": "QUERY",
        "explanation_code": "MISSING_CAPABILITY_EVIDENCE",
        "repair_hints": ["Request a scoped capability grant."],
        "timestamp": exact_time(),
    },
    "supervisor-decision": {
        "decision": "QUERY",
        "confidence": 0.74,
        "violated_constraint_ids": [],
        "uncertainty_reasons": ["Driver availability is unknown."],
        "requested_information": ["Is the designated driver available?"],
        "proposed_repair": None,
        "evidence_refs": [],
        "supervisor_model_version": "supervisor.1.0",
        "adapter_version": None,
    },
    "tool-outcome": {
        "outcome_id": "outcome:1",
        "action_id": "action:1",
        "tool_id": "tool:calendar",
        "tool_version": "2.1",
        "status": "SUCCEEDED",
        "started_at": exact_time(),
        "completed_at": exact_time("2026-11-26T14:00:01Z"),
        "raw_result_ref": evidence(),
        "normalized_effects": [{"reservation_status": "confirmed"}],
        "verified_effects": [{"reservation_status": "confirmed"}],
        "state_version_before": 3,
        "state_version_after": 4,
        "error_code": None,
        "idempotency_key": "idem:action:1",
    },
    "outcome-vector": {
        "goal_success": True,
        "constraint_score": 1,
        "hard_violation_count": 0,
        "optimality_gap": 0.05,
        "recovery_success": None,
        "execution_cost": 0.12,
        "latency": 1.4,
        "token_count": 512,
        "tool_calls": 1,
        "user_interventions": 1,
        "clarification_total": 1,
        "clarification_necessary": 1,
        "clarification_unnecessary": 0,
        "clarification_insufficient": 0,
        "clarification_repeated": 0,
        "clarification_incorrect_scope": 0,
        "evaluator_disagreement": 0,
    },
    "user-model": {
        "user_model_id": "user-model:p6-oracle",
        "version": "1.0",
        "private_world_state_ref": {
            "ref_id": "private-state:1",
            "access_class": "PRIVATE_ENVIRONMENT",
        },
        "answerable_facts": ["fact:driver-availability"],
        "response_policy": "DETERMINISTIC_ORACLE",
        "ambiguity_policy": {},
        "correction_policy": {},
        "noise_policy": {},
        "maximum_turns": 3,
        "oracle_access_rules": {"reveal_only_requested": True},
        "template_family": "template:p6-oracle",
        "seed": 42,
    },
    "instance-manifest": {
        "generator_id": "generator:realm",
        "generator_version": "1.0",
        "scenario_family": "P6",
        "seed": 42,
        "difficulty_parameters": {"entities": 8},
        "constraint_graph_hash": "sha256:" + "1" * 64,
        "entity_graph_hash": "sha256:" + "2" * 64,
        "disruption_schedule_hash": "sha256:" + "3" * 64,
        "user_model_version": "1.0",
        "source_dataset_lineage": ["dataset:realm-p6"],
        "feasibility_oracle_version": "solver.1.0",
        "split_assignment": "TEST",
    },
    "adapter-manifest": {
        "adapter_id": "adapter:p6",
        "base_model_hash": "sha256:" + "4" * 64,
        "training_data_version": "dataset.1.0",
        "domain": "realm:p6",
        "capability_scope": ["capability:planning"],
        "rank": 16,
        "target_modules": ["module:q_proj"],
        "router_features": ["feature:scenario-family"],
        "eval_report": evidence("report:adapter-p6", "EVALUATOR"),
        "known_failures": [],
        "incompatibilities": [],
        "fallback_adapter": None,
        "status": "CANDIDATE",
    },
    "event": {
        "event_id": "event:1",
        "episode_id": "episode:1",
        "event_type": "OBSERVE",
        "logical_clock": 1,
        "timestamp": exact_time(),
        "source": "ENVIRONMENT",
        "access_class": "EVALUATOR_ONLY",
        "payload": {"observation_ref": "observation:1"},
        "provenance": provenance(),
        "content_hash": "sha256:" + "5" * 64,
    },
    "action-proposal": {
        "action_id": "action:1",
        "plan_id": "plan:1",
        "actor_id": "worker:1",
        "state_version": 3,
        "action_type": "calendar:create-reservation",
        "arguments": {"slot": "14:00"},
        "expected_preconditions": [{"resource": "room:1", "available": True}],
        "expected_effects": [{"reservation": "created"}],
        "required_capabilities": ["calendar:write"],
        "risk_class": "MODERATE",
        "reversibility": "COMPENSATABLE",
        "compensation_action": {
            "action_type": "calendar:cancel-reservation",
            "arguments": {"reservation_ref": "pending"},
            "required_capabilities": ["calendar:write"],
            "prevalidation_id": "prevalidation:1",
        },
        "postconditions": [{"reservation": "confirmed"}],
        "audit_deadline": exact_time("2026-11-26T14:05:00Z"),
        "evidence_refs": [],
        "confidence": 0.91,
        "idempotency_key": "idem:action:1",
    },
    "canonical-state": {
        "schema_version": "1.0",
        "episode_id": "episode:1",
        "state_version": 3,
        "logical_clock": 7,
        "entities": {"person:1": {"role": "driver"}},
        "resources": {"vehicle:1": {"capacity": 4}},
        "obligations": [],
        "dependencies": [],
        "deadlines": [],
        "permissions": [],
        "active_plan": {"plan_id": "plan:1"},
        "completed_actions": ["action:0"],
        "pending_questions": [],
        "exogenous_events": ["event:weather"],
        "provenance": [],
        "revision_chain": ["state:2"],
    },
    "access-scoped-observation": {
        "observation_id": "observation:1",
        "episode_id": "episode:1",
        "state_version": 3,
        "actor_id": "worker:1",
        "access_class": "POLICY_VISIBLE",
        "visible_facts": [
            {
                "fact_id": "fact:driver-availability",
                "value": "available",
                "epistemic_status": "OBSERVED",
                "evidence_refs": [],
                "access_class": "POLICY_VISIBLE",
            }
        ],
        "goal_refs": ["goal:transport"],
        "generated_at": exact_time(),
        "context_budget_tokens": 2048,
    },
}


def invalid_copy(schema_name: str, suffix: str, mutate) -> tuple[str, dict]:
    value = json.loads(json.dumps(VALID[schema_name]))
    mutate(value)
    return f"{schema_name}.{suffix}.invalid.json", value


INVALID = {
    "validator-result": [
        invalid_copy("validator-result", "hard-unknown-execute", lambda x: x.update(permitted_resolution="EXECUTE")),
        invalid_copy("validator-result", "pass-repair", lambda x: x.update(status="PASS", uncertainty_reason=None, permitted_resolution="REPAIR")),
    ],
    "supervisor-decision": [
        invalid_copy("supervisor-decision", "confidence", lambda x: x.update(confidence=1.1)),
        invalid_copy("supervisor-decision", "query-empty", lambda x: x.update(requested_information=[])),
    ],
    "tool-outcome": [
        invalid_copy("tool-outcome", "missing-version", lambda x: x.pop("tool_version")),
        invalid_copy("tool-outcome", "state-version", lambda x: x.update(state_version_before=-1)),
    ],
    "outcome-vector": [
        invalid_copy("outcome-vector", "negative-count", lambda x: x.update(tool_calls=-1)),
        invalid_copy("outcome-vector", "score-range", lambda x: x.update(constraint_score=1.1)),
    ],
    "user-model": [
        invalid_copy("user-model", "private-leak", lambda x: x["private_world_state_ref"].update(access_class="POLICY_VISIBLE")),
        invalid_copy("user-model", "turn-bound", lambda x: x.update(maximum_turns=-1)),
    ],
    "instance-manifest": [
        invalid_copy("instance-manifest", "hash", lambda x: x.update(entity_graph_hash="not-a-hash")),
        invalid_copy("instance-manifest", "empty-lineage", lambda x: x.update(source_dataset_lineage=[])),
    ],
    "adapter-manifest": [
        invalid_copy("adapter-manifest", "rank", lambda x: x.update(rank=0)),
        invalid_copy("adapter-manifest", "empty-targets", lambda x: x.update(target_modules=[])),
    ],
    "event": [
        invalid_copy("event", "logical-clock", lambda x: x.update(logical_clock=-1)),
        invalid_copy("event", "hash", lambda x: x.update(content_hash="5" * 63)),
    ],
    "action-proposal": [
        invalid_copy("action-proposal", "compensation-null", lambda x: x.update(compensation_action=None)),
        invalid_copy("action-proposal", "audit-null", lambda x: x.update(audit_deadline=None)),
        invalid_copy(
            "action-proposal",
            "irreversible-compensation",
            lambda x: x.update(reversibility="IRREVERSIBLE"),
        ),
    ],
    "canonical-state": [
        invalid_copy("canonical-state", "state-version", lambda x: x.update(state_version=-1)),
        invalid_copy("canonical-state", "extra-field", lambda x: x.update(private_world_state={"secret": True})),
    ],
    "access-scoped-observation": [
        invalid_copy("access-scoped-observation", "private-field", lambda x: x.update(private_world_state_ref={"ref_id": "private:1"})),
        invalid_copy("access-scoped-observation", "evaluator-field", lambda x: x.update(evaluator_labels=[])),
        invalid_copy("access-scoped-observation", "access-class", lambda x: x.update(access_class="EVALUATOR_ONLY")),
    ],
}


TICKETS = {
    "B1-1": ("validator-result", "Spec §10.1; Amendment §4"),
    "B1-2": ("supervisor-decision", "Spec §10.2; Amendment §4"),
    "B1-3": ("tool-outcome", "Spec §2.4; §10.4; Amendment §§2, 4"),
    "B1-4": ("outcome-vector", "Spec §10.3; Amendment §4"),
    "B1-5": ("user-model", "Spec §3.4; Amendment §4"),
    "B1-6": ("instance-manifest", "Spec §8.4; Amendment §4"),
    "B1-7": ("adapter-manifest", "Spec §6; Amendment §4"),
    "B1-8": ("event", "Spec §§2.1-2.4; Amendment §4"),
    "B2-1": ("action-proposal", "Spec §§2.3–2.4; Amendment §5"),
    "B2-2": ("canonical-state", "Spec §§2.1–2.2, 2.4; Amendment §5"),
    "B2-3": ("access-scoped-observation", "Spec §§2.1, 4; Amendment §5"),
}


def ticket_note(ticket: str, name: str, source: str) -> str:
    fields = list(SCHEMAS[name]["properties"])
    access_rows = [
        f"| `{field}` | {', '.join(definition['x-access-class'])} |"
        for field, definition in SCHEMAS[name]["properties"].items()
    ]
    invalid_names = [entry[0] for entry in INVALID[name]]
    return f"""# {ticket}: `{name}.schema.json`

**Status:** DONE
**Specification:** {source}

## Field inventory

{', '.join(f'`{field}`' for field in fields)}

## Access-class inventory

| Field | Authorized consumers |
|---|---|
{chr(10).join(access_rows)}

## Constraint inventory

- The contract is a closed object. Its `required` array is authoritative;
  nullable fields use explicit `null` unions rather than accidental absence.
- Stable IDs, versions, hashes, normalized times, provenance, evidence, and
  approved enums reference `common.defs.schema.json`.
- Arrays constrain item types; identifier sets that represent scopes or
  references reject duplicates.
- Numeric confidence/score fields are bounded to `[0, 1]`; counts, clocks,
  versions, costs, and latency reject negative values where applicable.
- Contract-specific conditionals and access restrictions are encoded directly
  in the schema.
- Required-field/type, enum, pattern/reference, bound, closed-object, and
  conditional failures are treated as equivalence classes. The package-level
  shared-definition corpus covers the referenced primitives; the ticket
  fixtures cover the contract-specific classes.

## Fixtures and validation

- Valid: `fixtures/valid/{name}.valid.json`
- Invalid: {', '.join(f'`fixtures/invalid/{item}`' for item in invalid_names)}
- Both pinned validators are exercised by the package checker.

## Deferred invariants

No new deferred invariant was required. Applicable cross-artifact, temporal,
authorization, integrity, or semantic requirements are already owned by
`deferred-invariants.md`.

## Review

Independent specification-fidelity review completed. See
`outputs/B1_B2_Specification_Fidelity_Review.md`.
"""


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for name, value in SCHEMAS.items():
        write_json(ROOT / f"{name}.schema.json", value)
        write_json(ROOT / "fixtures" / "valid" / f"{name}.valid.json", VALID[name])
        for filename, invalid in INVALID[name]:
            write_json(ROOT / "fixtures" / "invalid" / filename, invalid)

    for ticket, (name, source) in TICKETS.items():
        (ROOT / "tickets" / f"{ticket}.md").write_text(
            ticket_note(ticket, name, source), encoding="utf-8"
        )

    fixture_manifest = json.loads((ROOT / "fixture-manifest.json").read_text(encoding="utf-8"))
    fixture_manifest["fixtures"] = [
        entry
        for entry in fixture_manifest["fixtures"]
        if entry.get("batch", "batch0") == "batch0"
    ]
    for entry in fixture_manifest["fixtures"]:
        entry["batch"] = "batch0"
    fixture_manifest["batch"] = "batches0-2"
    for ticket, (name, _) in TICKETS.items():
        batch = "batch1" if ticket.startswith("B1") else "batch2"
        fixture_manifest["fixtures"].append(
            {
                "path": f"fixtures/valid/{name}.valid.json",
                "schema": f"{name}.schema.json",
                "batch": batch,
                "expected": "valid",
                "constraints": ["ticket valid representative"],
            }
        )
        for filename, _ in INVALID[name]:
            fixture_manifest["fixtures"].append(
                {
                    "path": f"fixtures/invalid/{filename}",
                    "schema": f"{name}.schema.json",
                    "batch": batch,
                    "expected": "invalid",
                    "constraint": filename.removesuffix(".invalid.json"),
                }
            )
    write_json(ROOT / "fixture-manifest.json", fixture_manifest)

    mutation_registry = json.loads((ROOT / "mutation-registry.json").read_text(encoding="utf-8"))
    for mutation in mutation_registry["mutations"]:
        if mutation["batch"] in {"batch1", "batch2"}:
            mutation["status"] = "ACTIVE"
    write_json(ROOT / "mutation-registry.json", mutation_registry)

    print(f"Wrote {len(SCHEMAS)} schemas, {len(VALID)} valid fixtures, "
          f"{sum(map(len, INVALID.values()))} invalid fixtures, and "
          f"{len(TICKETS)} ticket notes.")


if __name__ == "__main__":
    main()
