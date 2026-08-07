from __future__ import annotations

import unittest
from copy import deepcopy
from threading import Event, Thread

from runtime.conditional_autonomy.tools import (
    ToolAdapter,
    ToolSurface,
    ToolSurfaceError,
    canonical_execution_bytes,
)
from runtime.conditional_autonomy.thanksgiving import run_thanksgiving_episode


TIME = {
    "instant": "2026-11-26T14:00:00Z",
    "source_timezone": "America/New_York",
    "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
}
LATER = {**TIME, "instant": "2026-11-26T14:00:01Z"}


def action(
    *,
    action_id: str = "action:reserve",
    action_type: str = "calendar:create-reservation",
    state_version: int = 3,
    capability: str = "calendar:write",
    arguments: dict | None = None,
    compensatable: bool = False,
) -> dict:
    value = {
        "action_id": action_id,
        "plan_id": "plan:thanksgiving",
        "actor_id": "actor:planner",
        "state_version": state_version,
        "action_type": action_type,
        "arguments": arguments or {"slot": "14:00"},
        "expected_preconditions": [],
        "expected_effects": [{"reservation_status": "confirmed"}],
        "required_capabilities": [capability],
        "risk_class": "MODERATE",
        "reversibility": "COMPENSATABLE" if compensatable else "REVERSIBLE",
        "compensation_action": (
            {
                "action_type": "calendar:cancel-reservation",
                "arguments": {"reservation": "reservation:1"},
                "required_capabilities": ["calendar:write"],
                "prevalidation_id": "prevalidation:reserve",
            }
            if compensatable
            else None
        ),
        "postconditions": [{"reservation_status": "confirmed"}],
        "audit_deadline": deepcopy(LATER) if compensatable else None,
        "evidence_refs": [],
        "confidence": 1.0,
        "idempotency_key": f"idem:{action_id}",
    }
    return value


def decision(
    kind: str,
    *,
    proposed_repair: dict | None = None,
    adapter_version: str | None = None,
) -> dict:
    return {
        "decision": kind,
        "confidence": 1.0,
        "violated_constraint_ids": [],
        "uncertainty_reasons": ["Need confirmation."] if kind == "QUERY" else [],
        "requested_information": ["Confirm the reservation."] if kind == "QUERY" else [],
        "proposed_repair": proposed_repair if kind == "REPAIR" else None,
        "evidence_refs": [],
        "supervisor_model_version": "supervisor.1.0",
        "adapter_version": adapter_version,
    }


def validator(
    validator_id: str,
    *,
    state_version: int = 3,
    status: str = "PASS",
    resolution: str = "EXECUTE",
    criticality: str = "HARD",
) -> dict:
    return {
        "validator_id": validator_id,
        "validator_version": "1.0",
        "status": status,
        "criticality": criticality,
        "enforceability": "PREVENTABLE",
        "constraint_ids": ["constraint:preexecution"],
        "evidence_refs": [],
        "observed_state_version": state_version,
        "uncertainty_reason": "Evidence is incomplete." if status == "UNKNOWN" else None,
        "permitted_resolution": resolution,
        "explanation_code": "PREEXECUTION_RESULT",
        "repair_hints": ["Repair the proposal."] if resolution == "REPAIR" else [],
        "timestamp": deepcopy(TIME),
    }


def validators(
    *,
    state_version: int = 3,
    compensatable: bool = False,
    current_status: str = "PASS",
    current_resolution: str = "EXECUTE",
) -> list[dict]:
    ids = ["current_version_check", "adapter_compatibility_check"]
    if compensatable:
        ids.append("compensation_prevalidation_check")
    return [
        validator(
            item,
            state_version=state_version,
            status=current_status if item == "current_version_check" else "PASS",
            resolution=current_resolution if item == "current_version_check" else "EXECUTE",
        )
        for item in ids
    ]


