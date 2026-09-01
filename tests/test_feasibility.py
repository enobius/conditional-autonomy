from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from runtime.conditional_autonomy.disruptions import (
    P9_JAMES_ARRIVAL,
    p9_replanned_actions,
)
from runtime.conditional_autonomy.feasibility import (
    FeasibilityOracle,
    FeasibilityOracleError,
)
from runtime.conditional_autonomy.feasibility_checker import IndependentWitnessChecker
from runtime.conditional_autonomy.feasibility_solver import DeterministicConstraintSolver
from runtime.conditional_autonomy.feasibility_types import (
    ActionAssignment,
    FeasibilityWitness,
)
from runtime.conditional_autonomy.storage import canonical_json_bytes
from runtime.conditional_autonomy.thanksgiving import (
    DINNER,
    initial_thanksgiving_state,
    normalized_time,
    thanksgiving_actions,
    utc_minute,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "feasibility" / "corpus.json"


def p9_state():
    state = initial_thanksgiving_state()
    state["entities"]["person:james"]["arrival_at"] = normalized_time(P9_JAMES_ARRIVAL)
    return state


def corpus_problem(variant: str):
    state = initial_thanksgiving_state()
    actions = thanksgiving_actions()
    if variant == "P6":
        return state, actions
    if variant == "P9":
        return p9_state(), p9_replanned_actions()
    if variant == "MISSING_ACTION":
        return state, actions[:-1]
    if variant == "OVEN_CONFLICT":
        sides = next(item for item in actions if item.action_id == "action:prepare-sides")
        sides = replace(sides, resource_ids=("resource:oven",))
        constrained = deepcopy(state)
        target = next(
            item for item in constrained["obligations"]
            if item["obligation_id"] == "obligation:sides-ready"
        )
        fixed = normalized_time(utc_minute("2026-11-26T19:00:00Z"))
        target["window"] = {"start": fixed, "end": normalized_time(DINNER)}
        return constrained, tuple(sides if item.action_id == sides.action_id else item for item in actions)
    if variant == "P9_STALE":
        delayed = p9_state()
        rental = next(item for item in actions if item.action_type == "thanksgiving:land-and-rent")
        target = next(
            item for item in delayed["obligations"]
            if item["obligation_id"] == rental.obligation_id
        )
        target["window"]["end"] = normalized_time(rental.start_minute)
        target["deadline"] = normalized_time(rental.start_minute)
        return delayed, actions
    if variant == "TURKEY_WINDOW":
        constrained = deepcopy(state)
        target = next(
            item for item in constrained["obligations"]
            if item["obligation_id"] == "obligation:turkey-ready"
        )
        target["window"]["start"] = normalized_time(DINNER - 120)
        return constrained, actions
    raise AssertionError(f"unknown corpus variant {variant}")


class FeasibilityOracleTests(unittest.TestCase):
    def test_reviewed_hand_authored_corpus(self) -> None:
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(corpus["review_status"], "hand-authored-and-reviewed")
        oracle = FeasibilityOracle()
        for case in corpus["cases"]:
            with self.subTest(case_id=case["case_id"]):
                state, actions = corpus_problem(case["variant"])
                self.assertEqual(
                    oracle.assess(state, actions).feasible,
                    case["expected_feasible"],
                )

    def test_witness_is_deterministic_and_canonically_ordered(self) -> None:
        oracle = FeasibilityOracle()
        left = oracle.assess(initial_thanksgiving_state(), thanksgiving_actions())
        right = oracle.assess(
            initial_thanksgiving_state(), tuple(reversed(thanksgiving_actions()))
        )
        self.assertIsNotNone(left.witness)
        self.assertEqual(left.witness.canonical_bytes(), right.witness.canonical_bytes())
        self.assertEqual(
            [item.action_id for item in left.witness.assignments],
            sorted(item.action_id for item in left.witness.assignments),
        )

    def test_witness_is_identical_across_fresh_processes(self) -> None:
        program = (
            "from runtime.conditional_autonomy.feasibility import FeasibilityOracle; "
            "from runtime.conditional_autonomy.thanksgiving import "
            "initial_thanksgiving_state,thanksgiving_actions; import sys; "
            "w=FeasibilityOracle().assess(initial_thanksgiving_state(),thanksgiving_actions()).witness; "
            "sys.stdout.buffer.write(w.canonical_bytes())"
        )
        outputs = []
        for seed in ("3", "811"):
            outputs.append(
                subprocess.run(
                    [sys.executable, "-c", program],
                    cwd=ROOT,
                    env=dict(os.environ, PYTHONHASHSEED=seed),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).stdout
            )
        self.assertEqual(outputs[0], outputs[1])

    def test_checker_rejects_early_arrival_even_with_valid_problem_binding(self) -> None:
        state = p9_state()
        actions = p9_replanned_actions()
        witness = DeterministicConstraintSolver().solve(state, actions)
        self.assertIsNotNone(witness)
        forged = tuple(
            ActionAssignment(item.action_id, item.start_minute - 180, item.end_minute - 180)
            if item.action_id == "action:p9-james-land-and-rent"
            else item
            for item in witness.assignments
        )
        check = IndependentWitnessChecker().check(
            state, actions, replace(witness, assignments=forged)
        )
        self.assertFalse(check.accepted)
        self.assertTrue(any("ledger arrival" in item for item in check.failures))

    def test_checker_rejects_resource_conflict_without_consulting_solver(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        witness = DeterministicConstraintSolver().solve(state, actions)
        self.assertIsNotNone(witness)
        assignments = []
        turkey = next(item for item in witness.assignments if item.action_id == "action:cook-turkey")
        for item in witness.assignments:
            if item.action_id == "action:prepare-sides":
                assignments.append(ActionAssignment(item.action_id, turkey.start_minute, turkey.start_minute + 120))
            else:
                assignments.append(item)
        modified_templates = tuple(
            replace(item, resource_ids=("resource:oven",))
            if item.action_id == "action:prepare-sides"
            else item
            for item in actions
        )
        # Rebind only the input hash, as a malicious/buggy solver could do.
        problem_hash = IndependentWitnessChecker._independent_problem_hash(
            state, modified_templates
        )
        forged = FeasibilityWitness(witness.environment_version, problem_hash, tuple(assignments))
        check = IndependentWitnessChecker().check(state, modified_templates, forged)
        self.assertFalse(check.accepted)
        self.assertTrue(any("resource-capacity" in item for item in check.failures))

    def test_checker_rejects_incomplete_or_cross_problem_witness(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        witness = DeterministicConstraintSolver().solve(state, actions)
        self.assertIsNotNone(witness)
        incomplete = replace(witness, assignments=witness.assignments[:-1])
        self.assertFalse(
            IndependentWitnessChecker().check(state, actions, incomplete).accepted
        )
        changed = deepcopy(state)
        changed["entities"]["person:james"]["arrival_at"] = normalized_time(P9_JAMES_ARRIVAL)
        self.assertFalse(
            IndependentWitnessChecker().check(changed, actions, witness).accepted
        )

    def test_oracle_fails_closed_when_buggy_solver_emits_invalid_witness(self) -> None:
        state = initial_thanksgiving_state()
        actions = thanksgiving_actions()
        valid = DeterministicConstraintSolver().solve(state, actions)
        self.assertIsNotNone(valid)
        turkey = next(item for item in valid.assignments if item.action_id == "action:cook-turkey")
        forged = replace(
            valid,
            assignments=tuple(
                ActionAssignment(item.action_id, item.start_minute, item.end_minute + 1)
                if item.action_id == turkey.action_id
                else item
                for item in valid.assignments
            ),
        )

        class BuggySolver:
            def solve(self, _state, _templates):
                return forged

        with self.assertRaisesRegex(FeasibilityOracleError, "independent checker"):
            FeasibilityOracle(solver=BuggySolver()).assess(state, actions)

    def test_faulty_negative_solver_cannot_reject_feasible_problem(self) -> None:
        class AlwaysNegativeSolver:
            def solve(self, _state, _templates):
                return None

        with self.assertRaisesRegex(
            FeasibilityOracleError, "independent checker found a witness"
        ):
            FeasibilityOracle(solver=AlwaysNegativeSolver()).assess(
                initial_thanksgiving_state(), thanksgiving_actions()
            )

    def test_internal_solver_error_is_not_reported_as_infeasibility(self) -> None:
        class BrokenSolver:
            def solve(self, _state, _templates):
                raise RuntimeError("internal defect")

        with self.assertRaisesRegex(FeasibilityOracleError, "solver failed"):
            FeasibilityOracle(solver=BrokenSolver()).assess(
                initial_thanksgiving_state(), thanksgiving_actions()
            )

    def test_genuine_infeasibility_requires_completed_independent_proof(self) -> None:
        class RecordingChecker(IndependentWitnessChecker):
            def __init__(self):
                self.proof_calls = 0

            def prove_or_find(self, state, templates):
                self.proof_calls += 1
                return super().prove_or_find(state, templates)

        checker = RecordingChecker()
        state, actions = corpus_problem("TURKEY_WINDOW")
        decision = FeasibilityOracle(checker=checker).assess(state, actions)
        self.assertFalse(decision.feasible)
        self.assertEqual(checker.proof_calls, 1)
        self.assertIn("independently proven", decision.reason)

    def test_checker_failure_during_negative_proof_returns_unknown_error(self) -> None:
        class NegativeSolver:
            def solve(self, _state, _templates):
                return None

        class BrokenChecker(IndependentWitnessChecker):
            def prove_or_find(self, _state, _templates):
                raise RuntimeError("proof engine defect")

        with self.assertRaisesRegex(
            FeasibilityOracleError, "negative proof did not complete"
        ):
            FeasibilityOracle(
                solver=NegativeSolver(), checker=BrokenChecker()
            ).assess(initial_thanksgiving_state(), thanksgiving_actions())

    def test_solver_and_checker_are_source_independent(self) -> None:
        solver_source = (ROOT / "runtime" / "conditional_autonomy" / "feasibility_solver.py").read_text()
        checker_source = (ROOT / "runtime" / "conditional_autonomy" / "feasibility_checker.py").read_text()
        solver_imports = {
            node.module
            for node in ast.walk(ast.parse(solver_source))
            if isinstance(node, ast.ImportFrom)
        }
        checker_imports = {
            node.module
            for node in ast.walk(ast.parse(checker_source))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("feasibility_checker", solver_imports)
        self.assertNotIn("feasibility_solver", checker_imports)
        solver_names = {
            alias.name
            for node in ast.walk(ast.parse(solver_source))
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        checker_names = {
            alias.name
            for node in ast.walk(ast.parse(checker_source))
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("evaluate_schedule", solver_names)
        self.assertIn("evaluate_schedule", checker_names)


if __name__ == "__main__":
    unittest.main()
