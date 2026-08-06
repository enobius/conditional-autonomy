from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path

from runtime.conditional_autonomy.storage import (
    AppendOnlyStore,
    DuplicateArtifactIdError,
    DuplicateEventIdError,
    IntegrityError,
    canonical_content_hash,
    canonical_json_bytes,
    with_content_hash,
)


def event(event_id: str, clock: int) -> dict[str, object]:
    return with_content_hash(
        {
            "event_id": event_id,
            "episode_id": "episode:1",
            "event_type": "OBSERVE",
            "logical_clock": clock,
            "payload": {"observation_ref": f"observation:{clock}"},
        }
    )


def append_event_worker(
    root: str,
    event_id: str,
    clock: int,
    start: object,
    results: object,
) -> None:
    store = AppendOnlyStore(root)
    start.wait()
    try:
        store.append_event(event(event_id, clock))
    except Exception as exc:  # pragma: no cover - asserted in the parent process
        results.put(type(exc).__name__)
    else:
        results.put("ok")


def put_artifact_worker(
    root: str,
    artifact_id: str,
    start: object,
    results: object,
) -> None:
    store = AppendOnlyStore(root)
    start.wait()
    try:
        store.put_artifact(
            artifact_id,
            "canonical-state",
            {"state_id": artifact_id, "version": 1},
        )
    except Exception as exc:  # pragma: no cover - asserted in the parent process
        results.put(type(exc).__name__)
    else:
        results.put("ok")


def hold_shared_root_lock_worker(
    root: str,
    acquired: object,
    release: object,
) -> None:
    store = AppendOnlyStore(root)
    with store._locked():
        acquired.set()
        if not release.wait(timeout=10):
            raise TimeoutError("parent did not release shared-root lock")


def contending_append_worker(
    root: str,
    started: object,
    entered_write_transaction: object,
) -> None:
    store = AppendOnlyStore(root)
    started.set()
    store.append_event(
        event("event:contender", 1),
        _before_replace=entered_write_transaction.set,
    )


class CanonicalJsonTests(unittest.TestCase):
    def test_object_key_order_does_not_change_canonical_bytes_or_hash(self) -> None:
        left = {"z": [2, 1], "a": {"b": True}}
        right = {"a": {"b": True}, "z": [2, 1]}
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(canonical_content_hash(left), canonical_content_hash(right))

    def test_self_hash_is_excluded_from_content_hash_domain(self) -> None:
        content = {"artifact": "one"}
        hashed = with_content_hash(content)
        self.assertEqual(hashed["content_hash"], canonical_content_hash(hashed))
        self.assertNotIn("content_hash", content)


class AppendOnlyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = AppendOnlyStore(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_concurrently(self, target: object, arguments: list[tuple[object, ...]]) -> list[str]:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(target=target, args=(*args, start, results))
            for args in arguments
        ]
        for process in processes:
            process.start()
        try:
            start.set()
            outcomes = [results.get(timeout=10) for _ in processes]
        finally:
            for process in processes:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            results.close()
            results.join_thread()
        for process in processes:
            self.assertEqual(process.exitcode, 0)
        return outcomes

    def test_distinct_concurrent_events_from_separate_processes_are_not_lost(self) -> None:
        count = 6
        outcomes = self.run_concurrently(
            append_event_worker,
            [(str(self.root), f"event:{index}", index) for index in range(count)],
        )

        self.assertEqual(outcomes, ["ok"] * count)
        stored = AppendOnlyStore(self.root).events()
        self.assertEqual(
            {item["event_id"] for item in stored},
            {f"event:{index}" for index in range(count)},
        )

    def test_cross_process_contender_waits_for_shared_root_lock(self) -> None:
        context = multiprocessing.get_context("spawn")
        acquired = context.Event()
        release = context.Event()
        started = context.Event()
        entered_write_transaction = context.Event()
        holder = context.Process(
            target=hold_shared_root_lock_worker,
            args=(str(self.root), acquired, release),
        )
        contender = context.Process(
            target=contending_append_worker,
            args=(str(self.root), started, entered_write_transaction),
        )
        holder.start()
        try:
            self.assertTrue(acquired.wait(timeout=5), "holder did not acquire root lock")
            contender.start()
            self.assertTrue(started.wait(timeout=5), "contender did not start")
            self.assertFalse(
                entered_write_transaction.wait(timeout=0.5),
                "contender entered append transaction while holder owned root lock",
            )
            release.set()
            self.assertTrue(
                entered_write_transaction.wait(timeout=5),
                "contender did not proceed after root lock release",
            )
        finally:
            release.set()
            for process in (holder, contender):
                if process.pid is not None:
                    process.join(timeout=10)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=10)
        self.assertEqual(holder.exitcode, 0)
        self.assertEqual(contender.exitcode, 0)
        self.assertEqual(
            [item["event_id"] for item in AppendOnlyStore(self.root).events()],
            ["event:contender"],
        )

    def test_separate_instances_serialize_durable_event_reads(self) -> None:
        first = AppendOnlyStore(self.root)
        second = AppendOnlyStore(self.root)
        first_entered_read = threading.Event()
        release_first = threading.Event()
        second_entered_read = threading.Event()
        failures: list[BaseException] = []
        first_read = first._read_verified_log
        second_read = second._read_verified_log

        def paused_first_read() -> tuple[bytes, list[dict[str, object]]]:
            first_entered_read.set()
            if not release_first.wait(timeout=5):
                raise TimeoutError("test did not release first store read")
            return first_read()

        def observed_second_read() -> tuple[bytes, list[dict[str, object]]]:
            second_entered_read.set()
            return second_read()

        def append(store: AppendOnlyStore, item: dict[str, object]) -> None:
            try:
                store.append_event(item)
            except BaseException as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        first._read_verified_log = paused_first_read
        second._read_verified_log = observed_second_read
        first_thread = threading.Thread(target=append, args=(first, event("event:1", 1)))
        second_thread = threading.Thread(target=append, args=(second, event("event:2", 2)))
        first_thread.start()
        self.assertTrue(first_entered_read.wait(timeout=5))
        second_thread.start()
        try:
            self.assertFalse(
                second_entered_read.wait(timeout=0.5),
                "second instance read durable state before first released root lock",
            )
        finally:
            release_first.set()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(
            [item["event_id"] for item in AppendOnlyStore(self.root).events()],
            ["event:1", "event:2"],
        )

    def test_duplicate_concurrent_event_ids_have_exactly_one_winner(self) -> None:
        outcomes = self.run_concurrently(
            append_event_worker,
            [(str(self.root), "event:shared", clock) for clock in range(4)],
        )

        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(outcomes.count("DuplicateEventIdError"), 3)
        self.assertEqual(len(AppendOnlyStore(self.root).events()), 1)

    def test_duplicate_concurrent_artifact_ids_have_exactly_one_winner(self) -> None:
        outcomes = self.run_concurrently(
            put_artifact_worker,
            [(str(self.root), "state:shared") for _ in range(4)],
        )

        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(outcomes.count("DuplicateArtifactIdError"), 3)
        self.assertEqual(
            AppendOnlyStore(self.root).get_artifact("state:shared"),
            {"state_id": "state:shared", "version": 1},
        )

    def test_artifact_round_trip_is_immutable_and_hash_verified(self) -> None:
        # Canonical-state contracts do not have a top-level content_hash; the
        # artifact envelope supplies it without altering contract content.
        content = {"state_id": "state:1", "version": 1}
        expected_hash = canonical_content_hash(content)
        self.assertEqual(
            self.store.put_artifact("state:1", "canonical-state", content),
            expected_hash,
        )
        self.assertEqual(
            self.store.get_artifact("state:1", expected_type="canonical-state"),
            content,
        )
        self.assertEqual(self.store.verify_artifact("state:1"), expected_hash)
        with self.assertRaises(DuplicateArtifactIdError):
            self.store.put_artifact("state:1", "canonical-state", content)

    def test_one_byte_artifact_mutation_fails_verification(self) -> None:
        content = with_content_hash({"state_id": "state:1", "value": "safe"})
        self.store.put_artifact("state:1", "canonical-state", content)
        artifact_path = next((self.root / "artifacts").glob("*.json"))
        stored = artifact_path.read_bytes()
        offset = stored.index(b"safe")
        artifact_path.write_bytes(stored[:offset] + b"x" + stored[offset + 1 :])

        with self.assertRaisesRegex(IntegrityError, "content hash mismatch"):
            self.store.verify_artifact("state:1")

    def test_nonfinite_persisted_artifact_is_integrity_error(self) -> None:
        self.store.put_artifact("state:1", "canonical-state", {"value": 1})
        artifact_path = next((self.root / "artifacts").glob("*.json"))
        artifact_path.write_text('{"value":NaN}', encoding="utf-8")

        with self.assertRaisesRegex(IntegrityError, "not valid strict JSON"):
            self.store.get_artifact("state:1")

    def test_event_append_rejects_duplicate_id_from_durable_log(self) -> None:
        first = event("event:1", 1)
        self.store.append_event(first)

        # A fresh store instance proves duplicate detection is not session state.
        reopened = AppendOnlyStore(self.root)
        with self.assertRaises(DuplicateEventIdError):
            reopened.append_event(event("event:1", 2))
        self.assertEqual(reopened.events(), [first])

    def test_interruption_before_atomic_replace_leaves_complete_prior_log(self) -> None:
        first = event("event:1", 1)
        expected_hash = self.store.append_event(first)

        def interrupt() -> None:
            raise RuntimeError("forced interruption")

        with self.assertRaisesRegex(RuntimeError, "forced interruption"):
            self.store.append_event(event("event:2", 2), _before_replace=interrupt)

        reopened = AppendOnlyStore(self.root)
        self.assertEqual(reopened.events(), [first])
        self.assertEqual(reopened.verify_event_log(expected_hash), expected_hash)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_event_log_hash_covers_exact_canonical_jsonl_bytes(self) -> None:
        events = [event("event:1", 1), event("event:2", 3)]
        for item in events:
            actual_hash = self.store.append_event(item)
        expected_bytes = b"".join(canonical_json_bytes(item) + b"\n" for item in events)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), expected_bytes)
        self.assertEqual(actual_hash, self.store.verify_event_log())

    def test_event_log_tamper_and_wrong_expected_hash_fail_verification(self) -> None:
        self.store.append_event(event("event:1", 1))
        log_path = self.root / "events.jsonl"
        stored = log_path.read_bytes()
        offset = stored.index(b"OBSERVE")
        log_path.write_bytes(stored[:offset] + b"X" + stored[offset + 1 :])

        with self.assertRaisesRegex(IntegrityError, "content hash mismatch"):
            self.store.verify_event_log()

        log_path.write_bytes(stored)
        with self.assertRaisesRegex(IntegrityError, "event-log hash mismatch"):
            self.store.verify_event_log("sha256:" + "0" * 64)

    def test_noncanonical_or_partial_durable_log_fails_closed(self) -> None:
        item = event("event:1", 1)
        (self.root / "events.jsonl").write_text(json.dumps(item), encoding="utf-8")
        with self.assertRaisesRegex(IntegrityError, "partial record"):
            self.store.events()

    def test_nonfinite_persisted_event_is_integrity_error(self) -> None:
        (self.root / "events.jsonl").write_bytes(b'{"event_id":"event:1","x":NaN}\n')

        with self.assertRaisesRegex(IntegrityError, "not valid strict JSON"):
            self.store.events()


if __name__ == "__main__":
    unittest.main()
