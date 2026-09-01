from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runtime.conditional_autonomy.invariant_register import (
    DEFAULT_CORPUS,
    DEFAULT_REGISTER,
    InvariantStatus,
    RegisterEvidenceError,
    TestEvidence,
    _collect_evidence_suite,
    _validate_corpus_bindings,
    available_validators,
    build_report,
    collect_test_evidence,
    compute_status,
    load_register,
    parse_register,
)

class InvariantRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_register()
        cls.validators = available_validators(cls.records)
        cls.passing = tuple(
            TestEvidence(test_id, True)
            for record in cls.records
            for test_id in (record.positive_test, record.negative_test)
        )

    def test_live_named_test_evidence_verifies_all_sixteen(self) -> None:
        evidence = collect_test_evidence(self.records)
        report = compute_status(self.records, self.validators, evidence)
        self.assertEqual(report.verified, 16)
        self.assertTrue(
            all(result.status is InvariantStatus.VERIFIED for result in report.results)
        )

    def test_missing_or_failed_named_test_drops_only_that_status(self) -> None:
        for evidence in (self.passing[:-1], self.passing[:-1] + (replace(self.passing[-1], passed=False),)):
            with self.subTest(evidence_count=len(evidence)):
                report = compute_status(self.records, self.validators, evidence)
                self.assertEqual(report.verified, 15)
                self.assertIs(report.results[-1].status, InvariantStatus.IMPLEMENTED)
                self.assertFalse(report.results[-1].negative_passed)

    def test_missing_validator_is_open_despite_passing_evidence(self) -> None:
        report = compute_status(
            self.records,
            self.validators - {self.records[0].validator},
            self.passing,
        )
        self.assertIs(report.results[0].status, InvariantStatus.OPEN)
        self.assertEqual(report.verified, 15)

    def test_duplicate_and_malformed_evidence_fail_closed(self) -> None:
        duplicate = self.passing + (self.passing[0],)
        with self.assertRaisesRegex(RegisterEvidenceError, "duplicate evidence"):
            compute_status(self.records, self.validators, duplicate)
        with self.assertRaisesRegex(RegisterEvidenceError, "malformed"):
            compute_status(
                self.records,
                self.validators,
                (TestEvidence(self.records[0].positive_test, 1),),  # type: ignore[arg-type]
            )

    def test_malformed_and_duplicate_register_records_fail_closed(self) -> None:
        text = DEFAULT_REGISTER.read_text(encoding="utf-8")
        with self.assertRaisesRegex(RegisterEvidenceError, "fields differ"):
            parse_register(text.replace("owner: Workstream 1C\n", "", 1))
        with self.assertRaisesRegex(RegisterEvidenceError, "canonical|unique and ordered"):
            parse_register(text.replace("invariant_id: INV-002", "invariant_id: INV-001", 1))
        with self.assertRaisesRegex(RegisterEvidenceError, "assigns a named test"):
            parse_register(text.replace("positive_test: INV-002-P", "positive_test: INV-001-P", 1))

    def test_validator_substitution_and_helper_alias_fail_closed(self) -> None:
        text = DEFAULT_REGISTER.read_text(encoding="utf-8")
        substituted = text.replace(
            "validator: compensation_prevalidation_check",
            "validator: _mapping",
            1,
        )
        with self.assertRaisesRegex(RegisterEvidenceError, "canonical phase/validator"):
            parse_register(substituted)

        from runtime.conditional_autonomy import preexecution

        with mock.patch.object(
            preexecution,
            "compensation_prevalidation_check",
            preexecution._mapping,
        ):
            validators = available_validators(self.records)
        report = compute_status(self.records, validators, self.passing)
        self.assertIs(report.results[0].status, InvariantStatus.OPEN)
        self.assertEqual(report.verified, 15)

        spoof = lambda context: None
        spoof.__module__ = preexecution.__name__
        spoof.__name__ = "compensation_prevalidation_check"
        with mock.patch.object(preexecution, "compensation_prevalidation_check", spoof):
            spoofed_validators = available_validators(self.records)
        spoofed = compute_status(self.records, spoofed_validators, self.passing)
        self.assertIs(spoofed.results[0].status, InvariantStatus.OPEN)
        self.assertEqual(spoofed.verified, 15)

    def test_canonical_corpus_validator_swap_fails_closed(self) -> None:
        import json

        corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        canonical = next(case for case in corpus["cases"] if case["test_id"] == "INV-001-P")
        canonical["validator"] = "current_version_check"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(corpus), encoding="utf-8")
            with self.assertRaisesRegex(RegisterEvidenceError, "registered invariant ownership"):
                _validate_corpus_bindings(self.records, path)

    def test_late_suite_failure_or_error_invalidates_passing_subtests(self) -> None:
        import tests.test_invariant_register as this_module

        for terminal in ("failure", "error"):
            class LateEvidenceTest(unittest.TestCase):
                def test_evidence(self) -> None:
                    for number in range(1, 17):
                        for polarity in ("P", "N"):
                            with self.subTest(test_id=f"INV-{number:03d}-{polarity}"):
                                pass
                    if terminal == "failure":
                        self.fail("late suite failure")
                    raise RuntimeError("late suite error")

            LateEvidenceTest.__module__ = "tests.test_invariant_register"
            LateEvidenceTest.__qualname__ = "_LateEvidenceTest"
            test_name = (
                "tests.test_invariant_register._LateEvidenceTest.test_evidence"
            )
            with self.subTest(terminal=terminal), mock.patch.object(
                this_module, "_LateEvidenceTest", LateEvidenceTest, create=True
            ), self.assertRaisesRegex(RegisterEvidenceError, "not fully successful"):
                _collect_evidence_suite(self.records, (test_name,))

    def test_hand_edited_source_status_does_not_determine_result(self) -> None:
        source = DEFAULT_REGISTER.read_text(encoding="utf-8").replace(
            "status: OPEN", "status: VERIFIED"
        )
        records = parse_register(source)
        report = compute_status(records, available_validators(records), self.passing)
        self.assertEqual(report.verified, 16)

    def test_register_path_is_repository_relative_not_working_directory(self) -> None:
        self.assertTrue(DEFAULT_REGISTER.is_absolute())
        self.assertEqual(Path(DEFAULT_REGISTER).name, "deferred-invariants.md")
        previous_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                evidence = collect_test_evidence(self.records)
            finally:
                os.chdir(previous_directory)
        report = compute_status(self.records, self.validators, evidence)
        self.assertEqual(report.verified, 16)

    def test_custom_register_uses_its_own_records_for_corpus_binding(self) -> None:
        source = DEFAULT_REGISTER.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            matching = Path(directory) / "matching.md"
            matching.write_text(source, encoding="utf-8")
            self.assertEqual(build_report(matching).verified, 16)

            mismatched = Path(directory) / "mismatched.md"
            mismatched.write_text(
                source.replace("failure_resolution: REJECT", "failure_resolution: ESCALATE", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RegisterEvidenceError, "registered invariant ownership"
            ):
                build_report(mismatched)


if __name__ == "__main__":
    unittest.main()
