"""Deterministic Thanksgiving instance generation and manifest emission."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from .contracts import ContractValidationError, validate_contract
from .feasibility import FEASIBILITY_ORACLE_VERSION, FeasibilityOracle
from .ingest import artifact_integrity_check
from .oracle import OracleSimulatorError, OracleUserSimulator
from .storage import AppendOnlyStore, canonical_content_hash, canonical_json_bytes
from .thanksgiving import (
    ENVIRONMENT_VERSION,
    ScheduledAction,
    initial_thanksgiving_state,
    thanksgiving_actions,
)


GENERATOR_ID = "generator:thanksgiving-stage1"
GENERATOR_VERSION = "1.0"
SCENARIO_FAMILY = "P6"
_INSTANCE_FIELDS = {
    "instance_id",
    "generator_id",
    "generator_version",
    "scenario_family",
    "environment_version",
    "seed",
    "difficulty_parameters",
    "user_model",
    "private_world_state",
    "source_dataset_lineage",
    "split_assignment",
    "disruption_schedule",
    "feasibility_oracle_version",
    "initial_state",
    "action_plan",
    "constraint_graph",
    "entity_graph",
}


class InstanceGenerationError(RuntimeError):
    """Generation input or emitted integrity evidence is invalid."""


@dataclass(frozen=True, init=False)
class GeneratedInstance:
    """Immutable generated evaluator instance and schema-valid manifest."""

    _instance_bytes: bytes = field(repr=False)
    _manifest_bytes: bytes = field(repr=False)

    def __init__(self, instance: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_instance_bytes", canonical_json_bytes(instance))
        object.__setattr__(self, "_manifest_bytes", canonical_json_bytes(manifest))

    @property
    def instance(self) -> dict[str, Any]:
        return json.loads(self._instance_bytes)

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(self._manifest_bytes)

    @property
    def instance_content_hash(self) -> str:
        return canonical_content_hash(self.instance)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {"instance": self.instance, "manifest": self.manifest}
        )

    def verify(self) -> None:
        """Recompute graph hashes and cross-check all emitted manifest bindings."""

        instance = self.instance
        if set(instance) != _INSTANCE_FIELDS:
            raise InstanceGenerationError("generated instance field inventory is invalid")
        try:
            manifest = validate_contract(
                self.manifest,
                "instance-manifest.schema.json",
                "generated instance manifest",
            )
            state = validate_contract(
                instance["initial_state"],
                "canonical-state.schema.json",
                "generated initial state",
            )
        except (ContractValidationError, KeyError, TypeError) as exc:
            raise InstanceGenerationError("generated instance contract is invalid") from exc
        schedule = instance["disruption_schedule"]
        user_model = instance["user_model"]
        private_world_state = instance["private_world_state"]
        if (
            not isinstance(schedule, list)
            or not all(isinstance(item, Mapping) for item in schedule)
            or not isinstance(user_model, Mapping)
            or not isinstance(private_world_state, Mapping)
        ):
            raise InstanceGenerationError("generated instance evaluator inputs are invalid")
        try:
            OracleUserSimulator(user_model, private_world_state)
        except OracleSimulatorError as exc:
            raise InstanceGenerationError("generated oracle configuration is invalid") from exc
        pinned = {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "scenario_family": SCENARIO_FAMILY,
            "environment_version": ENVIRONMENT_VERSION,
            "feasibility_oracle_version": FEASIBILITY_ORACLE_VERSION,
        }
        for field_name, expected in pinned.items():
            if instance[field_name] != expected:
                raise InstanceGenerationError(
                    f"{field_name} is not the supported generation contract"
                )
        lineage = instance["source_dataset_lineage"]
        if not isinstance(lineage, list) or lineage != sorted(lineage):
            raise InstanceGenerationError(
                "source_dataset_lineage is not in canonical sorted order"
            )

        expected_constraint_graph = _constraint_graph(state)
        expected_entity_graph = _entity_graph(state)
        if canonical_json_bytes(state) != canonical_json_bytes(initial_thanksgiving_state()):
            raise InstanceGenerationError("initial state is not the bound P6 environment")
        if instance["action_plan"] != [
            _serialize_action(action) for action in thanksgiving_actions()
        ]:
            raise InstanceGenerationError("action plan is not the bound P6 schedule")
        expected_identity = _domain_hash(
            "instance-identity-v1",
            {key: value for key, value in instance.items() if key != "instance_id"},
        )
        expected_instance_id = (
            "instance:thanksgiving:"
            + expected_identity.removeprefix("sha256:")[:32]
        )
        if instance["instance_id"] != expected_instance_id:
            raise InstanceGenerationError("instance_id does not match generated content")
        if instance.get("constraint_graph") != expected_constraint_graph:
            raise InstanceGenerationError("constraint graph does not match initial state")
        if instance.get("entity_graph") != expected_entity_graph:
            raise InstanceGenerationError("entity graph does not match initial state")
        expected_hashes = {
            "constraint_graph_hash": _domain_hash(
                "constraint-graph-v1", expected_constraint_graph
            ),
            "entity_graph_hash": _domain_hash("entity-graph-v1", expected_entity_graph),
            "disruption_schedule_hash": _domain_hash(
                "disruption-schedule-v1", instance.get("disruption_schedule")
            ),
        }
        for field_name, expected in expected_hashes.items():
            if manifest[field_name] != expected:
                raise InstanceGenerationError(f"{field_name} does not match generated content")
        bindings = {
            "generator_id": instance.get("generator_id"),
            "generator_version": instance.get("generator_version"),
            "scenario_family": instance.get("scenario_family"),
            "seed": instance.get("seed"),
            "difficulty_parameters": instance.get("difficulty_parameters"),
            "user_model_version": user_model.get("version"),
            "source_dataset_lineage": instance.get("source_dataset_lineage"),
            "feasibility_oracle_version": instance.get("feasibility_oracle_version"),
            "split_assignment": instance.get("split_assignment"),
        }
        for field_name, expected in bindings.items():
            if manifest[field_name] != expected:
                raise InstanceGenerationError(f"manifest {field_name} is not bound to instance")

    def emit(self, store: AppendOnlyStore) -> tuple[str, str]:
        """Persist instance and manifest, then enforce store-wide INV-015."""

        if not isinstance(store, AppendOnlyStore):
            raise InstanceGenerationError("emission requires an AppendOnlyStore")
        self.verify()
        instance = self.instance
        suffix = instance["instance_id"].removeprefix("instance:")
        instance_ref = instance["instance_id"]
        manifest_ref = f"manifest:{suffix}"
        try:
            store.put_artifacts_atomic(
                (
                    (instance_ref, "generated-instance", instance),
                    (manifest_ref, "instance-manifest", self.manifest),
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise InstanceGenerationError("instance emission failed") from exc
        integrity = artifact_integrity_check(store, (instance_ref, manifest_ref))
        if not integrity.succeeded:
            raise InstanceGenerationError(
                "emitted instance failed INV-015: " + ",".join(integrity.failure_codes)
            )
        return instance_ref, manifest_ref


def generate_thanksgiving_instance(
    *,
    seed: int,
    difficulty_parameters: Mapping[str, Any],
    user_model: Mapping[str, Any],
    private_world_state: Mapping[str, Any],
    source_dataset_lineage: Iterable[str],
    split_assignment: str,
    disruption_schedule: Iterable[Mapping[str, Any]] = (),
    generator_id: str = GENERATOR_ID,
    generator_version: str = GENERATOR_VERSION,
    feasibility_oracle_version: str = FEASIBILITY_ORACLE_VERSION,
) -> GeneratedInstance:
    """Generate one byte-stable P6 evaluator instance from explicit inputs."""

    if (
        generator_id != GENERATOR_ID
        or generator_version != GENERATOR_VERSION
        or feasibility_oracle_version != FEASIBILITY_ORACLE_VERSION
    ):
        raise InstanceGenerationError("unsupported generator or feasibility version")

    try:
        normalized_difficulty = _strict_json_object(
            difficulty_parameters, "difficulty_parameters"
        )
        normalized_user_model = _strict_json_object(user_model, "user_model")
        normalized_private = _strict_json_object(
            private_world_state, "private_world_state"
        )
        lineage = tuple(sorted(tuple(source_dataset_lineage)))
        schedule = tuple(disruption_schedule)
        if not all(isinstance(item, Mapping) for item in schedule):
            raise InstanceGenerationError("disruption_schedule members must be objects")
        normalized_schedule = json.loads(canonical_json_bytes(list(schedule)))
    except Exception as exc:
        if isinstance(exc, InstanceGenerationError):
            raise
        raise InstanceGenerationError("generation inputs must be finite strict JSON") from exc
    if not lineage or not all(isinstance(item, str) and item for item in lineage):
        raise InstanceGenerationError("source_dataset_lineage must contain stable IDs")
    if len(set(lineage)) != len(lineage):
        raise InstanceGenerationError("source_dataset_lineage must not contain duplicates")
    try:
        checked_user_model = validate_contract(
            normalized_user_model,
            "user-model.schema.json",
            "generated instance user model",
        )
        OracleUserSimulator(checked_user_model, normalized_private)
    except (ContractValidationError, OracleSimulatorError) as exc:
        raise InstanceGenerationError("oracle configuration is invalid") from exc

    state = initial_thanksgiving_state()
    actions = thanksgiving_actions()
    if not FeasibilityOracle().assess(state, actions).feasible:
        raise InstanceGenerationError("base Thanksgiving environment is infeasible")
    constraint_graph = _constraint_graph(state)
    entity_graph = _entity_graph(state)
    action_plan = [_serialize_action(action) for action in actions]

    generation_identity = {
        "generator_id": generator_id,
        "generator_version": generator_version,
        "scenario_family": SCENARIO_FAMILY,
        "environment_version": ENVIRONMENT_VERSION,
        "seed": seed,
        "difficulty_parameters": normalized_difficulty,
        "user_model": checked_user_model,
        "private_world_state": normalized_private,
        "source_dataset_lineage": list(lineage),
        "split_assignment": split_assignment,
        "disruption_schedule": normalized_schedule,
        "feasibility_oracle_version": feasibility_oracle_version,
    }
    instance_content = {
        **generation_identity,
        "initial_state": state,
        "action_plan": action_plan,
        "constraint_graph": constraint_graph,
        "entity_graph": entity_graph,
    }
    identity_hash = _domain_hash("instance-identity-v1", instance_content)
    instance_id = f"instance:thanksgiving:{identity_hash.removeprefix('sha256:')[:32]}"
    instance = {"instance_id": instance_id, **instance_content}
    manifest = {
        "generator_id": generator_id,
        "generator_version": generator_version,
        "scenario_family": SCENARIO_FAMILY,
        "seed": seed,
        "difficulty_parameters": normalized_difficulty,
        "constraint_graph_hash": _domain_hash(
            "constraint-graph-v1", constraint_graph
        ),
        "entity_graph_hash": _domain_hash("entity-graph-v1", entity_graph),
        "disruption_schedule_hash": _domain_hash(
            "disruption-schedule-v1", normalized_schedule
        ),
        "user_model_version": checked_user_model["version"],
        "source_dataset_lineage": list(lineage),
        "feasibility_oracle_version": feasibility_oracle_version,
        "split_assignment": split_assignment,
    }
    try:
        checked_manifest = validate_contract(
            manifest,
            "instance-manifest.schema.json",
            "generated instance manifest",
        )
    except ContractValidationError as exc:
        raise InstanceGenerationError("generated manifest is invalid") from exc
    result = GeneratedInstance(instance, checked_manifest)
    result.verify()
    return result


def _strict_json_object(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InstanceGenerationError(f"{description} must be an object")
    try:
        detached = json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as exc:
        raise InstanceGenerationError(f"{description} must be strict JSON") from exc
    return detached


def _domain_hash(domain: str, value: object) -> str:
    payload = canonical_json_bytes({"domain": domain, "value": value})
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _constraint_graph(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "obligations": state["obligations"],
        "dependencies": state["dependencies"],
        "deadlines": state["deadlines"],
        "permissions": state["permissions"],
    }


def _entity_graph(state: Mapping[str, Any]) -> dict[str, Any]:
    return {"entities": state["entities"], "resources": state["resources"]}


def _serialize_action(action: ScheduledAction) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "action_type": action.action_type,
        "obligation_id": action.obligation_id,
        "start_minute": action.start_minute,
        "end_minute": action.end_minute,
        "resource_ids": list(action.resource_ids),
        "dependencies": list(action.dependencies),
        "effects": [
            {
                "path": effect.path,
                "value": effect.value,
                "earliest_minute": effect.earliest_minute,
                "latest_minute": effect.latest_minute,
            }
            for effect in action.effects
        ],
    }
