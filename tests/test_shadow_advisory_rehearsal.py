from pathlib import Path
import subprocess
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

    def test_capture_binds_exact_event_revisions_and_excludes_token(self):
        with patch.object(rehearsal.Path, 'resolve', return_value=Path('/git')), patch.object(
                rehearsal, 'evaluate_registered', return_value=guard.Result(
                    guard.Decision.PROTECTED_CHANGE, ('file.txt',))) as check:
            raw = rehearsal.snapshot(self.env, git='/git')
        self.assertNotIn(b'dummy-token', raw)
        self.assertEqual(check.call_args.kwargs['subject'], guard.Subject(
            rehearsal.REPOSITORY.repository_id, 3, 'b' * 40, 'c' * 40))
        self.assertEqual(check.call_args.kwargs['requested_policy_revision'], rehearsal.POLICY_PIN)
        self.assertIn(b'"protected_paths":["file.txt"]', raw)
        with patch.object(rehearsal, 'evaluate_registered') as check:
            with self.assertRaises(ValueError):
                rehearsal.snapshot(self.env | {'GITHUB_EVENT_NAME': 'pull_request_target'})
            check.assert_not_called()

    def test_dummy_gets_only_input_and_no_network_or_host_mounts(self):
        canary = {'UNRELATED_HOST_ONLY': 'dummy'}
        run_result = subprocess.CompletedProcess([], 0, rehearsal.dummy_output(self.raw), b'')
        with patch.dict(rehearsal.os.environ, canary, clear=True), patch.object(
                rehearsal.subprocess, 'run', return_value=run_result) as run:
            self.assertEqual(rehearsal.invoke_dummy(self.raw), run_result.stdout)
        argv = run.call_args.args[0]
        for flag in ('--read-only', '--cap-drop', '--security-opt'):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        for flag in ('--env', '--env-file', '-e', '--mount', '-v', '--privileged'):
            self.assertNotIn(flag, argv)
        self.assertNotIn('UNRELATED_HOST_ONLY', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['input'], self.raw)
        with patch.dict(rehearsal.os.environ, {'GH_TOKEN': 'dummy'}, clear=True), patch.object(
                rehearsal.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'credential variable'):
                rehearsal.invoke_dummy(self.raw)
            run.assert_not_called()

    def test_evidence_rejects_changed_head_attempt_and_unsolicited_verdict(self):
        output = rehearsal.dummy_output(self.raw)
        original = rehearsal.artifact(self.raw, output)
        rehearsal.verify_artifact(original, self.raw)
        for change in (self.raw.replace(b'c' * 40, b'd' * 40),
                       self.raw.replace(b'"run_attempt":"1"', b'"run_attempt":"2"')):
            with self.assertRaisesRegex(ValueError, 'fresh observation'):
                rehearsal.verify_artifact(original, change)
        with self.assertRaisesRegex(ValueError, 'invalid dummy response'):
            rehearsal.artifact(self.raw, b'{"verdict":"approve"}')

    def test_workflow_is_same_repo_pull_request_only_with_read_only_permissions(self):
        text = Path('.github/workflows/shadow-advisory-rehearsal.yml').read_text(encoding='utf-8')
        self.assertNotIn('secrets.', text)
        self.assertNotIn('actions/cache', text)
        doc = yaml.load(text, Loader=UniqueBaseLoader)
        self.assertEqual(set(doc['on']), {'pull_request'})
        self.assertEqual(doc['permissions'], {})
        self.assertEqual(set(doc['jobs']), {'rehearsal', 'verify-artifact'})
        for name, job in doc['jobs'].items():
            self.assertEqual(job['if'], '${{ github.event.pull_request.head.repo.id == github.event.repository.id }}')
            self.assertEqual(job['permissions'], {'contents': 'read'} if name == 'rehearsal'
                             else {'contents': 'read', 'actions': 'read'})
            checkout = job['steps'][0]
            self.assertEqual(checkout['with']['ref'], '${{ github.event.pull_request.head.sha }}')
            self.assertEqual(checkout['with']['persist-credentials'], 'false')
            for step in job['steps']:
                if 'GH_TOKEN' in step.get('env', {}):
                    self.assertTrue(' capture ' in step['run'] or step['run'].endswith(' verify'))
        self.assertEqual(doc['jobs']['verify-artifact']['needs'], 'rehearsal')
