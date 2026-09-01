"""Generation-to-promotion adapter for deferred invariant INV-013."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .preexecution import Verdict
from .promotion_invariants import PROHIBITED_SPLIT_DIMENSIONS, split_leakage_check


class SplitHygieneError(RuntimeError):
    """Generated artifacts cannot be promoted without violating INV-013."""


def generation_manifest_evidence(
    instance: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, object]:
    """Translate T-19 vocabulary into the compact INV-013 evidence contract."""

    try:
        return {
            "instance_id": instance["instance_id"],
            "split": manifest["split_assignment"],
            "seed": manifest["seed"],
            "template_family": manifest["scenario_family"],
            "constraint_graph_hash": manifest["constraint_graph_hash"],
            "disruption_composition_hash": manifest["disruption_schedule_hash"],
        }
    except (KeyError, TypeError) as exc:
        raise SplitHygieneError("generated pair lacks INV-013 evidence") from exc


def enforce_generation_split_hygiene(
    generated_pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    """Apply the canonical INV-013 policy to generated instance/manifest pairs."""

    try:
        manifests = [
            generation_manifest_evidence(instance, manifest)
            for instance, manifest in generated_pairs
        ]
    except (TypeError, ValueError) as exc:
        raise SplitHygieneError("generated split-hygiene evidence is invalid") from exc
    outcome = split_leakage_check(
        {
            "prohibited_dimensions": sorted(PROHIBITED_SPLIT_DIMENSIONS),
            "manifests": manifests,
        }
    )
    if outcome.verdict is not Verdict.PASS:
        detail = ",".join(outcome.failure_codes) or "INV-013"
        raise SplitHygieneError(f"generated artifacts failed INV-013: {detail}")


def _generation_pair_store_preflight(
    records: tuple[Mapping[str, Any], ...],
    candidate_instance_ref: str,
    candidate_instance: Mapping[str, Any],
    candidate_manifest_ref: str,
    candidate_manifest: Mapping[str, Any],
) -> None:
    """Closed storage preflight for complete generated pairs.

    Imported lazily by storage's private typed transaction so neither public
    storage callers nor generation callers can select or replace the policy.
    """

    # Lazy import avoids a module cycle: generation imports storage, while this
    # verifier is called only after both modules have finished loading.
    from .generation import GeneratedInstance, InstanceGenerationError

    generated: dict[str, Mapping[str, Any]] = {}
    manifests: dict[str, Mapping[str, Any]] = {}
    for record in records:
        artifact_id = record.get("artifact_id")
        artifact_type = record.get("artifact_type")
        content = record.get("content")
        if not isinstance(artifact_id, str):
            raise SplitHygieneError("stored artifact has an invalid ID")
        looks_like_instance = artifact_id.startswith("instance:")
        looks_like_manifest = artifact_id.startswith("manifest:")
        if artifact_type == "generated-instance":
            if not looks_like_instance or not isinstance(content, Mapping):
                raise SplitHygieneError("generated-instance artifact is malformed")
            generated[artifact_id] = content
        elif artifact_type == "instance-manifest":
            if not looks_like_manifest or not isinstance(content, Mapping):
                raise SplitHygieneError("instance-manifest artifact is malformed")
            manifests[artifact_id] = content
        elif looks_like_instance or looks_like_manifest:
            raise SplitHygieneError(
                "generated pair member has an unexpected artifact type"
            )

    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    pair_suffixes = {
        artifact_id.removeprefix("instance:") for artifact_id in generated
    } | {artifact_id.removeprefix("manifest:") for artifact_id in manifests}
    for suffix in sorted(pair_suffixes):
        instance_ref = "instance:" + suffix
        manifest_ref = "manifest:" + suffix
        instance = generated.get(instance_ref)
        manifest = manifests.get(manifest_ref)
        if instance is None or manifest is None:
            raise SplitHygieneError("stored generated pair is incomplete")
        if instance.get("instance_id") != instance_ref:
            raise SplitHygieneError("stored generated pair IDs are not bound")
        try:
            GeneratedInstance(instance, manifest).verify()
        except (InstanceGenerationError, TypeError, ValueError) as exc:
            raise SplitHygieneError("stored generated pair failed reconstruction") from exc
        pairs.append((instance, manifest))

    if (
        candidate_instance.get("instance_id") != candidate_instance_ref
        or candidate_manifest_ref
        != "manifest:" + candidate_instance_ref.removeprefix("instance:")
    ):
        raise SplitHygieneError("candidate generated pair IDs are not bound")
    try:
        GeneratedInstance(candidate_instance, candidate_manifest).verify()
    except (InstanceGenerationError, TypeError, ValueError) as exc:
        raise SplitHygieneError("candidate generated pair failed reconstruction") from exc
    pairs.append((candidate_instance, candidate_manifest))
    enforce_generation_split_hygiene(pairs)
