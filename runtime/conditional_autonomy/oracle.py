"""Deterministic oracle user simulator with an INV-014-safe output boundary.

The simulator keeps its user model and private world state as immutable
canonical bytes. Answers are released only as complete policy-visible facts
through ``project_observation`` and are checked by ``policy_input_leakage_check``
before being returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
import threading
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .ingest import policy_input_leakage_check
from .projection import ObservationProjection, ProjectionError, project_observation
from .storage import canonical_json_bytes


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_RESPONSE_SLOT = "oracle_response"
_TEMPLATE_FAMILIES = {
    "template:p6-oracle": {
        "answer": (
            "The requested value is {value}.",
            "I can confirm {value}.",
            "For that fact: {value}.",
        ),
        "unknown": (
            "I cannot answer that fact.",
            "That fact is not available to me.",
            "I do not have an answer for that fact.",
        ),
    }
}


class OracleSimulatorError(RuntimeError):
    """The simulator configuration or requested sequence is invalid."""


class OracleTurnLimitError(OracleSimulatorError):
    """A requested sequence exceeds the user model's maximum turns."""


@dataclass(frozen=True, init=False)
class OracleResponse:
    """One policy-safe answer and the derived state that proves its lineage."""

    question_id: str
    requested_fact_id: str
    turn_index: int
    projection: ObservationProjection
    _projection_state_bytes: bytes

    def __init__(
        self,
        *,
        question_id: str,
        requested_fact_id: str,
        turn_index: int,
        projection: ObservationProjection,
        projection_state: Mapping[str, Any],
    ) -> None:
        object.__setattr__(self, "question_id", question_id)
        object.__setattr__(self, "requested_fact_id", requested_fact_id)
        object.__setattr__(self, "turn_index", turn_index)
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "_projection_state_bytes", canonical_json_bytes(projection_state))

    @property
    def policy_input(self) -> dict[str, Any]:
        """Return a detached schema-valid policy observation."""

        return self.projection.observation

    @property
    def projection_state(self) -> dict[str, Any]:
        """Return a detached source state for independent lineage validation."""

        return json.loads(self._projection_state_bytes)

    def canonical_bytes(self) -> bytes:
        """Return the deterministic public response representation."""

        return canonical_json_bytes(
            {
                "question_id": self.question_id,
                "requested_fact_id": self.requested_fact_id,
                "turn_index": self.turn_index,
                "policy_input": self.policy_input,
                "lineage": [entry.__dict__ for entry in self.projection.lineage],
            }
        )


