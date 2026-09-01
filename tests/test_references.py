from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.conditional_autonomy.references import (
    ArtifactReferenceResolver,
    ReferenceFailureCode,
)
from runtime.conditional_autonomy.storage import AppendOnlyStore


FIXTURES = Path("architecture/schemas/v1.0/fixtures/valid")


class ArtifactReferenceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = AppendOnlyStore(self.root)
        self.resolver = ArtifactReferenceResolver(self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def fixture(self, name: str) -> dict[str, object]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_resolve_accepts_stable_id_and_expected_type(self) -> None:
        content = {"event_id": "event-001", "event_type": "OBSERVE"}
        self.store.put_artifact("event-001", "event", content)

        result = self.resolver.resolve("event-001", "event")

        self.assertTrue(result.succeeded)
        self.assertEqual(result.artifacts[0].ref_id, "event-001")
        self.assertEqual(result.artifacts[0].artifact_type, "event")
        self.assertEqual(result.artifacts[0].content, content)

    def test_real_episode_string_and_object_refs_resolve_declared_types(self) -> None:
        episode = self.fixture("episode.valid.json")
        step = episode["steps"][0]
        from tests.test_generation import generate

        _, manifest_ref = generate().emit(self.store)
        episode["generator_manifest_ref"] = manifest_ref
        self.store.put_artifact(
            episode["user_model_ref"],
            "user-model",
            self.fixture("user-model.valid.json"),
        )
        self.store.put_artifact(
            step["canonical_state_ref"]["ref_id"],
            "canonical-state",
            self.fixture("canonical-state.valid.json"),
        )

        result = self.resolver.resolve_all(
            (
                (episode["generator_manifest_ref"], "instance-manifest"),
                (episode["user_model_ref"], "user-model"),
                (step["canonical_state_ref"], "canonical-state"),
            )
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(
            [(item.ref_id, item.artifact_type) for item in result.artifacts],
            [
                (manifest_ref, "instance-manifest"),
                ("user-model:p6-oracle:1.0", "user-model"),
                ("state:episode-1:version-3", "canonical-state"),
            ],
        )

    def test_real_evidence_ref_object_adapter_uses_ref_id(self) -> None:
        outcome = self.fixture("tool-outcome.valid.json")
        self.store.put_artifact(
            outcome["raw_result_ref"]["ref_id"],
            "tool-evidence",
            {"payload": "verified bytes"},
        )

        result = self.resolver.resolve_object_reference(
            outcome["raw_result_ref"], "tool-evidence"
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.artifacts[0].ref_id, "evidence:1")

    def test_dangling_reference_returns_registered_quarantine_resolution(self) -> None:
        result = self.resolver.resolve_string_reference("missing", "event")

        self.assertFalse(result.succeeded)
        self.assertEqual(result.artifacts, ())
        self.assertEqual(result.failure.invariant_id, "INV-003")
        self.assertEqual(result.failure.failure_resolution, "QUARANTINE")
        self.assertEqual(result.failure.code, ReferenceFailureCode.DANGLING_REFERENCE)

    def test_wrong_type_returns_registered_quarantine_resolution(self) -> None:
        self.store.put_artifact(
            "proposal-001", "action-proposal", {"proposal_id": "proposal-001"}
        )

        result = self.resolver.resolve("proposal-001", "event")

        self.assertFalse(result.succeeded)
        self.assertEqual(result.artifacts, ())
        self.assertEqual(result.failure.failure_resolution, "QUARANTINE")
        self.assertEqual(result.failure.code, ReferenceFailureCode.WRONG_ARTIFACT_TYPE)

    def test_batch_failure_does_not_expose_partially_resolved_inputs(self) -> None:
        self.store.put_artifact("event-001", "event", {"event_id": "event-001"})

        result = self.resolver.resolve_all(
            (("event-001", "event"), ("missing", "event"))
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(result.artifacts, ())
        self.assertEqual(result.failure.ref_id, "missing")
        self.assertEqual(result.failure.failure_resolution, "QUARANTINE")

    def test_corrupt_artifact_is_normalized_to_quarantine(self) -> None:
        self.store.put_artifact("event-001", "event", {"value": 1})
        artifact_path = next((self.root / "artifacts").glob("*.json"))
        artifact_path.write_text('{"value":NaN}', encoding="utf-8")

        result = self.resolver.resolve("event-001", "event")

        self.assertFalse(result.succeeded)
        self.assertEqual(result.artifacts, ())
        self.assertEqual(
            result.failure.code, ReferenceFailureCode.ARTIFACT_INTEGRITY_FAILURE
        )
        self.assertEqual(result.failure.failure_resolution, "QUARANTINE")

    def test_malformed_inputs_fail_closed_without_attribute_errors(self) -> None:
        cases = (
            self.resolver.resolve(None, "event"),
            self.resolver.resolve("event-001", None),
            self.resolver.resolve_object_reference(None, "event"),
            self.resolver.resolve_object_reference({}, "event"),
            self.resolver.resolve_all(None),
            self.resolver.resolve_all((None,)),
        )

        for result in cases:
            with self.subTest(result=result):
                self.assertFalse(result.succeeded)
                self.assertEqual(result.artifacts, ())
                self.assertEqual(
                    result.failure.code, ReferenceFailureCode.MALFORMED_REFERENCE
                )
                self.assertEqual(result.failure.failure_resolution, "QUARANTINE")


if __name__ == "__main__":
    unittest.main()
