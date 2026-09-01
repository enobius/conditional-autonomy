from __future__ import annotations

import base64
import json
import subprocess
import sys
import unittest
from copy import deepcopy

from runtime.conditional_autonomy.contracts import validate_contract
from runtime.conditional_autonomy.disruptions import (
    P9_EPISODE_ID,
    P9_JAMES_ARRIVAL,
    P9_NOTIFICATION,
    P9_PLAN_ID,
    canonical_disrupted_episode_bytes,
    p9_replanned_actions,
    plan_respects_james_arrival,
    run_disrupted_thanksgiving_episode,
)
from runtime.conditional_autonomy.reducer import canonical_state_bytes, replay_events
from runtime.conditional_autonomy.replay import validate_logical_clock_order
from runtime.conditional_autonomy.storage import canonical_json_bytes
from runtime.conditional_autonomy.thanksgiving import (
    JAMES_ARRIVAL,
    evaluate_schedule,
    normalized_time,
    thanksgiving_actions,
)


class ThanksgivingDisruptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.episode = run_disrupted_thanksgiving_episode()

    def test_exact_p9_delay_is_one_mid_episode_ledger_transition(self) -> None:
        event = self.episode.disruption_event
        self.assertEqual(event["source"], "USER")
        self.assertEqual(event["event_type"], "STATE_TRANSITION")
        self.assertEqual(event["logical_clock"], 2)
        self.assertEqual(event["timestamp"], normalized_time(P9_NOTIFICATION))
        self.assertEqual(event["timestamp"]["instant"], "2026-11-26T15:00:00Z")
        self.assertEqual(
            self.episode.events[0]["timestamp"]["instant"],
            "2026-11-26T14:00:00Z",
        )
        self.assertEqual(P9_NOTIFICATION + 180, JAMES_ARRIVAL)
        self.assertLess(JAMES_ARRIVAL, P9_JAMES_ARRIVAL)
        self.assertEqual(event["payload"]["operation"], "SET")
        self.assertEqual(
            event["payload"]["path"], "/entities/person:james/arrival_at"
        )
        self.assertEqual(event["payload"]["value"], normalized_time(P9_JAMES_ARRIVAL))
        self.assertEqual(
            sum(item["event_id"] == "event:p9-james-delay" for item in self.episode.events),
            1,
        )
        self.assertEqual(self.episode.events[0]["event_type"], "PLAN_AUTHORIZED")

    def test_delay_forces_replanning_before_revised_execution(self) -> None:
        state_after_delay = replay_events(
            self.episode.initial_state, [self.episode.disruption_event]
        )
        self.assertFalse(plan_respects_james_arrival(state_after_delay, thanksgiving_actions()))
        revised = p9_replanned_actions()
        self.assertTrue(plan_respects_james_arrival(state_after_delay, revised))
        self.assertTrue(all(item.passed for item in evaluate_schedule(state_after_delay, revised)))
        self.assertNotEqual(self.episode.original_plan_id, self.episode.replacement_plan_id)
        self.assertEqual(self.episode.replacement_plan_id, P9_PLAN_ID)
        self.assertEqual(self.episode.replanning_event["logical_clock"], 3)
        first_revised_effect_clock = min(
            event["logical_clock"]
            for event in self.episode.events
            if event["event_type"] == "STATE_TRANSITION"
            and event["logical_clock"] > self.episode.replanning_event["logical_clock"]
        )
        self.assertLess(self.episode.replanning_event["logical_clock"], first_revised_effect_clock)

    def test_all_state_changes_replay_from_ledger_byte_identically(self) -> None:
        events = list(self.episode.events)
        for event in events:
            validate_contract(event, "event.schema.json", "P9 event")
            self.assertEqual(event["episode_id"], P9_EPISODE_ID)
        validate_logical_clock_order(events)
        transitions = [event for event in events if event["event_type"] == "STATE_TRANSITION"]
        replayed = replay_events(self.episode.initial_state, transitions)
        self.assertEqual(
            canonical_state_bytes(replayed),
            canonical_state_bytes(self.episode.final_state),
        )
        self.assertEqual(
            self.episode.final_state["state_version"], len(transitions)
        )
        self.assertEqual(
            self.episode.final_state["revision_chain"],
            [event["event_id"] for event in transitions],
        )

    def test_no_hidden_mutation_and_accessors_are_defensive(self) -> None:
        initial_before = canonical_json_bytes(self.episode.initial_state)
        disrupted = replay_events(self.episode.initial_state, [self.episode.disruption_event])
        self.assertEqual(canonical_json_bytes(self.episode.initial_state), initial_before)
        self.assertEqual(
            disrupted["entities"]["person:james"]["arrival_at"],
            normalized_time(P9_JAMES_ARRIVAL),
        )
        exposed = self.episode.final_state
        exposed["active_plan"]["plan_id"] = "plan:corrupt"
        self.assertEqual(self.episode.final_state["active_plan"]["plan_id"], P9_PLAN_ID)

    def test_replanned_episode_completes_required_obligations_by_dinner(self) -> None:
        final = self.episode.final_state
        self.assertTrue(all(item["status"] == "COMPLETED" for item in final["obligations"]))
        self.assertTrue(
            all(
                final["entities"][person]["location"] == "HOME"
                for person in (
                    "person:james",
                    "person:emily",
                    "person:michael",
                    "person:grandma",
                )
            )
        )
        self.assertEqual(final["resources"]["food"]["turkey"]["status"], "READY")
        self.assertEqual(final["resources"]["food"]["sides"]["status"], "READY")

    def test_disrupted_episode_is_identical_across_fresh_processes(self) -> None:
        expected = base64.b64encode(
            canonical_disrupted_episode_bytes(self.episode)
        ).decode("ascii")
        script = (
            "import base64; "
            "from runtime.conditional_autonomy.disruptions import "
            "run_disrupted_thanksgiving_episode, canonical_disrupted_episode_bytes; "
            "print(base64.b64encode(canonical_disrupted_episode_bytes("
            "run_disrupted_thanksgiving_episode())).decode('ascii'))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
