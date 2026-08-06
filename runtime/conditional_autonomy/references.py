"""Typed, fail-closed resolution of stored artifact references.

Contract schemas represent references either as stable-ID strings or as
objects containing ``ref_id`` and access/provenance metadata.  This module
adapts both real contract shapes to one internal resolution path.  ``INV-003``
assigns every artifact-reference failure to ``QUARANTINE``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .storage import AppendOnlyStore, ArtifactTypeMismatchError, IntegrityError


ARTIFACT_REFERENCE_INVARIANT = "INV-003"
ARTIFACT_REFERENCE_FAILURE_RESOLUTION = "QUARANTINE"


class ReferenceFailureCode(str, Enum):
    """Stable failure categories emitted by the typed resolver."""

    DANGLING_REFERENCE = "DANGLING_REFERENCE"
    WRONG_ARTIFACT_TYPE = "WRONG_ARTIFACT_TYPE"
    ARTIFACT_INTEGRITY_FAILURE = "ARTIFACT_INTEGRITY_FAILURE"
    MALFORMED_REFERENCE = "MALFORMED_REFERENCE"


@dataclass(frozen=True)
class ResolvedArtifact:
    """Verified content and the runtime type against which it was checked."""

    ref_id: str
    artifact_type: str
    content: Mapping[str, Any]


@dataclass(frozen=True)
class ReferenceFailure:
    """Fail-closed resolution prescribed by the deferred-invariant register."""

    ref_id: str | None
    expected_type: str | None
    code: ReferenceFailureCode
    detail: str
    invariant_id: str = ARTIFACT_REFERENCE_INVARIANT
    failure_resolution: str = ARTIFACT_REFERENCE_FAILURE_RESOLUTION


@dataclass(frozen=True)
class ReferenceResolution:
    """All-or-nothing result for an execution input's artifact references."""

    artifacts: tuple[ResolvedArtifact, ...] = ()
    failure: ReferenceFailure | None = None

    def __post_init__(self) -> None:
        if self.failure is not None and self.artifacts:
            raise ValueError("a failed resolution cannot expose partial artifacts")

    @property
    def succeeded(self) -> bool:
        return self.failure is None


