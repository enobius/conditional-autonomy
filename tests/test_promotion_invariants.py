from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.preexecution import InvariantDisposition, Verdict
from runtime.conditional_autonomy.promotion_invariants import (
    PROMOTION_FAILURE_RESOLUTIONS,
    PROMOTION_INVARIANT_VALIDATORS,
    PROHIBITED_SPLIT_DIMENSIONS,
    clarification_counter_reconciliation,
    split_leakage_check,
)


CORPUS = Path("tests/fixtures/invariants/corpus.json")
INVARIANTS = {"INV-011", "INV-013"}


def manifest(
    instance_id: str,
    split: str,
    *,
    seed: int = 101,
    template: str = "template-a",
    graph: str = "graph-a",
    disruption: str = "disruption-a",
) -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "split": split,
        "seed": seed,
        "template_family": template,
        "constraint_graph_hash": graph,
        "disruption_composition_hash": disruption,
    }


class PromotionInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]

    def test_all_registered_and_supplemental_corpus_cases(self) -> None:
        selected = [case for case in self.cases if case["invariant_id"] in INVARIANTS]
        self.assertEqual(len(selected), 8)
        for case in selected:
            with self.subTest(test_id=case["test_id"]):
                before = deepcopy(case["input"])
                validator = PROMOTION_INVARIANT_VALIDATORS[case["validator"]]
                first = validator(case["input"])
                second = validator(case["input"])
                self.assertEqual(first, second)
                self.assertEqual(first.verdict.value, case["expected"]["verdict"])
                expected = case["expected"]["expected_failure_resolution"]
                actual = first.failure_resolution.value if first.failure_resolution else None
                self.assertEqual(actual, expected)
                self.assertEqual(case["input"], before)

    def test_registry_and_phase_dispositions_are_exact(self) -> None:
        self.assertEqual(
            set(PROMOTION_INVARIANT_VALIDATORS),
            {"clarification_counter_reconciliation", "split_leakage_check"},
        )
        self.assertEqual(
            PROMOTION_FAILURE_RESOLUTIONS,
            {
                "INV-011": InvariantDisposition.QUARANTINE,
                "INV-013": InvariantDisposition.QUARANTINE,
            },
        )
        self.assertEqual(
            PROHIBITED_SPLIT_DIMENSIONS,
            {
                "seed",
                "template_family",
                "constraint_graph_hash",
                "disruption_composition_hash",
            },
        )

    def test_malformed_contexts_fail_closed_to_quarantine(self) -> None:
        for validator in (
            clarification_counter_reconciliation,
            split_leakage_check,
        ):
            for context in (None, {}, [], {"unexpected": True}):
                with self.subTest(validator=validator.__name__, context=context):
                    outcome = validator(context)
                    self.assertEqual(outcome.verdict, Verdict.FAIL)
                    self.assertEqual(
                        outcome.failure_resolution, InvariantDisposition.QUARANTINE
                    )
                    self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))

    def test_clarification_counts_both_event_classes_and_all_mismatches(self) -> None:
        context = {
            "classified_events": [
                {"event_id": "event-1", "classification": "QUERY"},
                {"event_id": "event-2", "classification": "ACTION"},
                {"event_id": "event-3", "classification": "QUERY"},
                {"event_id": "event-4", "classification": "USER_RESPONSE"},
            ],
            "recorded_counters": {"queries": 0, "user_responses": 0},
        }
        self.assertEqual(
            clarification_counter_reconciliation(context).failure_codes,
            ("QUERY_COUNT_MISMATCH", "USER_RESPONSE_COUNT_MISMATCH"),
        )
        context["recorded_counters"] = {"queries": 2, "user_responses": 1}
        self.assertTrue(clarification_counter_reconciliation(context).succeeded)

    def test_zero_clarifications_are_valid_but_boolean_counts_are_not(self) -> None:
        context = {
            "classified_events": [
                {"event_id": "event-1", "classification": "ACTION"}
            ],
            "recorded_counters": {"queries": 0, "user_responses": 0},
        }
        self.assertTrue(clarification_counter_reconciliation(context).succeeded)
        context["recorded_counters"]["queries"] = False
        self.assertEqual(
            clarification_counter_reconciliation(context).failure_codes,
            ("MALFORMED_CONTEXT",),
        )

    def test_clarification_rejects_duplicate_events_and_noncanonical_shapes(self) -> None:
        base = {
            "classified_events": [
                {"event_id": "event-1", "classification": "QUERY"}
            ],
            "recorded_counters": {"queries": 1, "user_responses": 0},
        }
        mutations = (
            lambda value: value["classified_events"].append(
                {"event_id": "event-1", "classification": "QUERY"}
            ),
            lambda value: value["classified_events"][0].update(extra=True),
            lambda value: value["classified_events"][0].update(event_id="   "),
            lambda value: value["recorded_counters"].update(extra=0),
        )
        for mutate in mutations:
            context = deepcopy(base)
            mutate(context)
            with self.subTest(context=context):
                self.assertEqual(
                    clarification_counter_reconciliation(context).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )

    def test_split_check_reports_every_leaking_dimension_in_stable_order(self) -> None:
        context = {
            "prohibited_dimensions": list(PROHIBITED_SPLIT_DIMENSIONS),
            "manifests": [
                manifest("instance-train", "TRAIN"),
                manifest("instance-test", "TEST"),
            ],
        }
        self.assertEqual(
            split_leakage_check(context).failure_codes,
            (
                "CROSS_SPLIT_REUSE:constraint_graph_hash",
                "CROSS_SPLIT_REUSE:disruption_composition_hash",
                "CROSS_SPLIT_REUSE:seed",
                "CROSS_SPLIT_REUSE:template_family",
            ),
        )

    def test_same_split_reuse_is_allowed_and_cross_split_values_are_isolated(self) -> None:
        context = {
            "prohibited_dimensions": list(PROHIBITED_SPLIT_DIMENSIONS),
            "manifests": [
                manifest("instance-train-1", "TRAIN"),
                manifest("instance-train-2", "TRAIN"),
                manifest(
                    "instance-test",
                    "TEST",
                    seed=202,
                    template="template-b",
                    graph="graph-b",
                    disruption="disruption-b",
                ),
            ],
        }
        self.assertTrue(split_leakage_check(context).succeeded)

    def test_split_check_requires_complete_policy_and_well_formed_manifests(self) -> None:
        base = {
            "prohibited_dimensions": list(PROHIBITED_SPLIT_DIMENSIONS),
            "manifests": [manifest("instance-train", "TRAIN")],
        }
        mutations = (
            lambda value: value["prohibited_dimensions"].remove("seed"),
            lambda value: value["prohibited_dimensions"].append("seed"),
            lambda value: value["manifests"][0].update(split="VALIDATION"),
            lambda value: value["manifests"][0].update(split=[]),
            lambda value: value["manifests"][0].update(seed=True),
            lambda value: value["manifests"][0].update(template_family="   "),
            lambda value: value["manifests"].append(deepcopy(value["manifests"][0])),
        )
        for mutate in mutations:
            context = deepcopy(base)
            mutate(context)
            with self.subTest(context=context):
                self.assertEqual(
                    split_leakage_check(context).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )


if __name__ == "__main__":
    unittest.main()
