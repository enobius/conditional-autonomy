"""Assemble a review candidate in shadow mode; never authorize a merge.

The caller must independently establish the origin of context and response.
The functions here do not authenticate Claude, enforce a retry budget, or post
GitHub checks. They are usable with synthetic fixtures without credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json

from .review_verdict import ReviewVerdictError, parse_review_verdict, _object, _constant, _validator


@dataclass(frozen=True)
class ReviewContext:
    repository_id: int
    repository_name: str
    pr_number: int
    head_sha: str
    base_sha: str
    review_run_id: str
    reviewer_vendor: str
    reviewer_model: str
    reviewer_run_id: str
    implementer_vendor: str
    implementer_model: str
    implementer_run_id: str
    rubric_sha256: str
    attempt: int


def model_output_schema() -> dict:
    """Derive Claude's response schema from the pinned full verdict schema.

    Context and identity fields are deliberately omitted: the model cannot be
    the source of the metadata that the orchestrator later binds to its review.
    """
    schema = _validator().schema
    fields = ('outcome', 'findings', 'uncertainties', 'confidence', 'rationale')
    return deepcopy({
        '$schema': schema['$schema'],
        'type': 'object',
        'additionalProperties': False,
        'required': list(fields),
        'properties': {key: schema['properties'][key] for key in fields},
        '$defs': schema['$defs'],
        'allOf': schema['allOf'],
    })


def assemble_shadow_verdict(response: bytes, diff: bytes, context: ReviewContext) -> dict:
    """Bind bounded, untrusted model output to caller-supplied metadata.

    Neither the caller-supplied metadata nor the response is authenticated by
    this helper. Verification and publication must be implemented separately.
    """
    if not isinstance(response, bytes) or len(response) > 1024 * 1024:
        raise ReviewVerdictError('model response must be bounded bytes')
    if not isinstance(diff, bytes):
        raise ReviewVerdictError('diff must be bytes')
    if not isinstance(context, ReviewContext):
        raise ReviewVerdictError('review context missing')
    if (not isinstance(context.reviewer_vendor, str) or
            not isinstance(context.implementer_vendor, str) or
            not context.reviewer_vendor.strip() or not context.implementer_vendor.strip() or
            context.reviewer_vendor.strip().casefold() == context.implementer_vendor.strip().casefold()):
        raise ReviewVerdictError('review and implementation vendors must differ')
    try:
        result = json.loads(response.decode('utf-8'), object_pairs_hook=_object,
                            parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReviewVerdictError('invalid model response JSON') from exc
    allowed = {'outcome', 'findings', 'uncertainties', 'confidence', 'rationale'}
    if not isinstance(result, dict) or set(result) != allowed:
        raise ReviewVerdictError('model result fields do not match response contract')
    candidate = {
        'schema_version': '1.0',
        'repository': {'id': context.repository_id, 'full_name': context.repository_name},
        'pr_number': context.pr_number,
        'head_sha': context.head_sha,
        'base_sha': context.base_sha,
        'diff_sha256': hashlib.sha256(diff).hexdigest(),
        'review_run_id': context.review_run_id,
        'reviewer': {'vendor': context.reviewer_vendor, 'model': context.reviewer_model,
                     'run_id': context.reviewer_run_id},
        'implementer': {'vendor': context.implementer_vendor, 'model': context.implementer_model,
                        'run_id': context.implementer_run_id},
        'rubric_sha256': context.rubric_sha256,
        'evidence_sha256': hashlib.sha256(response).hexdigest(),
        'attempt': context.attempt,
        **result,
    }
    try:
        serialized = json.dumps(candidate, allow_nan=False, ensure_ascii=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReviewVerdictError('invalid model response values') from exc
    return parse_review_verdict(serialized)


def check_shadow_binding(verdict: bytes, diff: bytes, context: ReviewContext,
                         raw_response: bytes) -> dict:
    """Check a candidate against a separately obtained snapshot, not authority.

    The caller must authenticate both the context and raw model response. This
    comparison alone is not an attestation or permission to publish a check.
    """
    actual = parse_review_verdict(verdict)
    expected = assemble_shadow_verdict(raw_response, diff, context)
    if actual != expected:
        raise ReviewVerdictError('verdict does not match supplied review snapshot')
    return actual
