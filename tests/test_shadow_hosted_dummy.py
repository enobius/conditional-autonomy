import json
import copy
from contextlib import contextmanager
import io
import os
from pathlib import Path
import unittest
import subprocess
import tempfile
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
            with patch('sys.stdout', new=io.StringIO()):
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

    def assert_safe_workflow(self, workflow):
        raw = json.dumps(workflow)
        self.assertEqual(set(workflow), {'name', 'on', 'permissions', 'jobs'})
        self.assertEqual(set(workflow['on']), {'pull_request', 'push', 'workflow_dispatch'})
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        paths = ['.github/workflows/shadow-hosted-dummy.yml',
                 '.github/workflows/claude-review-isolated.yml',
                 '.github/shadow-provider-policy.json', 'tests/**', 'tools/**']
        self.assertEqual(workflow['on']['pull_request'], {'paths': paths})
        self.assertEqual(workflow['on']['push']['paths'], paths)
        self.assertEqual(workflow['permissions'], {})
        self.assertNotIn('secrets.', raw)
        self.assertNotIn('actions/cache', raw)
        self.assertNotIn('pull_request_target', raw)
        self.assertEqual(workflow['jobs']['artifact-check']['needs'], 'probe')
        self.assertEqual(sum(step.get('run') == 'python -m tests.shadow_adversarial_host'
                             for step in workflow['jobs']['probe']['steps']), 1)
        native = [step for step in workflow['jobs']['probe']['steps']
                  if step.get('name') == 'Rehearse pinned native CLI with dummy OAuth and isolated TLS']
        self.assertEqual(len(native), 1)
        self.assertEqual(set(native[0]), {'name', 'run'})
        self.assertEqual(native[0]['run'], 'binary=$(python -m tools.install_claude_shadow)\n'
                         'python -m tests.shadow_native_tls_probe --binary "$binary"\n')
        self.assertEqual(set(workflow['jobs']), {'probe', 'artifact-check'})
        for name, job in workflow['jobs'].items():
            self.assertEqual(set(job), {'runs-on', 'timeout-minutes', 'permissions', 'steps'} |
                             ({'outputs'} if name == 'probe' else {'needs'}))
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertEqual(job['permissions'], {'contents': 'read'} if name == 'probe'
                             else {'contents': 'read', 'actions': 'read'})
            for step in job['steps']:
                self.assertLessEqual(set(step), {'name', 'id', 'uses', 'with'} if 'uses' in step
                                     else {'name', 'env', 'run'})
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'@[a-f0-9]{40}$')
                    if step['uses'].startswith('actions/checkout@'):
                        self.assertEqual(step['with']['persist-credentials'], 'false')

    def test_workflow_has_no_secrets_cache_or_write_permissions(self):
        workflow = yaml.load(Path('.github/workflows/shadow-hosted-dummy.yml').read_text(),
                             Loader=UniqueBaseLoader)
        self.assert_safe_workflow(workflow)

    def test_step_overrides_are_rejected(self):
        original = yaml.load(Path('.github/workflows/shadow-hosted-dummy.yml').read_text(),
                             Loader=UniqueBaseLoader)
        for key, value in [('shell', 'bash'), ('if', '${{ false }}')]:
            workflow = copy.deepcopy(original)
            workflow['jobs']['probe']['steps'][0][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.assert_safe_workflow(workflow)

    def exercise_probe(self, fault=None):
        token = 'dummy-hosted-' + 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credential = root / 'provider.env'
            order = []

            @contextmanager
            def secret(_token):
                self.assertEqual(_token, token)
                credential.write_text(token)
                try:
                    yield credential
                finally:
                    order.append('unlink')
                    if fault != 'surviving-secret':
                        credential.unlink(missing_ok=True)

            @contextmanager
            def topology(_tools, origin, path):
                self.assertEqual(origin, 'provider.example')
                self.assertEqual(path, credential)
                try:
                    yield 'fake-network'
                finally:
                    order.append('teardown')
                    self.assertTrue(credential.exists())
                    if fault == 'early-unlink':
                        credential.unlink()

            def execute(args):
                if args[:2] == ['network', 'inspect']:
                    return json.dumps([{'Containers': {'fake-proxy': {}}}]).encode()
                self.assertEqual(args, ['inspect', 'fake-proxy'])
                return json.dumps([{'Mounts': [] if fault == 'missing-mount' else [{
                    'Destination': '/run/shadow-provider.env', 'RW': fault == 'writable-mount'}],
                    'canary': token if fault == 'config-leak' else ''}]).encode()

            output = subprocess.CompletedProcess([], 1 if fault == 'logs-failed' else 0,
                stdout=token.encode() if fault == 'stdout-leak' else b'',
                stderr=token.encode() if fault == 'stderr-leak' else b'')
            with patch.dict(os.environ, self.environment), patch.object(hosted.secrets, 'token_hex',
                    return_value='a' * 64), patch.object(hosted, 'secret_file', secret), patch.object(
                    hosted.network, 'topology', topology), patch.object(hosted.network, 'execute', execute), \
                    patch.object(hosted.subprocess, 'run', return_value=output) as logs, \
                    patch('sys.stdout', new=io.StringIO()):
                hosted.probe(root / 'result')
                self.assertEqual(order, ['teardown', 'unlink'])
                self.assertEqual(logs.call_args.args[0], ['docker', 'logs', 'fake-proxy'])
                self.assertTrue(logs.call_args.kwargs['capture_output'])
                self.assertEqual(logs.call_args.kwargs['env'], hosted.docker_env())
                self.assertEqual(logs.call_args.kwargs['timeout'], 30)
                raw = (root / 'result/result.json').read_bytes()
                self.assertNotIn(token.encode(), raw)
                self.assertTrue(json.loads(raw)['credential_unlinked'])

    def test_probe_success_and_cleanup_order(self):
        self.exercise_probe()

    def test_probe_rejects_leaks_mount_and_cleanup_failures(self):
        for fault in ['config-leak', 'stdout-leak', 'stderr-leak', 'logs-failed',
                      'missing-mount', 'writable-mount', 'early-unlink', 'surviving-secret']:
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.exercise_probe(fault)


if __name__ == '__main__':
    unittest.main()
