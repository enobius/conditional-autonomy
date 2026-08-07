"""Fail-closed ingest validators for the deferred-invariant register.

The validators in this module are deliberately thin adapters over the Stage 1
runtime boundaries. Reference resolution stays in ``ArtifactReferenceResolver``;
durable uniqueness and integrity are read through ``AppendOnlyStore``; and
policy-input checking accepts the projector's inseparable observation/lineage
aggregate rather than an untrusted detached observation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .preexecution import InvariantDisposition, ValidationOutcome, Verdict
from .projection import (
    POLICY_VISIBLE,
    AccessBoundaryError,
    ObservationProjection,
    ProjectionLineageEntry,
    ProjectionSourceError,
    _assert_policy_visible,
    _resolve_pointer,
)
from .references import ArtifactReferenceResolver
from .storage import AppendOnlyStore, IntegrityError, canonical_content_hash, canonical_json_bytes


INGEST_FAILURE_RESOLUTION = InvariantDisposition.QUARANTINE


def _pass(invariant_id: str, validator: str) -> ValidationOutcome:
    return ValidationOutcome(invariant_id, validator, Verdict.PASS, None)


def _fail(invariant_id: str, validator: str, *codes: str) -> ValidationOutcome:
    return ValidationOutcome(
        invariant_id,
        validator,
        Verdict.FAIL,
        INGEST_FAILURE_RESOLUTION,
        tuple(sorted(set(codes))) or ("MALFORMED_CONTEXT",),
    )


def _sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return None


def artifact_reference_check(
    resolver: object,
    references: Iterable[tuple[object, object]] | object,
) -> ValidationOutcome:
    """Enforce INV-003 through the typed, integrity-checking resolver."""

    invariant, validator = "INV-003", "artifact_reference_check"
    if not isinstance(resolver, ArtifactReferenceResolver):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    try:
        normalized_references = tuple(references)  # type: ignore[arg-type]
    except TypeError:
        return _fail(invariant, validator, "MALFORMED_REFERENCES")
    except Exception:
        return _fail(invariant, validator, "REFERENCE_ITERATOR_FAILURE")
    try:
        result = resolver.resolve_all(normalized_references)
    except OSError:
        return _fail(invariant, validator, "REFERENCE_STORE_UNAVAILABLE")
    except Exception:
        return _fail(invariant, validator, "REFERENCE_BOUNDARY_FAILURE")
    if result.succeeded:
        return _pass(invariant, validator)
    assert result.failure is not None
    return _fail(invariant, validator, result.failure.code.value)


def event_id_uniqueness_check(
    store: object, candidate_event_id: object
) -> ValidationOutcome:
    """Enforce INV-005 against a completely verified durable event log."""

    invariant, validator = "INV-005", "event_id_uniqueness_check"
    if not isinstance(store, AppendOnlyStore) or not isinstance(candidate_event_id, str) or not candidate_event_id:
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    try:
        existing_ids = {event["event_id"] for event in store.events()}
    except OSError:
        return _fail(invariant, validator, "EVENT_STORE_UNAVAILABLE")
    except (IntegrityError, KeyError, TypeError, ValueError):
        return _fail(invariant, validator, "EVENT_LOG_INTEGRITY_FAILURE")
    except Exception:
        return _fail(invariant, validator, "EVENT_STORE_BOUNDARY_FAILURE")
    if candidate_event_id in existing_ids:
        return _fail(invariant, validator, "DUPLICATE_EVENT_ID")
    return _pass(invariant, validator)


def policy_input_leakage_check(
    projection: object, canonical_state: object
) -> ValidationOutcome:
    """Enforce INV-014, including complete bijective projection lineage.

    Every output fact must have exactly one lineage member, and no lineage
    member may target anything else. Each member is checked against the actual
    canonical-state source, episode, state version, and effective access class.
    """

    invariant, validator = "INV-014", "policy_input_leakage_check"
    if not isinstance(projection, ObservationProjection):
        return _fail(invariant, validator, "MALFORMED_PROJECTION_AGGREGATE")
    try:
        state = validate_contract(canonical_state, "canonical-state.schema.json", "projection source state")
        observation = validate_contract(
            projection.observation,
            "access-scoped-observation.schema.json",
            "policy input observation",
        )
    except ContractValidationError:
        return _fail(invariant, validator, "CONTRACT_VIOLATION")

    facts = observation.get("visible_facts")
    if not isinstance(facts, list):  # defended by the public contract
        return _fail(invariant, validator, "CONTRACT_VIOLATION")
    expected_paths = {f"/visible_facts/{index}" for index in range(len(facts))}
    entries_by_output: dict[str, list[ProjectionLineageEntry]] = {}
    codes: list[str] = []
    if observation["episode_id"] != state["episode_id"]:
        codes.append("STALE_OBSERVATION_EPISODE")
    if observation["state_version"] != state["state_version"]:
        codes.append("STALE_OBSERVATION_VERSION")
    for entry in projection.lineage:
        if not isinstance(entry, ProjectionLineageEntry):
            codes.append("MALFORMED_LINEAGE")
            continue
        entries_by_output.setdefault(entry.output_path, []).append(entry)

    actual_paths = set(entries_by_output)
    if expected_paths - actual_paths:
        codes.append("MISSING_LINEAGE")
    if actual_paths - expected_paths:
        codes.append("EXTRA_LINEAGE")
    if any(len(entries) != 1 for entries in entries_by_output.values()):
        codes.append("DUPLICATE_LINEAGE")

    for index, fact in enumerate(facts):
        entries = entries_by_output.get(f"/visible_facts/{index}", ())
        if len(entries) != 1:
            continue
        entry = entries[0]
        if (
            entry.source_episode_id != observation["episode_id"]
            or entry.source_episode_id != state["episode_id"]
        ):
            codes.append("STALE_LINEAGE_EPISODE")
        if (
            entry.source_state_version != observation["state_version"]
            or entry.source_state_version != state["state_version"]
        ):
            codes.append("STALE_LINEAGE_VERSION")
        if entry.source_access_class != POLICY_VISIBLE:
            codes.append("PROTECTED_LINEAGE_SOURCE")
        try:
            source = _resolve_pointer(state, entry.source_path)
            _assert_policy_visible(source, entry.source_path)
        except (ProjectionSourceError, AccessBoundaryError):
            codes.append("INVALID_LINEAGE_SOURCE")
            continue
        if canonical_json_bytes(source) != canonical_json_bytes(fact):
            codes.append("LINEAGE_VALUE_MISMATCH")
    try:
        for index, fact in enumerate(facts):
            _assert_policy_visible(fact, f"/visible_facts/{index}")
    except AccessBoundaryError:
        codes.append("PROTECTED_POLICY_INPUT")
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


def artifact_integrity_check(
    subject: object,
    artifact_ids: Iterable[str] | object = (),
    *,
    expected_event_log_hash: str | None = None,
) -> ValidationOutcome:
    """Enforce INV-015 for a durable store or the registered fixture envelope."""

    invariant, validator = "INV-015", "artifact_integrity_check"
    if isinstance(subject, AppendOnlyStore):
        if isinstance(artifact_ids, (str, bytes)):
            return _fail(invariant, validator, "MALFORMED_CONTEXT")
        try:
            ids = tuple(artifact_ids)
            if not all(isinstance(item, str) and item for item in ids):
                raise ValueError
        except (TypeError, ValueError):
            return _fail(invariant, validator, "MALFORMED_ARTIFACT_INVENTORY")
        except Exception:
            return _fail(invariant, validator, "ARTIFACT_INVENTORY_BOUNDARY_FAILURE")
        try:
            inventory = subject.verify_artifact_inventory()
            if any(artifact_id not in inventory for artifact_id in ids):
                return _fail(invariant, validator, "REQUIRED_ARTIFACT_MISSING")
            subject.verify_event_log(expected_event_log_hash)
        except OSError:
            return _fail(invariant, validator, "ARTIFACT_STORE_UNAVAILABLE")
        except (IntegrityError, KeyError, TypeError, ValueError):
            return _fail(invariant, validator, "STORED_INTEGRITY_FAILURE")
        except Exception:
            return _fail(invariant, validator, "ARTIFACT_STORE_BOUNDARY_FAILURE")
        return _pass(invariant, validator)

    if not isinstance(subject, Mapping):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    artifacts = _sequence(subject.get("artifacts"))
    event_log = subject.get("event_log")
    if (
        subject.get("canonicalization") != "STAGE1_CANONICAL_JSON_V1"
        or artifacts is None
        or not isinstance(event_log, Mapping)
        or event_log.get("serialization") != "CANONICAL_JSONL_WITH_FINAL_NEWLINE"
    ):
        return _fail(invariant, validator, "MALFORMED_CONTEXT")
    codes: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("content"), Mapping):
            codes.append("MALFORMED_ARTIFACT")
            continue
        declared = artifact.get("content_hash")
        try:
            actual = canonical_content_hash(artifact["content"])
        except (TypeError, ValueError):
            codes.append("MALFORMED_ARTIFACT")
            continue
        if not _hashes_equal(declared, actual):
            codes.append("ARTIFACT_HASH_MISMATCH")
    events = _sequence(event_log.get("events"))
    if events is None or not all(isinstance(event, Mapping) for event in events):
        codes.append("MALFORMED_EVENT_LOG")
    else:
        try:
            serialized = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        except (TypeError, ValueError):
            codes.append("MALFORMED_EVENT_LOG")
        else:
            actual_log_hash = "sha256:" + hashlib.sha256(serialized).hexdigest()
            if not _hashes_equal(event_log.get("integrity_hash"), actual_log_hash):
                codes.append("EVENT_LOG_HASH_MISMATCH")
    return _fail(invariant, validator, *codes) if codes else _pass(invariant, validator)


def _hashes_equal(left: object, right: str) -> bool:
    if not isinstance(left, str):
        return False
    return left.removeprefix("sha256:").lower() == right.removeprefix("sha256:").lower()


INGEST_VALIDATORS = {
    "artifact_reference_check": artifact_reference_check,
    "event_id_uniqueness_check": event_id_uniqueness_check,
    "policy_input_leakage_check": policy_input_leakage_check,
    "artifact_integrity_check": artifact_integrity_check,
}
