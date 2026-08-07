from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.projection import (
    AccessBoundaryError,
    ProjectionSourceError,
    project_observation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def canonical_state() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "episode_id": "episode:1",
        "state_version": 3,
        "logical_clock": 7,
        "entities": {},
        "resources": {
            "projection_facts": {
                "driver": {
                    "fact_id": "fact:driver-availability",
                    "value": "available",
                    "epistemic_status": "OBSERVED",
                    "evidence_refs": [],
                    "access_class": "POLICY_VISIBLE",
                }
            }
        },
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


GENERATED_AT = {
    "instant": "2026-11-26T14:00:00Z",
    "source_timezone": "America/New_York",
    "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
}


def project(state: dict[str, object]):
    return project_observation(
        state,
        observation_id="observation:1",
        actor_id="worker:1",
        source_paths=("/resources/projection_facts/driver",),
        goal_refs=("goal:transport",),
        generated_at=GENERATED_AT,
        context_budget_tokens=2048,
    )


class ObservationProjectorTests(unittest.TestCase):
    def test_projected_output_matches_contract_fixture_and_records_lineage(self) -> None:
        state = canonical_state()
        before = deepcopy(state)
        result = project(state)
        self.assertEqual(state, before)
        fixture = REPO_ROOT / "architecture/schemas/v1.0/fixtures/valid/access-scoped-observation.valid.json"
        expected = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(result.observation, expected)
        self.assertEqual(len(result.lineage), 1)
        entry = result.lineage[0]
        self.assertEqual(entry.output_path, "/visible_facts/0")
        self.assertEqual(entry.source_path, "/resources/projection_facts/driver")
        self.assertEqual(entry.source_episode_id, "episode:1")
        self.assertEqual(entry.source_state_version, 3)
        self.assertEqual(entry.source_access_class, "POLICY_VISIBLE")

    def test_protected_root_canaries_fail_closed(self) -> None:
        for access_class in (
            "PRIVATE_ENVIRONMENT",
            "EVALUATOR_ONLY",
            "VALIDATOR_VISIBLE",
        ):
            with self.subTest(access_class=access_class):
                state = canonical_state()
                state["resources"]["projection_facts"]["driver"]["access_class"] = access_class  # type: ignore[index]
                with self.assertRaisesRegex(AccessBoundaryError, access_class):
                    project(state)

    def test_nested_protected_canary_in_value_fails_closed(self) -> None:
        state = canonical_state()
        state["resources"]["projection_facts"]["driver"]["value"] = {  # type: ignore[index]
            "availability": "available",
            "private_state": {"access_class": "PRIVATE_ENVIRONMENT", "value": "canary"},
        }
        with self.assertRaisesRegex(AccessBoundaryError, "PRIVATE_ENVIRONMENT"):
            project(state)

    def test_each_named_protected_ancestor_fails_closed(self) -> None:
        for access_class in (
            "PRIVATE_ENVIRONMENT",
            "EVALUATOR_ONLY",
            "VALIDATOR_VISIBLE",
            "SUPERVISOR_VISIBLE",
        ):
            with self.subTest(access_class=access_class):
                state = canonical_state()
                state["resources"]["projection_facts"]["access_class"] = access_class  # type: ignore[index]
                with self.assertRaisesRegex(AccessBoundaryError, access_class):
                    project(state)

    def test_unknown_non_policy_ancestor_fails_closed(self) -> None:
        state = canonical_state()
        state["resources"]["projection_facts"]["access_class"] = "SECRET_UNKNOWN"  # type: ignore[index]
        with self.assertRaisesRegex(AccessBoundaryError, "SECRET_UNKNOWN"):
            project(state)

    def test_observation_accessor_returns_defensive_copies(self) -> None:
        result = project(canonical_state())
        first = result.observation
        first["visible_facts"][0]["value"] = "mutated"
        self.assertEqual(result.observation["visible_facts"][0]["value"], "available")

    def test_missing_and_duplicate_sources_fail_closed(self) -> None:
        with self.assertRaisesRegex(ProjectionSourceError, "does not exist"):
            project_observation(
                canonical_state(), observation_id="observation:1", actor_id="worker:1",
                source_paths=("/resources/missing",), goal_refs=(), generated_at=GENERATED_AT,
            )
        with self.assertRaisesRegex(ProjectionSourceError, "duplicates"):
            project_observation(
                canonical_state(), observation_id="observation:1", actor_id="worker:1",
                source_paths=("/resources/projection_facts/driver", "/resources/projection_facts/driver"),
                goal_refs=(), generated_at=GENERATED_AT,
            )

    def test_malformed_fact_and_metadata_fail_schema_validation(self) -> None:
        state = canonical_state()
        del state["resources"]["projection_facts"]["driver"]["epistemic_status"]  # type: ignore[index]
        with self.assertRaisesRegex(ProjectionSourceError, "projected observation"):
            project(state)
        with self.assertRaisesRegex(ProjectionSourceError, "projected observation"):
            project_observation(
                canonical_state(), observation_id="invalid id with spaces", actor_id="worker:1",
                source_paths=(), goal_refs=(), generated_at=GENERATED_AT,
            )

    def test_invalid_canonical_state_fails_before_projection(self) -> None:
        state = canonical_state()
        state["state_version"] = -1
        with self.assertRaisesRegex(ProjectionSourceError, "canonical state"):
            project(state)

    def test_output_is_deterministic_across_python_hash_seeds(self) -> None:
        script = r'''
import json
from tests.test_projection import canonical_state, project
result = project(canonical_state())
print(json.dumps({"observation": result.observation, "lineage": [entry.__dict__ for entry in result.lineage]}, sort_keys=True, separators=(",", ":")))
'''
        outputs = []
        for seed in ("1", "91"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outputs.append(subprocess.check_output([sys.executable, "-c", script], text=True, env=env).strip())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
