from __future__ import annotations

import json
import subprocess
import sys
import unittest
from copy import deepcopy

from runtime.conditional_autonomy.reducer import (
    IllegalTransitionError,
    ReducerError,
    SchemaValidationError,
    canonical_state_bytes,
    reduce_event,
    replay_events,
)
from runtime.conditional_autonomy.storage import with_content_hash


def initial_state() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "episode_id": "episode:1",
        "state_version": 0,
        "logical_clock": 0,
        "entities": {},
        "resources": {"chairs": 4},
        "obligations": [],
        "dependencies": [],
        "deadlines": [],
        "permissions": [],
        "active_plan": None,
        "completed_actions": [],
        "pending_questions": [],
        "exogenous_events": [],
        "provenance": [],
        "revision_chain": [],
    }


def transition_event(
    event_id: str,
    clock: int,
    from_version: int,
    to_version: int,
    path: str = "/resources/chairs",
    value: object = 6,
) -> dict[str, object]:
    return with_content_hash(
        {
            "event_id": event_id,
            "episode_id": "episode:1",
            "event_type": "STATE_TRANSITION",
            "logical_clock": clock,
            "timestamp": {
                "instant": "2026-11-26T14:00:00Z",
                "source_timezone": "America/New_York",
                "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
            },
            "source": "ENVIRONMENT",
            "access_class": "EVALUATOR_ONLY",
            "payload": {
                "operation": "SET",
                "path": path,
                "value": value,
                "from_state_version": from_version,
                "to_state_version": to_version,
            },
            "provenance": {
                "provenance_id": f"provenance:{event_id}",
                "source": "ENVIRONMENT",
                "recorded_at": {
                    "instant": "2026-11-26T14:00:00Z",
                    "source_timezone": "America/New_York",
                    "uncertainty": {"kind": "EXACT", "minus_seconds": 0, "plus_seconds": 0},
                },
                "access_class": "EVALUATOR_ONLY",
                "content_hash": "sha256:" + "a" * 64,
            },
        }
    )


def sample_events() -> list[dict[str, object]]:
    return [
        transition_event("event:001", 1, 0, 1, value=6),
        transition_event("event:002", 2, 1, 2, value=8),
    ]


