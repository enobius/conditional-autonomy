from __future__ import annotations

from copy import deepcopy
import multiprocessing
import tempfile
import unittest
from unittest import mock

from runtime.conditional_autonomy.generation import InstanceGenerationError
from runtime.conditional_autonomy.split_hygiene import (
    enforce_generation_split_hygiene,
    generation_manifest_evidence,
)
from runtime.conditional_autonomy.storage import (
    AppendOnlyStore,
    PromotionBoundaryError,
    canonical_content_hash,
    canonical_json_bytes,
)
from tests.test_generation import generate


def _legacy_artifact(store, artifact_id, artifact_type, content) -> None:
    """Install an integrity-valid pre-boundary record for adversarial tests."""
    record = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "content": deepcopy(content),
        "content_hash": canonical_content_hash(content),
    }
    store._artifact_path(artifact_id).write_bytes(canonical_json_bytes(record))


def _emit_worker(root, split, private_value, start, results) -> None:
    candidate = generate(seed=404, split=split, private_value=private_value)
    start.wait()
    try:
        candidate.emit(AppendOnlyStore(root))
    except InstanceGenerationError:
        results.put("REJECTED")
    else:
        results.put("PUBLISHED")


class GenerationSplitHygieneTests(unittest.TestCase):
    def test_adapter_translates_real_manifest_vocabulary_without_mutation(self) -> None:
        generated = generate(seed=71, split="TRAIN")
        instance, manifest = generated.instance, generated.manifest
        before = deepcopy((instance, manifest))
        self.assertEqual(
            generation_manifest_evidence(instance, manifest),
            {
                "instance_id": instance["instance_id"],
                "split": "TRAIN",
                "seed": 71,
                "template_family": manifest["scenario_family"],
                "constraint_graph_hash": manifest["constraint_graph_hash"],
                "disruption_composition_hash": manifest["disruption_schedule_hash"],
            },
        )
        self.assertEqual((instance, manifest), before)

    def test_each_prohibited_cross_split_overlap_uses_canonical_inv_013(self) -> None:
        first = generate(seed=101, split="TRAIN")
        mappings = {
            "seed": "seed",
            "template_family": "scenario_family",
            "constraint_graph_hash": "constraint_graph_hash",
            "disruption_composition_hash": "disruption_schedule_hash",
        }
        for dimension, manifest_field in mappings.items():
            other_instance = {"instance_id": f"instance:synthetic:{dimension}"}
            other_manifest = {
                "split_assignment": "TEST",
                "seed": 202,
                "scenario_family": "P7",
                "constraint_graph_hash": "sha256:" + "1" * 64,
                "disruption_schedule_hash": "sha256:" + "2" * 64,
            }
            other_manifest[manifest_field] = first.manifest[manifest_field]
            with self.subTest(dimension=dimension):
                with self.assertRaisesRegex(RuntimeError, f"CROSS_SPLIT_REUSE:{dimension}"):
                    enforce_generation_split_hygiene(
                        ((first.instance, first.manifest), (other_instance, other_manifest))
                    )

    def test_allowed_same_split_and_cross_split_non_overlap(self) -> None:
        first = generate(seed=101, split="TRAIN")
        second = generate(seed=101, split="TRAIN", private_value="busy")
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            first.emit(store)
            second.emit(store)
            self.assertEqual(len(store.verify_artifact_inventory()), 4)

        isolated_instance = {"instance_id": "instance:synthetic:isolated"}
        isolated_manifest = {
            "split_assignment": "TEST",
            "seed": 202,
            "scenario_family": "P7",
            "constraint_graph_hash": "sha256:" + "1" * 64,
            "disruption_schedule_hash": "sha256:" + "2" * 64,
        }
        enforce_generation_split_hygiene(
            ((first.instance, first.manifest), (isolated_instance, isolated_manifest))
        )

    def test_generic_storage_cannot_bypass_type_or_id_namespace_boundary(self) -> None:
        generated = generate()
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            members = (
                (generated.instance["instance_id"], "generated-instance", generated.instance),
                ("manifest:bypass", "instance-manifest", generated.manifest),
            )
            attempted_members = members + (
                ("instance:mistyped", "other", {"value": "blocked"}),
                ("manifest:mistyped", "other", {"value": "blocked"}),
                ("other:instance", "generated-instance", generated.instance),
                ("other:manifest", "instance-manifest", generated.manifest),
            )
            for artifact_id, artifact_type, content in attempted_members:
                with self.subTest(artifact_type=artifact_type):
                    with self.assertRaises(PromotionBoundaryError):
                        store.put_artifact(artifact_id, artifact_type, content)
                    self.assertEqual(store.verify_artifact_inventory(), {})
            with self.assertRaises(PromotionBoundaryError):
                store.put_artifacts_atomic(members)
            store.put_artifact("other:1", "other", {"value": "allowed"})
            self.assertEqual(set(store.verify_artifact_inventory()), {"other:1"})

    def test_every_forged_historical_binding_fails_without_publication(self) -> None:
        historical = generate(seed=101, split="TRAIN")
        candidate = generate(seed=202, split="TEST", private_value="busy")
        mutations = {
            "seed": lambda instance, manifest: manifest.update(seed=999),
            "split": lambda instance, manifest: manifest.update(split_assignment="TEST"),
            "scenario": lambda instance, manifest: manifest.update(scenario_family="P7"),
            "graph": lambda instance, manifest: manifest.update(
                constraint_graph_hash="sha256:" + "1" * 64
            ),
            "disruption": lambda instance, manifest: manifest.update(
                disruption_schedule_hash="sha256:" + "2" * 64
            ),
            "instance_id": lambda instance, manifest: instance.update(
                instance_id="instance:forged:id"
            ),
        }
        for binding, mutate in mutations.items():
            with self.subTest(binding=binding):
                instance, manifest = historical.instance, historical.manifest
                mutate(instance, manifest)
                with tempfile.TemporaryDirectory() as directory:
                    store = AppendOnlyStore(directory)
                    suffix = historical.instance["instance_id"].removeprefix("instance:")
                    instance_ref = historical.instance["instance_id"]
                    if binding == "instance_id":
                        instance_ref = "instance:thanksgiving:legacy-record-id"
                        suffix = instance_ref.removeprefix("instance:")
                    _legacy_artifact(store, instance_ref, "generated-instance", instance)
                    _legacy_artifact(store, f"manifest:{suffix}", "instance-manifest", manifest)
                    before = store.verify_artifact_inventory()
                    with self.assertRaises(InstanceGenerationError):
                        candidate.emit(store)
                    self.assertEqual(store.verify_artifact_inventory(), before)

    def test_both_orphan_directions_fail_closed_with_exact_inventory(self) -> None:
        historical = generate(seed=101, split="TRAIN")
        candidate = generate(seed=202, split="TEST", private_value="busy")
        suffix = historical.instance["instance_id"].removeprefix("instance:")
        cases = (
            (historical.instance["instance_id"], "generated-instance", historical.instance),
            (f"manifest:{suffix}", "instance-manifest", historical.manifest),
        )
        for artifact_id, artifact_type, content in cases:
            with self.subTest(artifact_type=artifact_type):
                with tempfile.TemporaryDirectory() as directory:
                    store = AppendOnlyStore(directory)
                    _legacy_artifact(store, artifact_id, artifact_type, content)
                    before = store.verify_artifact_inventory()
                    with self.assertRaises(InstanceGenerationError):
                        candidate.emit(store)
                    self.assertEqual(store.verify_artifact_inventory(), before)

    def test_wrong_and_alternate_pair_types_fail_closed(self) -> None:
        historical = generate(seed=101, split="TRAIN")
        candidate = generate(seed=202, split="TEST", private_value="busy")
        suffix = historical.instance["instance_id"].removeprefix("instance:")
        cases = (
            (historical.instance["instance_id"], "generated-instance-typo", historical.instance),
            (f"manifest:{suffix}", "manifest", historical.manifest),
            (historical.instance["instance_id"], "instance-manifest", historical.instance),
            (f"manifest:{suffix}", "generated-instance", historical.manifest),
        )
        for artifact_id, artifact_type, content in cases:
            with self.subTest(artifact_id=artifact_id, artifact_type=artifact_type):
                with tempfile.TemporaryDirectory() as directory:
                    store = AppendOnlyStore(directory)
                    _legacy_artifact(store, artifact_id, artifact_type, content)
                    before = store.verify_artifact_inventory()
                    with self.assertRaises(InstanceGenerationError):
                        candidate.emit(store)
                    self.assertEqual(store.verify_artifact_inventory(), before)

    def test_malformed_historical_content_fails_closed(self) -> None:
        historical = generate(seed=101, split="TRAIN")
        candidate = generate(seed=202, split="TEST", private_value="busy")
        suffix = historical.instance["instance_id"].removeprefix("instance:")
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            _legacy_artifact(store, historical.instance["instance_id"], "generated-instance", {})
            _legacy_artifact(store, f"manifest:{suffix}", "instance-manifest", historical.manifest)
            before = store.verify_artifact_inventory()
            with self.assertRaises(InstanceGenerationError):
                candidate.emit(store)
            self.assertEqual(store.verify_artifact_inventory(), before)

    def test_public_api_has_no_authorization_or_preflight_injection_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            store.put_artifact("existing:1", "other", {"value": "safe"})
            before = store.verify_artifact_inventory()
            with self.assertRaises(TypeError):
                store.put_artifacts_atomic(
                    (("candidate:1", "other", {"value": "blocked"}),),
                    _preflight=lambda _: None,
                )
            with self.assertRaises(TypeError):
                store.put_artifacts_atomic(
                    (("candidate:1", "other", {"value": "blocked"}),),
                    _promotion_capability=object(),
                )
            self.assertEqual(store.verify_artifact_inventory(), before)

    def test_split_hygiene_callback_error_never_publishes_candidate(self) -> None:
        candidate = generate(seed=707, split="TEST")
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            before = store.verify_artifact_inventory()
            with mock.patch(
                "runtime.conditional_autonomy.split_hygiene._generation_pair_store_preflight",
                side_effect=RuntimeError("validator crashed"),
            ):
                with self.assertRaises(InstanceGenerationError):
                    candidate.emit(store)
            self.assertEqual(store.verify_artifact_inventory(), before)

    def test_repeated_failure_is_deterministic_and_never_publishes(self) -> None:
        train = generate(seed=303, split="TRAIN")
        test = generate(seed=303, split="TEST", private_value="busy")
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            train.emit(store)
            before = store.verify_artifact_inventory()
            for _ in range(2):
                with self.assertRaises(InstanceGenerationError) as raised:
                    test.emit(store)
                messages.append(str(raised.exception.__cause__))
                self.assertEqual(store.verify_artifact_inventory(), before)
        self.assertEqual(messages[0], messages[1])

    def test_cross_process_overlap_has_exactly_one_complete_winner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("spawn")
            start, results = context.Event(), context.Queue()
            processes = [
                context.Process(target=_emit_worker, args=(directory, split, private, start, results))
                for split, private in (("TRAIN", "available"), ("TEST", "busy"))
            ]
            for process in processes:
                process.start()
            start.set()
            outcomes = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            self.assertTrue(all(process.exitcode == 0 for process in processes))
            self.assertEqual(sorted(outcomes), ["PUBLISHED", "REJECTED"])
            self.assertEqual(len(AppendOnlyStore(directory).verify_artifact_inventory()), 2)


if __name__ == "__main__":
    unittest.main()
