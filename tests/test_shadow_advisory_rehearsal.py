import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

from tests import shadow_advisory_rehearsal as rehearsal
from tests.test_claude_shadow_workflow import UniqueBaseLoader
from tools import trusted_review_guard as guard


class AdvisoryRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.env = {'GITHUB_REPOSITORY': rehearsal.REPOSITORY.slug,
                    'GITHUB_REPOSITORY_ID': str(rehearsal.REPOSITORY.repository_id),
                    'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_RUN_ID': '17',
                    'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40, 'PR_NUMBER': '3',
                    'PR_BASE': 'b' * 40, 'PR_HEAD': 'c' * 40, 'GH_TOKEN': 'dummy-token'}
        self.raw = rehearsal.encoded({'kind': 'rehearsal-input-v1', 'base': 'b' * 40,
                                      'head': 'c' * 40, 'run_id': '17', 'run_attempt': '1'})

    def capture(self, env, check=None):
        with patch.object(rehearsal.Path, 'resolve', return_value=Path('/git')), patch.object(
                rehearsal, 'evaluate_registered', return_value=guard.Result(
                    guard.Decision.PROTECTED_CHANGE, ('file.txt',))) as verifier:
            raw = rehearsal.snapshot(env, git='/git')
            if check is not None:
                check(verifier)
        return raw

    def test_capture_binds_exact_event_revisions_and_excludes_token(self):
        def verify_call(check):
            self.assertEqual(check.call_args.kwargs['subject'], guard.Subject(
                1315590853, 3, 'b' * 40, 'c' * 40))
            self.assertEqual(check.call_args.kwargs['requested_policy_revision'],
                             '7c0fee2aac8f88167f167c330caac5eb120561d4')
        raw = self.capture(self.env, verify_call)
        self.assertNotIn(b'dummy-token', raw)
        self.assertEqual(json.loads(raw), {
            'kind': 'rehearsal-input-v1', 'repository_id': 1315590853, 'pr': 3,
            'base': 'b' * 40, 'head': 'c' * 40, 'workflow_sha': 'a' * 40,
            'policy_pin': '7c0fee2aac8f88167f167c330caac5eb120561d4',
            'run_id': '17', 'run_attempt': '1', 'protected_paths': ['file.txt'],
        })

    def test_each_invalid_snapshot_identity_is_rejected_before_git(self):
        cases = {'GITHUB_REPOSITORY': 'owner/other', 'GITHUB_REPOSITORY_ID': '1315590854',
                 'GITHUB_EVENT_NAME': 'pull_request_target', 'GITHUB_RUN_ID': '0',
                 'GITHUB_RUN_ATTEMPT': '01', 'PR_NUMBER': '0', 'PR_BASE': 'main',
                 'PR_HEAD': '0' * 40, 'GITHUB_SHA': '0' * 40}
        for field, bad in cases.items():
            # All other inputs stay valid. Stub mirror evaluation so nothing
            # downstream can make a missing identity check appear to pass.
            with self.subTest(field=field), patch.object(
                    rehearsal.Path, 'resolve', return_value=Path('/git')), patch.object(
                    rehearsal, 'evaluate_registered', return_value=guard.Result(
                        guard.Decision.PROTECTED_CHANGE, ())) as check:
                with self.assertRaises(ValueError):
                    rehearsal.snapshot(self.env | {field: bad}, git='/git')
                check.assert_not_called()

    def test_dummy_gets_only_input_and_no_network_or_host_mounts(self):
        canary = {'UNRELATED_HOST_ONLY': 'dummy'}
        run_result = subprocess.CompletedProcess([], 0, rehearsal.dummy_output(self.raw), b'')
        with patch.object(rehearsal, 'os', SimpleNamespace(environ=canary)), patch.object(
                rehearsal.subprocess, 'run', return_value=run_result) as run:
            self.assertEqual(rehearsal.invoke_dummy(self.raw), run_result.stdout)
        argv = run.call_args.args[0]
        self.assertRegex(argv[4], r'^ca-shadow-[0-9a-f]{32}$')
        self.assertEqual(argv[:-1], [
            'docker', 'run', '--rm', '--name', argv[4], '--pull', 'never',
            '--network', 'none', '--read-only', '--user', '65534:65534',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32',
            '--memory', '128m', '--cpus', '1', '--entrypoint', 'python', '-i',
            'python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39',
            '-I', '-B', '-S', '-c',
        ])
        self.assertNotIn('UNRELATED_HOST_ONLY', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['input'], self.raw)
        self.assertEqual(run.call_args.kwargs['timeout'], 45)
        with patch.object(rehearsal, 'os', SimpleNamespace(environ={'GH_TOKEN': 'dummy'})), patch.object(
                rehearsal.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'credential variable'):
                rehearsal.invoke_dummy(self.raw)
            run.assert_not_called()

    def test_dummy_rejects_each_bad_process_result_independently(self):
        correct = rehearsal.dummy_output(self.raw)
        for name, result in (
            ('exit status', subprocess.CompletedProcess([], 1, correct, b'')),
            ('stderr', subprocess.CompletedProcess([], 0, correct, b'unexpected diagnostic')),
            ('stdout', subprocess.CompletedProcess([], 0, b'{}', b'')),
        ):
            with self.subTest(check=name), patch.object(rehearsal, 'os', SimpleNamespace(environ={})), patch.object(
                    rehearsal.subprocess, 'run', return_value=result) as run:
                with self.assertRaisesRegex(ValueError, 'dummy reviewer failed or returned unbound output'):
                    rehearsal.invoke_dummy(self.raw)
                run.assert_called_once()

    def test_evidence_rejects_changed_identity_and_unsolicited_verdict(self):
        raw = self.capture(self.env)
        original = rehearsal.artifact(raw, rehearsal.dummy_output(raw))
        rehearsal.verify_artifact(original, raw)
        for drift in ({'PR_HEAD': 'd' * 40}, {'GITHUB_RUN_ATTEMPT': '2'},
                      {'GITHUB_RUN_ID': '18'}, {'GITHUB_SHA': 'e' * 40}):
            change = self.capture(self.env | drift)
            self.assertNotEqual(change, raw)
            with self.assertRaisesRegex(ValueError, 'fresh observation'):
                rehearsal.verify_artifact(original, change)
        with self.assertRaisesRegex(ValueError, 'invalid dummy response'):
            rehearsal.artifact(raw, b'{"verdict":"approve"}')

    def test_workflow_is_same_repo_pull_request_only_with_read_only_permissions(self):
        text = Path('.github/workflows/shadow-advisory-rehearsal.yml').read_text(encoding='utf-8')
        self.assertNotIn('secrets.', text)
        self.assertNotIn('actions/cache', text)
        doc = yaml.load(text, Loader=UniqueBaseLoader)
        self.assertEqual(set(doc), {'name', 'on', 'permissions', 'env', 'jobs'})
        self.assertEqual(set(doc['on']), {'pull_request'})
        self.assertEqual(doc['on']['pull_request']['branches'], ['main'])
        self.assertEqual(doc['permissions'], {})
        self.assertEqual(doc['env'], {'PR_NUMBER': '${{ github.event.pull_request.number }}',
                                     'PR_BASE': '${{ github.event.pull_request.base.sha }}',
                                     'PR_HEAD': '${{ github.event.pull_request.head.sha }}'})
        self.assertEqual(set(doc['jobs']), {'rehearsal', 'verify-artifact'})
        expected_actions = {
            'rehearsal': ['actions/checkout@11d5960a326750d5838078e36cf38b85af677262',
                          'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065',
                          'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'],
            'verify-artifact': ['actions/checkout@11d5960a326750d5838078e36cf38b85af677262',
                                'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065'],
        }
        for name, job in doc['jobs'].items():
            self.assertEqual(set(job), {'if', 'runs-on', 'timeout-minutes', 'permissions', 'steps',
                                       'outputs' if name == 'rehearsal' else 'needs'})
            self.assertEqual(job['if'], '${{ github.event.pull_request.head.repo.id == github.event.repository.id }}')
            self.assertEqual(job['permissions'], {'contents': 'read'} if name == 'rehearsal'
                             else {'contents': 'read', 'actions': 'read'})
            checkout = job['steps'][0]
            self.assertEqual(checkout['with']['ref'], '${{ github.event.pull_request.head.sha }}')
            self.assertEqual(checkout['with']['fetch-depth'], '0')
            self.assertEqual(checkout['with']['persist-credentials'], 'false')
            self.assertEqual([step['uses'] for step in job['steps'] if 'uses' in step],
                             expected_actions[name])
            for step in job['steps']:
                self.assertLessEqual(set(step), {'name', 'id', 'uses', 'with'} if 'uses' in step
                                     else {'name', 'env', 'run'})
                if 'GH_TOKEN' in step.get('env', {}):
                    self.assertTrue(' capture ' in step['run'] or step['run'].endswith(' verify'))
        self.assertEqual(doc['jobs']['verify-artifact']['needs'], 'rehearsal')
        produce = doc['jobs']['rehearsal']
        consume = doc['jobs']['verify-artifact']
        self.assertEqual(produce['steps'][3]['run'],
                         'docker pull python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39')
        self.assertEqual(produce['steps'][-1]['id'], 'result')
        self.assertEqual(produce['steps'][-1]['with']['path'],
                         '${{ runner.temp }}/advisory-rehearsal/result.json')
        self.assertEqual(produce['outputs'], {'artifact_id': '${{ steps.result.outputs.artifact-id }}'})
        self.assertEqual(consume['steps'][-1]['env'],
                         {'GH_TOKEN': '${{ github.token }}',
                          'RESULT_ARTIFACT_ID': '${{ needs.rehearsal.outputs.artifact_id }}'})
