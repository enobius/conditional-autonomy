"""Adversarial syntax and schema tests; these do not prove reviewer origin."""
import copy
import json
import unittest

from runtime.conditional_autonomy.review_verdict import ReviewVerdictError, parse_review_verdict


def sample():
    return {
        'schema_version': '1.0', 'repository': {'id': 1, 'full_name': 'example/repo'},
        'pr_number': 1, 'head_sha': 'a' * 40, 'base_sha': 'b' * 40,
        'diff_sha256': 'c' * 64, 'review_run_id': 'review-1',
        'reviewer': {'vendor': 'review-vendor', 'model': 'test', 'run_id': 'review-1'},
        'implementer': {'vendor': 'other-vendor', 'model': 'test', 'run_id': 'build-1'},
        'rubric_sha256': 'd' * 64, 'evidence_sha256': 'e' * 64,
        'attempt': 1, 'outcome': 'approve', 'findings': [], 'uncertainties': [],
        'confidence': 0.9, 'rationale': 'synthetic fixture only',
    }


def finding():
    return {'id': 'F-001', 'severity': 'P1', 'blocking': True,
            'path': 'runtime/example.py', 'line': 1, 'requirement': 'example',
            'evidence': 'example', 'fix_criterion': 'example'}


def encode(value):
    return json.dumps(value).encode()


class ReviewVerdictTests(unittest.TestCase):
    def test_each_outcome_and_repository_scope(self):
        approve = sample()
        revise = sample()
        revise.update(outcome='revision-required', findings=[finding()])
        escalate = sample()
        escalate.update(outcome='escalate-to-human', uncertainties=['missing evidence'])
        repository = copy.deepcopy(revise)
        repository['findings'][0].update(path='@repository', line=None)
        for value in (approve, revise, escalate, repository):
            with self.subTest(outcome=value['outcome']):
                self.assertEqual(parse_review_verdict(encode(value)), value)

    def test_duplicate_keys_nonfinite_malformed_and_size_rejected(self):
        for raw in (b'{"a": 1, "a": 2}', b'{"x": NaN}', b'{"x": Infinity}',
                    b'\xff', b'{', b' ' * (1024 * 1024 + 1)):
            with self.subTest(raw=raw[:30]), self.assertRaises(ReviewVerdictError):
                parse_review_verdict(raw)
        raw = encode(sample()).replace(b'0.9', b'1e999')
        with self.assertRaises(ReviewVerdictError):
            parse_review_verdict(raw)

    def test_contradictions_unknown_versions_and_severity_fail(self):
        invalid = []
        base = sample()
        invalid.extend([dict(base, schema_version='2.0'), dict(base, surprise=True),
                        dict(base, outcome='revision-required'),
                        dict(base, outcome='escalate-to-human'),
                        dict(base, findings=[finding()]), dict(base, attempt=4),
                        dict(base, confidence=1.1), dict(base, head_sha='short')])
        bad_finding = finding()
        bad_finding['blocking'] = False
        invalid.append(dict(base, outcome='revision-required', findings=[bad_finding]))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ReviewVerdictError):
                parse_review_verdict(encode(value))

    def test_unsafe_paths_and_duplicate_ids_fail(self):
        for path in ('../outside', '/absolute', 'a/../b', 'a//b', 'a/./b',
                     'C:/file', 'a\\b', '@repository'):
            value = sample()
            item = finding()
            item['path'] = path
            value.update(outcome='revision-required', findings=[item])
            with self.subTest(path=path), self.assertRaises(ReviewVerdictError):
                parse_review_verdict(encode(value))
        value = sample()
        value.update(outcome='revision-required', findings=[finding(), finding()])
        with self.assertRaises(ReviewVerdictError):
            parse_review_verdict(encode(value))

    def test_untrusted_self_claim_does_not_create_authority(self):
        value = sample()
        value['reviewer'] = copy.deepcopy(value['implementer'])
        # Structural parser may preserve the claim; no authority API is exposed.
        self.assertEqual(parse_review_verdict(encode(value)), value)
        self.assertNotIn('authorized', parse_review_verdict(encode(value)))


if __name__ == '__main__':
    unittest.main()
