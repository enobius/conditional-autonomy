from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from runtime.conditional_autonomy.generation import (
    FEASIBILITY_ORACLE_VERSION,
    GENERATOR_ID,
    GENERATOR_VERSION,
    GeneratedInstance,
    InstanceGenerationError,
    generate_thanksgiving_instance,
)
from runtime.conditional_autonomy.ingest import artifact_integrity_check
from runtime.conditional_autonomy.references import ArtifactReferenceResolver
from runtime.conditional_autonomy.storage import AppendOnlyStore


ROOT = Path(__file__).resolve().parents[1]
USER_MODEL_FIXTURE = (
    ROOT / "architecture" / "schemas" / "v1.0" / "fixtures" / "valid" / "user-model.valid.json"
)


def user_model() -> dict[str, object]:
    return json.loads(USER_MODEL_FIXTURE.read_text(encoding="utf-8"))


def private_state(value: str = "available") -> dict[str, object]:
    return {
        "private_world_state_id": "private-state:1",
        "access_class": "PRIVATE_ENVIRONMENT",
        "facts": {"fact:driver-availability": value},
    }


def generate(
    *,
    seed: int = 42,
    private_value: str = "available",
    lineage=("dataset:realm-p6", "dataset:reviewed-static"),
    split: str = "TEST",
    schedule=(),
    difficulty=None,
):
    return generate_thanksgiving_instance(
        seed=seed,
        difficulty_parameters=difficulty or {"entities": 8, "disruptions": len(schedule)},
        user_model=user_model(),
        private_world_state=private_state(private_value),
        source_dataset_lineage=lineage,
        split_assignment=split,
        disruption_schedule=schedule,
    )


