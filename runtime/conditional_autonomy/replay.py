"""Replay, byte-diff, and episode verification primitives and CLI.

The commands operate on the append-only store instead of accepting unchecked
contract objects.  That keeps integrity, typed reference resolution, and state
transition semantics in their owning runtime components.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import validate_contract
from .reducer import canonical_state_bytes, replay_events
from .references import ArtifactReferenceResolver, ReferenceResolution
from .storage import AppendOnlyStore, canonical_json_bytes


class ReplayVerificationError(RuntimeError):
    """An episode cannot be replayed or verified without violating a contract."""


@dataclass(frozen=True)
class ByteDifference:
    """The first exact byte difference between two ledger files."""

    offset: int
    line: int
    column: int
    left_byte: int | None
    right_byte: int | None


@dataclass(frozen=True)
class VerificationReport:
    """Successful replay verification evidence."""

    episode_id: str
    event_count: int
    trace_step_count: int
    event_log_hash: str
    final_state_bytes: int


def first_byte_difference(left: bytes, right: bytes) -> ByteDifference | None:
    """Return the first differing byte with a one-based line and column."""

    common = min(len(left), len(right))
    offset = next((index for index in range(common) if left[index] != right[index]), common)
    if offset == common and len(left) == len(right):
        return None
    prefix = left[:offset]
    line = prefix.count(b"\n") + 1
    last_newline = prefix.rfind(b"\n")
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return ByteDifference(
        offset=offset,
        line=line,
        column=column,
        left_byte=left[offset] if offset < len(left) else None,
        right_byte=right[offset] if offset < len(right) else None,
    )


def diff_ledger_files(left: str | Path, right: str | Path) -> ByteDifference | None:
    """Compare ledger files without parsing or normalizing their bytes."""

    return first_byte_difference(Path(left).read_bytes(), Path(right).read_bytes())


def canonical_event_log_hash(events: Sequence[Mapping[str, Any]]) -> str:
    """Hash one ordered event subset as canonical JSONL, including final newline."""

    content = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _resolved_content(
    resolution: ReferenceResolution, *, description: str
) -> Mapping[str, Any]:
    if not resolution.succeeded:
        assert resolution.failure is not None
        raise ReplayVerificationError(
            f"{description} reference failed: {resolution.failure.code.value}: "
            f"{resolution.failure.detail}"
        )
    return resolution.artifacts[0].content


def _artifact(
    resolver: ArtifactReferenceResolver, ref_id: str, artifact_type: str
) -> Mapping[str, Any]:
    return _resolved_content(
        resolver.resolve_string_reference(ref_id, artifact_type),
        description=artifact_type,
    )


def validate_logical_clock_order(events: Sequence[Mapping[str, Any]]) -> None:
    """Enforce INV-006 for one already-declared total event order.

    Clocks need only be strictly increasing; gaps are valid.  Shape validation
    remains with the caller's contract boundary.
    """

    previous_clock: int | None = None
    for event in events:
        clock = event["logical_clock"]
        if previous_clock is not None and clock <= previous_clock:
            raise ReplayVerificationError(
                "INV-006: episode event logical clocks are not strictly ordered: "
                f"{previous_clock} then {clock} at event {event['event_id']!r}"
            )
        previous_clock = clock


def validate_episode_trace_order(
    episode_id: str, steps: Sequence[Mapping[str, Any]]
) -> None:
    """Enforce INV-016 sequence membership and relative contiguous ordering."""

    first_index = steps[0]["step_index"]
    for offset, step in enumerate(steps):
        expected_index = first_index + offset
        actual_index = step["step_index"]
        if step["episode_id"] != episode_id:
            raise ReplayVerificationError(
                f"INV-016: trace step {step['trace_step_id']!r} belongs to "
                f"{step['episode_id']!r}, not {episode_id!r}"
            )
        if actual_index != expected_index:
            raise ReplayVerificationError(
                "INV-016: trace step indexes must be unique, contiguous, and ascending; "
                f"expected {expected_index}, found {actual_index}"
            )


def _episode_events(
    store: AppendOnlyStore, episode_id: str
) -> list[dict[str, Any]]:
    events = []
    for index, event in enumerate(store.events(), start=1):
        if event.get("episode_id") != episode_id:
            continue
        events.append(validate_contract(event, "event.schema.json", f"event log record {index}"))
    validate_logical_clock_order(events)
    return events


def _verify_trace_steps(
    episode: Mapping[str, Any], resolver: ArtifactReferenceResolver
) -> tuple[dict[str, Any], ...]:
    episode_id = episode["episode_id"]
    validate_episode_trace_order(episode_id, episode["steps"])
    states: list[dict[str, Any]] = []
    for step in episode["steps"]:
        step_id = step["trace_step_id"]
        state = _resolved_content(
            resolver.resolve_object_reference(
                step["canonical_state_ref"], "canonical-state"
            ),
            description=f"trace step {step_id!r} canonical state",
        )
        checked_state = validate_contract(
            state, "canonical-state.schema.json", "trace-step canonical state"
        )
        if checked_state["episode_id"] != episode_id:
            raise ReplayVerificationError(
                f"INV-016: trace step {step_id!r} resolves a cross-episode state"
            )
        states.append(checked_state)
    return tuple(states)


def replay_from_store(
    store: AppendOnlyStore, initial_state_ref: str, *, episode_id: str | None = None
) -> dict[str, Any]:
    """Resolve an initial state and replay its episode's durable events."""

    resolver = ArtifactReferenceResolver(store)
    initial = _artifact(resolver, initial_state_ref, "canonical-state")
    checked_initial = validate_contract(
        initial, "canonical-state.schema.json", "initial canonical state"
    )
    selected_episode = episode_id or checked_initial["episode_id"]
    if checked_initial["episode_id"] != selected_episode:
        raise ReplayVerificationError("initial state belongs to a different episode")
    events = _episode_events(store, selected_episode)
    transitions = [event for event in events if event["event_type"] == "STATE_TRANSITION"]
    return replay_events(checked_initial, transitions)


