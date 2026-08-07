from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.preexecution import InvariantDisposition, Verdict
from runtime.conditional_autonomy.replay_invariants import (
    REPLAY_INVARIANT_VALIDATORS,
    deterministic_replay_check,
    episode_trace_order_check,
    logical_clock_order_check,
    state_version_transition_check,
)


CORPUS = Path("tests/fixtures/invariants/corpus.json")
INVARIANTS = {"INV-006", "INV-007", "INV-008", "INV-016"}


class ReplayInvariantAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]

    def test_all_registered_and_supplemental_corpus_cases(self) -> None:
        selected = [case for case in self.cases if case["invariant_id"] in INVARIANTS]
        self.assertEqual(len(selected), 11)
        for case in selected:
            with self.subTest(test_id=case["test_id"]):
                before = deepcopy(case["input"])
                validator = REPLAY_INVARIANT_VALIDATORS[case["validator"]]
                first = validator(case["input"])
                second = validator(case["input"])
                self.assertEqual(first, second)
                self.assertEqual(first.verdict.value, case["expected"]["verdict"])
                expected_resolution = case["expected"]["expected_failure_resolution"]
                actual_resolution = (
                    first.failure_resolution.value if first.failure_resolution else None
                )
                self.assertEqual(actual_resolution, expected_resolution)
                self.assertEqual(case["input"], before)

    def test_registry_resolves_exact_deferred_names(self) -> None:
        self.assertEqual(
            set(REPLAY_INVARIANT_VALIDATORS),
            {
                "logical_clock_order_check",
                "state_version_transition_check",
                "deterministic_replay_check",
                "episode_trace_order_check",
            },
        )

    def test_malformed_contexts_fail_closed_to_quarantine(self) -> None:
        validators = (
            logical_clock_order_check,
            state_version_transition_check,
            deterministic_replay_check,
            episode_trace_order_check,
        )
        malformed = (None, {}, [], {"events": "not-a-sequence"}, {"steps": []})
        for validator in validators:
            for context in malformed:
                with self.subTest(validator=validator.__name__, context=context):
                    outcome = validator(context)
                    self.assertEqual(outcome.verdict, Verdict.FAIL)
                    self.assertEqual(
                        outcome.failure_resolution, InvariantDisposition.QUARANTINE
                    )
                    self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))

    def test_inv_006_allows_clock_gaps_but_not_boolean_clocks(self) -> None:
        gap = {
            "concurrency_policy": "TOTAL_ORDER",
            "events": [
                {"event_id": "event:1", "logical_clock": 1},
                {"event_id": "event:2", "logical_clock": 100},
            ],
        }
        self.assertTrue(logical_clock_order_check(gap).succeeded)
        gap["events"][1]["logical_clock"] = True
        self.assertEqual(
            logical_clock_order_check(gap).failure_codes, ("MALFORMED_CONTEXT",)
        )

    def test_inv_008_reducer_rejects_missing_and_noop_paths(self) -> None:
        base = {
            "initial_state": {"state_version": 0, "resources": {"chairs": 4}},
            "ordered_events": [
                {
                    "event_id": "event:1",
                    "logical_clock": 1,
                    "operation": "SET",
                    "path": "/resources/chairs",
                    "value": 6,
                }
            ],
            "recorded_state": {"state_version": 1, "resources": {"chairs": 6}},
        }
        for path, value in (("/resources/missing", 6), ("/resources/chairs", 4)):
            context = deepcopy(base)
            context["ordered_events"][0].update(path=path, value=value)
            outcome = deterministic_replay_check(context)
            self.assertEqual(outcome.verdict, Verdict.FAIL)
            self.assertEqual(outcome.failure_codes, ("REPLAY_FAILED",))

    def test_inv_008_non_json_and_nonfinite_values_fail_closed(self) -> None:
        base = {
            "initial_state": {"state_version": 0, "resources": {"chairs": 4}},
            "ordered_events": [
                {
                    "event_id": "event:1",
                    "logical_clock": 1,
                    "operation": "SET",
                    "path": "/resources/chairs",
                    "value": 6,
                }
            ],
            "recorded_state": {"state_version": 1, "resources": {"chairs": 6}},
        }
        mutations = (
            lambda value: value["ordered_events"][0].update(value=object()),
            lambda value: value["ordered_events"][0].update(value=float("nan")),
            lambda value: value["initial_state"]["resources"].update(chairs=object()),
            lambda value: value["initial_state"]["resources"].update(chairs=float("nan")),
            lambda value: value["recorded_state"]["resources"].update(chairs=object()),
            lambda value: value["recorded_state"]["resources"].update(chairs=float("nan")),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                context = deepcopy(base)
                mutate(context)
                first = deterministic_replay_check(context)
                second = deterministic_replay_check(context)
                self.assertEqual(first, second)
                self.assertEqual(first.verdict, Verdict.FAIL)
                self.assertEqual(first.failure_resolution, InvariantDisposition.QUARANTINE)
                self.assertEqual(first.failure_codes, ("MALFORMED_CONTEXT",))

    def test_inv_016_contiguity_is_relative_to_first_index(self) -> None:
        context = {
            "episode_id": "episode:1",
            "steps": [
                {"trace_step_id": "step:1", "episode_id": "episode:1", "step_index": 4},
                {"trace_step_id": "step:2", "episode_id": "episode:1", "step_index": 5},
            ],
        }
        self.assertTrue(episode_trace_order_check(context).succeeded)


if __name__ == "__main__":
    unittest.main()
