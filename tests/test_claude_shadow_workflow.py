"""Offline tests for manual shadow review input and output handling."""
import json
from pathlib import Path
import tempfile
import unittest

from runtime.conditional_autonomy.review_verdict import ReviewVerdictError
from tools.claude_shadow_workflow import load_snapshot, prepare, validate

METADATA = {'repository': 'example/repo', 'pr_number': '12', 'run_id': '123'}

class ShadowWorkflowTests(unittest.TestCase):
    def test_shadow_review_snapshots_and_untrusted_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after, diff, prompt, output, artifact = (
                root / name for name in ('before', 'after', 'diff', 'prompt', 'output', 'artifact'))
            snapshot = {'state': 'OPEN', 'baseRefName': 'main', 'headRefOid': 'a' * 40, 'baseRefOid': 'b' * 40}
            for path in (before, after):
                path.write_text(json.dumps(snapshot), encoding='utf-8')
            diff.write_bytes(b'diff --git a/file b/file\n+untrusted text\n')
            prompt.write_text('Trusted instructions', encoding='utf-8')
            prepare(diff, before, prompt, output)
            rendered = output.read_text(encoding='utf-8')
            self.assertIn('Trusted instructions', rendered)
            self.assertIn('<untrusted_diff>', rendered)
            result = {'outcome': 'approve', 'findings': [], 'uncertainties': [],
                      'confidence': 0.9, 'rationale': 'synthetic test'}
            validate(json.dumps(result).encode(), before, after, diff, artifact, **METADATA)
            saved = json.loads(artifact.read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'shadow-unverified')
            self.assertEqual(saved['review'], result)
            self.assertEqual(saved['repository'], 'example/repo')
            self.assertEqual(saved['pr_number'], 12)
            self.assertEqual(saved['requested_model'], 'claude-opus-5-5')
            self.assertEqual(len(saved['diff_sha256']), 64)
            after.write_text(json.dumps(dict(snapshot, headRefOid='c' * 40)), encoding='utf-8')
            with self.assertRaises(ReviewVerdictError):
                validate(json.dumps(result).encode(), before, after, diff, artifact, **METADATA)

    def test_fails_closed_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after, diff, prompt, output = (root / n for n in ('before', 'after', 'diff', 'prompt', 'output'))
            snapshot = {'state': 'OPEN', 'baseRefName': 'main', 'headRefOid': 'a' * 40, 'baseRefOid': 'b' * 40}
            for path in (before, after):
                path.write_text(json.dumps(snapshot), encoding='utf-8')
            diff.write_bytes(b'')
            prompt.write_text('test', encoding='utf-8')
            with self.assertRaises(ReviewVerdictError):
                prepare(diff, before, prompt, output)
            diff.write_bytes(b'X' * 200_001)
            with self.assertRaises(ReviewVerdictError):
                prepare(diff, before, prompt, output)
            diff.write_bytes(b'diff')
            for raw in (b'', b'{}', b'{"x":1,"x":2}', b'\xff'):
                with self.subTest(raw=raw), self.assertRaises((ReviewVerdictError, ValueError, UnicodeError)):
                    validate(raw, before, after, diff, output, **METADATA)
            with self.assertRaises(ReviewVerdictError):
                validate(b'{}', before, after, diff, output,
                         repository='example/repo', pr_number='0', run_id='123')
            before.write_text(json.dumps(dict(snapshot, state='CLOSED')), encoding='utf-8')
            with self.assertRaises(ReviewVerdictError):
                load_snapshot(before)
            before.write_text(json.dumps(dict(snapshot, baseRefName='other')), encoding='utf-8')
            with self.assertRaises(ReviewVerdictError):
                load_snapshot(before)


if __name__ == '__main__':
    unittest.main()
