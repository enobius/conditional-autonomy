"""Generate Workstream 1A ticket B3-2 artifacts."""

from __future__ import annotations

import copy
import json

from build_batch_3_1 import valid_trace
from build_batches_1_2 import (
    EVALUATION,
    ROOT,
    VALID,
    annotated,
    array,
    ref,
    schema,
    write_json,
)


episode = schema(
    "episode",
    "Episode",
    [
        "episode_id",
        "environment_version",
        "schema_version",
        "generator_manifest_ref",
        "user_model_ref",
        "policy_versions",
        "steps",
        "final_outcome",
        "split_assignment",
        "event_log_hash",
        "terminal_status",
    ],
    {
        "episode_id": ref("stableId", EVALUATION),
        "environment_version": ref("versionIdentifier", EVALUATION),
        "schema_version": ref("versionIdentifier", EVALUATION),
        "generator_manifest_ref": ref("stableId", EVALUATION),
        "user_model_ref": ref("stableId", EVALUATION),
        "policy_versions": array(
            {"$ref": "common.defs.schema.json#/$defs/versionIdentifier"},
            EVALUATION,
            minItems=1,
            uniqueItems=True,
        ),
        "steps": array(
            {"$ref": "trace-step.schema.json"},
            EVALUATION,
            minItems=1,
        ),
        "final_outcome": annotated(
            {"$ref": "outcome-vector.schema.json"}, EVALUATION
        ),
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
        "event_log_hash": ref("contentHash", EVALUATION),
        "terminal_status": ref("stableId", EVALUATION),
    },
)


valid_episode = {
    "episode_id": "episode:1",
    "environment_version": "realm-p6.1.0",
    "schema_version": "1.0",
    "generator_manifest_ref": "instance-manifest:episode-1",
    "user_model_ref": "user-model:p6-oracle:1.0",
    "policy_versions": ["policy.1.0"],
    "steps": [copy.deepcopy(valid_trace)],
    "final_outcome": copy.deepcopy(VALID["outcome-vector"]),
    "split_assignment": "TEST",
    "event_log_hash": "sha256:" + "6" * 64,
    "terminal_status": "COMPLETED",
}


def invalid(suffix: str, mutate) -> tuple[str, dict]:
    value = copy.deepcopy(valid_episode)
    mutate(value)
    return f"episode.{suffix}.invalid.json", value


invalid_episodes = [
    invalid("empty-steps", lambda value: value.update(steps=[])),
    invalid(
        "trace-canonical-access",
        lambda value: value["steps"][0]["canonical_state_ref"].update(
            access_class="POLICY_VISIBLE"
        ),
    ),
    invalid(
        "final-outcome-count",
        lambda value: value["final_outcome"].update(hard_violation_count=-1),
    ),
    invalid("event-log-hash", lambda value: value.update(event_log_hash="bad-hash")),
    invalid(
        "missing-environment-version",
        lambda value: value.pop("environment_version"),
    ),
    invalid("empty-policy-versions", lambda value: value.update(policy_versions=[])),
    invalid("split-assignment", lambda value: value.update(split_assignment="VALIDATION")),
    invalid(
        "additional-field",
        lambda value: value.update(hidden_training_payload={"secret": True}),
    ),
]


