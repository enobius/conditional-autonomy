import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml
from tests.test_claude_shadow_workflow import UniqueBaseLoader
from tests import shadow_hosted_dummy as hosted


class HostedDummyTests(unittest.TestCase):
    def setUp(self):
        self.environment = {'GITHUB_REPOSITORY': 'owner/repo', 'RESULT_ARTIFACT_ID': '17',
                            'GITHUB_RUN_ID': '23', 'GITHUB_RUN_ATTEMPT': '1',
                            'GITHUB_SHA': 'a' * 40, 'GH_TOKEN': 'test-github-token'}
        self.result = {'kind': 'hosted-dummy-evidence-v1', 'run_id': '23',
                       'run_attempt': '1', 'commit': 'a' * 40,
                       'config_and_log_canary_absent': True, 'credential_unlinked': True,
                       'provider_requests': 0}

    def verify(self, responses):
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
                hosted, 'download', side_effect=responses) as downloader:
            hosted.verify_artifact()
            return downloader

    def test_real_download_entry_and_wrong_run_are_exercised(self):
        mock = self.verify([json.dumps(self.result).encode(), ValueError('wrong run')])
        self.assertEqual(mock.call_args_list[0].args[:3], ('owner/repo', '17', '23'))
        self.assertEqual(mock.call_args_list[1].args[:3], ('owner/repo', '17', '24'))

    def test_wrong_run_acceptance_fails(self):
        raw = json.dumps(self.result).encode()
        with self.assertRaisesRegex(ValueError, 'wrong-run'):
            self.verify([raw, raw])

    def test_binding_and_lifecycle_failures_are_rejected(self):
        for key, value in [('commit', 'b' * 40), ('run_attempt', '2'),
                           ('credential_unlinked', False), ('provider_requests', 1),
                           ('config_and_log_canary_absent', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify([json.dumps({**self.result, key: value}).encode()])

    def test_canaries_are_rejected(self):
        for canary in ['test-github-token', 'dummy-hosted-123']:
            with self.subTest(canary=canary), self.assertRaisesRegex(ValueError, 'canary'):
                self.verify([json.dumps({**self.result, 'extra': canary}).encode()])

    def test_workflow_has_no_secrets_cache_or_write_permissions(self):
        raw = Path('.github/workflows/shadow-hosted-dummy.yml').read_text()
        workflow = yaml.load(raw, Loader=UniqueBaseLoader)
        self.assertEqual(set(workflow['on']), {'pull_request', 'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {})
        self.assertNotIn('secrets.', raw)
        self.assertNotIn('actions/cache', raw)
        self.assertNotIn('pull_request_target', raw)
        self.assertEqual(workflow['jobs']['artifact-check']['needs'], 'probe')
        for job in workflow['jobs'].values():
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertTrue(all(value == 'read' for value in job['permissions'].values()))
            for step in job['steps']:
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'@[a-f0-9]{40}$')
                    if step['uses'].startswith('actions/checkout@'):
                        self.assertEqual(step['with']['persist-credentials'], 'false')


if __name__ == '__main__':
    unittest.main()
