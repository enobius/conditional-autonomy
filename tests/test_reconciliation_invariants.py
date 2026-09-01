from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.preexecution import InvariantDisposition, Verdict
from runtime.conditional_autonomy.reconciliation_invariants import (
    RECONCILIATION_FAILURE_RESOLUTIONS,
    RECONCILIATION_INVARIANT_VALIDATORS,
    audit_deadline_check,
    compensation_current_authority_check,
    verified_effect_check,
)


CORPUS = Path("tests/fixtures/invariants/corpus.json")
INVARIANTS = {"INV-002", "INV-009", "INV-010"}


class ReconciliationInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]

    def test_all_registered_and_supplemental_corpus_cases(self) -> None:
        selected = [case for case in self.cases if case["invariant_id"] in INVARIANTS]
        self.assertEqual(len(selected), 10)
        for case in selected:
            with self.subTest(test_id=case["test_id"]):
                before = deepcopy(case["input"])
                validator = RECONCILIATION_INVARIANT_VALIDATORS[case["validator"]]
                first = validator(case["input"])
                second = validator(case["input"])
                self.assertEqual(first, second)
                self.assertEqual(first.verdict.value, case["expected"]["verdict"])
                expected = case["expected"]["expected_failure_resolution"]
                actual = first.failure_resolution.value if first.failure_resolution else None
                self.assertEqual(actual, expected)
                self.assertEqual(case["input"], before)

    def test_registry_and_phase_dispositions_are_exact(self) -> None:
        self.assertEqual(
            set(RECONCILIATION_INVARIANT_VALIDATORS),
            {
                "compensation_current_authority_check",
                "verified_effect_check",
                "audit_deadline_check",
            },
        )
        self.assertEqual(
            RECONCILIATION_FAILURE_RESOLUTIONS,
            {
                "INV-002": InvariantDisposition.ESCALATE,
                "INV-009": InvariantDisposition.REPAIR,
                "INV-010": InvariantDisposition.ESCALATE,
            },
        )

    def test_malformed_contexts_fail_closed_to_owned_disposition(self) -> None:
        validators = (
            (compensation_current_authority_check, InvariantDisposition.ESCALATE),
            (verified_effect_check, InvariantDisposition.REPAIR),
            (audit_deadline_check, InvariantDisposition.ESCALATE),
        )
        for validator, disposition in validators:
            for context in (None, {}, [], {"unexpected": True}):
                with self.subTest(validator=validator.__name__, context=context):
                    outcome = validator(context)
                    self.assertEqual(outcome.verdict, Verdict.FAIL)
                    self.assertEqual(outcome.failure_resolution, disposition)
                    self.assertEqual(outcome.failure_codes, ("MALFORMED_CONTEXT",))

    def test_inv_002_reports_every_stale_authority_clause_deterministically(self) -> None:
        context = {
            "compensation": {
                "action_id": "compensation-001",
                "required_capabilities": ["z-write", "a-write"],
                "authorized_state_version": 8,
            },
            "current_context": {
                "state_version": 9,
                "authorized_action_id": "compensation-001",
                "granted_capabilities": [],
                "preconditions_hold": False,
            },
        }
        outcome = compensation_current_authority_check(context)
        self.assertEqual(
            outcome.failure_codes,
            (
                "STALE_STATE_VERSION",
                "MISSING_CAPABILITY:a-write",
                "MISSING_CAPABILITY:z-write",
                "PRECONDITION_FAILED",
            ),
        )
        context["compensation"]["authorized_state_version"] = True
        self.assertEqual(
            compensation_current_authority_check(context).failure_codes,
            ("MALFORMED_CONTEXT",),
        )

    def test_inv_002_binds_exact_action_authority_and_stable_ids(self) -> None:
        context = {
            "compensation": {
                "action_id": "compensation-001",
                "required_capabilities": ["inventory-write"],
                "authorized_state_version": 8,
            },
            "current_context": {
                "state_version": 8,
                "authorized_action_id": "compensation-other",
                "granted_capabilities": ["inventory-write"],
                "preconditions_hold": True,
            },
        }
        self.assertEqual(
            compensation_current_authority_check(context).failure_codes,
            ("STALE_ACTION_AUTHORITY",),
        )
        for path in (
            ("compensation", "action_id"),
            ("compensation", "required_capabilities"),
            ("current_context", "authorized_action_id"),
            ("current_context", "granted_capabilities"),
        ):
            malformed = deepcopy(context)
            if "capabilities" in path[1]:
                malformed[path[0]][path[1]] = ["   "]
            else:
                malformed[path[0]][path[1]] = "   "
            with self.subTest(path=path):
                self.assertEqual(
                    compensation_current_authority_check(malformed).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )

    def test_stable_id_length_boundary_is_exact_across_reconciliation(self) -> None:
        valid_id = "a" * 160
        invalid_id = "a" * 161

        authority = {
            "compensation": {
                "action_id": valid_id,
                "required_capabilities": [valid_id],
                "authorized_state_version": 8,
            },
            "current_context": {
                "state_version": 8,
                "authorized_action_id": valid_id,
                "granted_capabilities": [valid_id],
                "preconditions_hold": True,
            },
        }
        self.assertTrue(compensation_current_authority_check(authority).succeeded)
        for section, field in (
            ("compensation", "action_id"),
            ("compensation", "required_capabilities"),
            ("current_context", "authorized_action_id"),
            ("current_context", "granted_capabilities"),
        ):
            malformed = deepcopy(authority)
            malformed[section][field] = (
                [invalid_id] if "capabilities" in field else invalid_id
            )
            with self.subTest(invariant="INV-002", section=section, field=field):
                self.assertEqual(
                    compensation_current_authority_check(malformed).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )

        effects = {
            "tool_outcome": {
                "normalized_effects": [{"effect_id": valid_id}],
                "verified_effects": [
                    {"effect_id": valid_id, "evidence_ref": valid_id}
                ],
            },
            "canonical_fact_effect_ids": [valid_id],
        }
        self.assertTrue(verified_effect_check(effects).succeeded)
        for location in ("normalized", "verified", "evidence", "canonical"):
            malformed = deepcopy(effects)
            if location == "normalized":
                malformed["tool_outcome"]["normalized_effects"][0]["effect_id"] = invalid_id
            elif location == "verified":
                malformed["tool_outcome"]["verified_effects"][0]["effect_id"] = invalid_id
            elif location == "evidence":
                malformed["tool_outcome"]["verified_effects"][0]["evidence_ref"] = invalid_id
            else:
                malformed["canonical_fact_effect_ids"] = [invalid_id]
            with self.subTest(invariant="INV-009", location=location):
                self.assertEqual(
                    verified_effect_check(malformed).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )

        audit = {
            "audit_deadline": "2026-11-26T18:00:00Z",
            "observed_at": "2026-11-26T17:59:00Z",
            "audit": {"status": "VERIFIED", "evidence_ref": valid_id},
        }
        self.assertTrue(audit_deadline_check(audit).succeeded)
        audit["audit"]["evidence_ref"] = invalid_id
        self.assertEqual(
            audit_deadline_check(audit).failure_codes,
            ("AUDIT_UNVERIFIABLE",),
        )

    def test_inv_009_never_promotes_unverified_or_orphaned_effects(self) -> None:
        unverified = {
            "tool_outcome": {
                "normalized_effects": [{"effect_id": "effect-001"}],
                "verified_effects": [],
            },
            "canonical_fact_effect_ids": ["effect-001"],
        }
        self.assertEqual(
            verified_effect_check(unverified).failure_codes,
            ("CANONICAL_FACT_UNVERIFIED:effect-001",),
        )
        orphaned = deepcopy(unverified)
        orphaned["canonical_fact_effect_ids"] = []
        orphaned["tool_outcome"]["verified_effects"] = [
            {"effect_id": "effect-002", "evidence_ref": "evidence-002"}
        ]
        self.assertEqual(
            verified_effect_check(orphaned).failure_codes,
            ("VERIFIED_EFFECT_NOT_NORMALIZED:effect-002",),
        )
        orphaned["tool_outcome"]["verified_effects"][0]["evidence_ref"] = ""
        self.assertEqual(
            verified_effect_check(orphaned).failure_codes,
            ("MALFORMED_CONTEXT",),
        )

    def test_inv_009_binds_content_and_rejects_duplicate_or_whitespace_ids(self) -> None:
        contradictory = {
            "tool_outcome": {
                "normalized_effects": [
                    {"effect_id": "effect-001", "path": "/status", "value": "READY"}
                ],
                "verified_effects": [
                    {
                        "effect_id": "effect-001",
                        "path": "/status",
                        "value": "FAILED",
                        "evidence_ref": "evidence-001",
                    }
                ],
            },
            "canonical_fact_effect_ids": ["effect-001"],
        }
        outcome = verified_effect_check(contradictory)
        self.assertEqual(outcome.failure_resolution, InvariantDisposition.REPAIR)
        self.assertEqual(
            outcome.failure_codes,
            ("VERIFIED_EFFECT_CONTENT_MISMATCH:effect-001",),
        )
        for mutation in ("effect", "evidence", "duplicate", "canonical"):
            malformed = deepcopy(contradictory)
            if mutation == "effect":
                malformed["tool_outcome"]["normalized_effects"][0]["effect_id"] = "   "
            elif mutation == "evidence":
                malformed["tool_outcome"]["verified_effects"][0]["evidence_ref"] = "   "
            elif mutation == "duplicate":
                malformed["tool_outcome"]["normalized_effects"].append(
                    deepcopy(malformed["tool_outcome"]["normalized_effects"][0])
                )
            else:
                malformed["canonical_fact_effect_ids"] = ["   "]
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    verified_effect_check(malformed).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )

    def test_inv_010_deadline_is_inclusive_and_requires_independent_evidence(self) -> None:
        context = {
            "audit_deadline": "2026-11-26T18:00:00Z",
            "observed_at": "2026-11-26T18:00:00Z",
            "audit": {"status": "VERIFIED", "evidence_ref": "audit-evidence-001"},
        }
        self.assertTrue(audit_deadline_check(context).succeeded)
        context["audit"]["evidence_ref"] = None
        outcome = audit_deadline_check(context)
        self.assertEqual(outcome.failure_resolution, InvariantDisposition.ESCALATE)
        self.assertEqual(outcome.failure_codes, ("AUDIT_UNVERIFIABLE",))
        context["audit"] = {"status": "MISSING", "evidence_ref": "contradiction"}
        self.assertEqual(
            audit_deadline_check(context).failure_codes, ("MALFORMED_CONTEXT",)
        )

    def test_inv_010_rejects_non_normalized_instants_and_whitespace_evidence(self) -> None:
        base = {
            "audit_deadline": "2026-11-26T18:00:00Z",
            "observed_at": "2026-11-26T17:59:00Z",
            "audit": {"status": "VERIFIED", "evidence_ref": "audit-evidence-001"},
        }
        for field, value in (
            ("observed_at", "2026-11-26 17:59:00Z"),
            ("observed_at", "2026-11-26T17:59:00-05:00"),
            ("audit_deadline", "2026-11-26T18:00:00+00:00"),
        ):
            malformed = deepcopy(base)
            malformed[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(
                    audit_deadline_check(malformed).failure_codes,
                    ("MALFORMED_CONTEXT",),
                )
        whitespace = deepcopy(base)
        whitespace["audit"]["evidence_ref"] = "   "
        self.assertEqual(
            audit_deadline_check(whitespace).failure_codes,
            ("AUDIT_UNVERIFIABLE",),
        )


if __name__ == "__main__":
    unittest.main()
