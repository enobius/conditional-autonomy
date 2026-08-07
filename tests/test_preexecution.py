from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.preexecution import (
    Criticality, InvariantDisposition, ReconciliationEvidence, Resolution,
    ValidationOutcome, ValidatorStatus, Verdict,
    adapter_compatibility_check, compensation_prevalidation_check,
    current_version_check, reconcile_decision,
)


CORPUS = Path("tests/fixtures/invariants/corpus.json")
VALIDATOR_FIXTURE = Path(
    "architecture/schemas/v1.0/fixtures/valid/validator-result.valid.json"
)
VALIDATORS = {
    "compensation_prevalidation_check": compensation_prevalidation_check,
    "current_version_check": current_version_check,
    "adapter_compatibility_check": adapter_compatibility_check,
}


def evidence(criticality: str, status: str, resolution: str) -> ReconciliationEvidence:
    result = json.loads(VALIDATOR_FIXTURE.read_text(encoding="utf-8"))
    result.update(
        criticality=criticality,
        status=status,
        permitted_resolution=resolution,
        uncertainty_reason=("validator evidence is uncertain" if status == "UNKNOWN" else None),
    )
    return ReconciliationEvidence.from_validator_result(result)


class PreExecutionInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]

    def test_registered_and_supplemental_corpus_cases(self) -> None:
        selected = [case for case in self.cases if case["invariant_id"] in {"INV-001", "INV-004", "INV-012"}]
        self.assertEqual(len(selected), 10)
        for case in selected:
            with self.subTest(test_id=case["test_id"]):
                before = deepcopy(case["input"])
                outcome = VALIDATORS[case["validator"]](case["input"])
                self.assertEqual(outcome.verdict.value, case["expected"]["verdict"])
                expected = case["expected"]["expected_failure_resolution"]
                actual = outcome.failure_resolution.value if outcome.failure_resolution else None
                self.assertEqual(actual, expected)
                self.assertEqual(case["input"], before)

    def test_inv_001_accepts_real_action_contract_shape(self) -> None:
        context = {
            "action": {
                "action_id": "action-001",
                "reversibility": "COMPENSATABLE",
                "compensation_action": {
                    "action_type": "inventory:restore",
                    "arguments": {},
                    "required_capabilities": ["inventory:write"],
                    "prevalidation_id": "prevalidation-001",
                },
            },
            "authorization": {"authorized_at_logical_clock": 2},
            "prevalidations": [{"prevalidation_id": "prevalidation-001", "action_id": "action-001", "status": "PASS", "logical_clock": 1}],
        }
        self.assertTrue(compensation_prevalidation_check(context).succeeded)

    def test_inv_001_rejects_obsolete_top_level_prevalidation_alias(self) -> None:
        context = {
            "action": {
                "action_id": "action-001",
                "reversibility": "COMPENSATABLE",
                "compensation_prevalidation_id": "prevalidation-001",
                "compensation_action": {
                    "action_type": "inventory:restore",
                    "arguments": {},
                    "required_capabilities": ["inventory:write"],
                    "prevalidation_id": "prevalidation-001",
                },
            },
            "authorization": {"authorized_at_logical_clock": 2},
            "prevalidations": [{"prevalidation_id": "prevalidation-001", "action_id": "action-001", "status": "PASS", "logical_clock": 1}],
        }
        outcome = compensation_prevalidation_check(context)
        self.assertEqual(outcome.verdict, Verdict.FAIL)
        self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))

    def test_inv_001_validates_every_history_member_before_search(self) -> None:
        valid = {"prevalidation_id": "prevalidation-001", "action_id": "action-001", "status": "PASS", "logical_clock": 1}
        malformed = {"prevalidation_id": "damaged"}
        base = {
            "action": {
                "action_id": "action-001",
                "reversibility": "COMPENSATABLE",
                "compensation_action": {
                    "action_type": "inventory:restore",
                    "arguments": {},
                    "required_capabilities": ["inventory:write"],
                    "prevalidation_id": "prevalidation-001",
                },
            },
            "authorization": {"authorized_at_logical_clock": 2},
        }
        for records in ([valid, malformed], [malformed, valid]):
            with self.subTest(records=records):
                context = {**base, "prevalidations": records}
                outcome = compensation_prevalidation_check(context)
                self.assertEqual(outcome.verdict, Verdict.FAIL)
                self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))

    def test_malformed_contexts_fail_with_registered_resolution(self) -> None:
        cases = ((compensation_prevalidation_check, InvariantDisposition.REJECT), (current_version_check, InvariantDisposition.REPAIR), (adapter_compatibility_check, InvariantDisposition.REJECT))
        for validator, resolution in cases:
            with self.subTest(validator=validator.__name__):
                outcome = validator(None)
                self.assertEqual(outcome.verdict, Verdict.FAIL)
                self.assertEqual(outcome.failure_resolution, resolution)
                self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))


