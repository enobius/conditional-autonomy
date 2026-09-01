"""Compute deferred-invariant status from executable unittest evidence.

The Markdown register remains the contract source.  Its hand-written ``status``
field is deliberately ignored: validator availability and named test results are
the only inputs to the computed status.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from enum import Enum
import importlib
import json
import os
from pathlib import Path
import re
import sys
import unittest
from typing import Iterable, Mapping, Sequence

from runtime.conditional_autonomy.ingest import (
    artifact_integrity_check,
    artifact_reference_check,
    event_id_uniqueness_check,
    policy_input_leakage_check,
)
from runtime.conditional_autonomy.preexecution import (
    adapter_compatibility_check,
    compensation_prevalidation_check,
    current_version_check,
)
from runtime.conditional_autonomy.promotion_invariants import (
    clarification_counter_reconciliation,
    split_leakage_check,
)
from runtime.conditional_autonomy.reconciliation_invariants import (
    audit_deadline_check,
    compensation_current_authority_check,
    verified_effect_check,
)
from runtime.conditional_autonomy.replay_invariants import (
    deterministic_replay_check,
    episode_trace_order_check,
    logical_clock_order_check,
    state_version_transition_check,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTER = (
    REPOSITORY_ROOT / "architecture" / "schemas" / "v1.0" / "deferred-invariants.md"
)
DEFAULT_CORPUS = REPOSITORY_ROOT / "tests" / "fixtures" / "invariants" / "corpus.json"
EXPECTED_INVARIANTS = tuple(f"INV-{number:03d}" for number in range(1, 17))

_REQUIRED_FIELDS = frozenset(
    {
        "invariant_id",
        "statement",
        "reason_deferred",
        "owner",
        "validator",
        "enforcement_phase",
        "failure_resolution",
        "positive_test",
        "negative_test",
        "status",
    }
)
_PHASE_MODULES = {
    "ingest": "runtime.conditional_autonomy.ingest",
    "pre-execution": "runtime.conditional_autonomy.preexecution",
    "reconciliation": "runtime.conditional_autonomy.reconciliation_invariants",
    "replay": "runtime.conditional_autonomy.replay_invariants",
    "promotion": "runtime.conditional_autonomy.promotion_invariants",
}
_CANONICAL_OWNERSHIP = {
    "INV-001": ("pre-execution", "compensation_prevalidation_check", compensation_prevalidation_check),
    "INV-002": ("reconciliation", "compensation_current_authority_check", compensation_current_authority_check),
    "INV-003": ("ingest", "artifact_reference_check", artifact_reference_check),
    "INV-004": ("pre-execution", "current_version_check", current_version_check),
    "INV-005": ("ingest", "event_id_uniqueness_check", event_id_uniqueness_check),
    "INV-006": ("replay", "logical_clock_order_check", logical_clock_order_check),
    "INV-007": ("replay", "state_version_transition_check", state_version_transition_check),
    "INV-008": ("replay", "deterministic_replay_check", deterministic_replay_check),
    "INV-009": ("reconciliation", "verified_effect_check", verified_effect_check),
    "INV-010": ("reconciliation", "audit_deadline_check", audit_deadline_check),
    "INV-011": ("promotion", "clarification_counter_reconciliation", clarification_counter_reconciliation),
    "INV-012": ("pre-execution", "adapter_compatibility_check", adapter_compatibility_check),
    "INV-013": ("promotion", "split_leakage_check", split_leakage_check),
    "INV-014": ("ingest", "policy_input_leakage_check", policy_input_leakage_check),
    "INV-015": ("ingest", "artifact_integrity_check", artifact_integrity_check),
    "INV-016": ("replay", "episode_trace_order_check", episode_trace_order_check),
}
_EVIDENCE_TESTS = (
    "tests.test_ingest.IngestValidatorTests."
    "test_registered_and_supplemental_ingest_corpus_cases",
    "tests.test_preexecution.PreExecutionInvariantTests."
    "test_registered_and_supplemental_corpus_cases",
    "tests.test_reconciliation_invariants.ReconciliationInvariantTests."
    "test_all_registered_and_supplemental_corpus_cases",
    "tests.test_replay_invariants.ReplayInvariantAdapterTests."
    "test_all_registered_and_supplemental_corpus_cases",
    "tests.test_promotion_invariants.PromotionInvariantTests."
    "test_all_registered_and_supplemental_corpus_cases",
)
_FENCED_YAML = re.compile(r"```yaml\s*\n(?P<body>.*?)```", re.DOTALL)
_CORPUS_TEST_ID = re.compile(r"^(INV-\d{3})-([PN])(?:\.[a-z0-9-]+)?$")


class RegisterEvidenceError(ValueError):
    """The register or evidence cannot safely establish invariant status."""


class InvariantStatus(str, Enum):
    OPEN = "OPEN"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class InvariantRecord:
    invariant_id: str
    statement: str
    reason_deferred: str
    owner: str
    validator: str
    enforcement_phase: str
    failure_resolution: str
    positive_test: str
    negative_test: str


@dataclass(frozen=True)
class TestEvidence:
    test_id: str
    passed: bool


@dataclass(frozen=True)
class InvariantResult:
    invariant_id: str
    status: InvariantStatus
    validator_available: bool
    positive_passed: bool
    negative_passed: bool


@dataclass(frozen=True)
class RegisterReport:
    results: tuple[InvariantResult, ...]

    @property
    def counts(self) -> Mapping[InvariantStatus, int]:
        count = Counter(result.status for result in self.results)
        return {status: count[status] for status in InvariantStatus}

    @property
    def verified(self) -> int:
        return self.counts[InvariantStatus.VERIFIED]


class _NamedSubtestResult(unittest.TestResult):
    """Capture one result for every ``subTest(test_id=...)`` execution."""

    def __init__(self) -> None:
        super().__init__()
        self.evidence: list[TestEvidence] = []

    def addSubTest(self, test, subtest, outcome) -> None:  # noqa: N802
        super().addSubTest(test, subtest, outcome)
        params = dict(subtest.params)
        test_id = params.get("test_id")
        if test_id is not None:
            self.evidence.append(TestEvidence(test_id=test_id, passed=outcome is None))


def _test_ids(suite: unittest.TestSuite) -> tuple[str, ...]:
    ids: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            ids.extend(_test_ids(item))
        else:
            ids.append(item.id())
    return tuple(ids)


def parse_register(
    text: str,
    *,
    expected_invariants: Sequence[str] = EXPECTED_INVARIANTS,
) -> tuple[InvariantRecord, ...]:
    """Parse and strictly validate the fenced records in the Markdown register."""

    blocks = _FENCED_YAML.findall(text)
    if not blocks:
        raise RegisterEvidenceError("register contains no fenced YAML records")
    records: list[InvariantRecord] = []
    source_test_ids: list[str] = []
    for index, block in enumerate(blocks, start=1):
        values: dict[str, str] = {}
        for line in block.splitlines():
            if not line.strip():
                continue
            if line[:1].isspace() or ":" not in line:
                raise RegisterEvidenceError(f"record {index} has malformed field syntax")
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if key in values:
                raise RegisterEvidenceError(f"record {index} duplicates field {key!r}")
            if not key or not value:
                raise RegisterEvidenceError(f"record {index} has an empty field")
            values[key] = value
        if set(values) != _REQUIRED_FIELDS:
            missing = sorted(_REQUIRED_FIELDS - set(values))
            extra = sorted(set(values) - _REQUIRED_FIELDS)
            raise RegisterEvidenceError(
                f"record {index} fields differ (missing={missing}, extra={extra})"
            )
        if values["status"] not in {status.value for status in InvariantStatus}:
            raise RegisterEvidenceError(f"record {index} has invalid source status")
        if values["enforcement_phase"] not in _PHASE_MODULES:
            raise RegisterEvidenceError(f"record {index} has unknown enforcement phase")
        record = InvariantRecord(
            **{field: values[field] for field in InvariantRecord.__dataclass_fields__}
        )
        ownership = _CANONICAL_OWNERSHIP.get(record.invariant_id)
        if ownership is None or (record.enforcement_phase, record.validator) != ownership[:2]:
            raise RegisterEvidenceError(
                f"{record.invariant_id} does not match canonical phase/validator ownership"
            )
        records.append(record)
        source_test_ids.extend((record.positive_test, record.negative_test))

    actual_ids = [record.invariant_id for record in records]
    if tuple(actual_ids) != tuple(expected_invariants):
        raise RegisterEvidenceError(
            "register IDs must be unique and ordered exactly as expected"
        )
    if len(source_test_ids) != len(set(source_test_ids)):
        raise RegisterEvidenceError("register assigns a named test more than once")
    validators = [record.validator for record in records]
    if len(validators) != len(set(validators)):
        raise RegisterEvidenceError("register assigns a validator more than once")
    for record in records:
        if record.positive_test != f"{record.invariant_id}-P":
            raise RegisterEvidenceError(
                f"{record.invariant_id} has a noncanonical positive test"
            )
        if record.negative_test != f"{record.invariant_id}-N":
            raise RegisterEvidenceError(
                f"{record.invariant_id} has a noncanonical negative test"
            )
    return tuple(records)


def load_register(path: Path = DEFAULT_REGISTER) -> tuple[InvariantRecord, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RegisterEvidenceError(f"cannot read register: {exc}") from exc
    return parse_register(text)


def available_validators(records: Iterable[InvariantRecord]) -> frozenset[str]:
    """Resolve validators from their phase-owned production modules."""

    available: set[str] = set()
    modules: dict[str, object] = {}
    for record in records:
        module_name = _PHASE_MODULES[record.enforcement_phase]
        if module_name not in modules:
            try:
                modules[module_name] = importlib.import_module(module_name)
            except (ImportError, RuntimeError):
                modules[module_name] = None
        module = modules[module_name]
        candidate = getattr(module, record.validator, None) if module is not None else None
        expected_callable = _CANONICAL_OWNERSHIP[record.invariant_id][2]
        if candidate is expected_callable:
            available.add(record.validator)
    return frozenset(available)


def _validate_corpus_bindings(
    records: Sequence[InvariantRecord], path: Path = DEFAULT_CORPUS
) -> None:
    """Bind every canonical test ID to its registered runtime ownership."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegisterEvidenceError(f"cannot read invariant corpus: {exc}") from exc
    if not isinstance(document, dict) or document.get("format_version") != "1.0":
        raise RegisterEvidenceError("invariant corpus has an invalid format")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise RegisterEvidenceError("invariant corpus cases are malformed")
    cases_by_id: dict[str, dict[str, object]] = {}
    records_by_id = {record.invariant_id: record for record in records}
    canonical_ids = {
        test_id
        for record in records
        for test_id in (record.positive_test, record.negative_test)
    }
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("test_id"), str):
            raise RegisterEvidenceError("invariant corpus contains a malformed case")
        test_id = case["test_id"]
        if test_id in cases_by_id:
            raise RegisterEvidenceError(f"invariant corpus duplicates {test_id}")
        match = _CORPUS_TEST_ID.fullmatch(test_id)
        if match is None or match.group(1) not in records_by_id:
            raise RegisterEvidenceError(f"invariant corpus has invalid test ID {test_id}")
        invariant_id, polarity = match.groups()
        record = records_by_id[invariant_id]
        verdict = "PASS" if polarity == "P" else "FAIL"
        expected_resolution = None if verdict == "PASS" else record.failure_resolution
        if (
            case.get("invariant_id") != invariant_id
            or case.get("validator") != record.validator
            or case.get("enforcement_phase") != record.enforcement_phase
            or case.get("expected")
            != {
                "verdict": verdict,
                "expected_failure_resolution": expected_resolution,
            }
            or not isinstance(case.get("input"), dict)
            or not case["input"]
            or (
                test_id not in canonical_ids
                and (
                    not isinstance(case.get("coverage_clause"), str)
                    or not case["coverage_clause"]
                )
            )
        ):
            raise RegisterEvidenceError(
                f"{test_id} does not match registered invariant ownership"
            )
        cases_by_id[test_id] = case
    for record in records:
        for test_id in (record.positive_test, record.negative_test):
            case = cases_by_id.get(test_id)
            if case is None:
                raise RegisterEvidenceError(f"invariant corpus is missing {test_id}")


