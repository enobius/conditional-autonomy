"""Append-only artifact and event persistence.

Hash domains are deliberately small and explicit:

* canonical JSON is UTF-8 encoded, key-sorted, compact JSON with non-finite
  numbers rejected;
* a document's content hash covers that canonical representation after
  removing only its top-level ``content_hash`` field, avoiding a self-hash;
* the event-log hash covers the exact canonical JSONL bytes on disk, including
  the trailing newline for each event.

Writes are staged in the destination directory, flushed to durable storage,
and atomically installed with ``os.replace``. A failed write therefore leaves
the last complete store version visible rather than a partial record.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    """Base class for persistence failures."""


class IntegrityError(StorageError):
    """Stored bytes or a declared hash do not match canonical content."""


class ArtifactTypeMismatchError(IntegrityError):
    """An artifact exists but does not have the caller's declared type."""

    def __init__(self, artifact_id: str, actual_type: str, expected_type: str) -> None:
        self.artifact_id = artifact_id
        self.actual_type = actual_type
        self.expected_type = expected_type
        super().__init__(
            f"artifact {artifact_id!r} has type {actual_type!r}, "
            f"not {expected_type!r}"
        )


class DuplicateEventIdError(StorageError):
    """An event ID already exists in the durable event log."""


class DuplicateArtifactIdError(StorageError):
    """An artifact ID already exists in the append-only artifact store."""


class PromotionBoundaryError(StorageError):
    """A domain artifact attempted to bypass its mandatory promotion gate."""


_GENERATED_PAIR_ARTIFACT_TYPES = frozenset(
    {"generated-instance", "instance-manifest"}
)
_GENERATED_PAIR_ID_PREFIXES = ("instance:", "manifest:")


_ROOT_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.RLock] = {}


def _process_lock_for(root: Path) -> threading.RLock:
    """Return the process-local half of a lock shared by equivalent roots."""

    key = root.resolve()
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _locked_file(path: Path):
    """Hold an exclusive advisory lock on byte zero of ``path``.

    ``flock`` and ``msvcrt.locking`` locks are released by the operating system
    if a writer exits unexpectedly. The process-local lock above also makes
    same-process behavior independent of platform-specific lock ownership
    semantics.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b", buffering=0) as lock_file:
        if lock_file.seek(0, os.SEEK_END) == 0:
            lock_file.write(b"\0")
            os.fsync(lock_file.fileno())
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    time.sleep(0.01)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def canonical_json_bytes(value: Any) -> bytes:
    """Return the runtime's deterministic JSON representation of ``value``."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical-JSON serializable: {exc}") from exc
    return encoded.encode("utf-8")


def _hash_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_persisted_json(content: bytes, description: str) -> Any:
    """Parse persisted bytes as strict JSON and normalize failures."""

    try:
        return json.loads(content, parse_constant=_reject_nonfinite_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise IntegrityError(f"{description} is not valid strict JSON") from exc


def _hash_value(hash_value: str) -> str:
    if not isinstance(hash_value, str):
        raise IntegrityError("declared content hash must be a string")
    return hash_value.removeprefix("sha256:").lower()


def _content_hash_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(content))
    payload.pop("content_hash", None)
    return payload


def canonical_content_hash(content: Mapping[str, Any]) -> str:
    """Hash a contract object, excluding its top-level self-hash field."""

    if not isinstance(content, Mapping):
        raise TypeError("content must be a mapping")
    return _hash_bytes(canonical_json_bytes(_content_hash_payload(content)))