class RecordingTool:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, proposal: dict) -> dict:
        self.calls.append(deepcopy(proposal))
        proposal["arguments"]["adapter_mutation"] = True
        effect = {"reservation_status": "cancelled"} if "cancel" in proposal["action_type"] else {"reservation_status": "confirmed"}
        return {
            "status": "SUCCEEDED",
            "raw_result_ref": {
                "ref_id": f"evidence:{proposal['action_id']}",
                "source": "TOOL",
                "access_class": "EVALUATOR_ONLY",
                "uri": None,
                "content_hash": None,
            },
            "normalized_effects": [effect],
            "state_version_after": proposal["state_version"] + 1,
            "error_code": None,
        }

    @staticmethod
    def verify(_proposal: dict, effects: list[dict]) -> list[dict]:
        return deepcopy(effects)


def surface(recorder: RecordingTool, *, grants=("calendar:write",)) -> ToolSurface:
    return ToolSurface(
        [
            ToolAdapter(
                "tool:calendar",
                "1.0",
                ("calendar:create-reservation", "calendar:cancel-reservation"),
                ("calendar:write",),
                recorder.execute,
                recorder.verify,
            )
        ],
        granted_capabilities=grants,
    )


def prevalidation(proposal: dict) -> dict:
    return {
        "action": proposal,
        "authorization": {
            "authorized_at_logical_clock": 2,
            "state_version": proposal["state_version"],
            "plan_id": proposal["plan_id"],
        },
        "prevalidations": [
            {
                "prevalidation_id": "prevalidation:reserve",
                "action_id": proposal["action_id"],
                "status": "PASS",
                "logical_clock": 1,
            }
        ],
    }