def _collect_evidence_suite(
    records: Sequence[InvariantRecord], test_names: Sequence[str]
) -> tuple[TestEvidence, ...]:
    _validate_corpus_bindings(records, DEFAULT_CORPUS)
    previous_directory = Path.cwd()
    try:
        os.chdir(REPOSITORY_ROOT)
        loader = unittest.TestLoader()
        loaded_tests: list[unittest.TestSuite] = []
        for name in test_names:
            loaded = loader.loadTestsFromName(name)
            if (
                loader.errors
                or loaded.countTestCases() != 1
                or _test_ids(loaded) != (name,)
            ):
                raise RegisterEvidenceError(
                    f"evidence test {name!r} did not load exactly once"
                )
            loaded_tests.append(loaded)
        suite = unittest.TestSuite(loaded_tests)
        if suite.countTestCases() != len(test_names):
            raise RegisterEvidenceError("evidence suite does not contain the exact test set")
        result = _NamedSubtestResult()
        suite.run(result)
    finally:
        os.chdir(previous_directory)
    if (
        not result.wasSuccessful()
        or result.testsRun != len(test_names)
        or result.failures
        or result.errors
        or result.unexpectedSuccesses
        or result.expectedFailures
        or result.skipped
    ):
        raise RegisterEvidenceError("named evidence suite was not fully successful")
    canonical_ids = {
        f"{invariant_id}-{polarity}"
        for invariant_id in EXPECTED_INVARIANTS
        for polarity in ("P", "N")
    }
    counts = Counter(
        item.test_id for item in result.evidence if item.test_id in canonical_ids
    )
    if set(counts) != canonical_ids or any(count != 1 for count in counts.values()):
        raise RegisterEvidenceError(
            "evidence suite did not emit exactly one result per canonical test ID"
        )
    return tuple(result.evidence)