ticket_note = """# B3-2: `episode.schema.json`

**Status:** DONE
**Specification:** Spec §§4–5; Amendment §6

## Field inventory

`episode_id`, `environment_version`, `schema_version`,
`generator_manifest_ref`, `user_model_ref`, `policy_versions`, `steps`,
`final_outcome`, `split_assignment`, `event_log_hash`, `terminal_status`

## Access-class inventory

| Field | Authorized consumers |
|---|---|
| `episode_id` | EVALUATOR_ONLY |
| `environment_version` | EVALUATOR_ONLY |
| `schema_version` | EVALUATOR_ONLY |
| `generator_manifest_ref` | EVALUATOR_ONLY |
| `user_model_ref` | EVALUATOR_ONLY |
| `policy_versions` | EVALUATOR_ONLY |
| `steps` | EVALUATOR_ONLY |
| `final_outcome` | EVALUATOR_ONLY |
| `split_assignment` | EVALUATOR_ONLY |
| `event_log_hash` | EVALUATOR_ONLY |
| `terminal_status` | EVALUATOR_ONLY |

## Constraint inventory

- The episode is a closed evaluator-only object with an explicit required set.
- Stable IDs, versions, and the event-log hash use shared definitions.
- `policy_versions` is a non-empty unique set of version identifiers.
- `steps` is a non-empty array composed from `trace-step.schema.json`.
- `final_outcome` composes `outcome-vector.schema.json`.
- Split labels match the specification's byte-exact dataset partitions.
- Required/type, enum, pattern/reference, array-bound, closed-object, nested
  composition, and access-leakage constraints are covered as equivalence
  classes.

## Fixtures and validation

- Valid: `fixtures/valid/episode.valid.json`
- Invalid:
  - `fixtures/invalid/episode.empty-steps.invalid.json`
  - `fixtures/invalid/episode.trace-canonical-access.invalid.json`
  - `fixtures/invalid/episode.final-outcome-count.invalid.json`
  - `fixtures/invalid/episode.event-log-hash.invalid.json`
  - `fixtures/invalid/episode.missing-environment-version.invalid.json`
  - `fixtures/invalid/episode.empty-policy-versions.invalid.json`
  - `fixtures/invalid/episode.split-assignment.invalid.json`
  - `fixtures/invalid/episode.additional-field.invalid.json`
- Both pinned validators are exercised by `--batch batch3` and `--batch all`.

## Deferred invariants

- `INV-003` owns artifact-reference integrity.
- `INV-008` owns replay equality.
- `INV-011` owns clarification-counter reconciliation.
- `INV-013` owns split leakage.
- `INV-015` owns event-log hash correctness.
- `INV-016` owns episode trace-step identity, membership, and ordering.

## Review

Independent specification-fidelity review completed by Manny Reviewer on
2026-07-30. See `outputs/B3_2_Specification_Fidelity_Review.md`.
"""


def main() -> None:
    write_json(ROOT / "episode.schema.json", episode)
    write_json(ROOT / "fixtures" / "valid" / "episode.valid.json", valid_episode)
    for filename, value in invalid_episodes:
        write_json(ROOT / "fixtures" / "invalid" / filename, value)
    (ROOT / "tickets" / "B3-2.md").write_text(ticket_note, encoding="utf-8")

    manifest = json.loads((ROOT / "fixture-manifest.json").read_text(encoding="utf-8"))
    manifest["batch"] = "batches0-3"
    manifest["fixtures"] = [
        entry
        for entry in manifest["fixtures"]
        if entry.get("schema") != "episode.schema.json"
        and "episode." not in entry["path"]
    ]
    manifest["fixtures"].append(
        {
            "path": "fixtures/valid/episode.valid.json",
            "schema": "episode.schema.json",
            "batch": "batch3",
            "expected": "valid",
            "constraints": ["composite episode representative"],
        }
    )
    for filename, _ in invalid_episodes:
        manifest["fixtures"].append(
            {
                "path": f"fixtures/invalid/{filename}",
                "schema": "episode.schema.json",
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
        if mutation["id"] != "MUT-B3-002"
    ]
    mutations["mutations"].append(
        {
            "id": "MUT-B3-002",
            "batch": "batch3",
            "status": "ACTIVE",
            "description": (
                "Permit an episode with no trace steps; the empty-steps "
                "fixture must fail."
            ),
        }
    )
    write_json(ROOT / "mutation-registry.json", mutations)

    print(
        "Wrote episode schema, 1 valid fixture, "
        f"{len(invalid_episodes)} invalid fixtures, ticket evidence, and mutation."
    )


if __name__ == "__main__":
    main()
