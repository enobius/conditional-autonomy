"""Generate Workstream 1A ticket B3-1 artifacts.

The trace-step contract composes the reviewed Batch 1 and Batch 2 schemas.
Canonical state remains an evaluator-only reference and is never embedded.
"""

from __future__ import annotations

import copy
import json

from build_batches_1_2 import (
    EVALUATION,
    EXECUTION,
    POLICY,
    ROOT,
    VALID,
    annotated,
    array,
    evidence,
    integer,
    ref,
    schema,
    write_json,
)


CONTROL = ["SUPERVISOR_VISIBLE", "VALIDATOR_VISIBLE", "EVALUATOR_ONLY"]


canonical_state_ref = annotated(
    {
        "type": "object",
        "required": ["ref_id", "access_class"],
        "properties": {
            "ref_id": ref("stableId", EVALUATION),
            "access_class": annotated({"const": "EVALUATOR_ONLY"}, EVALUATION),
        },
        "additionalProperties": False,
    },
    EVALUATION,
)

trace_step = schema(
    "trace-step",
    "Trace Step",
    [
        "trace_step_id",
        "episode_id",
        "step_index",
        "canonical_state_ref",
        "actor_observation",
        "goal_ref",
        "policy_version",
        "adapter_version",
        "proposal",
        "supervisor_decision",
        "validator_results",
        "tool_result",
        "transition_diff",
        "outcome_vector",
        "evaluator_labels",
        "provenance",
    ],
    {
        "trace_step_id": ref("stableId", EVALUATION),
        "episode_id": ref("stableId", EVALUATION),
        "step_index": integer(EVALUATION, minimum=0),
        "canonical_state_ref": canonical_state_ref,
        "actor_observation": annotated(
            {"$ref": "access-scoped-observation.schema.json"}, POLICY
        ),
        "goal_ref": ref("stableId", POLICY),
        "policy_version": ref("versionIdentifier", EXECUTION),
        "adapter_version": annotated(
            {
                "oneOf": [
                    {"$ref": "common.defs.schema.json#/$defs/versionIdentifier"},
                    {"type": "null"},
                ]
            },
            EXECUTION,
        ),
        "proposal": annotated(
            {
                "oneOf": [
                    {"$ref": "action-proposal.schema.json"},
                    {"type": "null"},
                ]
            },
            EXECUTION,
        ),
        "supervisor_decision": annotated(
            {
                "oneOf": [
                    {"$ref": "supervisor-decision.schema.json"},
                    {"type": "null"},
                ]
            },
            CONTROL,
        ),
        "validator_results": array(
            {"$ref": "validator-result.schema.json"}, CONTROL
        ),
        "tool_result": annotated(
            {
                "oneOf": [
                    {"$ref": "tool-outcome.schema.json"},
                    {"type": "null"},
                ]
            },
            CONTROL,
        ),
        "transition_diff": annotated({"type": "object"}, EVALUATION),
        "outcome_vector": annotated(
            {"$ref": "outcome-vector.schema.json"}, EVALUATION
        ),
        "evaluator_labels": array({"type": "object"}, EVALUATION),
        "provenance": array(
            {"$ref": "common.defs.schema.json#/$defs/evidenceRef"},
            EVALUATION,
        ),
    },
)


valid_trace = {
    "trace_step_id": "trace-step:1",
    "episode_id": "episode:1",
    "step_index": 0,
    "canonical_state_ref": {
        "ref_id": "state:episode-1:version-3",
        "access_class": "EVALUATOR_ONLY",
    },
    "actor_observation": copy.deepcopy(VALID["access-scoped-observation"]),
    "goal_ref": "goal:transport",
    "policy_version": "policy.1.0",
    "adapter_version": None,
    "proposal": copy.deepcopy(VALID["action-proposal"]),
    "supervisor_decision": copy.deepcopy(VALID["supervisor-decision"]),
    "validator_results": [copy.deepcopy(VALID["validator-result"])],
    "tool_result": copy.deepcopy(VALID["tool-outcome"]),
    "transition_diff": {
        "from_state_version": 3,
        "to_state_version": 4,
        "changed_fact_ids": ["fact:reservation-status"],
    },
    "outcome_vector": copy.deepcopy(VALID["outcome-vector"]),
    "evaluator_labels": [{"label": "SAFE_SUCCESS", "confidence": 1}],
    "provenance": [evidence("trace-evidence:1", "ENVIRONMENT")],
}


def invalid(suffix: str, mutate) -> tuple[str, dict]:
    value = copy.deepcopy(valid_trace)
    mutate(value)
    return f"trace-step.{suffix}.invalid.json", value


invalid_traces = [
    invalid(
        "canonical-ref-access",
        lambda value: value["canonical_state_ref"].update(
            access_class="POLICY_VISIBLE"
        ),
    ),
    invalid(
        "canonical-state-embedded",
        lambda value: value.update(
            canonical_state_ref=copy.deepcopy(VALID["canonical-state"])
        ),
    ),
    invalid(
        "observation-private-leak",
        lambda value: value["actor_observation"].update(
            private_world_state_ref={"ref_id": "private-state:1"}
        ),
    ),
    invalid(
        "observation-evaluator-leak",
        lambda value: value["actor_observation"].update(
            evaluator_labels=[{"label": "hidden"}]
        ),
    ),
    invalid("missing-policy-version", lambda value: value.pop("policy_version")),
    invalid("step-index", lambda value: value.update(step_index=-1)),
    invalid(
        "nested-validator-guard",
        lambda value: value["validator_results"][0].update(
            permitted_resolution="EXECUTE"
        ),
    ),
]


