#!/usr/bin/env python3
"""Portable Workstream 1A schema gate.

Batch 0 checks only Batch 0 artifacts. Downstream contracts remain blocked
until their tickets add schemas, fixtures, and mutation cases.
"""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT.parent / ".vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402
import fastjsonschema  # noqa: E402


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


def batch0_schema_files() -> list[Path]:
    return [ROOT / "common.defs.schema.json"]


def all_batch0_json_files() -> list[Path]:
    return sorted(
        [
            ROOT / "common.defs.schema.json",
            ROOT / "ci-manifest.yaml",
            ROOT / "fixture-manifest.json",
            ROOT / "mutation-registry.json",
            *ROOT.glob("fixtures/**/*.json"),
        ]
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


def check_json_parsing() -> str:
    for path in all_batch0_json_files():
        load_json(path)
    return f"{len(all_batch0_json_files())} JSON/YAML-compatible files parsed"


def check_meta_schema() -> str:
    for path in batch0_schema_files():
        Draft202012Validator.check_schema(load_json(path))
    return "Batch 0 schemas pass the Draft 2020-12 meta-schema"


def check_ids() -> str:
    schemas = [load_json(path) for path in batch0_schema_files()]
    ids = [item.get("$id") for item in schemas]
    if None in ids or len(ids) != len(set(ids)):
        raise GateFailure(f"Schema IDs missing or duplicated: {ids}")
    return f"{len(ids)} unique absolute schema ID"


def check_reference_closure() -> str:
    by_name = {path.name: load_json(path) for path in batch0_schema_files()}
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


def check_access_annotations() -> str:
    errors = []
    for path in batch0_schema_files():
        errors.extend(access_lint_errors(load_json(path), path.name))
    if errors:
        raise GateFailure("Access lint failed:\n- " + "\n- ".join(errors))
    return "Every Batch 0 object property has a valid x-access-class annotation"


def check_enum_fidelity() -> str:
    errors = enum_fidelity_errors(load_json(ROOT / "common.defs.schema.json"))
    if errors:
        raise GateFailure("Enum fidelity failed:\n- " + "\n- ".join(errors))
    return f"{len(EXPECTED_ENUMS)} enum sets match the approved contract"


def validators():
    common = load_json(ROOT / "common.defs.schema.json")
    wrapper = fixture_wrapper(common)
    primary = Draft202012Validator(wrapper, format_checker=FormatChecker())
    secondary = fastjsonschema.compile(wrapper, use_formats=True)
    return wrapper, primary, secondary


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


def fixture_entries(expected: str) -> list[dict]:
    manifest = load_json(ROOT / "fixture-manifest.json")
    return [item for item in manifest["fixtures"] if item["expected"] == expected]


def check_positive_fixtures() -> str:
    _, primary, secondary = validators()
    entries = fixture_entries("valid")
    for item in entries:
        instance = load_json(ROOT / item["path"])
        p_errors = primary_errors(primary, instance)
        s_errors = secondary_errors(secondary, instance)
        if p_errors or s_errors:
            raise GateFailure(
                f"{item['path']} should be valid; primary={p_errors}; secondary={s_errors}"
            )
    return f"{len(entries)} positive fixture passes both validators"


def check_negative_fixtures() -> str:
    _, primary, secondary = validators()
    entries = fixture_entries("invalid")
    for item in entries:
        instance = load_json(ROOT / item["path"])
        p_errors = primary_errors(primary, instance)
        s_errors = secondary_errors(secondary, instance)
        if not p_errors or not s_errors:
            raise GateFailure(
                f"{item['path']} should fail both validators; "
                f"primary={p_errors}; secondary={s_errors}"
            )
    return f"{len(entries)} negative fixtures fail both validators as intended"


def check_mutations() -> str:
    registry = load_json(ROOT / "mutation-registry.json")
    active = [m for m in registry["mutations"] if m["status"] == "ACTIVE"]
    blocked = [m for m in registry["mutations"] if m["status"] == "BLOCKED"]
    common = load_json(ROOT / "common.defs.schema.json")

    missing_access = copy.deepcopy(common)
    del missing_access["$defs"]["normalizedTime"]["properties"]["instant"][
        "x-access-class"
    ]
    if not access_lint_errors(missing_access):
        raise GateFailure("MUT-B0-001 was not detected")

    wrapper, primary, _ = validators()
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

    if len(active) != 3:
        raise GateFailure(f"Expected 3 active Batch 0 mutations, found {len(active)}")
    return f"{len(active)} active mutations detected; {len(blocked)} downstream mutations remain blocked"


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
    parser.add_argument("--batch", choices=["batch0"], default="batch0")
    args = parser.parse_args()
    if args.batch != "batch0":
        raise GateFailure("Only Batch 0 is currently unblocked")

    checks = [
        ("1 JSON parsing", check_json_parsing),
        ("2 Meta-schema", check_meta_schema),
        ("3 Schema IDs", check_ids),
        ("4 Reference closure", check_reference_closure),
        ("5 Access lint", check_access_annotations),
        ("6 Enum fidelity", check_enum_fidelity),
        ("7 Positive fixtures", check_positive_fixtures),
        ("8 Negative fixtures", check_negative_fixtures),
        ("9 Mutation harness", check_mutations),
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
    print("BATCH 0 TECHNICAL GATE: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