class DeterministicReducerTests(unittest.TestCase):
    def test_schema_validation_error_remains_a_reducer_error(self) -> None:
        self.assertTrue(issubclass(SchemaValidationError, ReducerError))
        invalid_state = initial_state()
        del invalid_state["resources"]
        with self.assertRaises(ReducerError) as caught:
            reduce_event(invalid_state, transition_event("event:invalid-state", 1, 0, 1))
        self.assertIsInstance(caught.exception, SchemaValidationError)
        self.assertIsNotNone(caught.exception.__cause__)

    def test_pinned_validator_loads_under_isolated_python(self) -> None:
        program = (
            "from runtime.conditional_autonomy.contracts import _jsonschema_types; "
            "validator,*_= _jsonschema_types(); print(validator.__module__)"
        )
        completed = subprocess.run(
            [sys.executable, "-S", "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), "jsonschema.validators")

    def test_inv_007_versions_and_inv_008_set_semantics(self) -> None:
        result = replay_events(initial_state(), sample_events())
        self.assertEqual(result["resources"]["chairs"], 8)
        self.assertEqual(result["state_version"], 2)
        self.assertEqual(result["revision_chain"], ["event:001", "event:002"])
        canonical_state_bytes(result)  # validates the output contract

    def test_replay_is_byte_identical_and_does_not_mutate_inputs(self) -> None:
        state, events = initial_state(), sample_events()
        state_before, events_before = deepcopy(state), deepcopy(events)
        first = canonical_state_bytes(replay_events(state, events))
        second = canonical_state_bytes(replay_events(state, events))
        self.assertEqual(first, second)
        self.assertEqual(state, state_before)
        self.assertEqual(events, events_before)

    def test_fresh_process_replay_produces_identical_bytes(self) -> None:
        request = json.dumps({"state": initial_state(), "events": sample_events()})
        program = (
            "import json,sys; "
            "from runtime.conditional_autonomy.reducer import replay_events,canonical_state_bytes; "
            "x=json.load(sys.stdin); "
            "sys.stdout.buffer.write(canonical_state_bytes(replay_events(x['state'],x['events'])))"
        )
        outputs = [
            subprocess.run(
                [sys.executable, "-c", program], input=request.encode(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            ).stdout
            for _ in range(2)
        ]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(
            outputs[0],
            canonical_state_bytes(replay_events(initial_state(), sample_events())),
        )

    def test_invalid_state_and_event_schemas_fail_before_reduction(self) -> None:
        invalid_state = initial_state()
        del invalid_state["resources"]
        with self.assertRaisesRegex(SchemaValidationError, "canonical-state.schema.json"):
            reduce_event(invalid_state, transition_event("event:valid", 1, 0, 1))

        invalid_event = transition_event("event:invalid", 1, 0, 1)
        del invalid_event["timestamp"]
        invalid_event = with_content_hash(invalid_event)
        with self.assertRaisesRegex(SchemaValidationError, "event.schema.json"):
            reduce_event(initial_state(), invalid_event)

    def test_skipped_and_stale_versions_fail_closed(self) -> None:
        for event in (
            transition_event("event:skip", 1, 0, 2),
            transition_event("event:stale", 1, 1, 2),
            transition_event("event:backward", 1, 0, 0),
        ):
            with self.subTest(event=event["event_id"]):
                with self.assertRaises(IllegalTransitionError):
                    reduce_event(initial_state(), event)

    def test_invalid_operation_payload_and_paths_fail_closed(self) -> None:
        bad_operation = transition_event("event:op", 1, 0, 1)
        bad_operation["payload"]["operation"] = "ADD"
        bad_operation = with_content_hash(bad_operation)
        extra_payload = transition_event("event:extra", 1, 0, 1)
        extra_payload["payload"]["reason"] = "not in contract"
        extra_payload = with_content_hash(extra_payload)
        events = (
            bad_operation,
            extra_payload,
            transition_event("event:missing", 1, 0, 1, "/resources/tables", 2),
            transition_event("event:owned", 1, 0, 1, "/state_version", 1),
            transition_event("event:escape", 1, 0, 1, "/resources/~2bad", 1),
        )
        for event in events:
            with self.subTest(event=event["event_id"]):
                with self.assertRaises(IllegalTransitionError):
                    reduce_event(initial_state(), event)

    def test_non_transition_event_type_with_transition_payload_is_rejected(self) -> None:
        query = transition_event("event:query", 1, 0, 1)
        query["event_type"] = "QUERY"
        query = with_content_hash(query)
        with self.assertRaisesRegex(IllegalTransitionError, "STATE_TRANSITION"):
            reduce_event(initial_state(), query)

    def test_well_formed_but_tampered_content_hash_is_rejected(self) -> None:
        tampered = transition_event("event:tampered", 1, 0, 1)
        tampered["content_hash"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(IllegalTransitionError, "content_hash"):
            reduce_event(initial_state(), tampered)

    def test_same_value_noop_is_rejected(self) -> None:
        with self.assertRaisesRegex(IllegalTransitionError, "no-op"):
            reduce_event(initial_state(), transition_event("event:noop", 1, 0, 1, value=4))

    def test_noop_comparison_is_canonical_and_type_aware(self) -> None:
        numeric = initial_state()
        numeric["resources"]["chairs"] = 1
        changed = reduce_event(
            numeric, transition_event("event:number-to-boolean", 1, 0, 1, value=True)
        )
        self.assertIs(changed["resources"]["chairs"], True)
        with self.assertRaisesRegex(IllegalTransitionError, "no-op"):
            reduce_event(
                changed,
                transition_event("event:boolean-noop", 2, 1, 2, value=True),
            )

        nested = initial_state()
        nested["resources"]["configuration"] = {"b": [1, {"x": True}], "a": 2}
        equal_with_different_key_order = {"a": 2, "b": [1, {"x": True}]}
        with self.assertRaisesRegex(IllegalTransitionError, "no-op"):
            reduce_event(
                nested,
                transition_event(
                    "event:nested-noop",
                    1,
                    0,
                    1,
                    "/resources/configuration",
                    equal_with_different_key_order,
                ),
            )

    def test_episode_clock_successor_and_duplicate_guards(self) -> None:
        wrong_episode = transition_event("event:other", 1, 0, 1)
        wrong_episode["episode_id"] = "episode:other"
        wrong_episode = with_content_hash(wrong_episode)
        bad_value = transition_event("event:bad", 1, 0, 1, "/completed_actions", "not-array")
        duplicate_state = initial_state()
        duplicate_state["revision_chain"] = ["event:dup"]
        guarded = (
            (initial_state(), wrong_episode),
            (initial_state(), transition_event("event:clock", 0, 0, 1)),
            (initial_state(), bad_value),
            (duplicate_state, transition_event("event:dup", 1, 0, 1)),
        )
        for state, event in guarded:
            with self.subTest(event=event["event_id"]):
                with self.assertRaises(IllegalTransitionError):
                    reduce_event(state, event)


if __name__ == "__main__":
    unittest.main()