ticket_note = """# B3-1: `trace-step.schema.json`

**Status:** DONE
**Specification:** Spec §4; Amendment §§5–6

## Field inventory

`trace_step_id`, `episode_id`, `step_index`, `canonical_state_ref`,
`actor_observation`, `goal_ref`, `policy_version`, `adapter_version`,
`proposal`, `supervisor_decision`, `validator_results`, `tool_result`,
`transition_diff`, `outcome_vector`, `evaluator_labels`, `provenance`

## Access-class inventory

| Field | Authorized consumers |
|---|---|
| `trace_step_id` | EVALUATOR_ONLY |
| `episode_id` | EVALUATOR_ONLY |
| `step_index` | EVALUATOR_ONLY |
| `canonical_state_ref` | EVALUATOR_ONLY |
| `actor_observation` | POLICY_VISIBLE |
| `goal_ref` | POLICY_VISIBLE |
| `policy_version` | POLICY_VISIBLE, SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `adapter_version` | POLICY_VISIBLE, SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `proposal` | POLICY_VISIBLE, SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `supervisor_decision` | SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `validator_results` | SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `tool_result` | SUPERVISOR_VISIBLE, VALIDATOR_VISIBLE, EVALUATOR_ONLY |
| `transition_diff` | EVALUATOR_ONLY |
| `outcome_vector` | EVALUATOR_ONLY |
| `evaluator_labels` | EVALUATOR_ONLY |
| `provenance` | EVALUATOR_ONLY |

## Constraint inventory

- The trace step is a closed object with an explicit required-field set.
- IDs and versions use shared stable-ID and version definitions.
- `step_index` is a nonnegative integer.
- `canonical_state_ref` is a closed reference object whose runtime
  `access_class` is exactly `EVALUATOR_ONLY`; canonical state cannot be
  embedded.
- `actor_observation`, proposals, decisions, validator results, tool outcomes,
  and outcome vectors compose their reviewed v1.0 contracts by `$ref`.
- Proposal, supervisor decision, tool result, and adapter version are explicit
  nullable values so absence is not confused with an omitted field.
- Observation leakage, nested-validator semantics, required/type/bound,
  closed-object, reference-closure, and access constraints are covered as
  equivalence classes.

## Fixtures and validation

- Valid: `fixtures/valid/trace-step.valid.json`
- Invalid:
  - `fixtures/invalid/trace-step.canonical-ref-access.invalid.json`
  - `fixtures/invalid/trace-step.canonical-state-embedded.invalid.json`
  - `fixtures/invalid/trace-step.observation-private-leak.invalid.json`
  - `fixtures/invalid/trace-step.observation-evaluator-leak.invalid.json`
  - `fixtures/invalid/trace-step.missing-policy-version.invalid.json`
  - `fixtures/invalid/trace-step.step-index.invalid.json`
  - `fixtures/invalid/trace-step.nested-validator-guard.invalid.json`
- Both pinned validators are exercised by `--batch batch3` and `--batch all`.

## Deferred invariants

No new deferred invariant is required. Referential integrity, current-version
checks, policy-input leakage, replay equality, clarification reconciliation,
and integrity hashes are already assigned in `deferred-invariants.md`.

## Review

Independent specification-fidelity review completed by Manny Reviewer on
2026-07-30. See `outputs/B3_1_Specification_Fidelity_Review.md`.
"""


def main() -> None:
    write_json(ROOT / "trace-step.schema.json", trace_step)
    write_json(ROOT / "fixtures" / "valid" / "trace-step.valid.json", valid_trace)
    for filename, value in invalid_traces:
        write_json(ROOT / "fixtures" / "invalid" / filename, value)
    (ROOT / "tickets" / "B3-1.md").write_text(ticket_note, encoding="utf-8")

    manifest = json.loads((ROOT / "fixture-manifest.json").read_text(encoding="utf-8"))
    manifest["batch"] = "batches0-3"
    manifest["fixtures"] = [
        entry
        for entry in manifest["fixtures"]
        if entry.get("schema") != "trace-step.schema.json"
        and "trace-step." not in entry["path"]
    ]
    manifest["fixtures"].append(
        {
            "path": "fixtures/valid/trace-step.valid.json",
            "schema": "trace-step.schema.json",
            "batch": "batch3",
            "expected": "valid",
            "constraints": ["composite trace-step representative"],
        }
    )
    for filename, _ in invalid_traces:
        manifest["fixtures"].append(
            {
                "path": f"fixtures/invalid/{filename}",
                "schema": "trace-step.schema.json",
                "batch": "batch3",
                "expected": "invalid",
                "constraint": filename.removesuffix(".invalid.json"),
            }
        )
    write_json(ROOT / "fixture-manifest.json", manifest)

    mutations = json.loads(
        (ROOT / "mutation-registry.json").read_text(encoding="utf-8")
    )
    mutations["mutations"] = [
        mutation
        for mutation in mutations["mutations"]
        if mutation["id"] != "MUT-B3-001"
    ]
    mutations["mutations"].append(
        {
            "id": "MUT-B3-001",
            "batch": "batch3",
            "status": "ACTIVE",
            "description": (
                "Permit canonical_state_ref to be POLICY_VISIBLE; the trace "
                "leakage fixture must fail."
            ),
        }
    )
    write_json(ROOT / "mutation-registry.json", mutations)

    print(
        "Wrote trace-step schema, 1 valid fixture, "
        f"{len(invalid_traces)} invalid fixtures, ticket evidence, and mutation."
    )


if __name__ == "__main__":
    main()