def collect_test_evidence(
    records: Sequence[InvariantRecord],
) -> tuple[TestEvidence, ...]:
    """Run exactly the five phase-owned corpus tests and capture named outcomes."""

    return _collect_evidence_suite(records, _EVIDENCE_TESTS)


def compute_status(
    records: Sequence[InvariantRecord],
    validators: Iterable[str],
    evidence: Iterable[TestEvidence],
) -> RegisterReport:
    """Compute statuses, refusing ambiguous or malformed evidence."""

    validator_set = frozenset(validators)
    if any(not isinstance(name, str) or not name for name in validator_set):
        raise RegisterEvidenceError("validator availability contains an invalid name")
    evidence_by_id: dict[str, bool] = {}
    expected_tests = {
        test_id
        for record in records
        for test_id in (record.positive_test, record.negative_test)
    }
    for item in evidence:
        if (
            not isinstance(item, TestEvidence)
            or not isinstance(item.test_id, str)
            or not item.test_id
            or type(item.passed) is not bool
        ):
            raise RegisterEvidenceError("test evidence is malformed")
        if item.test_id in evidence_by_id:
            raise RegisterEvidenceError(f"duplicate evidence for {item.test_id}")
        if item.test_id not in expected_tests:
            continue  # Supplemental named corpus cases do not alter register status.
        evidence_by_id[item.test_id] = item.passed

    results: list[InvariantResult] = []
    for record in records:
        implemented = record.validator in validator_set
        positive_passed = evidence_by_id.get(record.positive_test) is True
        negative_passed = evidence_by_id.get(record.negative_test) is True
        if not implemented:
            status = InvariantStatus.OPEN
        elif positive_passed and negative_passed:
            status = InvariantStatus.VERIFIED
        else:
            status = InvariantStatus.IMPLEMENTED
        results.append(
            InvariantResult(
                invariant_id=record.invariant_id,
                status=status,
                validator_available=implemented,
                positive_passed=positive_passed,
                negative_passed=negative_passed,
            )
        )
    return RegisterReport(tuple(results))


