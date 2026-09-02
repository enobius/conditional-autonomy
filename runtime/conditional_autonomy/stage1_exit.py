"""Authoritative v1.1.2 Stage 1 keystone exit gate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from .invariant_register import RegisterEvidenceError, build_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXIT_CATEGORY_TESTS = {
    "deterministic-replay": (
        "tests.test_reducer.DeterministicReducerTests.test_replay_is_byte_identical_and_does_not_mutate_inputs",
        "tests.test_reducer.DeterministicReducerTests.test_fresh_process_replay_produces_identical_bytes",
        "tests.test_replay_cli.ReplayCliTests.test_golden_episode_replays_identically_in_fresh_process",
        "tests.test_disruptions.ThanksgivingDisruptionTests.test_exact_p9_delay_is_one_mid_episode_ledger_transition",
        "tests.test_disruptions.ThanksgivingDisruptionTests.test_all_state_changes_replay_from_ledger_byte_identically",
        "tests.test_disruptions.ThanksgivingDisruptionTests.test_disrupted_episode_is_identical_across_fresh_processes",
    ),
    "leakage": (
        "tests.test_projection.ObservationProjectorTests.test_protected_root_canaries_fail_closed",
        "tests.test_projection.ObservationProjectorTests.test_nested_protected_canary_in_value_fails_closed",
        "tests.test_projection.ObservationProjectorTests.test_each_named_protected_ancestor_fails_closed",
        "tests.test_oracle.OracleUserSimulatorTests.test_private_simulator_state_is_absent_from_policy_inputs",
        "tests.test_oracle.OracleUserSimulatorTests.test_injected_private_state_is_detected_by_policy_leakage_validator",
    ),
    "hard-unknown": (
        "tests.test_preexecution.ReconciliationTests.test_hard_unknown_can_never_execute",
        "tests.test_tools.ToolSurfaceTests.test_deny_query_repair_unknown_missing_grant_and_stale_never_dispatch",
        "tests.test_tools.ToolSurfaceTests.test_incomplete_verification_is_indeterminate_and_cannot_advance",
    ),
    "invariant-tests": (
        "tests.test_invariant_register.InvariantRegisterTests.test_live_named_test_evidence_verifies_all_sixteen",
        "tests.test_split_hygiene.GenerationSplitHygieneTests.test_each_prohibited_cross_split_overlap_uses_canonical_inv_013",
    ),
}


@dataclass(frozen=True)
class MutationSpec:
    workstream: str
    relative_path: str
    original: str
    replacement: str
    expected_category: str
    expected_signal: str


MUTATIONS = (
    MutationSpec("1B", "runtime/conditional_autonomy/reducer.py", "if to_version != from_version + 1:", "if to_version != from_version + 2:", "deterministic-replay", "test_replay_is_byte_identical_and_does_not_mutate_inputs"),
    MutationSpec(
        "1C",
        "tests/fixtures/invariants/corpus.json",
        '"test_id": "INV-001-P",\n      "invariant_id": "INV-001",\n      "validator": "compensation_prevalidation_check"',
        '"test_id": "INV-001-P",\n      "invariant_id": "INV-001",\n      "validator": "current_version_check"',
        "invariant-tests",
        "test_live_named_test_evidence_verifies_all_sixteen",
    ),
    MutationSpec("1D", "runtime/conditional_autonomy/disruptions.py", 'P9_JAMES_ARRIVAL = utc_minute("2026-11-26T21:00:00Z")', 'P9_JAMES_ARRIVAL = utc_minute("2026-11-26T22:00:00Z")', "deterministic-replay", "test_exact_p9_delay_is_one_mid_episode_ledger_transition"),
    MutationSpec("1E", "runtime/conditional_autonomy/split_hygiene.py", "if outcome.verdict is not Verdict.PASS:", "if False and outcome.verdict is not Verdict.PASS:", "invariant-tests", "test_each_prohibited_cross_split_overlap_uses_canonical_inv_013"),
)


class Stage1ExitError(RuntimeError):
    """The aggregate gate or mutation campaign was not trustworthy."""


@dataclass(frozen=True)
class CategoryResult:
    category: str
    passed: bool
    tests_run: int
    reason: str | None = None


@dataclass(frozen=True)
class Stage1ExitReport:
    categories: tuple[CategoryResult, ...]
    invariants_verified: int
    invariants_total: int

    @property
    def passed(self) -> bool:
        return len(self.categories) == 4 and all(item.passed for item in self.categories) and self.invariants_verified == self.invariants_total == 16


def _test_ids(suite: unittest.TestSuite) -> tuple[str, ...]:
    result: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.extend(_test_ids(item))
        else:
            result.append(item.id())
    return tuple(result)


def _run_category(category: str) -> CategoryResult:
    names = EXIT_CATEGORY_TESTS[category]
    loader = unittest.TestLoader()
    loaded: list[unittest.TestSuite] = []
    for name in names:
        suite = loader.loadTestsFromName(name)
        if loader.errors or suite.countTestCases() != 1 or _test_ids(suite) != (name,):
            return CategoryResult(category, False, 0, "EXACT_TEST_LOAD_FAILURE")
        loaded.append(suite)
    result = unittest.TestResult()
    unittest.TestSuite(loaded).run(result)
    passed = result.wasSuccessful() and result.testsRun == len(names) and not result.failures and not result.errors and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses
    failure_details = sorted(
        {
            test.id() + ":" + traceback.strip().splitlines()[-1]
            for test, traceback in (*result.failures, *result.errors)
        }
    )
    reason = None if passed else "FAILED_TESTS:" + "|".join(failure_details)
    return CategoryResult(category, passed, result.testsRun, reason)


def run_stage1_exit() -> Stage1ExitReport:
    categories = tuple(_run_category(name) for name in EXIT_CATEGORY_TESTS)
    try:
        invariant_report = build_report()
    except RegisterEvidenceError as exc:
        categories = tuple(
            replace(
                item,
                passed=False,
                reason=(item.reason + ";" if item.reason else "")
                + f"REGISTER_EVIDENCE_FAILURE: {exc}",
            )
            if item.category == "invariant-tests"
            else item
            for item in categories
        )
        return Stage1ExitReport(categories, 0, 16)
    return Stage1ExitReport(categories, invariant_report.verified, 16)


def _copy_clean_inputs(destination: Path) -> None:
    for name in ("runtime", "tests", "architecture"):
        shutil.copytree(REPOSITORY_ROOT / name, destination / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _run_exact_gate(checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "runtime.conditional_autonomy.stage1_exit"], cwd=checkout, capture_output=True, text=True, encoding="utf-8", check=False, timeout=180)


def _apply_mutation(checkout: Path, mutation: MutationSpec) -> bytes:
    path = checkout / mutation.relative_path
    original_bytes = path.read_bytes()
    text = original_bytes.decode("utf-8")
    if text.count(mutation.original) != 1:
        raise Stage1ExitError(f"{mutation.workstream} mutation target is not unique")
    path.write_text(text.replace(mutation.original, mutation.replacement), encoding="utf-8")
    return original_bytes


def verify_seeded_defects() -> None:
    """Run the exact gate on isolated copies before, during, and after mutation."""

    with tempfile.TemporaryDirectory() as directory:
        pristine = Path(directory) / "pristine"
        _copy_clean_inputs(pristine)
        initial = _run_exact_gate(pristine)
        if initial.returncode != 0 or "Stage 1 exit gate: GREEN" not in initial.stdout:
            raise Stage1ExitError("pristine aggregate gate is not green")
        for mutation in MUTATIONS:
            checkout = Path(directory) / f"mutant-{mutation.workstream}"
            shutil.copytree(pristine, checkout)
            path = checkout / mutation.relative_path
            original_bytes = _apply_mutation(checkout, mutation)
            seeded = _run_exact_gate(checkout)
            if (
                seeded.returncode == 0
                or f"{mutation.expected_category}: FAIL" not in seeded.stdout
                or mutation.expected_signal not in seeded.stdout
            ):
                raise Stage1ExitError(f"{mutation.workstream} mutation did not fail {mutation.expected_category}")
            path.write_bytes(original_bytes)
            restored = _run_exact_gate(checkout)
            if restored.returncode != 0 or "Stage 1 exit gate: GREEN" not in restored.stdout:
                raise Stage1ExitError(f"{mutation.workstream} restoration did not return green")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-seeded-defects", action="store_true")
    args = parser.parse_args(argv)
    report = run_stage1_exit()
    for category in report.categories:
        state = "PASS" if category.passed else "FAIL"
        detail = f" ({category.reason})" if category.reason else ""
        print(f"{category.category}: {state}; {category.tests_run} tests{detail}")
    print(f"Invariant register: {report.invariants_verified}/{report.invariants_total} VERIFIED")
    if report.passed and args.verify_seeded_defects:
        try:
            verify_seeded_defects()
        except (OSError, subprocess.SubprocessError, Stage1ExitError) as exc:
            print(f"Seeded defect campaign: FAIL ({exc})")
            print("Stage 1 exit gate: RED")
            return 2
        print("Seeded defect campaign: 4/4 isolated fail-and-restore proofs PASS")
    print(f"Stage 1 exit gate: {'GREEN' if report.passed else 'RED'}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
