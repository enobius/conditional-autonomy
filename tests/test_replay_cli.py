from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from runtime.conditional_autonomy.reducer import canonical_state_bytes, replay_events
from runtime.conditional_autonomy.replay import (
    ReplayVerificationError,
    canonical_event_log_hash,
    diff_ledger_files,
    replay_from_store,
    verify_episode,
)
from runtime.conditional_autonomy.storage import (
    AppendOnlyStore,
    IntegrityError,
    with_content_hash,
)
from tests.test_reducer import initial_state, sample_events, transition_event


ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "architecture" / "schemas" / "v1.0" / "fixtures" / "valid"


def _read_fixture(name: str) -> dict[str, object]:
    return json.loads((VALID / name).read_text(encoding="utf-8"))


def _episode(store: AppendOnlyStore, *, step_indexes: tuple[int, ...] = (0, 1)) -> dict[str, object]:
    episode = _read_fixture("episode.valid.json")
    prototype = episode["steps"][0]
    steps = []
    for ordinal, step_index in enumerate(step_indexes):
        step = deepcopy(prototype)
        step["trace_step_id"] = f"trace-step:{ordinal}"
        step["step_index"] = step_index
        step["canonical_state_ref"]["ref_id"] = "state:final"
        steps.append(step)
    episode["steps"] = steps
    episode_events = [
        event for event in store.events() if event["episode_id"] == episode["episode_id"]
    ]
    episode["event_log_hash"] = canonical_event_log_hash(episode_events)
    return episode


def _golden_store(root: Path) -> tuple[AppendOnlyStore, dict[str, object]]:
    store = AppendOnlyStore(root)
    initial = initial_state()
    events = sample_events()
    final = replay_events(initial, events)
    store.put_artifact("state:initial", "canonical-state", initial)
    store.put_artifact("state:final", "canonical-state", final)
    for event in events:
        store.append_event(event)
    episode = _episode(store)
    store.put_artifact("episode:1", "episode", episode)
    return store, final


def _nontransition_event(
    event_id: str, clock: int, event_type: str, *, episode_id: str = "episode:1"
) -> dict[str, object]:
    event = transition_event(event_id, clock, 0, 1)
    event["episode_id"] = episode_id
    event["event_type"] = event_type
    event["payload"] = {"classification": event_type}
    return with_content_hash(event)


