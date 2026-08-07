"""Public, pinned JSON Schema validation boundary for runtime contracts."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .storage import canonical_json_bytes


class ContractValidationError(RuntimeError):
    """A runtime value is not strict JSON or violates its named contract."""


_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "architecture" / "schemas" / "v1.0"
_VENDOR = _SCHEMA_ROOT.parent / ".vendor"


@lru_cache(maxsize=1)
def _jsonschema_types():
    """Load exactly the pinned validator from one selected package root."""

    vendor_selected = _VENDOR.exists()
    if vendor_selected and str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))
    try:
        import jsonschema
        import referencing
    except ImportError as exc:  # pragma: no cover - installation failure path
        raise RuntimeError(
            "runtime schema validation requires architecture/schemas/requirements-schema.txt"
        ) from exc
    try:
        installed_version = version("jsonschema")
    except PackageNotFoundError as exc:  # pragma: no cover - corrupt installation path
        raise RuntimeError("jsonschema distribution metadata is unavailable") from exc
    if installed_version != "4.25.1":
        raise RuntimeError(
            f"runtime requires jsonschema 4.25.1, found {installed_version}"
        )
    if vendor_selected:
        vendor_root = _VENDOR.resolve()
        module_paths = (
            Path(jsonschema.__file__).resolve(),
            Path(referencing.__file__).resolve(),
        )
        if any(not path.is_relative_to(vendor_root) for path in module_paths):
            raise RuntimeError(
                "vendored schema packages were selected but incompatible modules were already loaded"
            )
    return (
        jsonschema.Draft202012Validator,
        jsonschema.FormatChecker,
        referencing.Registry,
        referencing.Resource,
    )


@lru_cache(maxsize=None)
def _contract_validator(schema_name: str):
    Draft202012Validator, FormatChecker, Registry, Resource = _jsonschema_types()
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_SCHEMA_ROOT.glob("*.schema.json"))
    ]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    try:
        target = next(
            schema for schema in schemas if schema["$id"].endswith(f"/{schema_name}")
        )
    except StopIteration as exc:
        raise ValueError(f"unknown runtime contract {schema_name!r}") from exc
    return Draft202012Validator(
        target, registry=registry, format_checker=FormatChecker()
    )


def validate_contract(
    instance: object, schema_name: str, description: str
) -> dict[str, Any]:
    """Validate and return a detached strict-JSON contract object.

    The detached return value prevents validation callers from retaining
    aliases into mutable input mappings.
    """

    if not isinstance(instance, Mapping):
        raise ContractValidationError(f"{description} must be an object")
    try:
        detached = json.loads(canonical_json_bytes(instance))
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{description} is not strict JSON: {exc}") from exc
    errors = sorted(
        _contract_validator(schema_name).iter_errors(detached),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ContractValidationError(
            f"{description} fails {schema_name} at {location or '/'}: {error.message}"
        )
    return detached
