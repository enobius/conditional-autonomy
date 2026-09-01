from __future__ import annotations

import base64
import subprocess
import sys
from types import MappingProxyType
import unittest

from runtime.conditional_autonomy import counterfactuals
from runtime.conditional_autonomy.counterfactuals import (
    CounterfactualPairError,
    CounterfactualSafetyPair,
    canonical_counterfactual_pairs_bytes,
    changed_json_pointers,
    generate_counterfactual_safety_pairs,
    validate_counterfactual_pair,
)


class CounterfactualSafetyPairTests(unittest.TestCase):
    def test_every_pair_is_single_fact_and_flips_the_declared_verdict(self) -> None:
        pairs = generate_counterfactual_safety_pairs()
        self.assertEqual(len(pairs), 8)
        self.assertEqual([item.pair_id for item in pairs], sorted(item.pair_id for item in pairs))
        for pair in pairs:
            with self.subTest(pair=pair.pair_id):
                self.assertEqual(
                    changed_json_pointers(pair.baseline, pair.counterfactual),
                    (pair.safety_fact_pointer,),
                )
                result = validate_counterfactual_pair(pair)
                self.assertEqual(result.changed_pointer, pair.safety_fact_pointer)
                self.assertNotEqual(result.baseline_verdict, result.counterfactual_verdict)

    def test_unrelated_serialized_fields_are_byte_identical(self) -> None:
        for pair in generate_counterfactual_safety_pairs():
            baseline = pair.baseline
            counterfactual = pair.counterfactual
            # Exact leaf diff proves all other canonical subtrees are unchanged.
            self.assertEqual(
                changed_json_pointers(baseline, counterfactual),
                (pair.safety_fact_pointer,),
            )
            self.assertNotEqual(pair.canonical_bytes(), b"")

    def test_pair_accessors_are_defensive_and_validation_does_not_mutate(self) -> None:
        pair = next(
            item
            for item in generate_counterfactual_safety_pairs()
            if item.pair_id == "pair:capability-grant"
        )
        before = pair.canonical_bytes()
        exposed = pair.baseline
        exposed["granted_capabilities"][0] = "capability:tampered"
        validate_counterfactual_pair(pair)
        self.assertEqual(pair.canonical_bytes(), before)

    def test_fails_closed_on_undeclared_second_change_or_wrong_expectation(self) -> None:
        source = next(
            item
            for item in generate_counterfactual_safety_pairs()
            if item.pair_id == "pair:state-version"
        )
        altered = source.counterfactual
        altered["current"]["plan_version"] = 2
        bad = CounterfactualSafetyPair(
            pair_id="pair:bad-second-change",
            evaluator_id=source.evaluator_id,
            safety_fact_pointer=source.safety_fact_pointer,
            baseline=source.baseline,
            counterfactual=altered,
            expected_baseline_verdict="PASS",
            expected_counterfactual_verdict="FAIL",
        )
        with self.assertRaisesRegex(CounterfactualPairError, "exactly its declared"):
            validate_counterfactual_pair(bad)

        wrong = CounterfactualSafetyPair(
            pair_id="pair:wrong-expectation",
            evaluator_id=source.evaluator_id,
            safety_fact_pointer=source.safety_fact_pointer,
            baseline=source.baseline,
            counterfactual=source.counterfactual,
            expected_baseline_verdict="FAIL",
            expected_counterfactual_verdict="PASS",
        )
        with self.assertRaisesRegex(CounterfactualPairError, "do not match observed"):
            validate_counterfactual_pair(wrong)

    def test_shape_changes_are_rejected_not_misrepresented_as_one_fact(self) -> None:
        for left, right in (
            ({"a": 1}, {"a": 1, "b": 2}),
            ([1], [1, 2]),
            ({"nested": {"safe": True}}, {"nested": []}),
            ({"nested": [1]}, {"nested": {"0": 1}}),
        ):
            with self.subTest(left=left, right=right):
                with self.assertRaisesRegex(CounterfactualPairError, "topology"):
                    changed_json_pointers(left, right)
        with self.assertRaisesRegex(CounterfactualPairError, "non-root"):
            CounterfactualSafetyPair(
                pair_id="pair:shape",
                evaluator_id="current_version_check",
                safety_fact_pointer="/",
                baseline={"a": 1},
                counterfactual={"a": 2},
                expected_baseline_verdict="PASS",
                expected_counterfactual_verdict="FAIL",
            )

    def test_declared_pointer_must_resolve_to_a_leaf_in_both_cases(self) -> None:
        source = next(
            item
            for item in generate_counterfactual_safety_pairs()
            if item.pair_id == "pair:state-version"
        )
        parent = CounterfactualSafetyPair(
            pair_id="pair:parent-pointer",
            evaluator_id=source.evaluator_id,
            safety_fact_pointer="/current",
            baseline=source.baseline,
            counterfactual=source.counterfactual,
            expected_baseline_verdict="PASS",
            expected_counterfactual_verdict="FAIL",
        )
        with self.assertRaisesRegex(CounterfactualPairError, "leaf scalar"):
            validate_counterfactual_pair(parent)

        replaced = source.counterfactual
        replaced["current"] = []
        malformed = CounterfactualSafetyPair(
            pair_id="pair:container-replacement",
            evaluator_id=source.evaluator_id,
            safety_fact_pointer="/current",
            baseline=source.baseline,
            counterfactual=replaced,
            expected_baseline_verdict="PASS",
            expected_counterfactual_verdict="FAIL",
        )
        with self.assertRaisesRegex(CounterfactualPairError, "leaf scalar|topology"):
            validate_counterfactual_pair(malformed)

    def test_scalar_comparison_uses_canonical_json_identity(self) -> None:
        self.assertEqual(changed_json_pointers({"value": 1}, {"value": 1.0}), ("/value",))
        self.assertEqual(changed_json_pointers({"value": True}, {"value": 1}), ("/value",))

        source = next(
            item
            for item in generate_counterfactual_safety_pairs()
            if item.pair_id == "pair:state-version"
        )
        for pair_id, section, alias in (
            ("pair:int-float-alias", "current", 1.0),
            ("pair:bool-int-alias", "authorization", True),
        ):
            with self.subTest(pair_id=pair_id):
                altered = source.counterfactual
                altered[section]["plan_version"] = alias
                adversarial = CounterfactualSafetyPair(
                    pair_id=pair_id,
                    evaluator_id=source.evaluator_id,
                    safety_fact_pointer=source.safety_fact_pointer,
                    baseline=source.baseline,
                    counterfactual=altered,
                    expected_baseline_verdict="PASS",
                    expected_counterfactual_verdict="FAIL",
                )
                with self.assertRaisesRegex(
                    CounterfactualPairError, "exactly its declared"
                ):
                    validate_counterfactual_pair(adversarial)

    def test_evaluator_registry_is_closed_against_injection(self) -> None:
        self.assertIsInstance(counterfactuals._EVALUATORS, MappingProxyType)
        with self.assertRaises(TypeError):
            counterfactuals._EVALUATORS["injected"] = lambda _: "PASS"  # type: ignore[index]
        source = generate_counterfactual_safety_pairs()[0]
        with self.assertRaisesRegex(CounterfactualPairError, "unknown evaluator"):
            CounterfactualSafetyPair(
                pair_id="pair:injected",
                evaluator_id="injected",
                safety_fact_pointer=source.safety_fact_pointer,
                baseline=source.baseline,
                counterfactual=source.counterfactual,
                expected_baseline_verdict=source.expected_baseline_verdict,
                expected_counterfactual_verdict=source.expected_counterfactual_verdict,
            )

    def test_suite_serialization_is_order_independent_and_fresh_process_stable(self) -> None:
        pairs = generate_counterfactual_safety_pairs()
        expected = canonical_counterfactual_pairs_bytes(pairs)
        self.assertEqual(expected, canonical_counterfactual_pairs_bytes(tuple(reversed(pairs))))
        script = (
            "import base64; from runtime.conditional_autonomy.counterfactuals import "
            "canonical_counterfactual_pairs_bytes; "
            "print(base64.b64encode(canonical_counterfactual_pairs_bytes()).decode('ascii'))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script], check=True, capture_output=True, text=True
        )
        self.assertEqual(completed.stdout.strip(), base64.b64encode(expected).decode("ascii"))

    def test_duplicate_pair_ids_are_rejected(self) -> None:
        pair = generate_counterfactual_safety_pairs()[0]
        with self.assertRaisesRegex(CounterfactualPairError, "unique"):
            canonical_counterfactual_pairs_bytes((pair, pair))


if __name__ == "__main__":
    unittest.main()