def build_report(path: Path = DEFAULT_REGISTER) -> RegisterReport:
    records = load_register(path)
    return compute_status(
        records,
        available_validators(records),
        collect_test_evidence(records),
    )


def _json_report(report: RegisterReport) -> dict[str, object]:
    return {
        "counts": {status.value: count for status, count in report.counts.items()},
        "verified": report.verified,
        "total": len(report.results),
        "invariants": [
            {
                "invariant_id": result.invariant_id,
                "status": result.status.value,
                "validator_available": result.validator_available,
                "positive_passed": result.positive_passed,
                "negative_passed": result.negative_passed,
            }
            for result in report.results
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.register)
    except RegisterEvidenceError as exc:
        print(f"invariant-register: ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(_json_report(report), indent=2, sort_keys=True))
    else:
        for result in report.results:
            print(f"{result.invariant_id}: {result.status.value}")
        counts = report.counts
        print(
            "Invariant register: "
            f"{counts[InvariantStatus.OPEN]} OPEN, "
            f"{counts[InvariantStatus.IMPLEMENTED]} IMPLEMENTED, "
            f"{counts[InvariantStatus.VERIFIED]} VERIFIED"
        )
    return 0 if report.verified == len(report.results) == 16 else 1


if __name__ == "__main__":
    raise SystemExit(main())