def verify_episode(
    store: AppendOnlyStore,
    episode_ref: str,
    initial_state_ref: str,
    recorded_state_ref: str,
) -> VerificationReport:
    """Verify INV-006/007/008/016 for one stored episode."""

    resolver = ArtifactReferenceResolver(store)
    episode = validate_contract(
        _artifact(resolver, episode_ref, "episode"),
        "episode.schema.json",
        "episode",
    )
    initial = validate_contract(
        _artifact(resolver, initial_state_ref, "canonical-state"),
        "canonical-state.schema.json",
        "initial canonical state",
    )
    episode_id = episode["episode_id"]
    terminal_ref = episode["steps"][-1]["canonical_state_ref"]["ref_id"]
    if recorded_state_ref != terminal_ref:
        raise ReplayVerificationError(
            "recorded state reference does not match the terminal trace-step state reference"
        )
    if initial["episode_id"] != episode_id:
        raise ReplayVerificationError(
            "INV-016: episode and initial state memberships differ"
        )

    # INV-015 first verifies every durable byte and event self-hash.  The
    # episode contract then narrows its hash domain to this episode's ordered
    # canonical JSONL subset, so unrelated episode appends cannot perturb it.
    store.verify_event_log()
    events = _episode_events(store, episode_id)
    log_hash = canonical_event_log_hash(events)
    if log_hash.lower() != episode["event_log_hash"].lower():
        raise ReplayVerificationError(
            "episode event-log hash does not match its ordered event subset"
        )
    trace_states = _verify_trace_steps(episode, resolver)
    recorded = trace_states[-1]
    transitions = [event for event in events if event["event_type"] == "STATE_TRANSITION"]
    replayed = replay_events(initial, transitions)
    replayed_bytes = canonical_state_bytes(replayed)
    if replayed_bytes != canonical_state_bytes(recorded):
        raise ReplayVerificationError(
            "INV-008: replayed state differs from the recorded canonical state"
        )
    return VerificationReport(
        episode_id=episode_id,
        event_count=len(events),
        trace_step_count=len(episode["steps"]),
        event_log_hash=log_hash,
        final_state_bytes=len(replayed_bytes),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conditional-autonomy-replay")
    commands = parser.add_subparsers(dest="command", required=True)

    replay = commands.add_parser("replay", help="replay a stored episode")
    replay.add_argument("store")
    replay.add_argument("initial_state_ref")
    replay.add_argument("--episode-id")

    diff = commands.add_parser("diff", help="find the first exact ledger-byte change")
    diff.add_argument("left")
    diff.add_argument("right")

    verify = commands.add_parser("verify", help="verify a stored episode replay")
    verify.add_argument("store")
    verify.add_argument("episode_ref")
    verify.add_argument("initial_state_ref")
    verify.add_argument("recorded_state_ref")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "replay":
            state = replay_from_store(
                AppendOnlyStore(args.store),
                args.initial_state_ref,
                episode_id=args.episode_id,
            )
            sys.stdout.buffer.write(canonical_state_bytes(state) + b"\n")
            return 0
        if args.command == "diff":
            difference = diff_ledger_files(args.left, args.right)
            if difference is None:
                print('{"equal":true}')
                return 0
            print(canonical_json_bytes({"equal": False, **asdict(difference)}).decode())
            return 1
        report = verify_episode(
            AppendOnlyStore(args.store),
            args.episode_ref,
            args.initial_state_ref,
            args.recorded_state_ref,
        )
        print(canonical_json_bytes(asdict(report)).decode())
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
