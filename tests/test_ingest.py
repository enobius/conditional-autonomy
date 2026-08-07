from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runtime.conditional_autonomy.ingest import (
    INGEST_VALIDATORS,
    artifact_integrity_check,
    artifact_reference_check,
    event_id_uniqueness_check,
    policy_input_leakage_check,
)
from runtime.conditional_autonomy.preexecution import InvariantDisposition, Verdict
from runtime.conditional_autonomy.projection import ObservationProjection, project_observation
from runtime.conditional_autonomy.references import ArtifactReferenceResolver
from runtime.conditional_autonomy.storage import AppendOnlyStore, canonical_json_bytes
from tests.test_projection import GENERATED_AT, canonical_state, project
from tests.test_storage import event


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "invariants" / "corpus.json"
INGEST_IDS = {"INV-003", "INV-005", "INV-014", "INV-015"}


class BrokenIterable:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __iter__(self):
        raise self.error


class IngestValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = AppendOnlyStore(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def assert_quarantine(self, outcome, invariant_id: str) -> None:
        self.assertEqual(outcome.invariant_id, invariant_id)
        self.assertIs(outcome.verdict, Verdict.FAIL)
        self.assertIs(outcome.failure_resolution, InvariantDisposition.QUARANTINE)
        self.assertTrue(outcome.failure_codes)

    def test_named_registry_is_exact(self) -> None:
        self.assertEqual(
            set(INGEST_VALIDATORS),
            {
                "artifact_reference_check",
                "event_id_uniqueness_check",
                "policy_input_leakage_check",
                "artifact_integrity_check",
            },
        )

    def test_reference_check_reuses_typed_resolver(self) -> None:
        self.store.put_artifact("event:1", "event", {"artifact_id": "event:1"})
        resolver = ArtifactReferenceResolver(self.store)
        passed = artifact_reference_check(resolver, [("event:1", "event")])
        self.assertIs(passed.verdict, Verdict.PASS)
        wrong = artifact_reference_check(resolver, [("event:1", "action-proposal")])
        self.assert_quarantine(wrong, "INV-003")
        self.assertEqual(wrong.failure_codes, ("WRONG_ARTIFACT_TYPE",))
        dangling = artifact_reference_check(resolver, [("event:missing", "event")])
        self.assert_quarantine(dangling, "INV-003")

        broken = artifact_reference_check(resolver, BrokenIterable(RuntimeError("broken")))
        self.assert_quarantine(broken, "INV-003")
        self.assertEqual(broken.failure_codes, ("REFERENCE_ITERATOR_FAILURE",))
        with mock.patch.object(self.store, "get_artifact", side_effect=OSError("offline")):
            unavailable = artifact_reference_check(resolver, [("event:1", "event")])
        self.assert_quarantine(unavailable, "INV-003")
        self.assertEqual(unavailable.failure_codes, ("REFERENCE_STORE_UNAVAILABLE",))

    def test_event_uniqueness_reads_verified_store_without_mutating_it(self) -> None:
        self.store.append_event(event("event:1", 1))
        before = self.store.event_log_hash()
        self.assertIs(event_id_uniqueness_check(self.store, "event:2").verdict, Verdict.PASS)
        duplicate = event_id_uniqueness_check(self.store, "event:1")
        self.assert_quarantine(duplicate, "INV-005")
        self.assertEqual(self.store.event_log_hash(), before)

        with mock.patch.object(self.store, "events", side_effect=OSError("offline")):
            unavailable = event_id_uniqueness_check(self.store, "event:2")
        self.assert_quarantine(unavailable, "INV-005")
        self.assertEqual(unavailable.failure_codes, ("EVENT_STORE_UNAVAILABLE",))

    def test_policy_projection_requires_complete_bijective_lineage(self) -> None:
        state = canonical_state()
        valid = project(state)
        self.assertIs(policy_input_leakage_check(valid, state).verdict, Verdict.PASS)

        lineage = valid.lineage[0]
        variants = {
            "MISSING_LINEAGE": ObservationProjection(valid.observation, ()),
            "DUPLICATE_LINEAGE": ObservationProjection(valid.observation, (lineage, lineage)),
            "STALE_LINEAGE_VERSION": ObservationProjection(
                valid.observation, (replace(lineage, source_state_version=2),)
            ),
            "STALE_LINEAGE_EPISODE": ObservationProjection(
                valid.observation, (replace(lineage, source_episode_id="episode:other"),)
            ),
            "EXTRA_LINEAGE": ObservationProjection(
                valid.observation,
                (lineage, replace(lineage, output_path="/visible_facts/1")),
            ),
            "INVALID_LINEAGE_SOURCE": ObservationProjection(
                valid.observation, (replace(lineage, source_path="/resources/missing"),)
            ),
        }
        for expected_code, candidate in variants.items():
            with self.subTest(expected_code=expected_code):
                outcome = policy_input_leakage_check(candidate, state)
                self.assert_quarantine(outcome, "INV-014")
                self.assertIn(expected_code, outcome.failure_codes)

        stale_episode_observation = valid.observation
        stale_episode_observation["episode_id"] = "episode:other"
        stale_episode = policy_input_leakage_check(
            ObservationProjection(stale_episode_observation, valid.lineage), state
        )
        self.assert_quarantine(stale_episode, "INV-014")
        self.assertIn("STALE_OBSERVATION_EPISODE", stale_episode.failure_codes)

        stale_version_observation = valid.observation
        stale_version_observation["state_version"] = 2
        stale_version = policy_input_leakage_check(
            ObservationProjection(stale_version_observation, valid.lineage), state
        )
        self.assert_quarantine(stale_version, "INV-014")
        self.assertIn("STALE_OBSERVATION_VERSION", stale_version.failure_codes)

        changed_observation = valid.observation
        changed_observation["visible_facts"][0]["value"] = "unavailable"
        mismatch = policy_input_leakage_check(
            ObservationProjection(changed_observation, valid.lineage), state
        )
        self.assert_quarantine(mismatch, "INV-014")
        self.assertIn("LINEAGE_VALUE_MISMATCH", mismatch.failure_codes)

    def test_policy_projection_rejects_detached_observation(self) -> None:
        outcome = policy_input_leakage_check(project(canonical_state()).observation, canonical_state())
        self.assert_quarantine(outcome, "INV-014")
        self.assertEqual(outcome.failure_codes, ("MALFORMED_PROJECTION_AGGREGATE",))

    def test_integrity_check_reuses_store_and_canonical_hash_domains(self) -> None:
        self.store.put_artifact("artifact:1", "example", {"value": "approved"})
        self.store.append_event(event("event:1", 1))
        passed = artifact_integrity_check(
            self.store,
            ("artifact:1",),
            expected_event_log_hash=self.store.event_log_hash(),
        )
        self.assertIs(passed.verdict, Verdict.PASS)
        failed = artifact_integrity_check(
            self.store,
            ("artifact:1",),
            expected_event_log_hash="sha256:" + "0" * 64,
        )
        self.assert_quarantine(failed, "INV-015")

        self.store.put_artifact("artifact:omitted", "example", {"value": "original"})
        omitted_path = self.store._artifact_path("artifact:omitted")
        omitted_record = json.loads(omitted_path.read_text(encoding="utf-8"))
        omitted_record["content"]["value"] = "tampered"
        omitted_path.write_bytes(canonical_json_bytes(omitted_record))
        omitted_corruption = artifact_integrity_check(self.store, ("artifact:1",))
        self.assert_quarantine(omitted_corruption, "INV-015")
        self.assertEqual(omitted_corruption.failure_codes, ("STORED_INTEGRITY_FAILURE",))

        with mock.patch.object(
            self.store, "verify_artifact_inventory", side_effect=OSError("offline")
        ):
            unavailable = artifact_integrity_check(self.store)
        self.assert_quarantine(unavailable, "INV-015")
        self.assertEqual(unavailable.failure_codes, ("ARTIFACT_STORE_UNAVAILABLE",))

        broken_inventory = artifact_integrity_check(
            self.store, BrokenIterable(RuntimeError("broken"))
        )
        self.assert_quarantine(broken_inventory, "INV-015")
        self.assertEqual(
            broken_inventory.failure_codes,
            ("ARTIFACT_INVENTORY_BOUNDARY_FAILURE",),
        )

        malformed = artifact_integrity_check(
            {
                "canonicalization": "STAGE1_CANONICAL_JSON_V1",
                "artifacts": [{"content": {"value": float("nan")}, "content_hash": "sha256:bad"}],
                "event_log": {
                    "serialization": "CANONICAL_JSONL_WITH_FINAL_NEWLINE",
                    "events": [],
                    "integrity_hash": "sha256:" + "0" * 64,
                },
            }
        )
        self.assert_quarantine(malformed, "INV-015")
        self.assertIn("MALFORMED_ARTIFACT", malformed.failure_codes)

    def test_registered_and_supplemental_ingest_corpus_cases(self) -> None:
        cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
        ingest_cases = [case for case in cases if case["invariant_id"] in INGEST_IDS]
        self.assertEqual(len(ingest_cases), 12)
        for case in ingest_cases:
            with self.subTest(test_id=case["test_id"]):
                first = self._run_case(case)
                second = self._run_case(case)
                self.assertEqual(first, second)
                self.assertEqual(first.verdict.value, case["expected"]["verdict"])
                resolution = first.failure_resolution.value if first.failure_resolution else None
                self.assertEqual(resolution, case["expected"]["expected_failure_resolution"])

    def _run_case(self, case):
        case_input = case["input"]
        validator = INGEST_VALIDATORS[case["validator"]]
        if case["invariant_id"] == "INV-003":
            with tempfile.TemporaryDirectory() as directory:
                store = AppendOnlyStore(directory)
                for artifact in case_input["artifacts"]:
                    store.put_artifact(
                        artifact["artifact_id"],
                        artifact["artifact_type"],
                        {"artifact_id": artifact["artifact_id"]},
                    )
                refs = [
                    (reference["ref_id"], reference["declared_type"])
                    for reference in case_input["references"]
                ]
                return validator(ArtifactReferenceResolver(store), refs)
        if case["invariant_id"] == "INV-005":
            with tempfile.TemporaryDirectory() as directory:
                store = AppendOnlyStore(directory)
                for clock, event_id in enumerate(case_input["existing_event_ids"]):
                    store.append_event(event(event_id, clock))
                return validator(store, case_input["candidate_event_id"])
        if case["invariant_id"] == "INV-014":
            state = canonical_state()
            fact_input = case_input["training_example"]["visible_facts"][0]
            source = state["resources"]["projection_facts"]["driver"]
            source["fact_id"] = fact_input["fact_id"]
            source["value"] = fact_input["value"]
            source["access_class"] = fact_input["access_class"]
            valid_projection = project_observation(
                canonical_state(),
                observation_id="observation:1",
                actor_id="worker:1",
                source_paths=("/resources/projection_facts/driver",),
                goal_refs=("goal:transport",),
                generated_at=GENERATED_AT,
                context_budget_tokens=2048,
            )
            lineage = replace(
                valid_projection.lineage[0],
                source_access_class=case_input["projection_lineage"][0]["source_access_class"],
            )
            observation = valid_projection.observation
            observation["visible_facts"][0]["fact_id"] = fact_input["fact_id"]
            observation["visible_facts"][0]["value"] = fact_input["value"]
            observation["visible_facts"][0]["access_class"] = fact_input["access_class"]
            return validator(ObservationProjection(observation, (lineage,)), state)
        return validator(case_input)


if __name__ == "__main__":
    unittest.main()
