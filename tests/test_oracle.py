from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from runtime.conditional_autonomy.ingest import policy_input_leakage_check
from runtime.conditional_autonomy.oracle import (
    OracleSimulatorError,
    OracleTurnLimitError,
    OracleUserSimulator,
)
from runtime.conditional_autonomy.preexecution import InvariantDisposition, Verdict
from runtime.conditional_autonomy.projection import ObservationProjection
from runtime.conditional_autonomy.thanksgiving import (
    initial_thanksgiving_state,
    normalized_time,
    utc_minute,
)


ROOT = Path(__file__).resolve().parents[1]
USER_MODEL_FIXTURE = (
    ROOT / "architecture" / "schemas" / "v1.0" / "fixtures" / "valid" / "user-model.valid.json"
)
GENERATED_AT = normalized_time(utc_minute("2026-11-26T17:00:00Z"))
QUESTIONS = (
    {"question_id": "question:dinner", "fact_id": "fact:dinner-deadline"},
    {"question_id": "question:travel", "fact_id": "fact:travel-times"},
    {"question_id": "question:unknown", "fact_id": "fact:not-answerable"},
)


class HostileGoalRefs:
    def __iter__(self):
        raise RuntimeError("hostile goal iterator")


def user_model(seed: int = 42) -> dict[str, object]:
    model = json.loads(USER_MODEL_FIXTURE.read_text(encoding="utf-8"))
    model["answerable_facts"] = ["fact:dinner-deadline", "fact:travel-times"]
    model["maximum_turns"] = 3
    model["seed"] = seed
    return model


def private_state() -> dict[str, object]:
    return {
        "private_world_state_id": "private-state:1",
        "access_class": "PRIVATE_ENVIRONMENT",
        "facts": {
            "fact:dinner-deadline": "18:00",
            "fact:travel-times": {"HOME-BOS": 60},
            "fact:unrequested-secret": "PRIVATE-CANARY-DO-NOT-RELEASE",
        },
        "internal_notes": "SIMULATOR-ONLY-CANARY",
    }


def answer_bytes(seed: int = 42) -> list[bytes]:
    simulator = OracleUserSimulator(user_model(seed), private_state())
    return [
        response.canonical_bytes()
        for response in simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS,
            actor_id="actor:planner",
            goal_refs=("goal:thanksgiving-dinner",),
            generated_at=GENERATED_AT,
            context_budget_tokens=512,
        )
    ]


