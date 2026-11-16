import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import shadow_jobs as jobs


class ShadowJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle, self.fresh, self.result = [self.root / name for name in ('input', 'fresh', 'result')]
        for path in (self.bundle, self.fresh, self.result):
            path.mkdir()
        snapshot = {'baseRefName': 'main', 'state': 'OPEN', 'baseRefOid': 'b' * 40,
                    'headRefOid': 'c' * 40, 'mergeBaseOid': 'd' * 40}
        for directory in (self.bundle, self.fresh):
            (directory / 'snapshot.json').write_text(json.dumps(snapshot), encoding='utf-8')
            (directory / 'diff.patch').write_bytes(b'diff --git a/f b/f\n@@ -1 +1 @@\n-a\n+b\n')
        source = self.root / 'trusted-prompt'
        source.write_text('Trusted test instructions', encoding='utf-8')
        env = {'GITHUB_REPOSITORY': 'example/repo', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_SHA': 'a' * 40, 'PR_NUMBER': '42', 'GITHUB_OUTPUT': str(self.root / 'outputs')}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)
        jobs.fetch_bundle(self.bundle, source)
        self.digest = (self.root / 'outputs').read_text().strip().split('=')[1]
        os.environ['FETCH_MANIFEST_SHA256'] = self.digest
        self.verdict = {'outcome': 'approve', 'findings': [], 'uncertainties': [],
                        'confidence': 0.5, 'rationale': 'synthetic test only'}
        (self.result / 'result.json').write_text(json.dumps(self.verdict), encoding='utf-8')

    def test_data_only_fetch_and_final_validation(self):
        self.assertNotIn('prompt<<', (self.bundle / 'prompt.txt').read_text())
        jobs.verify_input(self.bundle)
        destination = self.root / 'validated.json'
        jobs.validate_result(self.bundle, self.result, self.fresh, destination)
        self.assertEqual(json.loads(destination.read_text())['status'], 'shadow-unverified')
        self.assertNotIn('Trusted test instructions', (self.root / 'outputs').read_text())

    def test_tampering_refetch_and_cross_attempt_replay_rejected(self):
        destination = self.root / 'must-not-exist'
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}), self.assertRaises(ValueError):
            jobs.validate_result(self.bundle, self.result, self.fresh, destination)
        (self.fresh / 'diff.patch').write_bytes(b'forged fresh diff')
        with self.assertRaises(ValueError):
            jobs.validate_result(self.bundle, self.result, self.fresh, destination)
        self.assertFalse(destination.exists())
        (self.bundle / 'prompt.txt').write_bytes(b'forged')
        with self.assertRaises(ValueError):
            jobs.verify_input(self.bundle)

    def test_result_inventory_and_disabled_policy_stop_before_provider(self):
        (self.result / 'execute.py').write_text('must never execute')
        with self.assertRaises(ValueError):
            jobs.validate_result(self.bundle, self.result, self.fresh, self.root / 'reject')
        policy = self.root / 'disabled.json'
        policy.write_text('{"version":"shadow-provider-policy-1","enabled":false,"origin":null}')
        with patch.object(jobs, 'isolated_run') as isolated, self.assertRaises(ValueError):
            jobs.review(self.bundle, 'unused', policy, self.root / 'review')
        isolated.assert_not_called()

    def test_mocked_provider_still_requires_bound_inputs_and_new_result(self):
        policy = self.root / 'test-policy.json'
        policy.write_text('{"version":"shadow-provider-policy-1","enabled":true,"origin":"provider.example"}')
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'dummy-only'}), \
             patch.object(jobs, 'isolated_run', return_value=json.dumps(self.verdict).encode()) as isolated:
            destination = self.root / 'new-result'
            jobs.review(self.bundle, 'unused', policy, destination)
            self.assertEqual(json.loads(destination.read_text()), self.verdict)
            self.assertEqual(isolated.call_args.args[3], 'dummy-only')
            with self.assertRaises(ValueError):
                jobs.review(self.bundle, 'unused', policy, destination)
            self.assertEqual(isolated.call_count, 1)
