"""Untrusted PR-review verdict parsing; never establishes authority by itself.

This module does not authenticate a reviewer, read GitHub, or publish checks.
Its output must not be interpreted as permission to merge.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path, PurePosixPath

from .contracts import _jsonschema_types


class ReviewVerdictError(ValueError):
    """Untrusted review data violates the structural verdict contract."""


_SCHEMA = Path(__file__).resolve().parents[2] / 'outputs' / 'S2_CR_01_Review_Verdict_SCHEMA_DRAFT.json'
_LIMIT = 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewVerdictError('duplicate JSON key')
        result[key] = value
    return result


def _constant(_value):
    raise ReviewVerdictError('non-finite JSON number')


@lru_cache(maxsize=1)
def _validator():
    validator, _, _, _ = _jsonschema_types()
    schema = json.loads(_SCHEMA.read_text(encoding='utf-8'))
    validator.check_schema(schema)
    return validator(schema)


def parse_review_verdict(data: bytes) -> dict:
    """Parse structural data only; provenance and revision binding remain external."""
    if not isinstance(data, bytes) or len(data) > _LIMIT:
        raise ReviewVerdictError('verdict must be bounded UTF-8 bytes')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_object,
                           parse_constant=_constant)
        errors = list(_validator().iter_errors(value))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReviewVerdictError('invalid verdict JSON') from exc
    if errors:
        raise ReviewVerdictError('verdict does not match versioned schema')
    validate_finding_structure(value['findings'])
    return value


def validate_finding_structure(findings: list) -> None:
    """Check finding IDs and canonical paths after schema validation."""
    seen = set()
    for finding in findings:
        if finding['id'] in seen:
            raise ReviewVerdictError('duplicate finding ID')
        seen.add(finding['id'])
        path = finding['path']
        if path == '@repository':
            if finding['line'] is not None:
                raise ReviewVerdictError('repository scope cannot have a line')
            continue
        relative = PurePosixPath(path)
        if ('\\' in path or ':' in path or relative.is_absolute() or
                not relative.parts or any(p in ('.', '..') for p in path.split('/')) or
                str(relative) != path or finding['line'] is None):
            raise ReviewVerdictError('finding path or line is not canonical')