class OracleUserSimulatorTests(unittest.TestCase):
    def test_identical_seeds_produce_identical_answer_sequences(self) -> None:
        self.assertEqual(answer_bytes(42), answer_bytes(42))
        self.assertNotEqual(answer_bytes(42), answer_bytes(43))

    def test_repeated_calls_share_one_cumulative_collision_free_turn_counter(self) -> None:
        simulator = OracleUserSimulator(user_model(), private_state())
        first = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS[:1],
            actor_id="actor:planner",
            goal_refs=("goal:thanksgiving-dinner",),
            generated_at=GENERATED_AT,
            context_budget_tokens=512,
        )
        remaining = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS[1:],
            actor_id="actor:planner",
            goal_refs=("goal:thanksgiving-dinner",),
            generated_at=GENERATED_AT,
            context_budget_tokens=512,
        )
        combined = (*first, *remaining)
        self.assertEqual([item.turn_index for item in combined], [0, 1, 2])
        self.assertEqual(
            [item.canonical_bytes() for item in combined],
            answer_bytes(42),
        )
        observation_ids = [item.policy_input["observation_id"] for item in combined]
        response_fact_ids = [
            item.policy_input["visible_facts"][0]["fact_id"] for item in combined
        ]
        self.assertEqual(len(set(observation_ids)), 3)
        self.assertEqual(len(set(response_fact_ids)), 3)
        with self.assertRaises(OracleTurnLimitError):
            simulator.answer_sequence(
                initial_thanksgiving_state(),
                QUESTIONS[:1],
                actor_id="actor:planner",
                goal_refs=("goal:thanksgiving-dinner",),
                generated_at=GENERATED_AT,
                context_budget_tokens=512,
            )

    def test_public_ids_are_seed_independent_but_rendering_uses_seed(self) -> None:
        def outputs(seed: int):
            simulator = OracleUserSimulator(user_model(seed), private_state())
            return simulator.answer_sequence(
                initial_thanksgiving_state(),
                QUESTIONS,
                actor_id="actor:planner",
                goal_refs=(),
                generated_at=GENERATED_AT,
            )

        left, right = outputs(42), outputs(43)
        self.assertEqual(
            [item.policy_input["observation_id"] for item in left],
            [item.policy_input["observation_id"] for item in right],
        )
        self.assertEqual(
            [item.policy_input["visible_facts"][0]["fact_id"] for item in left],
            [item.policy_input["visible_facts"][0]["fact_id"] for item in right],
        )
        self.assertNotEqual(
            [item.policy_input["visible_facts"][0]["value"]["utterance"] for item in left],
            [item.policy_input["visible_facts"][0]["value"]["utterance"] for item in right],
        )

    def test_every_response_is_schema_valid_and_inv_014_clean(self) -> None:
        simulator = OracleUserSimulator(user_model(), private_state())
        responses = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS,
            actor_id="actor:planner",
            goal_refs=("goal:thanksgiving-dinner",),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(len(responses), 3)
        for response in responses:
            with self.subTest(turn=response.turn_index):
                outcome = policy_input_leakage_check(
                    response.projection, response.projection_state
                )
                self.assertIs(outcome.verdict, Verdict.PASS)
                self.assertEqual(response.policy_input["access_class"], "POLICY_VISIBLE")
                self.assertEqual(len(response.policy_input["visible_facts"]), 1)

        unknown = responses[2].policy_input["visible_facts"][0]
        self.assertEqual(unknown["epistemic_status"], "UNKNOWN")
        self.assertIsNone(unknown["value"]["answer"])

    def test_private_simulator_state_is_absent_from_policy_inputs(self) -> None:
        model = user_model()
        private = private_state()
        simulator = OracleUserSimulator(model, private)
        # Constructor inputs are detached; later mutation cannot affect answers.
        model["seed"] = 999
        private["internal_notes"] = "MUTATED"
        responses = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS,
            actor_id="actor:planner",
            goal_refs=(),
            generated_at=GENERATED_AT,
        )
        serialized = b"".join(response.canonical_bytes() for response in responses)
        for canary in (
            b"PRIVATE-CANARY-DO-NOT-RELEASE",
            b"SIMULATOR-ONLY-CANARY",
            b"private-state:1",
            b"user-model:p6-oracle",
            b"template:p6-oracle",
            b'"seed"',
        ):
            self.assertNotIn(canary, serialized)
        self.assertIn(b'"answer":"18:00"', serialized)

    def test_injected_private_state_is_detected_by_policy_leakage_validator(self) -> None:
        simulator = OracleUserSimulator(user_model(), private_state())
        response = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS[:1],
            actor_id="actor:planner",
            goal_refs=(),
            generated_at=GENERATED_AT,
        )[0]
        tampered = response.policy_input
        tampered["visible_facts"][0]["value"]["private_state"] = {
            "access_class": "PRIVATE_ENVIRONMENT",
            "value": "injected-canary",
        }
        outcome = policy_input_leakage_check(
            ObservationProjection(tampered, response.projection.lineage),
            response.projection_state,
        )
        self.assertIs(outcome.verdict, Verdict.FAIL)
        self.assertIs(
            outcome.failure_resolution,
            InvariantDisposition.QUARANTINE,
        )
        self.assertIn("PROTECTED_POLICY_INPUT", outcome.failure_codes)

    def test_turn_limit_and_configuration_fail_closed(self) -> None:
        model = user_model()
        model["maximum_turns"] = 1
        simulator = OracleUserSimulator(model, private_state())
        with self.assertRaises(OracleTurnLimitError):
            simulator.answer_sequence(
                initial_thanksgiving_state(),
                QUESTIONS[:2],
                actor_id="actor:planner",
                goal_refs=(),
                generated_at=GENERATED_AT,
            )

        mismatched = private_state()
        mismatched["private_world_state_id"] = "private-state:other"
        with self.assertRaisesRegex(OracleSimulatorError, "must match"):
            OracleUserSimulator(user_model(), mismatched)

        unsupported = user_model()
        unsupported["template_family"] = "template:unsupported"
        with self.assertRaisesRegex(OracleSimulatorError, "unsupported oracle template_family"):
            OracleUserSimulator(unsupported, private_state())

        with self.assertRaisesRegex(OracleSimulatorError, "goal_refs must be a finite sequence"):
            OracleUserSimulator(user_model(), private_state()).answer_sequence(
                initial_thanksgiving_state(),
                QUESTIONS[:1],
                actor_id="actor:planner",
                goal_refs=HostileGoalRefs(),  # type: ignore[arg-type]
                generated_at=GENERATED_AT,
            )

        protected = private_state()
        protected["facts"]["fact:dinner-deadline"] = {
            "access_class": "PRIVATE_ENVIRONMENT",
            "value": "18:00",
        }
        protected_simulator = OracleUserSimulator(user_model(), protected)
        with self.assertRaisesRegex(OracleSimulatorError, "policy boundary"):
            protected_simulator.answer_sequence(
                initial_thanksgiving_state(),
                QUESTIONS[:1],
                actor_id="actor:planner",
                goal_refs=(),
                generated_at=GENERATED_AT,
            )

    def test_failed_batch_does_not_consume_any_turns(self) -> None:
        model = user_model()
        model["answerable_facts"].append("fact:protected")
        model["maximum_turns"] = 4
        private = private_state()
        private["facts"]["fact:protected"] = {
            "access_class": "PRIVATE_ENVIRONMENT",
            "value": "canary",
        }
        simulator = OracleUserSimulator(model, private)
        first = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS[:1],
            actor_id="actor:planner",
            goal_refs=(),
            generated_at=GENERATED_AT,
        )[0]
        with self.assertRaisesRegex(OracleSimulatorError, "policy boundary"):
            simulator.answer_sequence(
                initial_thanksgiving_state(),
                (
                    QUESTIONS[1],
                    {"question_id": "question:protected", "fact_id": "fact:protected"},
                ),
                actor_id="actor:planner",
                goal_refs=(),
                generated_at=GENERATED_AT,
            )
        after_failure = simulator.answer_sequence(
            initial_thanksgiving_state(),
            QUESTIONS[1:2],
            actor_id="actor:planner",
            goal_refs=(),
            generated_at=GENERATED_AT,
        )[0]
        self.assertEqual(first.turn_index, 0)
        self.assertEqual(after_failure.turn_index, 1)

    def test_sequence_is_identical_across_fresh_processes(self) -> None:
        program = (
            "from tests.test_oracle import answer_bytes; import sys; "
            "sys.stdout.buffer.write(b'\\n'.join(answer_bytes(42)))"
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