class ReplayCliTests(unittest.TestCase):
    def test_golden_episode_replays_identically_in_fresh_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, final = _golden_store(Path(directory))
            command = [
                sys.executable,
                "-m",
                "runtime.conditional_autonomy.replay",
                "replay",
                directory,
                "state:initial",
            ]
            outputs = [
                subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                ).stdout
                for _ in range(2)
            ]
            expected = canonical_state_bytes(final) + b"\n"
            self.assertEqual(outputs, [expected, expected])

    def test_verify_accepts_golden_episode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, final = _golden_store(Path(directory))
            report = verify_episode(
                store, "episode:1", "state:initial", "state:final"
            )
            self.assertEqual(report.episode_id, "episode:1")
            self.assertEqual(report.event_count, 2)
            self.assertEqual(report.trace_step_count, 2)
            self.assertEqual(report.final_state_bytes, len(canonical_state_bytes(final)))

            command = [
                sys.executable,
                "-m",
                "runtime.conditional_autonomy.replay",
                "verify",
                directory,
                "episode:1",
                "state:initial",
                "state:final",
            ]
            success = subprocess.run(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(success.stdout)["episode_id"], "episode:1")

            command[-1] = "state:initial"
            failure = subprocess.run(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(failure.returncode, 2)
            self.assertIn("terminal trace-step", failure.stderr)

    def test_inv_008_rejects_wrong_but_consistently_referenced_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _ = _golden_store(Path(directory))
            episode = _episode(store)
            episode["steps"][-1]["canonical_state_ref"]["ref_id"] = "state:initial"
            store.put_artifact("episode:wrong-terminal", "episode", episode)

            with self.assertRaisesRegex(ReplayVerificationError, "INV-008"):
                verify_episode(
                    store,
                    "episode:wrong-terminal",
                    "state:initial",
                    "state:initial",
                )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.conditional_autonomy.replay",
                    "verify",
                    directory,
                    "episode:wrong-terminal",
                    "state:initial",
                    "state:initial",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("INV-008", completed.stderr)

    def test_diff_pinpoints_single_byte_ledger_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _golden_store(root)
            left = root / "events.jsonl"
            right = root / "events.mutated.jsonl"
            shutil.copyfile(left, right)
            mutated = bytearray(right.read_bytes())
            offset = mutated.index(b"event:001") + len("event:")
            self.assertEqual(mutated[offset], ord("0"))
            mutated[offset] = ord("9")
            right.write_bytes(mutated)
            difference = diff_ledger_files(left, right)
            self.assertIsNotNone(difference)
            assert difference is not None
            self.assertEqual(difference.offset, offset)
            self.assertEqual((difference.left_byte, difference.right_byte), (48, 57))

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.conditional_autonomy.replay",
                    "diff",
                    str(left),
                    str(right),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(json.loads(completed.stdout)["offset"], offset)

    def test_episode_hash_and_replay_ignore_other_episode_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, final = _golden_store(Path(directory))
            declared_hash = store.get_artifact(
                "episode:1", expected_type="episode"
            )["event_log_hash"]
            whole_store_hash_before = store.event_log_hash()
            store.append_event(
                _nontransition_event(
                    "event:other", 1, "QUERY", episode_id="episode:other"
                )
            )
            self.assertNotEqual(store.event_log_hash(), whole_store_hash_before)
            report = verify_episode(
                store, "episode:1", "state:initial", "state:final"
            )
            self.assertEqual(report.event_log_hash, declared_hash)
            self.assertEqual(
                canonical_state_bytes(replay_from_store(store, "state:initial")),
                canonical_state_bytes(final),
            )

    def test_verify_checks_integrity_of_unrelated_whole_store_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = _golden_store(root)
            store.append_event(
                _nontransition_event(
                    "event:other", 1, "QUERY", episode_id="episode:other"
                )
            )
            ledger = root / "events.jsonl"
            tampered = ledger.read_bytes().replace(b"event:other", b"event:0ther", 1)
            ledger.write_bytes(tampered)
            with self.assertRaises(IntegrityError):
                verify_episode(store, "episode:1", "state:initial", "state:final")

    def test_query_and_user_response_are_hashed_and_clock_checked_not_reduced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            initial = initial_state()
            events = [
                transition_event("event:001", 1, 0, 1, value=6),
                _nontransition_event("event:query", 2, "QUERY"),
                _nontransition_event("event:response", 3, "USER_RESPONSE"),
                transition_event("event:002", 4, 1, 2, value=8),
            ]
            final = replay_events(initial, (events[0], events[-1]))
            store.put_artifact("state:initial", "canonical-state", initial)
            store.put_artifact("state:final", "canonical-state", final)
            for event in events:
                store.append_event(event)
            store.put_artifact("episode:1", "episode", _episode(store))
            report = verify_episode(
                store, "episode:1", "state:initial", "state:final"
            )
            self.assertEqual(report.event_count, 4)
            self.assertEqual(replay_from_store(store, "state:initial"), final)

    def test_nontransition_events_participate_in_clock_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            initial = initial_state()
            store.put_artifact("state:initial", "canonical-state", initial)
            store.put_artifact("state:final", "canonical-state", initial)
            store.append_event(_nontransition_event("event:query", 2, "QUERY"))
            store.append_event(
                _nontransition_event("event:response", 1, "USER_RESPONSE")
            )
            store.put_artifact("episode:1", "episode", _episode(store))
            with self.assertRaisesRegex(ReplayVerificationError, "INV-006"):
                verify_episode(store, "episode:1", "state:initial", "state:final")

    def test_verify_rejects_illegal_clock_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyStore(directory)
            initial = initial_state()
            store.put_artifact("state:initial", "canonical-state", initial)
            store.put_artifact("state:final", "canonical-state", initial)
            store.append_event(transition_event("event:late", 2, 0, 1, value=6))
            store.append_event(transition_event("event:early", 1, 1, 2, value=8))
            store.put_artifact("episode:1", "episode", _episode(store))
            with self.assertRaisesRegex(ReplayVerificationError, "INV-006"):
                verify_episode(store, "episode:1", "state:initial", "state:final")

    def test_verify_rejects_noncontiguous_and_cross_episode_steps(self) -> None:
        for name, mutate, message in (
            (
                "noncontiguous",
                lambda episode: episode["steps"][1].update(step_index=2),
                "INV-016",
            ),
            (
                "cross-episode",
                lambda episode: episode["steps"][1].update(episode_id="episode:other"),
                "INV-016",
            ),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                store, _ = _golden_store(Path(directory))
                episode = _episode(store)
                mutate(episode)
                store.put_artifact(f"episode:{name}", "episode", episode)
                with self.assertRaisesRegex(ReplayVerificationError, message):
                    verify_episode(
                        store, f"episode:{name}", "state:initial", "state:final"
                    )

    def test_trace_step_contiguity_is_relative_to_first_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _ = _golden_store(Path(directory))
            store.put_artifact(
                "episode:relative", "episode", _episode(store, step_indexes=(1, 2))
            )
            report = verify_episode(
                store, "episode:relative", "state:initial", "state:final"
            )
            self.assertEqual(report.trace_step_count, 2)


if __name__ == "__main__":
    unittest.main()