class DeterministicInstanceGenerationTests(unittest.TestCase):
    def test_fixed_seed_reproduces_byte_identical_instance_and_manifest(self) -> None:
        left = generate(seed=42)
        right = generate(seed=42, lineage=("dataset:reviewed-static", "dataset:realm-p6"))
        self.assertEqual(left.canonical_bytes(), right.canonical_bytes())
        self.assertEqual(left.instance_content_hash, right.instance_content_hash)
        left.verify()
        right.verify()

    def test_manifest_hashes_lineage_and_split_are_bound_and_valid(self) -> None:
        generated = generate()
        generated.verify()
        manifest = generated.manifest
        self.assertEqual(manifest["split_assignment"], "TEST")
        self.assertEqual(
            manifest["source_dataset_lineage"],
            ["dataset:realm-p6", "dataset:reviewed-static"],
        )
        for field_name in (
            "constraint_graph_hash",
            "entity_graph_hash",
            "disruption_schedule_hash",
        ):
            self.assertRegex(manifest[field_name], r"^sha256:[0-9a-f]{64}$")

        tampered = generated.manifest
        tampered["constraint_graph_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(InstanceGenerationError, "constraint_graph_hash"):
            GeneratedInstance(generated.instance, tampered).verify()

    def test_changed_inputs_change_only_relevant_hash_domains(self) -> None:
        baseline = generate(seed=42)
        changed_seed = generate(seed=43)
        disruption = generate(
            seed=42,
            schedule=(
                {
                    "event_type": "FLIGHT_DELAY",
                    "entity_id": "person:james",
                    "delay_minutes": 180,
                },
            ),
        )
        changed_private = generate(seed=42, private_value="unavailable")

        for candidate in (changed_seed, changed_private):
            self.assertNotEqual(
                baseline.instance_content_hash,
                candidate.instance_content_hash,
            )
            self.assertEqual(
                baseline.manifest["constraint_graph_hash"],
                candidate.manifest["constraint_graph_hash"],
            )
            self.assertEqual(
                baseline.manifest["entity_graph_hash"],
                candidate.manifest["entity_graph_hash"],
            )
        self.assertNotEqual(
            baseline.manifest["disruption_schedule_hash"],
            disruption.manifest["disruption_schedule_hash"],
        )
        self.assertEqual(
            baseline.manifest["constraint_graph_hash"],
            disruption.manifest["constraint_graph_hash"],
        )
        self.assertEqual(
            baseline.manifest["entity_graph_hash"],
            disruption.manifest["entity_graph_hash"],
        )

    def test_lineage_and_split_fail_closed_at_manifest_boundary(self) -> None:
        for lineage, split in (
            ((), "TEST"),
            (("dataset:realm-p6", "dataset:realm-p6"), "TEST"),
            (("dataset:realm-p6",), "UNASSIGNED"),
        ):
            with self.subTest(lineage=lineage, split=split):
                with self.assertRaises(InstanceGenerationError):
                    generate(lineage=lineage, split=split)

    def test_verify_pins_stage_one_generation_contract(self) -> None:
        generated = generate()
        for field_name, bad_value in (
            ("generator_id", "generator:other"),
            ("generator_version", "2.0"),
            ("scenario_family", "P5"),
            ("environment_version", "thanksgiving-p6.999"),
            ("feasibility_oracle_version", "environment-preflight.2.0"),
        ):
            with self.subTest(field_name=field_name):
                instance = generated.instance
                instance[field_name] = bad_value
                manifest = generated.manifest
                if field_name in manifest:
                    manifest[field_name] = bad_value
                with self.assertRaisesRegex(InstanceGenerationError, field_name):
                    GeneratedInstance(instance, manifest).verify()

    def test_verify_rejects_coherently_reversed_lineage(self) -> None:
        generated = generate()
        instance = generated.instance
        manifest = generated.manifest
        instance["source_dataset_lineage"].reverse()
        manifest["source_dataset_lineage"].reverse()
        with self.assertRaisesRegex(InstanceGenerationError, "canonical sorted order"):
            GeneratedInstance(instance, manifest).verify()

    def test_generation_rejects_unsupported_version_overrides(self) -> None:
        common = {
            "seed": 42,
            "difficulty_parameters": {"entities": 8},
            "user_model": user_model(),
            "private_world_state": private_state(),
            "source_dataset_lineage": ("dataset:realm-p6",),
            "split_assignment": "TEST",
        }
        for override in (
            {"generator_id": GENERATOR_ID + ":other"},
            {"generator_version": GENERATOR_VERSION + ".1"},
            {
                "feasibility_oracle_version": FEASIBILITY_ORACLE_VERSION + ".1"
            },
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(InstanceGenerationError, "unsupported"):
                    generate_thanksgiving_instance(**common, **override)

    def test_emission_uses_typed_artifacts_and_store_wide_inv_015(self) -> None:
        generated = generate()
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            instance_ref, manifest_ref = generated.emit(store)
            self.assertTrue(
                artifact_integrity_check(store, (instance_ref, manifest_ref)).succeeded
            )
            resolver = ArtifactReferenceResolver(store)
            self.assertTrue(
                resolver.resolve(instance_ref, "generated-instance").succeeded
            )
            self.assertTrue(
                resolver.resolve(manifest_ref, "instance-manifest").succeeded
            )

    def test_emission_preflight_conflict_leaves_no_partial_instance(self) -> None:
        generated = generate()
        suffix = generated.instance["instance_id"].removeprefix("instance:")
        manifest_ref = f"manifest:{suffix}"
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            store.put_artifact(manifest_ref, "reserved", {"owner": "existing"})
            with self.assertRaisesRegex(InstanceGenerationError, "emission failed"):
                generated.emit(store)
            with self.assertRaises(KeyError):
                store.get_artifact(generated.instance["instance_id"])
            self.assertEqual(
                store.get_artifact(manifest_ref, expected_type="reserved"),
                {"owner": "existing"},
            )

    def test_emission_forced_publish_failure_rolls_back_complete_batch(self) -> None:
        generated = generate()
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            atomic_put = store.put_artifacts_atomic

            def fail_after_first(_: str) -> None:
                raise RuntimeError("forced publication failure")

            def faulted_put(artifacts):
                return atomic_put(artifacts, _after_publish=fail_after_first)

            with mock.patch.object(store, "put_artifacts_atomic", side_effect=faulted_put):
                with self.assertRaisesRegex(InstanceGenerationError, "emission failed"):
                    generated.emit(store)
            self.assertEqual(store.verify_artifact_inventory(), {})

    def test_emission_rejects_corrupt_store_without_changing_any_bytes(self) -> None:
        generated = generate()
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            store.put_artifact("existing:1", "example", {"value": "safe"})
            artifact_path = next((Path(directory) / "artifacts").glob("*.json"))
            before = artifact_path.read_bytes()
            offset = before.index(b"safe")
            corrupt = before[:offset] + b"x" + before[offset + 1 :]
            artifact_path.write_bytes(corrupt)

            with self.assertRaisesRegex(InstanceGenerationError, "emission failed"):
                generated.emit(store)

            self.assertEqual(artifact_path.read_bytes(), corrupt)
            self.assertEqual(
                [path.name for path in (Path(directory) / "artifacts").iterdir()],
                [artifact_path.name],
            )

    def test_generation_is_identical_across_fresh_processes(self) -> None:
        program = (
            "from tests.test_generation import generate; import sys; "
            "sys.stdout.buffer.write(generate(seed=42).canonical_bytes())"
        )
        outputs = []
        for hash_seed in ("1", "91"):
            environment = dict(os.environ, PYTHONHASHSEED=hash_seed)
            outputs.append(
                subprocess.run(
                    [sys.executable, "-c", program],
                    cwd=ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                ).stdout
            )
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
