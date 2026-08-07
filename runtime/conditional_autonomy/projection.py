"""Fail-closed projection from canonical state to policy-visible observations.

The observation contract intentionally has no lineage field. This module
therefore returns lineage beside the schema-valid observation. A projection
selects complete visible-fact objects by JSON Pointer; it does not accept an
arbitrary transform capable of silently declassifying protected content.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .storage import canonical_json_bytes


POLICY_VISIBLE = "POLICY_VISIBLE"
PROTECTED_ACCESS_CLASSES = frozenset(
    {
        "PRIVATE_ENVIRONMENT",
        "EVALUATOR_ONLY",
        "VALIDATOR_VISIBLE",
        "SUPERVISOR_VISIBLE",
    }
)


class ProjectionError(RuntimeError):
    """Base class for fail-closed observation projection errors."""


class ProjectionSourceError(ProjectionError):
    """A projection source is missing, malformed, or ambiguous."""


class AccessBoundaryError(ProjectionError):
    """A protected access label would cross into policy-visible output."""


@dataclass(frozen=True)
class ProjectionLineageEntry:
    """One explicit canonical-state source to observation-output mapping."""

    output_path: str
    source_path: str
    source_episode_id: str
    source_state_version: int
    source_access_class: str = POLICY_VISIBLE


@dataclass(frozen=True, init=False)
class ObservationProjection:
    """A schema-valid observation and its inseparable projection lineage.

    The observation is held as immutable canonical bytes. Each property access
    returns a new JSON object so callers cannot invalidate the checked aggregate
    by mutating a retained dictionary.
    """

    _observation_bytes: bytes
    lineage: tuple[ProjectionLineageEntry, ...]

    def __init__(
        self,
        observation: Mapping[str, Any],
        lineage: Iterable[ProjectionLineageEntry],
    ) -> None:
        object.__setattr__(self, "_observation_bytes", canonical_json_bytes(observation))
        object.__setattr__(self, "lineage", tuple(lineage))

    @property
    def observation(self) -> dict[str, Any]:
        """Return a detached copy of the validated observation."""

        return json.loads(self._observation_bytes)


def _decode_pointer(pointer: object) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise ProjectionSourceError("source path must be a non-root JSON Pointer")
    tokens: list[str] = []
    for raw_token in pointer[1:].split("/"):
        index = 0
        while index < len(raw_token):
            if raw_token[index] == "~":
                if index + 1 >= len(raw_token) or raw_token[index + 1] not in "01":
                    raise ProjectionSourceError(
                        f"source path contains invalid JSON Pointer escaping: {pointer!r}"
                    )
                index += 2
            else:
                index += 1
        tokens.append(raw_token.replace("~1", "/").replace("~0", "~"))
    return tokens


def _assert_mapping_access(
    value: Mapping[str, Any], source_path: str, location: str
) -> None:
    access_class = value.get("access_class")
    if access_class is not None and access_class != POLICY_VISIBLE:
        raise AccessBoundaryError(
            f"source {source_path!r} traverses non-policy access class "
            f"{access_class!r} at {location or '/'}"
        )


def _resolve_pointer(document: Mapping[str, Any], pointer: str) -> Any:
    current: Any = document
    traversed = ""
    for token in _decode_pointer(pointer):
        if isinstance(current, Mapping):
            _assert_mapping_access(current, pointer, traversed)
            if token not in current:
                raise ProjectionSourceError(f"source path does not exist: {pointer!r}")
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or not token.isascii() or not token.isdigit():
                raise ProjectionSourceError(f"source path has an invalid array index: {pointer!r}")
            index = int(token)
            if index >= len(current):
                raise ProjectionSourceError(f"source path does not exist: {pointer!r}")
            current = current[index]
        else:
            raise ProjectionSourceError(f"source path traverses a scalar: {pointer!r}")
        escaped = token.replace("~", "~0").replace("/", "~1")
        traversed = f"{traversed}/{escaped}"
    return current


def _assert_policy_visible(value: Any, source_path: str, relative_path: str = "") -> None:
    """Reject protected runtime labels anywhere in a selected fact."""

    if isinstance(value, Mapping):
        access_class = value.get("access_class")
        if access_class is not None and access_class != POLICY_VISIBLE:
            location = relative_path or "/"
            raise AccessBoundaryError(
                f"source {source_path!r} contains non-policy access class "
                f"{access_class!r} at {location}"
            )
        for key, member in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            _assert_policy_visible(member, source_path, f"{relative_path}/{escaped}")
    elif isinstance(value, list):
        for index, member in enumerate(value):
            _assert_policy_visible(member, source_path, f"{relative_path}/{index}")


def project_observation(
    canonical_state: Mapping[str, Any],
    *,
    observation_id: str,
    actor_id: str,
    source_paths: Iterable[str],
    goal_refs: Iterable[str],
    generated_at: Mapping[str, Any],
    context_budget_tokens: int | None = None,
) -> ObservationProjection:
    """Project selected policy-labelled facts without mutating any input.

    Each source path must resolve to a complete ``visible_facts`` member whose
    root ``access_class`` is ``POLICY_VISIBLE``. Selected objects and every
    nested access-labelled object are checked before output-schema validation.
    Duplicate paths and fact IDs are rejected so lineage is unambiguous.
    """

    try:
        state = validate_contract(canonical_state, "canonical-state.schema.json", "canonical state")
    except ContractValidationError as exc:
        raise ProjectionSourceError(str(exc)) from exc

    if isinstance(source_paths, (str, bytes)):
        raise ProjectionSourceError("source_paths must be an iterable of JSON Pointers")
    try:
        paths = tuple(source_paths)
    except TypeError as exc:
        raise ProjectionSourceError("source_paths must be iterable") from exc
    if any(not isinstance(path, str) for path in paths):
        raise ProjectionSourceError("every source path must be a JSON Pointer string")
    if len(set(paths)) != len(paths):
        raise ProjectionSourceError("source_paths must not contain duplicates")

    visible_facts: list[dict[str, Any]] = []
    lineage: list[ProjectionLineageEntry] = []
    fact_ids: set[str] = set()
    for index, source_path in enumerate(paths):
        source = _resolve_pointer(state, source_path)
        if not isinstance(source, Mapping):
            raise ProjectionSourceError(
                f"source path must resolve to a visible-fact object: {source_path!r}"
            )
        if source.get("access_class") != POLICY_VISIBLE:
            access_class = source.get("access_class")
            if access_class in PROTECTED_ACCESS_CLASSES:
                raise AccessBoundaryError(
                    f"source {source_path!r} has protected access class {access_class!r}"
                )
            raise ProjectionSourceError(
                f"source {source_path!r} must declare access_class {POLICY_VISIBLE!r}"
            )
        _assert_policy_visible(source, source_path)
        fact = deepcopy(dict(source))
        fact_id = fact.get("fact_id")
        if isinstance(fact_id, str) and fact_id in fact_ids:
            raise ProjectionSourceError(f"duplicate projected fact_id: {fact_id!r}")
        if isinstance(fact_id, str):
            fact_ids.add(fact_id)
        visible_facts.append(fact)
        lineage.append(
            ProjectionLineageEntry(
                output_path=f"/visible_facts/{index}",
                source_path=source_path,
                source_episode_id=state["episode_id"],
                source_state_version=state["state_version"],
            )
        )

    if isinstance(goal_refs, (str, bytes)):
        raise ProjectionSourceError("goal_refs must be an iterable of stable IDs")
    try:
        detached_goal_refs = deepcopy(list(goal_refs))
    except TypeError as exc:
        raise ProjectionSourceError("goal_refs must be iterable") from exc

    observation: dict[str, Any] = {
        "observation_id": observation_id,
        "episode_id": state["episode_id"],
        "state_version": state["state_version"],
        "actor_id": actor_id,
        "access_class": POLICY_VISIBLE,
        "visible_facts": visible_facts,
        "goal_refs": detached_goal_refs,
        "generated_at": deepcopy(generated_at),
    }
    if context_budget_tokens is not None:
        observation["context_budget_tokens"] = context_budget_tokens
    try:
        checked_observation = validate_contract(
            observation,
            "access-scoped-observation.schema.json",
            "projected observation",
        )
    except ContractValidationError as exc:
        raise ProjectionSourceError(str(exc)) from exc
    return ObservationProjection(
        observation=checked_observation,
        lineage=lineage,
    )
