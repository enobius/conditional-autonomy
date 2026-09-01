"""Checked Stage 1 feasibility-oracle boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .feasibility_checker import IndependentWitnessChecker
from .feasibility_solver import DeterministicConstraintSolver
from .feasibility_types import FeasibilityDecision
from .thanksgiving import ScheduledAction


FEASIBILITY_ORACLE_VERSION = "thanksgiving-csp.1.0"


class FeasibilityOracleError(RuntimeError):
    """The solver/checker boundary failed closed."""


class FeasibilityOracle:
    """Compose an untrusted solver with an authoritative independent checker."""

    def __init__(
        self,
        solver: DeterministicConstraintSolver | None = None,
        checker: IndependentWitnessChecker | None = None,
    ) -> None:
        self._solver = solver or DeterministicConstraintSolver()
        self._checker = checker or IndependentWitnessChecker()

    def assess(
        self, state: Mapping[str, Any], templates: Sequence[ScheduledAction]
    ) -> FeasibilityDecision:
        try:
            witness = self._solver.solve(state, templates)
        except Exception as exc:
            raise FeasibilityOracleError("solver failed before producing a decision") from exc
        if witness is None:
            try:
                independent = self._checker.prove_or_find(state, templates)
            except Exception as exc:
                raise FeasibilityOracleError(
                    "independent negative proof did not complete"
                ) from exc
            if independent.feasible:
                raise FeasibilityOracleError(
                    "solver reported infeasible but the independent checker found a witness"
                )
            return FeasibilityDecision(
                False,
                None,
                "infeasibility independently proven by exhaustive finite-domain search",
            )
        try:
            checked = self._checker.check(state, templates, witness)
        except Exception as exc:
            raise FeasibilityOracleError("independent witness check failed") from exc
        if not checked.accepted:
            raise FeasibilityOracleError(
                "solver emitted a witness rejected by the independent checker: "
                + "; ".join(checked.failures)
            )
        return FeasibilityDecision(True, witness, "independently checked witness")