class ArtifactReferenceResolver:
    """Resolve declared artifact types through a verified append-only store."""

    def __init__(self, store: AppendOnlyStore) -> None:
        self._store = store

    def resolve(self, ref_id: object, expected_type: object) -> ReferenceResolution:
        """Resolve a normalized stable-ID string against its declared type."""

        normalized, failure = self._normalize_string(ref_id, expected_type)
        if failure is not None:
            return ReferenceResolution(failure=failure)
        return self._resolve_normalized(*normalized)

    def resolve_string_reference(
        self, reference: object, expected_type: object
    ) -> ReferenceResolution:
        """Resolve a schema field whose reference representation is a string."""

        return self.resolve(reference, expected_type)

    def resolve_object_reference(
        self, reference: object, expected_type: object
    ) -> ReferenceResolution:
        """Resolve a schema reference object containing a ``ref_id`` member."""

        normalized, failure = self._normalize_object(reference, expected_type)
        if failure is not None:
            return ReferenceResolution(failure=failure)
        return self._resolve_normalized(*normalized)

    def resolve_all(
        self, references: Iterable[tuple[object, object]] | object
    ) -> ReferenceResolution:
        """Resolve real string/object reference values without exposing partials.

        Each input is ``(schema_reference_value, expected_artifact_type)``.  A
        mapping uses the contract's ``ref_id`` member; a string is already the
        normalized ID.  Malformed batch members fail closed.
        """

        if not isinstance(references, Iterable):
            return self._failed(
                None,
                None,
                ReferenceFailureCode.MALFORMED_REFERENCE,
                "reference batch must be iterable",
            )
        resolved: list[ResolvedArtifact] = []
        for item in references:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                return self._failed(
                    None,
                    None,
                    ReferenceFailureCode.MALFORMED_REFERENCE,
                    "each batch member must contain a reference value and expected type",
                )
            reference, expected_type = item
            if isinstance(reference, Mapping):
                normalized, failure = self._normalize_object(reference, expected_type)
            else:
                normalized, failure = self._normalize_string(reference, expected_type)
            if failure is not None:
                return ReferenceResolution(failure=failure)
            outcome = self._resolve_normalized(*normalized)
            if not outcome.succeeded:
                return outcome
            resolved.extend(outcome.artifacts)
        return ReferenceResolution(artifacts=tuple(resolved))

    def _resolve_normalized(
        self, ref_id: str, expected_type: str
    ) -> ReferenceResolution:
        try:
            content = self._store.get_artifact(ref_id, expected_type=expected_type)
        except KeyError:
            return self._failed(
                ref_id,
                expected_type,
                ReferenceFailureCode.DANGLING_REFERENCE,
                f"artifact {ref_id!r} does not exist",
            )
        except ArtifactTypeMismatchError as exc:
            return self._failed(
                ref_id,
                expected_type,
                ReferenceFailureCode.WRONG_ARTIFACT_TYPE,
                str(exc),
            )
        except IntegrityError as exc:
            return self._failed(
                ref_id,
                expected_type,
                ReferenceFailureCode.ARTIFACT_INTEGRITY_FAILURE,
                str(exc),
            )
        return ReferenceResolution(
            artifacts=(
                ResolvedArtifact(
                    ref_id=ref_id, artifact_type=expected_type, content=content
                ),
            )
        )

    @classmethod
    def _normalize_string(
        cls, reference: object, expected_type: object
    ) -> tuple[tuple[str, str] | None, ReferenceFailure | None]:
        if not isinstance(reference, str) or not reference:
            return None, cls._failure(
                reference if isinstance(reference, str) else None,
                expected_type if isinstance(expected_type, str) else None,
                ReferenceFailureCode.MALFORMED_REFERENCE,
                "string reference must be a non-empty string",
            )
        return cls._normalize_type(reference, expected_type)

    @classmethod
    def _normalize_object(
        cls, reference: object, expected_type: object
    ) -> tuple[tuple[str, str] | None, ReferenceFailure | None]:
        if not isinstance(reference, Mapping):
            return None, cls._failure(
                None,
                expected_type if isinstance(expected_type, str) else None,
                ReferenceFailureCode.MALFORMED_REFERENCE,
                "object reference must be a mapping containing ref_id",
            )
        ref_id = reference.get("ref_id")
        if not isinstance(ref_id, str) or not ref_id:
            return None, cls._failure(
                ref_id if isinstance(ref_id, str) else None,
                expected_type if isinstance(expected_type, str) else None,
                ReferenceFailureCode.MALFORMED_REFERENCE,
                "object reference ref_id must be a non-empty string",
            )
        return cls._normalize_type(ref_id, expected_type)

    @classmethod
    def _normalize_type(
        cls, ref_id: str, expected_type: object
    ) -> tuple[tuple[str, str] | None, ReferenceFailure | None]:
        if not isinstance(expected_type, str) or not expected_type:
            return None, cls._failure(
                ref_id,
                expected_type if isinstance(expected_type, str) else None,
                ReferenceFailureCode.MALFORMED_REFERENCE,
                "expected artifact type must be a non-empty string",
            )
        return (ref_id, expected_type), None

    @staticmethod
    def _failure(
        ref_id: str | None,
        expected_type: str | None,
        code: ReferenceFailureCode,
        detail: str,
    ) -> ReferenceFailure:
        return ReferenceFailure(
            ref_id=ref_id,
            expected_type=expected_type,
            code=code,
            detail=detail,
        )

    @classmethod
    def _failed(
        cls,
        ref_id: str | None,
        expected_type: str | None,
        code: ReferenceFailureCode,
        detail: str,
    ) -> ReferenceResolution:
        return ReferenceResolution(
            failure=cls._failure(ref_id, expected_type, code, detail)
        )