def with_content_hash(content: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached contract object carrying its canonical self-hash."""

    result = deepcopy(dict(content))
    result["content_hash"] = canonical_content_hash(result)
    return result


def _verify_declared_content_hash(
    content: Mapping[str, Any], *, required: bool = True
) -> str:
    declared = content.get("content_hash")
    if declared is None:
        if required:
            raise IntegrityError("content_hash is required for stored contract content")
        return canonical_content_hash(content)
    actual = canonical_content_hash(content)
    if _hash_value(declared) != _hash_value(actual):
        raise IntegrityError(
            f"content hash mismatch: declared {declared!r}, computed {actual!r}"
        )
    return actual


class AppendOnlyStore:
    """Filesystem-backed append-only storage for artifacts and events."""

    _EVENT_LOG_NAME = "events.jsonl"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self._artifacts = self.root / "artifacts"
        self._event_log = self.root / self._EVENT_LOG_NAME
        self._lock_file = self.root / ".store.lock"
        self._process_lock = _process_lock_for(self.root)
        self._artifacts.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        """Serialize a complete storage transaction for this shared root."""

        with self._process_lock:
            with _locked_file(self._lock_file):
                yield

    def put_artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        content: Mapping[str, Any],
    ) -> str:
        """Atomically add immutable, self-hashed contract content."""

        return self.put_artifacts_atomic(((artifact_id, artifact_type, content),))[
            artifact_id
        ]

    def put_artifacts_atomic(
        self,
        artifacts: Iterable[tuple[str, str, Mapping[str, Any]]] | object,
        *,
        _after_publish: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """Publish a batch as one lock-isolated all-or-nothing transaction.

        Every record is validated and staged before the first destination is
        installed. Store readers use the same cross-process lock, so they see
        either the old inventory or the complete batch. If publishing raises,
        every destination installed by this transaction is removed before the
        lock is released. ``_after_publish`` is a private fault-injection seam.
        """

        return self._put_artifacts_atomic(
            artifacts,
            _after_publish=_after_publish,
        )

    def _put_generated_pair_atomic(
        self,
        instance_ref: str,
        instance: Mapping[str, Any],
        manifest_ref: str,
        manifest: Mapping[str, Any],
        *,
        _after_publish: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """Publish one generated pair through the fixed INV-013 gate."""

        from .split_hygiene import _generation_pair_store_preflight

        artifacts = (
            (instance_ref, "generated-instance", instance),
            (manifest_ref, "instance-manifest", manifest),
        )

        def mandatory_preflight(records: tuple[Mapping[str, Any], ...]) -> None:
            _generation_pair_store_preflight(
                records,
                instance_ref,
                instance,
                manifest_ref,
                manifest,
            )

        return self._put_artifacts_atomic(
            artifacts,
            _preflight=mandatory_preflight,
            _allow_generated_pair=True,
            _after_publish=_after_publish,
        )

    def _put_artifacts_atomic(
        self,
        artifacts: Iterable[tuple[str, str, Mapping[str, Any]]] | object,
        *,
        _preflight: Callable[[tuple[Mapping[str, Any], ...]], None] | None = None,
        _allow_generated_pair: bool = False,
        _after_publish: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """Internal transaction primitive; public callers cannot select gates."""

        try:
            items = tuple(artifacts)  # type: ignore[arg-type]
        except Exception as exc:
            raise ValueError("artifact batch must be a finite iterable") from exc
        prepared: list[tuple[str, Path, bytes, str]] = []
        seen_ids: set[str] = set()
        artifact_types: list[str] = []
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 3:
                raise ValueError("each artifact batch member must contain ID, type, content")
            artifact_id, artifact_type, content = item
            self._require_identifier("artifact_id", artifact_id)
            self._require_identifier("artifact_type", artifact_type)
            artifact_types.append(artifact_type)
            if not isinstance(content, Mapping):
                raise TypeError("artifact content must be an object")
            if artifact_id in seen_ids:
                raise DuplicateArtifactIdError(
                    f"duplicate artifact ID within batch: {artifact_id}"
                )
            seen_ids.add(artifact_id)
            content_copy = deepcopy(dict(content))
            content_hash = _verify_declared_content_hash(content_copy, required=False)
            record = {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "content": content_copy,
                "content_hash": content_hash,
            }
            prepared.append(
                (
                    artifact_id,
                    self._artifact_path(artifact_id),
                    canonical_json_bytes(record),
                    content_hash,
                )
            )

        uses_reserved_boundary = any(
            artifact_type in _GENERATED_PAIR_ARTIFACT_TYPES
            or artifact_id.startswith(_GENERATED_PAIR_ID_PREFIXES)
            for artifact_id, artifact_type, _ in items
        )
        if uses_reserved_boundary and (
            not _allow_generated_pair
            or _preflight is None
            or len(items) != 2
            or set(artifact_types) != _GENERATED_PAIR_ARTIFACT_TYPES
            or not any(item[0].startswith("instance:") for item in items)
            or not any(item[0].startswith("manifest:") for item in items)
        ):
            raise PromotionBoundaryError(
                "generated instance pairs require the split-hygiene promotion gate"
            )

        staged: list[tuple[str, Path, Path]] = []
        published: list[Path] = []
        with self._locked():
            # A batch must not extend an already-corrupt store. This check is
            # inside the same cross-process transaction as collision preflight
            # and publication, so the verified inventory cannot change between
            # validation and commit.
            inventory = self._verify_artifact_inventory_unlocked()
            if _preflight is not None:
                _preflight(
                    tuple(
                        deepcopy(self._read_artifact_record(artifact_id))
                        for artifact_id in inventory
                    )
                )
            for artifact_id, destination, _, _ in prepared:
                if destination.exists():
                    raise DuplicateArtifactIdError(
                        f"artifact ID already exists: {artifact_id}"
                    )
            try:
                for artifact_id, destination, record_bytes, _ in prepared:
                    staged.append(
                        (artifact_id, destination, self._stage_content(destination, record_bytes))
                    )
                for artifact_id, destination, temporary_path in staged:
                    os.replace(temporary_path, destination)
                    published.append(destination)
                    self._sync_directory(destination.parent)
                    if _after_publish is not None:
                        _after_publish(artifact_id)
                # Re-read the committed bytes before releasing the lock. Any
                # publication-time corruption rolls back only this batch.
                self._verify_artifact_inventory_unlocked()
            except BaseException:
                for destination in reversed(published):
                    destination.unlink(missing_ok=True)
                if published:
                    self._sync_directory(self._artifacts)
                raise
            finally:
                for _, _, temporary_path in staged:
                    temporary_path.unlink(missing_ok=True)
        return {artifact_id: content_hash for artifact_id, _, _, content_hash in prepared}

    def get_artifact(
        self, artifact_id: str, *, expected_type: str | None = None
    ) -> dict[str, Any]:
        """Load an artifact only after its ID, type, bytes, and hashes verify."""

        with self._locked():
            record = self._read_artifact_record(artifact_id)
        if expected_type is not None and record["artifact_type"] != expected_type:
            raise ArtifactTypeMismatchError(
                artifact_id, record["artifact_type"], expected_type
            )
        return deepcopy(record["content"])

    def verify_artifact(self, artifact_id: str) -> str:
        """Verify an artifact and return its normalized canonical hash."""

        with self._locked():
            return self._read_artifact_record(artifact_id)["content_hash"]

    def verify_artifact_inventory(self) -> dict[str, str]:
        """Verify and inventory every file in the append-only artifact store.

        Inventory is store-wide: an unexpected directory entry, malformed
        filename, invalid envelope, path/ID mismatch, noncanonical JSON, or
        content-hash mismatch fails the complete operation. The returned map
        is inserted in deterministic path order and contains detached IDs and
        normalized hashes only.
        """

        with self._locked():
            return self._verify_artifact_inventory_unlocked()

    def _verify_artifact_inventory_unlocked(self) -> dict[str, str]:
        """Verify the inventory while the caller owns ``_locked``."""

        inventory: dict[str, str] = {}
        for path in sorted(self._artifacts.iterdir(), key=lambda item: item.name):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix != ".json"
                or len(path.stem) != 64
                or any(character not in "0123456789abcdef" for character in path.stem)
            ):
                raise IntegrityError(f"unexpected artifact-store entry: {path.name!r}")
            stored_bytes = path.read_bytes()
            record = _load_persisted_json(stored_bytes, f"artifact file {path.name!r}")
            if not isinstance(record, dict):
                raise IntegrityError(f"artifact file {path.name!r} is not an envelope")
            artifact_id = record.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id:
                raise IntegrityError(f"artifact file {path.name!r} has an invalid ID")
            if path != self._artifact_path(artifact_id):
                raise IntegrityError(
                    f"artifact file {path.name!r} does not match ID {artifact_id!r}"
                )
            verified = self._verify_artifact_record_bytes(artifact_id, stored_bytes)
            if artifact_id in inventory:
                raise IntegrityError(f"duplicate artifact ID in store: {artifact_id!r}")
            inventory[artifact_id] = verified["content_hash"]
        return inventory

    def append_event(
        self,
        event: Mapping[str, Any],
        *,
        _before_replace: Callable[[], None] | None = None,
    ) -> str:
        """Atomically append a self-hashed event and return the new log hash.

        ``_before_replace`` is a private fault-injection seam used to prove that
        interruption before the commit point cannot expose a partial event.
        """

        event_copy = deepcopy(dict(event))
        event_id = event_copy.get("event_id")
        self._require_identifier("event_id", event_id)
        _verify_declared_content_hash(event_copy)
        event_bytes = canonical_json_bytes(event_copy) + b"\n"

        with self._locked():
            existing_bytes, existing_events = self._read_verified_log()
            # Duplicate detection intentionally inspects the durable log while
            # holding the write lock, immediately before staging replacement.
            if any(stored["event_id"] == event_id for stored in existing_events):
                raise DuplicateEventIdError(f"event ID already exists: {event_id}")
            new_bytes = existing_bytes + event_bytes
            self._atomic_replace(
                self._event_log, new_bytes, before_replace=_before_replace
            )
        return _hash_bytes(new_bytes)

    def events(self) -> list[dict[str, Any]]:
        """Return verified events in durable order."""

        with self._locked():
            _, events = self._read_verified_log()
        return deepcopy(events)

    def event_log_hash(self) -> str:
        """Return the hash of the exact verified canonical event-log bytes."""

        with self._locked():
            content, _ = self._read_verified_log()
        return _hash_bytes(content)

    def verify_event_log(self, expected_hash: str | None = None) -> str:
        """Verify canonical bytes, event hashes, unique IDs, and an optional hash."""

        actual = self.event_log_hash()
        if expected_hash is not None and _hash_value(expected_hash) != _hash_value(actual):
            raise IntegrityError(
                f"event-log hash mismatch: expected {expected_hash!r}, computed {actual!r}"
            )
        return actual

    @staticmethod
    def _require_identifier(name: str, value: Any) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")

    def _artifact_path(self, artifact_id: str) -> Path:
        safe_name = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()
        return self._artifacts / f"{safe_name}.json"

    def _read_artifact_record(self, artifact_id: str) -> dict[str, Any]:
        destination = self._artifact_path(artifact_id)
        try:
            stored_bytes = destination.read_bytes()
        except FileNotFoundError:
            raise KeyError(artifact_id) from None
        return self._verify_artifact_record_bytes(artifact_id, stored_bytes)

    @staticmethod
    def _verify_artifact_record_bytes(
        artifact_id: str, stored_bytes: bytes
    ) -> dict[str, Any]:
        """Verify one already-read envelope without changing its hash domain."""

        record = _load_persisted_json(stored_bytes, f"artifact {artifact_id!r}")
        if not isinstance(record, dict) or set(record) != {
            "artifact_id",
            "artifact_type",
            "content",
            "content_hash",
        }:
            raise IntegrityError(f"artifact {artifact_id!r} has an invalid store envelope")
        if stored_bytes != canonical_json_bytes(record):
            raise IntegrityError(f"artifact {artifact_id!r} is not canonically serialized")
        if record["artifact_id"] != artifact_id:
            raise IntegrityError(f"artifact path does not match ID {artifact_id!r}")
        if not isinstance(record["artifact_type"], str) or not record["artifact_type"]:
            raise IntegrityError(f"artifact {artifact_id!r} has an invalid type")
        if not isinstance(record["content"], dict):
            raise IntegrityError(f"artifact {artifact_id!r} content is not an object")
        actual = _verify_declared_content_hash(record["content"], required=False)
        if _hash_value(record["content_hash"]) != _hash_value(actual):
            raise IntegrityError(f"artifact {artifact_id!r} envelope hash is invalid")
        record["content_hash"] = actual
        return record

    def _read_verified_log(self) -> tuple[bytes, list[dict[str, Any]]]:
        if not self._event_log.exists():
            return b"", []
        stored_bytes = self._event_log.read_bytes()
        if stored_bytes and not stored_bytes.endswith(b"\n"):
            raise IntegrityError("event log ends with a partial record")
        events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for line_number, line in enumerate(stored_bytes.splitlines(), start=1):
            event = _load_persisted_json(line, f"event log line {line_number}")
            if not isinstance(event, dict):
                raise IntegrityError(f"event log line {line_number} is not an object")
            if line != canonical_json_bytes(event):
                raise IntegrityError(f"event log line {line_number} is not canonical JSON")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise IntegrityError(
                    f"event log line {line_number} has an invalid event_id"
                )
            if event_id in seen_ids:
                raise IntegrityError(f"duplicate durable event ID: {event_id}")
            seen_ids.add(event_id)
            _verify_declared_content_hash(event)
            events.append(event)
        return stored_bytes, events

    @staticmethod
    def _atomic_replace(
        destination: Path,
        content: bytes,
        *,
        before_replace: Callable[[], None] | None = None,
    ) -> None:
        temporary_path = AppendOnlyStore._stage_content(destination, content)
        try:
            if before_replace is not None:
                before_replace()
            os.replace(temporary_path, destination)
            AppendOnlyStore._sync_directory(destination.parent)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _stage_content(destination: Path, content: bytes) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        return temporary_path

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        """Persist a replacement's directory entry where the OS supports it."""

        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
