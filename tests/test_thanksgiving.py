from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from runtime.conditional_autonomy.reducer import canonical_state_bytes, replay_events
from runtime.conditional_autonomy.thanksgiving import (
    DINNER,
    EMILY_ARRIVAL,
    ENVIRONMENT_VERSION,
    JAMES_ARRIVAL,
    MICHAEL_ARRIVAL,
    Criticality,
    Enforceability,
    PredictedEffect,
    evaluate_schedule,
    initial_thanksgiving_state,
    normalized_time,
    run_thanksgiving_episode,
    thanksgiving_actions,
    utc_minute,
)


ROOT = Path(__file__).resolve().parents[1]


class ThanksgivingEnvironmentTests(unittest.TestCase):
    def test_table_6_facts_are_encoded_without_p9_disruption(self) -> None:
        state = initial_thanksgiving_state()
        facts = state["resources"]["projection_facts"]
        self.assertEqual(ENVIRONMENT_VERSION, "thanksgiving-p6.1.0")
        self.assertEqual(facts["dinner_deadline"]["value"], normalized_time(DINNER))
        self.assertEqual(
            facts["cooking_requirements"]["value"],
            {
                "turkey_minutes": 240,
                "sides_minutes": 120,
                "continuous_home_supervision": True,
            },
        )
        self.assertEqual(
            facts["travel_times"]["value"],
            {"HOME-BOS": 60, "BOS-GRANDMA_HOME": 60, "HOME-GRANDMA_HOME": 30},
        )
        self.assertEqual(state["entities"]["person:james"]["origin"], "SF")
        self.assertEqual(state["entities"]["person:emily"]["origin"], "Chicago")
        self.assertEqual(state["entities"]["person:michael"]["origin"], "NY")
        self.assertEqual(state["entities"]["person:grandma"]["health_status"], "HEALTHY")
        self.assertEqual(
            state["entities"]["person:james"]["arrival_at"],
            normalized_time(JAMES_ARRIVAL),
        )
        self.assertEqual(
            state["entities"]["person:emily"]["arrival_at"],
            normalized_time(EMILY_ARRIVAL),
        )
        self.assertEqual(
            state["entities"]["person:michael"]["arrival_at"],
            normalized_time(MICHAEL_ARRIVAL),
        )
        self.assertEqual(state["exogenous_events"], [])
        self.assertNotIn("delay", json.dumps(state).lower())

    def test_hand_authored_episode_executes_through_reducer(self) -> None:
        episode = run_thanksgiving_episode()
        replayed = replay_events(episode.initial_state, episode.events)
        self.assertEqual(
            canonical_state_bytes(replayed), canonical_state_bytes(episode.final_state)
        )
        self.assertTrue(all(item["status"] == "COMPLETED" for item in replayed["obligations"]))
        self.assertTrue(
            all(
                replayed["entities"][person]["location"] == "HOME"
                for person in (
                    "person:sarah",
                    "person:james",
                    "person:emily",
                    "person:michael",
                    "person:grandma",
                )
            )
        )
        self.assertEqual(replayed["resources"]["food"]["turkey"]["status"], "READY")
        self.assertEqual(replayed["resources"]["food"]["sides"]["status"], "READY")
        self.assertEqual(len(replayed["completed_actions"]), 5)

    def test_all_constraint_classes_and_outcome_execute(self) -> None:
        episode = run_thanksgiving_episode()
        self.assertEqual(
            {item.constraint.enforceability for item in episode.evaluations},
            {
                Enforceability.PREVENTABLE,
                Enforceability.PREDICTIVE,
                Enforceability.DETECTABLE,
            },
        )
        self.assertEqual(
            {item.constraint.criticality for item in episode.evaluations},
            {Criticality.HARD, Criticality.SOFT},
        )
        self.assertTrue(all(item.passed for item in episode.evaluations))
        self.assertEqual(
            episode.outcome,
            {
                "goal_success": True,
                "constraint_score": 1.0,
                "hard_violation_count": 0,
                "optimality_gap": None,
                "recovery_success": None,
                "execution_cost": 0.0,
                "latency": 0.0,
                "token_count": 0,
                "tool_calls": 0,
                "user_interventions": 0,
                "clarification_total": 0,
                "clarification_necessary": 0,
                "clarification_unnecessary": 0,
                "clarification_insufficient": 0,
                "clarification_repeated": 0,
                "clarification_incorrect_scope": 0,
                "evaluator_disagreement": 0.0,
            },
        )

    def test_policy_projection_is_schema_valid_and_lineage_bound(self) -> None:
        projection = run_thanksgiving_episode().observation_projection
        observation = projection.observation
        self.assertEqual(observation["episode_id"], "episode:thanksgiving-p6-static-001")
        self.assertEqual(len(observation["visible_facts"]), 3)
        self.assertEqual(
            tuple(item.output_path for item in projection.lineage),
            ("/visible_facts/0", "/visible_facts/1", "/visible_facts/2"),
        )
        self.assertTrue(all(item.source_access_class == "POLICY_VISIBLE" for item in projection.lineage))

    def test_windows_are_half_open_and_deadlines_are_inclusive(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        turkey = next(item for item in actions if item.action_id == "action:cook-turkey")
        sides = next(item for item in actions if item.action_id == "action:prepare-sides")
        self.assertEqual(turkey.end_minute, DINNER)
        self.assertEqual(sides.end_minute, DINNER)
        self.assertTrue(
            next(
                result
                for result in evaluate_schedule(state, actions)
                if result.constraint.constraint_id == "constraint:time-windows"
            ).passed
        )

        boundary_pair = (
            replace(turkey, end_minute=sides.start_minute),
            replace(sides, resource_ids=("resource:oven",)),
        )
        capacity = next(
            result
            for result in evaluate_schedule(state, boundary_pair)
            if result.constraint.constraint_id == "constraint:resource-capacity"
        )
        self.assertTrue(capacity.passed)

    def test_preventable_capacity_and_predictive_deadline_fail_closed(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        turkey = next(item for item in actions if item.action_id == "action:cook-turkey")
        sides = next(item for item in actions if item.action_id == "action:prepare-sides")
        conflicting = replace(
            sides,
            start_minute=turkey.start_minute,
            resource_ids=("resource:oven",),
        )
        results = evaluate_schedule(
            state, tuple(conflicting if item is sides else item for item in actions)
        )
        self.assertFalse(
            next(item for item in results if item.constraint.constraint_id == "constraint:resource-capacity").passed
        )

        late_effect = replace(
            turkey.effects[0], earliest_minute=DINNER, latest_minute=DINNER + 1
        )
        late_turkey = replace(turkey, effects=(late_effect,))
        results = evaluate_schedule(
            state, tuple(late_turkey if item is turkey else item for item in actions)
        )
        self.assertFalse(
            next(item for item in results if item.constraint.constraint_id == "constraint:predicted-completion").passed
        )

    def test_exact_table_6_cooking_durations_are_enforced(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        for action_id, wrong_duration in (
            ("action:cook-turkey", 60),
            ("action:prepare-sides", 60),
        ):
            with self.subTest(action_id=action_id):
                target = next(item for item in actions if item.action_id == action_id)
                shortened = replace(
                    target, start_minute=target.end_minute - wrong_duration
                )
                results = evaluate_schedule(
                    state,
                    tuple(shortened if item is target else item for item in actions),
                )
                duration = next(
                    item
                    for item in results
                    if item.constraint.constraint_id == "constraint:exact-duration"
                )
                self.assertFalse(duration.passed)

    def test_action_obligation_and_state_dependencies_must_agree(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        transport = next(
            item for item in actions if item.action_id == "action:airport-grandma-pickup"
        )
        removed_action_dependency = replace(transport, dependencies=())
        results = evaluate_schedule(
            state,
            tuple(
                removed_action_dependency if item is transport else item
                for item in actions
            ),
        )
        dependency = next(
            item
            for item in results
            if item.constraint.constraint_id == "constraint:dependencies"
        )
        self.assertFalse(dependency.passed)
        self.assertIn("disagree with state", dependency.detail)

        mutated_state = deepcopy(state)
        target = next(
            item
            for item in mutated_state["obligations"]
            if item["obligation_id"] == "obligation:airport-grandma-pickup"
        )
        target["dependency_ids"] = []
        dependency = next(
            item
            for item in evaluate_schedule(mutated_state, actions)
            if item.constraint.constraint_id == "constraint:dependencies"
        )
        self.assertFalse(dependency.passed)
        self.assertIn("obligation and state dependencies disagree", dependency.detail)

        mutated_state = deepcopy(state)
        mutated_state["dependencies"] = []
        dependency = next(
            item
            for item in evaluate_schedule(mutated_state, actions)
            if item.constraint.constraint_id == "constraint:dependencies"
        )
        self.assertFalse(dependency.passed)

    def test_supervision_tracks_actions_that_move_people(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        rental = next(
            item for item in actions if item.action_id == "action:james-land-and-rent"
        )
        sarah_leaves = PredictedEffect(
            "/entities/person:sarah/location",
            "AWAY",
            rental.end_minute,
            rental.end_minute,
        )
        modified = replace(rental, effects=(*rental.effects, sarah_leaves))
        supervision = next(
            item
            for item in evaluate_schedule(
                state, tuple(modified if item is rental else item for item in actions)
            )
            if item.constraint.constraint_id == "constraint:cooking-supervision"
        )
        self.assertFalse(supervision.passed)
        self.assertIn("no family member HOME", supervision.detail)

    def test_predicted_effect_time_must_equal_actual_transition_time(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        turkey = next(item for item in actions if item.action_id == "action:cook-turkey")
        premature = replace(
            turkey.effects[0],
            earliest_minute=turkey.start_minute,
            latest_minute=turkey.start_minute,
        )
        modified = replace(turkey, effects=(premature,))
        prediction = next(
            item
            for item in evaluate_schedule(
                state, tuple(modified if item is turkey else item for item in actions)
            )
            if item.constraint.constraint_id == "constraint:predicted-completion"
        )
        self.assertFalse(prediction.passed)
        self.assertIn("transition time", prediction.detail)

    def test_schema_boundaries_use_normalized_times_and_honest_reversibility(self) -> None:
        state = initial_thanksgiving_state()
        for entity_id in ("person:james", "person:emily", "person:michael"):
            self.assertIn("arrival_at", state["entities"][entity_id])
            self.assertNotIn("arrival_minute", state["entities"][entity_id])
        for obligation in state["obligations"]:
            self.assertEqual(set(obligation["window"]), {"start", "end"})
            self.assertIn("deadline", obligation)
            self.assertNotIn("deadline_minute", obligation)

        episode = run_thanksgiving_episode()
        for proposal in episode.actions:
            self.assertEqual(set(proposal["arguments"]), {"start_at", "end_at", "resource_ids"})
            for effect in proposal["expected_effects"]:
                self.assertIn("earliest_at", effect)
                self.assertIn("latest_at", effect)
                self.assertNotIn("earliest_minute", effect)
                self.assertNotIn("latest_minute", effect)
            expected = (
                "IRREVERSIBLE"
                if proposal["action_type"]
                in {"thanksgiving:cook-turkey", "thanksgiving:prepare-sides"}
                else "REVERSIBLE"
            )
            self.assertEqual(proposal["reversibility"], expected)
        self.assertIsNone(episode.outcome["optimality_gap"])

    def test_effects_and_constraints_are_immutable(self) -> None:
        action = thanksgiving_actions()[0]
        with self.assertRaises(FrozenInstanceError):
            action.effects[0].latest_minute = DINNER  # type: ignore[misc]
        constraint = run_thanksgiving_episode().evaluations[0].constraint
        with self.assertRaises(FrozenInstanceError):
            constraint.description = "mutated"  # type: ignore[misc]

    def test_utc_minute_boundary_rejects_non_utc_or_subminute_values(self) -> None:
        self.assertEqual(normalized_time(utc_minute("2026-11-26T23:00:00Z"))["instant"], "2026-11-26T23:00:00Z")
        with self.assertRaises(ValueError):
            utc_minute("2026-11-26T18:00:00-05:00")
        with self.assertRaises(ValueError):
            utc_minute("2026-11-26T23:00:01Z")

    def test_episode_is_identical_across_fresh_processes(self) -> None:
        program = (
            "from runtime.conditional_autonomy.thanksgiving import "
            "run_thanksgiving_episode; import sys; "
            "sys.stdout.buffer.write(run_thanksgiving_episode().canonical_summary())"
        )
        outputs = []
        for seed in ("1", "91"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
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
