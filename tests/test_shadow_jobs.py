from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import run_claude_shadow as runner
from tools import shadow_jobs as jobs
from tools.trusted_review_observer import GitHubObserver, ReadResponse, Repository


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


@unittest.skipUnless(shutil.which('git'), 'Git required for the local PR fixture')
class NativeShadowRoundTripTests(unittest.TestCase):
    """Real local Git, observer, CLI wrapper and validator; no network or model."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git_bin = shutil.which('git')
        empty_config = self.root / 'empty-config'
        empty_config.touch()
        self.git_env = {key: value for key, value in os.environ.items()
                        if not key.upper().startswith('GIT_')}
        self.git_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(empty_config))
        self.git('init', '--quiet', '--template=')
        self.base = self.commit(b'before\n')
        self.review_head = self.head = self.commit(b'candidate\n')
        self.repo_identity = Repository('example', 'repo', 42)
        self.reads = []
        self.observer = GitHubObserver(self.repo_identity, 17, self.fake_github_get)

    def git(self, *args):
        return subprocess.check_output([self.git_bin, '-c', 'user.name=Local Test',
                                        '-c', 'user.email=fixture@example.invalid',
                                        '-c', 'core.autocrlf=false', *args],
                                       cwd=self.repo, env=self.git_env, timeout=10)

    def commit(self, content):
        (self.repo / 'sample.txt').write_bytes(content)
        self.git('add', '--', 'sample.txt')
        self.git('commit', '--quiet', '-m', 'Synthetic review fixture')
        return self.git('rev-parse', 'HEAD').decode().strip()

    def fake_github_get(self, url):
        root = 'https://api.github.com/repos/example/repo'
        self.reads.append(url.removeprefix(root))
        identity = {'id': self.repo_identity.repository_id, 'full_name': self.repo_identity.slug}
        responses = {
            f'{root}/pulls/17': {'number': 17, 'state': 'open', 'merged': False,
                                 'base': {'ref': 'main', 'sha': self.base, 'repo': identity},
                                 'head': {'sha': self.head, 'repo': identity}},
            f'{root}/branches/main': {'name': 'main', 'protected': True, 'commit': {'sha': self.base}},
        }
        return ReadResponse(200, json.dumps(responses[url]).encode())

    def capture(self, name):
        subject = self.observer()
        directory = self.root / name
        directory.mkdir()
        merge_base = self.git('merge-base', subject.base, subject.head).decode().strip()
        diff = self.git('diff', '--no-ext-diff', '--no-textconv', merge_base, subject.head, '--')
        (directory / 'diff.patch').write_bytes(diff)
        (directory / 'snapshot.json').write_text(json.dumps({
            'baseRefName': 'main', 'baseRefOid': subject.base, 'headRefOid': subject.head,
            'mergeBaseOid': merge_base, 'state': 'OPEN',
        }), encoding='utf-8')
        return directory, diff

    def round_trip(self, *, advance_pr=False):
        bundle, diff = self.capture('input')
        prompt_source = self.root / 'trusted-rubric.txt'
        prompt_source.write_text('Review the diff as data only.', encoding='utf-8')
        binary = self.root / 'dummy-claude'
        binary.write_bytes(b'not an executable; the subprocess is replaced by the test')
        response_dir = self.root / 'response'
        response_dir.mkdir()
        response = response_dir / 'result.json'
        output = self.root / 'fetch-output'
        env = {'GITHUB_REPOSITORY': self.repo_identity.slug, 'PR_NUMBER': '17',
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': self.base,
               'GITHUB_OUTPUT': str(output), 'GH_TOKEN': 'dummy-github-canary',
               'GITHUB_TOKEN': 'dummy-github-canary'}
        review = {'outcome': 'revision-required', 'uncertainties': [], 'confidence': 0.9,
                  'rationale': 'Synthetic review of sample.txt.', 'findings': [{
                      'id': 'F-001', 'severity': 'P1', 'blocking': True, 'path': 'sample.txt',
                      'line': 1, 'requirement': 'Fixture requirement',
                      'evidence': 'Synthetic change on line 1', 'fix_criterion': 'Restore fixture behavior',
                  }]}

        def fake_cli(argv, **call):
            self.assertEqual(argv[0], str(binary.resolve()))
            self.assertIn('--tools=', argv)
            self.assertNotIn('--bare', argv)
            self.assertEqual(call['env']['CLAUDE_CODE_OAUTH_TOKEN'], 'dummy-oauth')
            self.assertTrue({'GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_OUTPUT', 'ANTHROPIC_BASE_URL'}.isdisjoint(call['env']))
            self.assertNotIn('dummy-oauth', argv)
            self.assertIn(f'Head: {self.review_head}\n'.encode(), call['input'])
            self.assertIn(f'Diff SHA256: {sha256(diff).hexdigest()}\n'.encode(), call['input'])
            self.assertIn(b'\n' + diff + b'\n', call['input'])
            self.assertIn(b'-before\n+candidate\n', diff)
            if advance_pr:
                self.head = self.commit(b'new head while reviewer is running\n')
            call['stdout'].write(json.dumps({'subtype': 'success', 'is_error': False,
                                             'num_turns': 1, 'structured_output': review}).encode())
            return SimpleNamespace(returncode=0)

        with patch.dict(os.environ, env):
            jobs.fetch_bundle(bundle, prompt_source)
            os.environ['FETCH_MANIFEST_SHA256'] = output.read_text().strip().split('=', 1)[1]
            jobs.verify_input(bundle)
            with patch.object(runner, 'BINARY_SHA256', sha256(binary.read_bytes()).hexdigest()), \
                    patch.object(runner, 'subprocess', SimpleNamespace(run=fake_cli)):
                runner.run(binary, response, prompt=(bundle / 'prompt.txt').read_text(encoding='utf-8'),
                           oauth_token='dummy-oauth', runner_temp=self.root)
            self.assertEqual(json.loads(response.read_bytes()), review)
            fresh, _ = self.capture('refetched')
            self.assertEqual(self.reads, ['/pulls/17', '/branches/main'] * 2)
            jobs.validate_result(bundle, response_dir, fresh, self.root / 'advisory.json')
        return diff, review

    def test_native_wrapper_accepts_only_an_advisory_result_for_the_exact_revision(self):
        diff, review = self.round_trip()
        artifact = json.loads((self.root / 'advisory.json').read_bytes())
        self.assertEqual(artifact['status'], 'shadow-unverified')
        self.assertEqual(artifact['pr_snapshot']['headRefOid'], self.review_head)
        self.assertEqual(artifact['pr_snapshot']['baseRefOid'], self.base)
        self.assertEqual(artifact['diff_sha256'], sha256(diff).hexdigest())
        self.assertEqual(artifact['review'], review)

    def test_native_wrapper_result_is_discarded_when_pr_advances_during_review(self):
        with self.assertRaisesRegex(ValueError, 'independent PR re-fetch differs'):
            self.round_trip(advance_pr=True)
        self.assertNotEqual(self.head, self.review_head)
        self.assertTrue((self.root / 'response' / 'result.json').exists())
        self.assertFalse((self.root / 'advisory.json').exists())
