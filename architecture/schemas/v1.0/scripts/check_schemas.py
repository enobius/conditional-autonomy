#!/usr/bin/env python3
"""Portable Workstream 1A schema gate.

Each batch can be checked independently; ``--batch all`` validates the
integrated package through B3-1. B3-2 remains dependency-blocked.
"""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT.parent / ".vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402
import fastjsonschema  # noqa: E402
from referencing import Registry, Resource  # noqa: E402


BATCH1_SCHEMAS = [
    "validator-result.schema.json",
    "supervisor-decision.schema.json",
    "tool-outcome.schema.json",
    "outcome-vector.schema.json",
    "user-model.schema.json",
    "instance-manifest.schema.json",
    "adapter-manifest.schema.json",
    "event.schema.json",
]
BATCH2_SCHEMAS = [
    "action-proposal.schema.json",
    "canonical-state.schema.json",
    "access-scoped-observation.schema.json",
]
BATCH3_SCHEMAS = ["trace-step.schema.json"]


EXPECTED_ENUMS = {
    "accessClass": [
        "POLICY_VISIBLE",
        "SUPERVISOR_VISIBLE",
        "VALIDATOR_VISIBLE",
        "EVALUATOR_ONLY",
        "PRIVATE_ENVIRONMENT",
    ],
    "provenanceSource": [
        "USER",
        "TOOL",
        "ENVIRONMENT",
        "DERIVED_RULE",
        "MODEL_CLAIM",
        "EVALUATOR",
    ],
    "epistemicStatus": [
        "OBSERVED",
        "ASSERTED",
        "INFERRED",
        "UNKNOWN",
        "CONTRADICTED",
        "SUPERSEDED",
    ],
    "validatorStatus": ["PASS", "FAIL", "UNKNOWN"],
    "criticality": ["HARD", "SOFT"],
    "enforceability": ["PREVENTABLE", "PREDICTIVE", "DETECTABLE"],
    "reversibility": ["REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE"],
    "decision": ["APPROVE", "REPAIR", "QUERY", "REJECT", "ESCALATE"],
    "uncertaintyKind": ["EXACT", "BOUNDED", "ESTIMATED", "UNKNOWN"],
}

ACCESS_CLASSES = set(EXPECTED_ENUMS["accessClass"])
DEFERRED_KEYS = {
    "invariant_id",
    "statement",
    "reason_deferred",
    "owner",
    "validator",
    "enforcement_phase",
    "failure_resolution",
    "positive_test",
    "negative_test",
    "status",
}


class GateFailure(RuntimeError):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateFailure(f"JSON parse failed: {path}: {exc}") from exc


def schema_files(batch: str) -> list[Path]:
    names = ["common.defs.schema.json"]
    if batch in {"batch1", "batch3", "all"}:
        names.extend(BATCH1_SCHEMAS)
    if batch in {"batch2", "batch3", "all"}:
        names.extend(BATCH2_SCHEMAS)
    if batch in {"batch3", "all"}:
        names.extend(BATCH3_SCHEMAS)
    return [ROOT / name for name in names]


def fixture_entries(batch: str, expected: str | None = None) -> list[dict]:
    manifest = load_json(ROOT / "fixture-manifest.json")
    batches = (
        {"batch0", "batch1", "batch2", "batch3"}
        if batch == "all"
        else {batch}
    )
    return [
        item
        for item in manifest["fixtures"]
        if item.get("batch", "batch0") in batches
        and (expected is None or item["expected"] == expected)
    ]


def json_files(batch: str) -> list[Path]:
    return sorted(
        {
            *schema_files(batch),
            ROOT / "ci-manifest.yaml",
            ROOT / "fixture-manifest.json",
            ROOT / "mutation-registry.json",
            *(ROOT / item["path"] for item in fixture_entries(batch)),
        }
    )