class ToolSurfaceTests(unittest.TestCase):
    def test_external_evidence_set_and_observed_version_are_closed(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        for results, message in (
            ([], "evidence set mismatch"),
            (validators(state_version=2), "stale external"),
            (validators() + [validator("unexpected_validator")], "evidence set mismatch"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ToolSurfaceError, message):
                    gateway.invoke(
                        action(), decision("APPROVE"), results,
                        started_at=TIME, completed_at=LATER, current_state_version=3,
                    )
        self.assertEqual(recorder.calls, [])

    def test_adapter_contract_and_supervisor_version_pin_fail_before_call(self) -> None:
        recorder = RecordingTool()
        invalid = (
            ("bad tool id", "1.0", ("calendar:create",), ("calendar:write",)),
            ("tool:calendar", "", ("calendar:create",), ("calendar:write",)),
            ("tool:calendar", "1.0", ("bad action type!",), ("calendar:write",)),
            ("tool:calendar", "1.0", ("calendar:create",), ("bad capability!",)),
        )
        for tool_id, version, actions, capabilities in invalid:
            with self.subTest(tool_id=tool_id, version=version):
                with self.assertRaises(ValueError):
                    ToolAdapter(
                        tool_id, version, actions, capabilities,
                        recorder.execute, recorder.verify,
                    )
        denied = surface(recorder).invoke(
            action(), decision("APPROVE", adapter_version="2.0"), validators(),
            started_at=TIME, completed_at=LATER, current_state_version=3,
        )
        self.assertEqual(denied.authorization.resolution.value, "REJECT")
        self.assertFalse(denied.executed)
        self.assertEqual(recorder.calls, [])

    def test_authorization_and_execution_are_deeply_immutable(self) -> None:
        recorder = RecordingTool()
        result = surface(recorder).invoke(
            action(), decision("APPROVE"), validators(),
            started_at=TIME, completed_at=LATER, current_state_version=3,
        )
        before = canonical_execution_bytes(result)
        result.authorization.action["arguments"]["slot"] = "corrupt"
        result.authorization.supervisor_decision["decision"] = "REJECT"
        result.authorization.validator_results[0]["status"] = "FAIL"
        result.outcome["status"] = "FAILED"
        self.assertEqual(canonical_execution_bytes(result), before)

    def test_thanksgiving_proposal_uses_capability_gated_surface(self) -> None:
        proposal = deepcopy(run_thanksgiving_episode().actions[0])
        calls: list[dict] = []

        def execute(item: dict) -> dict:
            calls.append(deepcopy(item))
            return {
                "status": "SUCCEEDED",
                "raw_result_ref": {
                    "ref_id": "evidence:thanksgiving-tool",
                    "source": "TOOL",
                    "access_class": "EVALUATOR_ONLY",
                    "uri": None,
                    "content_hash": None,
                },
                "normalized_effects": deepcopy(item["expected_effects"]),
                "state_version_after": item["state_version"] + 1,
                "error_code": None,
            }

        gateway = ToolSurface(
            [ToolAdapter(
                "tool:thanksgiving-environment", "1.0", (proposal["action_type"],),
                ("capability:environment-transition",), execute,
                lambda _action, effects: deepcopy(effects),
            )],
            granted_capabilities=("capability:environment-transition",),
        )
        result = gateway.invoke(
            proposal, decision("APPROVE"), validators(state_version=proposal["state_version"]),
            started_at=TIME, completed_at=LATER,
            current_state_version=proposal["state_version"],
        )
        self.assertTrue(result.executed)
        self.assertEqual(calls[0]["action_id"], proposal["action_id"])
        self.assertEqual(result.outcome["verified_effects"], proposal["expected_effects"])

    def test_permit_execute_verify_and_idempotency_are_end_to_end(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        proposal = action()

        permit = gateway.authorize(
            proposal,
            decision("APPROVE"),
            validators(),
            timestamp=TIME,
            current_state_version=3,
        )
        self.assertEqual(permit.resolution.value, "APPROVE")
        self.assertEqual(gateway.dispatch_count, 0)

        executed = gateway.invoke(
            proposal,
            decision("APPROVE"),
            validators(),
            started_at=TIME,
            completed_at=LATER,
            current_state_version=3,
        )
        self.assertTrue(executed.executed)
        self.assertEqual(executed.outcome["normalized_effects"], executed.outcome["verified_effects"])
        self.assertEqual(executed.outcome["state_version_after"], 4)
        self.assertNotIn("adapter_mutation", executed.authorization.action["arguments"])
        self.assertEqual(gateway.dispatch_count, 1)

        repeated = gateway.invoke(
            proposal,
            decision("APPROVE"),
            validators(),
            started_at=TIME,
            completed_at=LATER,
            current_state_version=4,
        )
        self.assertEqual(repeated.outcome, executed.outcome)
        self.assertEqual(gateway.dispatch_count, 1)
        self.assertEqual(canonical_execution_bytes(repeated), canonical_execution_bytes(executed))

    def test_deny_query_repair_unknown_missing_grant_and_stale_never_dispatch(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        cases = (
            (decision("REJECT"), validators(), 3),
            (decision("QUERY"), validators(), 3),
            (decision("REPAIR", proposed_repair=action()), validators(), 3),
            (decision("APPROVE"), validators(current_status="UNKNOWN", current_resolution="QUERY"), 3),
            (decision("APPROVE"), validators(), 4),
        )
        expected = ("REJECT", "QUERY", "REPAIR", "QUERY", "REPAIR")
        for (supervisor, results, current), resolution in zip(cases, expected):
            with self.subTest(resolution=resolution):
                attempt = gateway.invoke(
                    action(), supervisor, results,
                    started_at=TIME, completed_at=LATER,
                    current_state_version=current,
                )
                self.assertFalse(attempt.executed)
                self.assertEqual(attempt.authorization.resolution.value, resolution)
        missing = surface(recorder, grants=()).invoke(
            action(), decision("APPROVE"), validators(),
            started_at=TIME, completed_at=LATER, current_state_version=3,
        )
        self.assertEqual(missing.authorization.resolution.value, "REJECT")
        self.assertFalse(missing.executed)
        self.assertEqual(len(recorder.calls), 0)

    def test_repair_reenters_complete_gate_before_execution(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        repaired = action(arguments={"slot": "15:00"})
        result = gateway.repair(
            action(),
            decision("REPAIR", proposed_repair=repaired),
            validators(current_status="FAIL", current_resolution="REPAIR"),
            decision("APPROVE"),
            validators(),
            started_at=TIME,
            completed_at=LATER,
            current_state_version=3,
        )
        self.assertTrue(result.executed)
        self.assertEqual(recorder.calls[0]["arguments"], {"slot": "15:00"})
        self.assertEqual(len(result.authorization.validator_results), 4)

    def test_compensation_is_prevalidated_and_reenters_same_gate(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        original = action(compensatable=True)
        original_execution = gateway.invoke(
            original,
            decision("APPROVE"),
            validators(compensatable=True),
            started_at=TIME,
            completed_at=LATER,
            current_state_version=3,
            compensation_prevalidation=prevalidation(original),
        )
        self.assertTrue(original_execution.executed)
        recovery = gateway.compensate(
            original,
            original_execution.outcome,
            decision("APPROVE"),
            validators(state_version=4),
            expected_effects=[{"reservation_status": "cancelled"}],
            started_at=LATER,
            completed_at={**LATER, "instant": "2026-11-26T14:00:02Z"},
            current_state_version=4,
        )
        self.assertTrue(recovery.executed)
        self.assertEqual(recovery.outcome["action_id"], "compensation:action:reserve")
        self.assertEqual(recovery.outcome["verified_effects"], [{"reservation_status": "cancelled"}])
        self.assertEqual(gateway.dispatch_count, 2)

    def test_compensation_rejects_forged_unrecorded_and_changed_template(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        original = action(compensatable=True)
        completed = gateway.invoke(
            original, decision("APPROVE"), validators(compensatable=True),
            started_at=TIME, completed_at=LATER, current_state_version=3,
            compensation_prevalidation=prevalidation(original),
        )
        for field, value in (
            ("status", "PENDING"),
            ("tool_version", "9.9"),
            ("state_version_after", 9),
            ("idempotency_key", "idem:forged"),
        ):
            forged = deepcopy(completed.outcome)
            forged[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ToolSurfaceError):
                    gateway.compensate(
                        original, forged, decision("APPROVE"), validators(state_version=4),
                        expected_effects=[{"reservation_status": "cancelled"}],
                        started_at=LATER,
                        completed_at={**LATER, "instant": "2026-11-26T14:00:02Z"},
                        current_state_version=4,
                    )
        with self.assertRaisesRegex(ToolSurfaceError, "exact recorded"):
            surface(RecordingTool()).compensate(
                original, completed.outcome, decision("APPROVE"), validators(state_version=4),
                expected_effects=[{"reservation_status": "cancelled"}],
                started_at=LATER,
                completed_at={**LATER, "instant": "2026-11-26T14:00:02Z"},
                current_state_version=4,
            )

        changed = deepcopy(original)
        changed["compensation_action"]["arguments"] = {"reservation": "reservation:other"}
        changed["idempotency_key"] = "idem:changed-template"
        separate = surface(RecordingTool())
        denied = separate.invoke(
            changed, decision("APPROVE"), validators(compensatable=True),
            started_at=TIME, completed_at=LATER, current_state_version=3,
            compensation_prevalidation=prevalidation(original),
        )
        self.assertEqual(denied.authorization.resolution.value, "REJECT")
        self.assertFalse(denied.executed)
        self.assertEqual(separate.dispatch_count, 0)

    def test_concurrent_claim_and_indeterminate_failures_never_redispatch(self) -> None:
        entered = Event()
        release = Event()
        calls: list[dict] = []

        def blocking_execute(proposal: dict) -> dict:
            calls.append(deepcopy(proposal))
            entered.set()
            release.wait(5)
            return RecordingTool().execute(proposal)

        adapter = ToolAdapter(
            "tool:calendar", "1.0", ("calendar:create-reservation",),
            ("calendar:write",), blocking_execute, RecordingTool.verify,
        )
        gateway = ToolSurface([adapter], granted_capabilities=("calendar:write",))
        results: list[object] = []

        def first() -> None:
            try:
                results.append(gateway.invoke(
                    action(), decision("APPROVE"), validators(),
                    started_at=TIME, completed_at=LATER, current_state_version=3,
                ))
            except Exception as exc:  # pragma: no cover - diagnostic capture
                results.append(exc)

        thread = Thread(target=first)
        thread.start()
        self.assertTrue(entered.wait(5))
        with self.assertRaisesRegex(ToolSurfaceError, "in flight"):
            gateway.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        release.set()
        thread.join(5)
        self.assertEqual(len(calls), 1)
        self.assertTrue(results[0].executed)

        failing_calls: list[int] = []
        def fail(_proposal: dict) -> dict:
            failing_calls.append(1)
            raise RuntimeError("adapter exploded")
        failing = ToolSurface(
            [ToolAdapter(
                "tool:calendar", "1.0", ("calendar:create-reservation",),
                ("calendar:write",), fail, RecordingTool.verify,
            )],
            granted_capabilities=("calendar:write",),
        )
        with self.assertRaisesRegex(ToolSurfaceError, "executor failed"):
            failing.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        with self.assertRaisesRegex(ToolSurfaceError, "indeterminate"):
            failing.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=4,
            )
        self.assertEqual(failing_calls, [1])

    def test_incomplete_verification_is_indeterminate_and_cannot_advance(self) -> None:
        recorder = RecordingTool()
        gateway = ToolSurface(
            [ToolAdapter(
                "tool:calendar", "1.0", ("calendar:create-reservation",),
                ("calendar:write",), recorder.execute, lambda _a, _e: [],
            )],
            granted_capabilities=("calendar:write",),
        )
        with self.assertRaisesRegex(ToolSurfaceError, "exact non-empty"):
            gateway.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        with self.assertRaisesRegex(ToolSurfaceError, "indeterminate"):
            gateway.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=4,
            )
        self.assertEqual(len(recorder.calls), 1)

    def test_successful_undeclared_extra_effect_is_indeterminate(self) -> None:
        calls: list[int] = []

        def execute(proposal: dict) -> dict:
            calls.append(1)
            return {
                "status": "SUCCEEDED",
                "raw_result_ref": {
                    "ref_id": "evidence:extra-effect",
                    "source": "TOOL",
                    "access_class": "EVALUATOR_ONLY",
                    "uri": None,
                    "content_hash": None,
                },
                "normalized_effects": [
                    *deepcopy(proposal["expected_effects"]),
                    {"undeclared": "extra"},
                ],
                "state_version_after": proposal["state_version"] + 1,
                "error_code": None,
            }

        gateway = ToolSurface(
            [ToolAdapter(
                "tool:calendar", "1.0", ("calendar:create-reservation",),
                ("calendar:write",), execute,
                lambda _proposal, effects: deepcopy(effects),
            )],
            granted_capabilities=("calendar:write",),
        )
        with self.assertRaisesRegex(ToolSurfaceError, "exact non-empty"):
            gateway.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        with self.assertRaisesRegex(ToolSurfaceError, "indeterminate"):
            gateway.invoke(
                action(), decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=4,
            )
        self.assertEqual(calls, [1])

    def test_compensatable_without_inv_001_prevalidation_is_denied(self) -> None:
        recorder = RecordingTool()
        attempt = surface(recorder).invoke(
            action(compensatable=True),
            decision("APPROVE"),
            validators(compensatable=True),
            started_at=TIME,
            completed_at=LATER,
            current_state_version=3,
        )
        self.assertEqual(attempt.authorization.resolution.value, "REJECT")
        self.assertFalse(attempt.executed)
        self.assertEqual(recorder.calls, [])

    def test_malformed_outputs_and_idempotency_conflicts_fail_closed(self) -> None:
        recorder = RecordingTool()
        gateway = surface(recorder)
        proposal = action()
        gateway.invoke(
            proposal, decision("APPROVE"), validators(),
            started_at=TIME, completed_at=LATER, current_state_version=3,
        )
        conflict = action(arguments={"slot": "16:00"})
        with self.assertRaisesRegex(ToolSurfaceError, "idempotency key"):
            gateway.invoke(
                conflict, decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        with self.assertRaisesRegex(ToolSurfaceError, "fails action-proposal"):
            gateway.invoke(
                {**proposal, "required_capabilities": []},
                decision("APPROVE"), validators(),
                started_at=TIME, completed_at=LATER, current_state_version=3,
            )
        self.assertEqual(gateway.dispatch_count, 1)


if __name__ == "__main__":
    unittest.main()