class ReconciliationTests(unittest.TestCase):
    def test_invariant_dispositions_are_not_reconciliation_resolutions(self) -> None:
        with self.assertRaises(ValueError):
            Resolution("QUARANTINE")
        with self.assertRaisesRegex(ValueError, "unknown supervisor decision"):
            reconcile_decision("QUARANTINE", evidence("HARD", "PASS", "EXECUTE"))
        with self.assertRaisesRegex(ValueError, "unknown supervisor decision"):
            reconcile_decision(
                InvariantDisposition.REJECT, evidence("HARD", "PASS", "EXECUTE")
            )

        for disposition in InvariantDisposition:
            with self.subTest(disposition=disposition):
                self.assertNotIsInstance(disposition, Resolution)
                fixture = json.loads(VALIDATOR_FIXTURE.read_text(encoding="utf-8"))
                fixture.update(permitted_resolution=disposition)
                with self.assertRaisesRegex(ValueError, "invariant disposition"):
                    ReconciliationEvidence(fixture)

        fixture = json.loads(VALIDATOR_FIXTURE.read_text(encoding="utf-8"))
        fixture.update(permitted_resolution=InvariantDisposition.QUARANTINE.value)
        with self.assertRaisesRegex(ValueError, "validator-result.schema.json"):
            ReconciliationEvidence(fixture)

        with self.assertRaisesRegex(ValueError, "invariant disposition"):
            ValidationOutcome(
                "INV-001", "validator", Verdict.FAIL, Resolution.REJECT, ("CODE",)
            )  # type: ignore[arg-type]

    def test_projects_validator_result_schema_vocabulary(self) -> None:
        fixture = json.loads(
            VALIDATOR_FIXTURE.read_text(encoding="utf-8")
        )
        projected = ReconciliationEvidence.from_validator_result(fixture)
        self.assertEqual(projected.criticality, Criticality.HARD)
        self.assertEqual(projected.status, ValidatorStatus.UNKNOWN)
        self.assertEqual(projected.permitted_resolution, "QUERY")

    def test_validator_evidence_is_immutable_and_accessors_are_defensive(self) -> None:
        external = json.loads(VALIDATOR_FIXTURE.read_text(encoding="utf-8"))
        evidence_value = ReconciliationEvidence.from_validator_result(external)

        external.update(status="PASS", permitted_resolution="EXECUTE", uncertainty_reason=None)
        exposed = evidence_value.validator_result
        exposed.update(status="PASS", permitted_resolution="EXECUTE", uncertainty_reason=None)

        self.assertEqual(evidence_value.status, ValidatorStatus.UNKNOWN)
        self.assertEqual(evidence_value.permitted_resolution, "QUERY")
        self.assertEqual(evidence_value.validator_result["status"], "UNKNOWN")
        self.assertEqual(
            reconcile_decision(Resolution.APPROVE, evidence_value),
            Resolution.QUERY,
        )

    def test_partial_evidence_cannot_be_reconciled(self) -> None:
        partial = {
            "criticality": "SOFT",
            "status": "FAIL",
            "permitted_resolution": "EXECUTE",
        }
        for factory in (
            ReconciliationEvidence,
            ReconciliationEvidence.from_validator_result,
        ):
            with self.subTest(factory=factory):
                with self.assertRaisesRegex(ValueError, "validator-result.schema.json"):
                    factory(partial)
        with self.assertRaisesRegex(ValueError, "complete schema-valid"):
            reconcile_decision(
                Resolution.APPROVE,
                partial,  # type: ignore[arg-type]
                soft_risk_below_ceiling=True,
            )

    def test_every_specification_table_row(self) -> None:
        rows = (
            (Resolution.APPROVE, evidence("HARD", "PASS", "EXECUTE"), {}, Resolution.APPROVE),
            (Resolution.APPROVE, evidence("HARD", "FAIL", "REPAIR"), {}, Resolution.REPAIR),
            (Resolution.APPROVE, evidence("HARD", "FAIL", "REJECT"), {}, Resolution.REJECT),
            (Resolution.APPROVE, evidence("HARD", "UNKNOWN", "QUERY"), {}, Resolution.QUERY),
            (Resolution.APPROVE, evidence("HARD", "UNKNOWN", "ESCALATE"), {}, Resolution.ESCALATE),
            (Resolution.APPROVE, evidence("SOFT", "FAIL", "EXECUTE"), {"soft_risk_below_ceiling": True}, Resolution.APPROVE),
            (Resolution.APPROVE, evidence("SOFT", "UNKNOWN", "QUERY"), {"soft_risk_below_ceiling": False}, Resolution.ESCALATE),
            (Resolution.APPROVE, evidence("SOFT", "UNKNOWN", "QUERY"), {"soft_risk_below_ceiling": True}, Resolution.QUERY),
            (Resolution.REPAIR, evidence("HARD", "PASS", "EXECUTE"), {}, Resolution.REPAIR),
            (Resolution.REPAIR, evidence("HARD", "FAIL", "REJECT"), {}, Resolution.REJECT),
            (Resolution.REPAIR, evidence("HARD", "UNKNOWN", "ESCALATE"), {}, Resolution.ESCALATE),
            (Resolution.QUERY, evidence("HARD", "PASS", "EXECUTE"), {}, Resolution.QUERY),
            (Resolution.REJECT, evidence("HARD", "PASS", "EXECUTE"), {}, Resolution.REJECT),
            (Resolution.ESCALATE, evidence("HARD", "PASS", "EXECUTE"), {}, Resolution.ESCALATE),
        )
        for supervisor, validator_evidence, kwargs, expected in rows:
            with self.subTest(supervisor=supervisor, evidence=validator_evidence):
                self.assertEqual(reconcile_decision(supervisor, validator_evidence, **kwargs), expected)

    def test_hard_unknown_can_never_execute(self) -> None:
        for permitted in ("EXECUTE", "REPAIR", "REJECT"):
            with self.subTest(permitted=permitted):
                with self.assertRaises(ValueError):
                    evidence("HARD", "UNKNOWN", permitted)
        for permitted, expected in (("QUERY", Resolution.QUERY), ("ESCALATE", Resolution.ESCALATE)):
            result = reconcile_decision(Resolution.APPROVE, evidence("HARD", "UNKNOWN", permitted))
            self.assertEqual(result, expected)
            self.assertNotEqual(result, Resolution.APPROVE)

    def test_soft_nonpass_requires_explicit_residual_risk_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "residual-risk"):
            reconcile_decision(Resolution.APPROVE, evidence("SOFT", "FAIL", "EXECUTE"))


if __name__ == "__main__":
    unittest.main()