def fixture_wrapper(common: dict) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://thesis.local/schemas/v1.0/batch0-fixture.schema.json",
        "type": "object",
        "required": [
            "normalized_time",
            "provenance",
            "epistemic_status",
            "version_identifier",
        ],
        "properties": {
            "normalized_time": {"$ref": "#/$defs/normalizedTime"},
            "provenance": {"$ref": "#/$defs/provenance"},
            "epistemic_status": {"$ref": "#/$defs/epistemicStatus"},
            "version_identifier": {"$ref": "#/$defs/versionIdentifier"},
        },
        "$defs": copy.deepcopy(common["$defs"]),
        "additionalProperties": False,
    }


def json_pointer_exists(document: object, fragment: str) -> bool:
    if not fragment:
        return True
    if not fragment.startswith("/"):
        return False
    node = document
    for raw in fragment[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return False
    return True


def walk_refs(node: object):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"]
        for value in node.values():
            yield from walk_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_refs(value)


def access_lint_errors(schema: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            for name, definition in props.items():
                current = f"{path}.properties.{name}"
                annotation = (
                    definition.get("x-access-class")
                    if isinstance(definition, dict)
                    else None
                )
                if not isinstance(annotation, list) or not annotation:
                    errors.append(f"{current}: missing non-empty x-access-class")
                elif len(set(annotation)) != len(annotation):
                    errors.append(f"{current}: duplicate access classes")
                elif not set(annotation) <= ACCESS_CLASSES:
                    errors.append(f"{current}: invalid access class")
        # `properties` inside applicator branches constrain fields already declared
        # on the owning object; they are not new field declarations.
        for key, value in schema.items():
            if key in {"if", "then", "else"}:
                continue
            errors.extend(access_lint_errors(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            errors.extend(access_lint_errors(value, f"{path}[{index}]"))
    return errors


def enum_fidelity_errors(common: dict) -> list[str]:
    errors = []
    for name, expected in EXPECTED_ENUMS.items():
        actual = common.get("$defs", {}).get(name, {}).get("enum")
        if actual != expected:
            errors.append(f"$defs.{name}: expected {expected!r}, found {actual!r}")
    return errors


def normalized_times(node: object):
    if isinstance(node, dict):
        if {"instant", "source_timezone", "uncertainty"} <= set(node):
            yield node
        for value in node.values():
            yield from normalized_times(value)
    elif isinstance(node, list):
        for value in node:
            yield from normalized_times(value)


def timezone_errors(instance: object) -> list[str]:
    errors = []
    for index, value in enumerate(normalized_times(instance)):
        name = value.get("source_timezone")
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            errors.append(f"normalized time #{index}: invalid IANA timezone {name!r}")
    return errors


def check_json_parsing(batch: str) -> str:
    for path in json_files(batch):
        load_json(path)
    return f"{len(json_files(batch))} JSON/YAML-compatible files parsed"


def check_meta_schema(batch: str) -> str:
    for path in schema_files(batch):
        Draft202012Validator.check_schema(load_json(path))
    return f"{len(schema_files(batch))} schemas pass the Draft 2020-12 meta-schema"


def check_ids(batch: str) -> str:
    schemas = [load_json(path) for path in schema_files(batch)]
    ids = [item.get("$id") for item in schemas]
    if None in ids or len(ids) != len(set(ids)):
        raise GateFailure(f"Schema IDs missing or duplicated: {ids}")
    return f"{len(ids)} unique absolute schema ID"


def check_reference_closure(batch: str) -> str:
    by_name = {path.name: load_json(path) for path in schema_files(batch)}
    count = 0
    for filename, schema in by_name.items():
        for ref in walk_refs(schema):
            count += 1
            if ref.startswith("#"):
                if not json_pointer_exists(schema, ref[1:]):
                    raise GateFailure(f"{filename}: unresolved internal reference {ref}")
                continue
            target_name, _, fragment = ref.partition("#")
            if target_name not in by_name:
                raise GateFailure(f"{filename}: missing reference target {target_name}")
            if fragment and not json_pointer_exists(by_name[target_name], fragment):
                raise GateFailure(f"{filename}: unresolved reference fragment {ref}")
    return f"{count} references resolve"


def check_access_annotations(batch: str) -> str:
    errors = []
    for path in schema_files(batch):
        errors.extend(access_lint_errors(load_json(path), path.name))
    if errors:
        raise GateFailure("Access lint failed:\n- " + "\n- ".join(errors))
    return "Every declared object property has a valid x-access-class annotation"


def check_enum_fidelity() -> str:
    errors = enum_fidelity_errors(load_json(ROOT / "common.defs.schema.json"))
    if errors:
        raise GateFailure("Enum fidelity failed:\n- " + "\n- ".join(errors))
    return f"{len(EXPECTED_ENUMS)} enum sets match the approved contract"


def validator_bundle(schema_name: str | None):
    available = {
        path.name: load_json(path)
        for path in [
            ROOT / "common.defs.schema.json",
            *[
                ROOT / name
                for name in BATCH1_SCHEMAS + BATCH2_SCHEMAS + BATCH3_SCHEMAS
            ],
        ]
        if path.exists()
    }
    if schema_name is None:
        target = fixture_wrapper(available["common.defs.schema.json"])
    else:
        target = available[schema_name]

    resources = [
        (item["$id"], Resource.from_contents(item))
        for item in available.values()
    ]
    registry = Registry().with_resources(resources)
    primary = Draft202012Validator(
        target,
        format_checker=FormatChecker(),
        registry=registry,
    )

    by_id = {item["$id"]: item for item in available.values()}

    def retrieve(uri: str):
        base_uri, _ = urldefrag(uri)
        if base_uri not in by_id:
            raise GateFailure(f"Secondary validator requested unknown schema {uri}")
        return by_id[base_uri]

    # fastjsonschema asserts its built-in formats by default.  The pinned
    # 2.21.2 compile API has no ``use_formats`` keyword.
    secondary = fastjsonschema.compile(target, handlers={"https": retrieve})
    return target, primary, secondary


def primary_errors(primary, instance: object) -> list[str]:
    return [error.message for error in primary.iter_errors(instance)] + timezone_errors(
        instance
    )


def secondary_errors(secondary, instance: object) -> list[str]:
    errors = []
    try:
        secondary(instance)
    except fastjsonschema.JsonSchemaException as exc:
        errors.append(str(exc))
    errors.extend(timezone_errors(instance))
    return errors


def check_positive_fixtures(batch: str) -> str:
    entries = fixture_entries(batch, "valid")
    for item in entries:
        _, primary, secondary = validator_bundle(item.get("schema"))
        instance = load_json(ROOT / item["path"])
        p_errors = primary_errors(primary, instance)
        s_errors = secondary_errors(secondary, instance)
        if p_errors or s_errors:
            raise GateFailure(
                f"{item['path']} should be valid; primary={p_errors}; secondary={s_errors}"
            )
    return f"{len(entries)} positive fixture passes both validators"


def check_negative_fixtures(batch: str) -> str:
    entries = fixture_entries(batch, "invalid")
    for item in entries:
        _, primary, secondary = validator_bundle(item.get("schema"))
        instance = load_json(ROOT / item["path"])
        p_errors = primary_errors(primary, instance)
        s_errors = secondary_errors(secondary, instance)
        if not p_errors or not s_errors:
            raise GateFailure(
                f"{item['path']} should fail both validators; "
                f"primary={p_errors}; secondary={s_errors}"
            )
    return f"{len(entries)} negative fixtures fail both validators as intended"


def check_mutations(batch: str) -> str:
    registry = load_json(ROOT / "mutation-registry.json")
    batches = (
        {"batch0", "batch1", "batch2", "batch3"}
        if batch == "all"
        else {batch}
    )
    active = [
        m
        for m in registry["mutations"]
        if m["status"] == "ACTIVE" and m["batch"] in batches
    ]
    blocked = [m for m in registry["mutations"] if m["status"] == "BLOCKED"]
    common = load_json(ROOT / "common.defs.schema.json")

    if "batch0" in batches:
        missing_access = copy.deepcopy(common)
        del missing_access["$defs"]["normalizedTime"]["properties"]["instant"][
            "x-access-class"
        ]
        if not access_lint_errors(missing_access):
            raise GateFailure("MUT-B0-001 was not detected")

        wrapper, _, _ = validator_bundle(None)
        renamed = copy.deepcopy(wrapper)
        renamed["properties"]["normalized_timestamp"] = renamed["properties"].pop(
            "normalized_time"
        )
        renamed_validator = Draft202012Validator(
            renamed, format_checker=FormatChecker()
        )
        valid_fixture = load_json(ROOT / "fixtures/valid/common.valid.json")
        if not list(renamed_validator.iter_errors(valid_fixture)):
            raise GateFailure("MUT-B0-002 was not detected")

        wrong_enum = copy.deepcopy(common)
        values = wrong_enum["$defs"]["provenanceSource"]["enum"]
        values[values.index("MODEL_CLAIM")] = "MODEL"
        if not enum_fidelity_errors(wrong_enum):
            raise GateFailure("MUT-B0-003 was not detected")

    if "batch1" in batches:
        hard_unknown = load_json(
            ROOT
            / "fixtures/invalid/validator-result.hard-unknown-execute.invalid.json"
        )
        validator_schema = load_json(ROOT / "validator-result.schema.json")
        validator_schema["allOf"] = validator_schema["allOf"][1:]
        resources = Registry().with_resource(
            common["$id"], Resource.from_contents(common)
        )
        mutant = Draft202012Validator(validator_schema, registry=resources)
        if list(mutant.iter_errors(hard_unknown)):
            raise GateFailure("MUT-B1-001 did not isolate the HARD + UNKNOWN guard")

    if "batch2" in batches:
        action_fixture = load_json(
            ROOT / "fixtures/invalid/action-proposal.compensation-null.invalid.json"
        )
        action_schema = load_json(ROOT / "action-proposal.schema.json")
        action_schema["allOf"] = action_schema["allOf"][1:]
        resources = Registry().with_resource(
            common["$id"], Resource.from_contents(common)
        )
        action_mutant = Draft202012Validator(action_schema, registry=resources)
        if list(action_mutant.iter_errors(action_fixture)):
            raise GateFailure("MUT-B2-001 did not isolate the compensation guard")

        observation_fixture = load_json(
            ROOT
            / "fixtures/invalid/access-scoped-observation.private-field.invalid.json"
        )
        observation_schema = load_json(ROOT / "access-scoped-observation.schema.json")
        observation_schema["properties"]["private_world_state_ref"] = {
            "type": "object",
            "x-access-class": ["POLICY_VISIBLE"],
        }
        observation_mutant = Draft202012Validator(
            observation_schema, registry=resources
        )
        if list(observation_mutant.iter_errors(observation_fixture)):
            raise GateFailure("MUT-B2-002 did not isolate observation leakage")

    if "batch3" in batches:
        trace_fixture = load_json(
            ROOT / "fixtures/invalid/trace-step.canonical-ref-access.invalid.json"
        )
        trace_schema = load_json(ROOT / "trace-step.schema.json")
        trace_schema["properties"]["canonical_state_ref"]["properties"][
            "access_class"
        ]["enum"] = ["EVALUATOR_ONLY", "POLICY_VISIBLE"]
        del trace_schema["properties"]["canonical_state_ref"]["properties"][
            "access_class"
        ]["const"]
        dependency_documents = [
            load_json(ROOT / name)
            for name in BATCH1_SCHEMAS + BATCH2_SCHEMAS
        ]
        trace_resources = Registry().with_resources(
            [
                (common["$id"], Resource.from_contents(common)),
                *[
                    (document["$id"], Resource.from_contents(document))
                    for document in dependency_documents
                ],
            ]
        )
        trace_mutant = Draft202012Validator(
            trace_schema, registry=trace_resources
        )
        if list(trace_mutant.iter_errors(trace_fixture)):
            raise GateFailure(
                "MUT-B3-001 did not isolate canonical-state reference leakage"
            )

    expected = sum(
        1
        for mutation in registry["mutations"]
        if mutation["batch"] in batches
    )
    if len(active) != expected:
        raise GateFailure(
            f"Expected {expected} active mutations for {batch}, found {len(active)}"
        )
    return (
        f"{len(active)} active mutations detected; "
        f"{len(blocked)} mutations remain blocked"
    )


def parse_yaml_blocks(markdown: str) -> list[dict[str, str]]:
    blocks = re.findall(r"```yaml\s+(.*?)```", markdown, flags=re.DOTALL)
    records = []
    for block in blocks:
        record = {}
        for line in block.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition(":")
            if not separator:
                continue
            record[key.strip()] = value.strip().strip('"')
        records.append(record)
    return records


def check_deferred_register() -> str:
    text = (ROOT / "deferred-invariants.md").read_text(encoding="utf-8")
    records = parse_yaml_blocks(text)
    if len(records) != 15:
        raise GateFailure(f"Expected 15 deferred invariants, found {len(records)}")
    ids = []
    for record in records:
        missing = DEFERRED_KEYS - set(record)
        if missing:
            raise GateFailure(
                f"{record.get('invariant_id', '<unknown>')}: missing keys {sorted(missing)}"
            )
        if not all(record[key] for key in DEFERRED_KEYS):
            raise GateFailure(f"{record['invariant_id']}: empty required value")
        ids.append(record["invariant_id"])
    if len(ids) != len(set(ids)):
        raise GateFailure("Deferred invariant IDs are not unique")
    return "15 deferred invariants have complete ownership and test records"


def check_manifest_versions() -> str:
    manifest = load_json(ROOT / "ci-manifest.yaml")
    actual_primary = importlib.metadata.version("jsonschema")
    actual_secondary = importlib.metadata.version("fastjsonschema")
    expected_primary = manifest["primary_validator"]["version"]
    expected_secondary = manifest["secondary_validator"]["version"]
    if actual_primary != expected_primary or actual_secondary != expected_secondary:
        raise GateFailure(
            "Pinned validator mismatch: "
            f"jsonschema {actual_primary}/{expected_primary}, "
            f"fastjsonschema {actual_secondary}/{expected_secondary}"
        )
    return (
        f"Validator pins satisfied: jsonschema {actual_primary}, "
        f"fastjsonschema {actual_secondary}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch",
        choices=["batch0", "batch1", "batch2", "batch3", "all"],
        default="batch0",
    )
    args = parser.parse_args()

    checks = [
        ("1 JSON parsing", lambda: check_json_parsing(args.batch)),
        ("2 Meta-schema", lambda: check_meta_schema(args.batch)),
        ("3 Schema IDs", lambda: check_ids(args.batch)),
        ("4 Reference closure", lambda: check_reference_closure(args.batch)),
        ("5 Access lint", lambda: check_access_annotations(args.batch)),
        ("6 Enum fidelity", check_enum_fidelity),
        ("7 Positive fixtures", lambda: check_positive_fixtures(args.batch)),
        ("8 Negative fixtures", lambda: check_negative_fixtures(args.batch)),
        ("9 Mutation harness", lambda: check_mutations(args.batch)),
        ("10 Deferred register", check_deferred_register),
        ("Manifest validator pins", check_manifest_versions),
    ]

    print(f"Workstream 1A schema gate: {args.batch}")
    for label, function in checks:
        try:
            detail = function()
        except Exception as exc:
            print(f"FAIL {label}: {exc}")
            return 1
        print(f"PASS {label}: {detail}")
    print(f"{args.batch.upper()} TECHNICAL GATE: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
