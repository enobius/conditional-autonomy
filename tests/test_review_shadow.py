"""Offline tests for the non-authoritative Claude verdict assembly boundary."""
from dataclasses import replace
import hashlib
import json
import unittest

from runtime.conditional_autonomy.review_shadow import ReviewContext, assemble_shadow_verdict, check_shadow_binding, model_output_schema
from runtime.conditional_autonomy.contracts import _jsonschema_types
from runtime.conditional_autonomy.review_verdict import ReviewVerdictError


def context():
    return ReviewContext(1, 'example/repo', 2, 'a' * 40, 'b' * 40, 'review-1',
                         'Anthropic', 'claude-opus-5-5', 'claude-run-1',
                         'OpenAI', 'implementation-model', 'build-1', 'c' * 64, 1)


def response(**updates):
    result = {'outcome': 'approve', 'findings': [], 'uncertainties': [],
              'confidence': 0.9, 'rationale': 'synthetic test'}
    result.update(updates)
    return json.dumps(result).encode()


class ReviewShadowTests(unittest.TestCase):
    def test_model_response_schema_rejects_asserted_identity_and_contradictions(self):
        validator_type, _, _, _ = _jsonschema_types()
        schema = model_output_schema()
        validator_type.check_schema(schema)
        validator = validator_type(schema)
        base = json.loads(response())
        self.assertTrue(validator.is_valid(base))
        self.assertFalse(validator.is_valid(dict(base, head_sha='a' * 40)))
        self.assertFalse(validator.is_valid(dict(base, outcome='revision-required')))
        self.assertFalse(validator.is_valid(dict(base, outcome='escalate-to-human')))

    def test_returned_schema_cannot_change_later_validation(self):
        exported = model_output_schema()
        exported['$defs']['finding']['properties']['blocking'] = {'const': False}
        value = {'id': 'F-001', 'severity': 'P1', 'blocking': True,
                 'path': 'runtime/a.py', 'line': 1, 'requirement': 'constraint',
                 'evidence': 'example', 'fix_criterion': 'fix'}
        result = assemble_shadow_verdict(
            response(outcome='revision-required', findings=[value]), b'diff', context())
        self.assertTrue(result['findings'][0]['blocking'])

    def test_binding_is_derived_from_context_and_exact_bytes(self):
        raw = response()
        diff = b'example diff\n'
        value = assemble_shadow_verdict(raw, diff, context())
        self.assertEqual(value['diff_sha256'], hashlib.sha256(diff).hexdigest())
        self.assertEqual(value['evidence_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['head_sha'], context().head_sha)
        self.assertEqual(value['reviewer']['model'], 'claude-opus-5-5')
        self.assertNotIn('authenticated', value)

    def test_stale_or_forged_binding_fails(self):
        raw, diff, ctx = response(), b'example diff', context()
        value = assemble_shadow_verdict(raw, diff, ctx)
        serialized = json.dumps(value).encode()
        self.assertEqual(check_shadow_binding(serialized, diff, ctx, raw), value)
        for changed_diff, changed_ctx, changed_raw in (
            (b'other diff', ctx, raw),
            (diff, replace(ctx, head_sha='d' * 40), raw),
            (diff, replace(ctx, base_sha='d' * 40), raw),
            (diff, replace(ctx, pr_number=3), raw),
            (diff, replace(ctx, reviewer_run_id='other-run'), raw),
            (diff, ctx, response(rationale='different evidence')),
        ):
            with self.subTest(context=changed_ctx), self.assertRaises(ReviewVerdictError):
                check_shadow_binding(serialized, changed_diff, changed_ctx, changed_raw)

    def test_model_cannot_override_revision_or_identity(self):
        for field in ('head_sha', 'reviewer', 'repository', 'diff_sha256'):
            with self.subTest(field=field), self.assertRaises(ReviewVerdictError):
                assemble_shadow_verdict(response(**{field: 'forged'}), b'diff', context())

    def test_contradictions_and_bad_context_fail(self):
        for raw in (response(outcome='revision-required'),
                    response(outcome='escalate-to-human'),
                    b'{"outcome":"approve","outcome":"approve"}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(ReviewVerdictError):
                assemble_shadow_verdict(raw, b'diff', context())
        for ctx in (replace(context(), reviewer_vendor=' openAI '),
                    replace(context(), head_sha='bad'), replace(context(), attempt=4)):
            with self.subTest(ctx=ctx), self.assertRaises(ReviewVerdictError):
                assemble_shadow_verdict(response(), b'diff', ctx)

    def test_revision_and_escalation_are_preserved(self):
        finding = {'id': 'F-001', 'severity': 'P1', 'blocking': True,
                   'path': 'runtime/a.py', 'line': 1, 'requirement': 'constraint',
                   'evidence': 'example', 'fix_criterion': 'correct the defect'}
        for raw, outcome in ((response(outcome='revision-required', findings=[finding]), 'revision-required'),
                             (response(outcome='escalate-to-human', uncertainties=['missing evidence']),
                              'escalate-to-human')):
            self.assertEqual(assemble_shadow_verdict(raw, b'diff', context())['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()