class OracleUserSimulator:
    """Stateful deterministic oracle for one cumulative conversation.

    Repeated ``answer_sequence`` calls continue the same absolute turn counter.
    A whole call is preflighted and generated before that counter advances, so
    an invalid batch cannot consume turns or expose a partial internal update.
    """

    def __init__(self, user_model: object, private_world_state: object) -> None:
        try:
            checked_model = validate_contract(
                user_model, "user-model.schema.json", "oracle user model"
            )
        except ContractValidationError as exc:
            raise OracleSimulatorError(str(exc)) from exc
        if checked_model["response_policy"] != "DETERMINISTIC_ORACLE":
            raise OracleSimulatorError(
                "oracle user model response_policy must be DETERMINISTIC_ORACLE"
            )
        if checked_model["oracle_access_rules"].get("reveal_only_requested") is not True:
            raise OracleSimulatorError(
                "oracle_access_rules must require reveal_only_requested"
            )
        if checked_model["template_family"] not in _TEMPLATE_FAMILIES:
            raise OracleSimulatorError(
                f"unsupported oracle template_family: {checked_model['template_family']!r}"
            )
        if not isinstance(private_world_state, Mapping):
            raise OracleSimulatorError("private world state must be an object")
        try:
            private_copy = json.loads(canonical_json_bytes(private_world_state))
        except (TypeError, ValueError) as exc:
            raise OracleSimulatorError("private world state must be strict JSON") from exc
        if (
            not {"private_world_state_id", "access_class", "facts"}.issubset(private_copy)
            or private_copy.get("private_world_state_id")
            != checked_model["private_world_state_ref"]["ref_id"]
            or private_copy.get("access_class") != "PRIVATE_ENVIRONMENT"
            or not isinstance(private_copy.get("facts"), dict)
        ):
            raise OracleSimulatorError(
                "private world state must match its PRIVATE_ENVIRONMENT model reference"
            )
        answerable = tuple(checked_model["answerable_facts"])
        if any(fact_id not in private_copy["facts"] for fact_id in answerable):
            raise OracleSimulatorError("every answerable fact must exist in private world state")
        self._model_bytes = canonical_json_bytes(checked_model)
        self._private_bytes = canonical_json_bytes(private_copy)
        self._next_turn = 0
        self._used_observation_ids: set[str] = set()
        self._used_fact_ids: set[str] = set()
        self._conversation_lock = threading.Lock()

    def answer_sequence(
        self,
        canonical_state: object,
        questions: Iterable[Mapping[str, Any]] | object,
        *,
        actor_id: str,
        goal_refs: Sequence[str],
        generated_at: Mapping[str, Any],
        context_budget_tokens: int | None = None,
    ) -> tuple[OracleResponse, ...]:
        """Answer an ordered question sequence without exposing private state."""

        try:
            state = validate_contract(
                canonical_state, "canonical-state.schema.json", "oracle projection state"
            )
        except ContractValidationError as exc:
            raise OracleSimulatorError(str(exc)) from exc
        if not _valid_id(actor_id):
            raise OracleSimulatorError("actor_id must be a stable ID")
        if isinstance(questions, (str, bytes)):
            raise OracleSimulatorError("questions must be an iterable of objects")
        try:
            ordered_questions = tuple(questions)  # type: ignore[arg-type]
        except Exception as exc:
            raise OracleSimulatorError("questions must be a finite iterable") from exc
        try:
            ordered_questions = tuple(
                json.loads(canonical_json_bytes(list(ordered_questions)))
            )
        except (TypeError, ValueError) as exc:
            raise OracleSimulatorError("questions must contain strict JSON") from exc
        model = json.loads(self._model_bytes)
        if isinstance(goal_refs, (str, bytes)):
            raise OracleSimulatorError("goal_refs must be a sequence of stable IDs")
        try:
            detached_goal_refs = tuple(goal_refs)
        except Exception as exc:
            raise OracleSimulatorError("goal_refs must be a finite sequence") from exc
        if not all(_valid_id(item) for item in detached_goal_refs):
            raise OracleSimulatorError("goal_refs must contain stable IDs")
        if len(set(detached_goal_refs)) != len(detached_goal_refs):
            raise OracleSimulatorError("goal_refs must not contain duplicates")

        normalized_questions: list[tuple[str, str]] = []
        for question in ordered_questions:
            if not isinstance(question, Mapping) or set(question) != {
                "question_id",
                "fact_id",
            }:
                raise OracleSimulatorError(
                    "each question must contain only question_id and fact_id"
                )
            question_id = question["question_id"]
            fact_id = question["fact_id"]
            if not _valid_id(question_id) or not _valid_id(fact_id):
                raise OracleSimulatorError("question_id and fact_id must be stable IDs")
            normalized_questions.append((question_id, fact_id))

        with self._conversation_lock:
            start_turn = self._next_turn
            end_turn = start_turn + len(normalized_questions)
            if end_turn > model["maximum_turns"]:
                raise OracleTurnLimitError(
                    "cumulative question sequence exceeds maximum_turns"
                )
            planned_ids = [
                _public_ids(state["episode_id"], start_turn + offset, question_id, fact_id)
                for offset, (question_id, fact_id) in enumerate(normalized_questions)
            ]
            observation_ids = [item[0] for item in planned_ids]
            fact_ids = [item[1] for item in planned_ids]
            if (
                len(set(observation_ids)) != len(observation_ids)
                or len(set(fact_ids)) != len(fact_ids)
                or self._used_observation_ids.intersection(observation_ids)
                or self._used_fact_ids.intersection(fact_ids)
            ):
                raise OracleSimulatorError("oracle public response ID collision")

            responses = tuple(
                self._answer(
                    state,
                    model,
                    question_id=question_id,
                    fact_id=fact_id,
                    turn_index=start_turn + offset,
                    observation_id=planned_ids[offset][0],
                    response_fact_id=planned_ids[offset][1],
                    actor_id=actor_id,
                    goal_refs=detached_goal_refs,
                    generated_at=generated_at,
                    context_budget_tokens=context_budget_tokens,
                )
                for offset, (question_id, fact_id) in enumerate(normalized_questions)
            )
            self._next_turn = end_turn
            self._used_observation_ids.update(observation_ids)
            self._used_fact_ids.update(fact_ids)
            return responses

    def _answer(
        self,
        canonical_state: Mapping[str, Any],
        model: Mapping[str, Any],
        *,
        question_id: str,
        fact_id: str,
        turn_index: int,
        observation_id: str,
        response_fact_id: str,
        actor_id: str,
        goal_refs: Sequence[str],
        generated_at: Mapping[str, Any],
        context_budget_tokens: int | None,
    ) -> OracleResponse:
        private_state = json.loads(self._private_bytes)
        answerable = fact_id in model["answerable_facts"]
        value = deepcopy(private_state["facts"].get(fact_id)) if answerable else None
        family = _TEMPLATE_FAMILIES[model["template_family"]]
        templates = family["answer"] if answerable else family["unknown"]
        variant = _template_variant(
            model["seed"], turn_index, question_id, fact_id, len(templates)
        )
        rendered_value = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        answer = {
            "requested_fact_id": fact_id,
            "answer": value,
            "utterance": templates[variant].format(value=rendered_value),
        }
        fact = {
            "fact_id": response_fact_id,
            "value": answer,
            "epistemic_status": "ASSERTED" if answerable else "UNKNOWN",
            "evidence_refs": [],
            "access_class": "POLICY_VISIBLE",
        }
        source_state = deepcopy(dict(canonical_state))
        resources = source_state["resources"]
        if _RESPONSE_SLOT in resources:
            raise OracleSimulatorError(
                f"canonical state reserves resources/{_RESPONSE_SLOT} for oracle responses"
            )
        resources[_RESPONSE_SLOT] = fact
        try:
            projection = project_observation(
                source_state,
                observation_id=observation_id,
                actor_id=actor_id,
                source_paths=(f"/resources/{_RESPONSE_SLOT}",),
                goal_refs=goal_refs,
                generated_at=generated_at,
                context_budget_tokens=context_budget_tokens,
            )
        except ProjectionError as exc:
            raise OracleSimulatorError("oracle answer cannot cross the policy boundary") from exc
        leakage = policy_input_leakage_check(projection, source_state)
        if not leakage.succeeded:
            raise OracleSimulatorError(
                "oracle answer failed INV-014: " + ",".join(leakage.failure_codes)
            )
        return OracleResponse(
            question_id=question_id,
            requested_fact_id=fact_id,
            turn_index=turn_index,
            projection=projection,
            projection_state=source_state,
        )


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _STABLE_ID.fullmatch(value) is not None


def _variant_digest(seed: int, turn_index: int, question_id: str, fact_id: str) -> str:
    material = canonical_json_bytes(
        {
            "seed": seed,
            "turn_index": turn_index,
            "question_id": question_id,
            "fact_id": fact_id,
        }
    )
    return hashlib.sha256(material).hexdigest()


def _template_variant(
    seed: int, turn_index: int, question_id: str, fact_id: str, count: int
) -> int:
    return int(_variant_digest(seed, turn_index, question_id, fact_id)[:16], 16) % count


def _public_ids(
    episode_id: str, turn_index: int, question_id: str, fact_id: str
) -> tuple[str, str]:
    """Derive collision-resistant public IDs without evaluator-only seed input."""

    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "episode_id": episode_id,
                "turn_index": turn_index,
                "question_id": question_id,
                "fact_id": fact_id,
            }
        )
    ).hexdigest()
    return (
        f"observation:oracle:{turn_index}:{digest}",
        f"fact:oracle-response:{turn_index}:{digest}",
    )
