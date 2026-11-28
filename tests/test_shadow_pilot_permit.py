"""No-network tests for the one-run approval before the protected OAuth step."""
from contextlib import redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import shadow_artifact_binding as binding
from tools import shadow_jobs as jobs
from tools import shadow_pilot_permit as gate
import yaml
from tests.test_claude_shadow_workflow import UniqueBaseLoader

DIFF = b'''diff --git a/pilot-fixtures/synthetic-review.txt b/pilot-fixtures/synthetic-review.txt
new file mode 100644
index 0000000..c1ac6b3
--- /dev/null
+++ b/pilot-fixtures/synthetic-review.txt
@@ -0,0 +1,7 @@
+Synthetic reservation review fixture
+This record and rule are invented and are not executed.
+
+Rule: an unconfirmed reservation stays on hold.
+Record: TEST-0001
+Confirmed: false
+Disposition: approve
'''
BASE, HEAD = 'a' * 40, 'b' * 40
NOW = datetime(2026, 11, 25, 17, tzinfo=timezone.utc)
ENV = {'GITHUB_REPOSITORY': 'enobius/conditional-autonomy', 'GITHUB_REPOSITORY_ID': '1315590853',
       'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_ACTOR': 'enobius',
       'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': BASE, 'PR_NUMBER': '53',
       'SHADOW_BASE_SHA': BASE, 'SHADOW_HEAD_SHA': HEAD}
SNAPSHOT = {'baseRefName': 'main', 'baseRefOid': BASE, 'headRefOid': HEAD, 'mergeBaseOid': BASE, 'state': 'OPEN'}
PERMIT = {'version': 'shadow-pro-pilot-permit-1', 'origin': 'api.anthropic.com', 'run_id': '12345',
          'run_attempt': '1', 'pr_number': '53', 'base_sha': BASE, 'head_sha': HEAD,
          'diff_sha256': binding.digest(DIFF), 'expires_at': '2026-11-25T17:20:00Z'}


class PilotPermitTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'snapshot': SNAPSHOT, 'files': {'diff.patch': {'sha256': binding.digest(DIFF)}}}

    def check(self, *, permit=PERMIT, env=ENV, manifest=None, now=NOW):
        return gate.require_permit(json.dumps(permit), self.manifest if manifest is None else manifest, env, now=now)

    def test_frozen_synthetic_fixture_accepts_one_current_owner_run(self):
        self.assertEqual(len(DIFF), 408)
        self.assertEqual(binding.digest(DIFF), '0ad0a64edf21751af79788a62dcc03552b2143cb233eaffd6f5e1d3024c2eb80')
        self.assertIsNone(self.check())

    def test_same_approval_cannot_be_reused_for_new_run_rerun_other_actor_or_branch(self):
        for field, value in (
            ('GITHUB_RUN_ID', '12346'), ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_ACTOR', 'different-owner'),
            ('GITHUB_REF', 'refs/tags/main'), ('GITHUB_EVENT_NAME', 'pull_request_target'),
            ('GITHUB_REPOSITORY', 'enobius/example'), ('GITHUB_REPOSITORY_ID', '1315590854'),
            ('PR_NUMBER', '54'), ('GITHUB_SHA', 'c' * 40),
            ('SHADOW_BASE_SHA', 'd' * 40), ('SHADOW_HEAD_SHA', 'e' * 40),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(env=ENV | {field: value})

    def test_different_diff_is_refused_even_when_the_permit_names_it(self):
        different = binding.digest(DIFF + b'extra text')
        changed = deepcopy(self.manifest)
        changed['files']['diff.patch']['sha256'] = different
        with self.assertRaisesRegex(ValueError, 'immutable synthetic diff'):
            self.check(permit=PERMIT | {'diff_sha256': different}, manifest=changed)

    def test_approval_must_match_exact_fields_and_not_be_stale_or_unbounded(self):
        for field, value in (
            ('version', 'invalid'), ('origin', 'example.invalid'), ('run_id', 12345),
            ('run_attempt', '2'), ('pr_number', '54'), ('base_sha', 'd' * 40), ('head_sha', 'c' * 40),
            ('diff_sha256', '0' * 64), ('extra_claim', 'unrecognized'), ('expires_at', '2026-11-25T17:00:00Z'),
            ('expires_at', '2026-11-25T17:30:01Z'), ('expires_at', '2026-11-25T17:20:00+00:00'),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.check(permit=PERMIT | {field: value})
        with self.assertRaises(ValueError):
            self.check(now=NOW + timedelta(minutes=21))

    def test_missing_duplicate_and_oversized_permits_fail_closed(self):
        valid = json.dumps(PERMIT)
        for raw in ('', '[]', valid + ' ' * 2048, valid[:-1] + ',"run_id":"12345"}',
                    valid.replace('12345', 'é')):
            with self.subTest(prefix=raw[:16]), self.assertRaises(ValueError):
                gate.require_permit(raw, self.manifest, ENV, now=NOW)

    def test_verify_pilot_cli_distinguishes_a_sealed_bundle_from_an_authorized_one(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True):
            bundle = Path(directory)
            (bundle / 'snapshot.json').write_bytes(binding.canonical(SNAPSHOT))
            (bundle / 'diff.patch').write_bytes(DIFF)
            (bundle / 'prompt.txt').write_bytes(b'Synthetic fixture only.')
            os.environ['FETCH_MANIFEST_SHA256'] = binding.seal(bundle, jobs.context())
            with patch.object(jobs.sys, 'argv', ['shadow_jobs', 'verify-pilot', '--bundle', str(bundle)]):
                with redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(jobs.main(), 1)
                self.assertIn('failed closed', errors.getvalue())
                expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
                os.environ['SHADOW_PILOT_PERMIT'] = json.dumps(PERMIT | {'expires_at': expiry})
                self.assertEqual(jobs.main(), 0)

    def test_native_entry_gates_sealed_fetch_before_policy_or_token_and_rejects_disabled_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'bundle'
            bundle.mkdir()
            (bundle / 'snapshot.json').write_bytes(binding.canonical(SNAPSHOT))
            (bundle / 'diff.patch').write_bytes(DIFF)
            (bundle / 'prompt.txt').write_bytes(b'Synthetic fixture only.')
            policy = root / 'policy.json'
            policy.write_bytes(binding.canonical({'version': 'shadow-provider-policy-1', 'enabled': False, 'origin': None}))
            destination = root / 'result.json'
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
            permit = json.dumps(PERMIT | {'expires_at': expiry})
            with patch.dict(os.environ, ENV, clear=True):
                digest = binding.seal(bundle, jobs.context())
                os.environ['FETCH_MANIFEST_SHA256'] = digest
                with patch.object(jobs, 'native_policy') as guard, patch.object(jobs, 'native_run') as run:
                    with self.assertRaisesRegex(ValueError, 'pilot permit missing'):
                        jobs.review(bundle, 'unused', policy, destination, native=True)
                    guard.assert_not_called()
                    run.assert_not_called()
                os.environ['SHADOW_PILOT_PERMIT'] = permit
                jobs.verify_pilot(bundle)
                with patch.object(jobs, 'native_run') as run, self.assertRaisesRegex(ValueError, 'no enabled'):
                    jobs.review(bundle, 'unused', policy, destination, native=True)
                run.assert_not_called()
                self.assertFalse(destination.exists())
                # Simulate a separate approval to enable a temporary policy,
                # using only a dummy token and mocked provider invocation.
                policy.write_bytes(binding.canonical({'version': 'shadow-provider-policy-1',
                                                      'enabled': True, 'origin': 'api.anthropic.com'}))
                os.environ['CLAUDE_CODE_OAUTH_TOKEN'] = 'dummy-only'
                with patch.object(jobs, 'native_run', return_value=b'{}') as run:
                    jobs.review(bundle, 'unused', policy, destination, native=True)
                    run.assert_called_once_with('unused', Path(jobs.__file__).resolve().parent,
                                                'Synthetic fixture only.', 'dummy-only', policy)
                self.assertEqual(destination.read_bytes(), b'{}')
                (bundle / 'diff.patch').write_bytes(DIFF + b'changed')
                with self.assertRaisesRegex(ValueError, 'artifact contents or context changed'):
                    jobs.verify_pilot(bundle)


class TimingRehearsalTests(unittest.TestCase):
    def workflow(self):
        raw = Path('.github/workflows/shadow-permit-timing-rehearsal.yml').read_text(encoding='utf-8')
        self.assertFalse(any(isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(raw)))
        return yaml.load(raw, Loader=UniqueBaseLoader)

    def test_workflow_is_manual_main_only_and_has_no_secrets_or_provider_steps(self):
        workflow = self.workflow()
        self.assertEqual(set(workflow), {'name', 'on', 'permissions', 'jobs'})
        self.assertEqual(workflow['on'], {'workflow_dispatch': ''})
        self.assertEqual(workflow['permissions'], {})
        self.assertEqual(set(workflow['jobs']), {'show-marker', 'check-after-approval'})
        first, protected = (workflow['jobs'][name] for name in ('show-marker', 'check-after-approval'))
        self.assertEqual(set(first), {'if', 'runs-on', 'timeout-minutes', 'steps'})
        self.assertEqual(set(protected), set(first) | {'needs', 'environment'})
        self.assertEqual(protected['needs'], 'show-marker')
        self.assertEqual(protected['environment'], 'claude-shadow-review')
        for job in (first, protected):
            self.assertEqual(len(job['steps']), 1)
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
            self.assertEqual(job['if'], "${{ github.repository_id == '1315590853' && github.ref == 'refs/heads/main' && github.actor == 'enobius' && github.run_attempt == '1' }}")
            self.assertNotIn('${{', job['steps'][0]['run'])
        self.assertEqual(set(first['steps'][0]), {'name', 'run'})
        self.assertEqual(set(protected['steps'][0]), {'name', 'env', 'run'})
        self.assertEqual(protected['steps'][0]['env'], {
            'SHADOW_PILOT_PERMIT': '${{ vars.CLAUDE_SHADOW_ONE_RUN_PERMIT }}',
        })
        for marker in ('secrets.', 'github.token', 'https://', 'tools.shadow_jobs', 'curl', 'docker', 'claude -'):
            self.assertNotIn(marker, json.dumps(workflow))

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'), 'hosted Linux shell')
    def test_hosted_scripts_show_and_require_the_exact_run_marker(self):
        workflow = self.workflow()['jobs']
        show, check = (workflow[name]['steps'][0]['run'] for name in ('show-marker', 'check-after-approval'))
        marker = f'timing-rehearsal:12345:{BASE}'
        env = {'GITHUB_RUN_ID': '12345', 'GITHUB_SHA': BASE}
        bash = shutil.which('bash')
        shown = subprocess.run([bash, '-c', show], env=env, capture_output=True, check=True, timeout=10)
        self.assertEqual(shown.stdout.decode().splitlines()[-1], marker)
        for candidate in ('', f'timing-rehearsal:54321:{BASE}', f'timing-rehearsal:12345:{HEAD}', marker):
            with self.subTest(candidate=candidate):
                result = subprocess.run([bash, '-c', check], env=env | {'SHADOW_PILOT_PERMIT': candidate},
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0 if candidate == marker else 1)
                self.assertNotIn(marker.encode(), result.stdout + result.stderr)
        with self.assertRaises(ValueError):
            gate.require_permit(marker, {'snapshot': SNAPSHOT, 'files': {'diff.patch': {'sha256': gate.FIXTURE_DIFF}}}, ENV, now=NOW)


class OneShotActivationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / 'bundle'
        self.fresh = self.root / 'fresh'
        for directory in (self.bundle, self.fresh):
            directory.mkdir()
            (directory / 'snapshot.json').write_bytes(binding.canonical(SNAPSHOT))
            (directory / 'diff.patch').write_bytes(DIFF)
        (self.bundle / 'prompt.txt').write_bytes(b'Synthetic fixture only.')
        self.destination = self.root / 'result.json'
        self.baseline = self.root / 'policy.json'
        self.disabled = binding.canonical({'version': 'shadow-provider-policy-1', 'enabled': False, 'origin': None})
        self.baseline.write_bytes(self.disabled)
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        values = ENV | {'RUNNER_TEMP': str(self.root), 'SHADOW_PILOT_ARM_SHA': BASE,
                        'SHADOW_PILOT_PERMIT': json.dumps(PERMIT | {'expires_at': expiry})}
        session = patch.dict(os.environ, values, clear=True)
        session.start()
        self.addCleanup(session.stop)
        os.environ['FETCH_MANIFEST_SHA256'] = binding.seal(self.bundle, jobs.context())

    def review(self):
        jobs.one_shot_review(self.bundle, self.fresh, 'dummy-cli', self.baseline, self.destination)

    def test_exact_armed_permitted_fresh_attempt_gets_only_a_temporary_policy(self):
        policies = []

        def provider(binary, tools, prompt, token, policy):
            self.assertEqual((binary, prompt, token), ('dummy-cli', 'Synthetic fixture only.', 'dummy-token'))
            self.assertEqual(binding.parse(policy.read_bytes()), {'version': 'shadow-provider-policy-1',
                                                                 'enabled': True, 'origin': 'api.anthropic.com'})
            self.assertEqual(self.baseline.read_bytes(), self.disabled)
            policies.append(policy)
            return b'{}'

        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'dummy-token'}), \
                patch.object(jobs, 'native_run', side_effect=provider) as run:
            jobs.verify_activation(self.bundle, self.fresh, self.baseline)
            run.assert_not_called()
            self.review()
            self.assertEqual(self.destination.read_bytes(), b'{}')
            self.assertFalse(policies[0].exists())
            self.destination = self.root / 'second-result.json'
            with self.assertRaises(FileExistsError):
                self.review()
            run.assert_called_once()

    def test_arm_permit_freshness_and_disabled_baseline_fail_before_token_access(self):
        changed = self.fresh / 'diff.patch'
        for field, value in (('SHADOW_PILOT_ARM_SHA', ''), ('SHADOW_PILOT_ARM_SHA', HEAD),
                             ('SHADOW_PILOT_PERMIT', ''), ('GITHUB_RUN_ATTEMPT', '2')):
            with self.subTest(field=field, value=value), patch.dict(os.environ, {field: value}), \
                    patch.object(jobs, 'native_run') as run, self.assertRaises(ValueError):
                self.review()
            run.assert_not_called()
        changed.write_bytes(DIFF + b'changed after dispatch')
        with patch.object(jobs, 'native_run') as run, self.assertRaisesRegex(ValueError, 'independent PR re-fetch differs'):
            self.review()
        run.assert_not_called()
        changed.write_bytes(DIFF)
        self.baseline.write_bytes(binding.canonical({'version': 'shadow-provider-policy-1',
                                                    'enabled': True, 'origin': 'api.anthropic.com'}))
        with patch.object(jobs, 'native_run') as run, self.assertRaisesRegex(ValueError, 'must remain disabled'):
            self.review()
        run.assert_not_called()
        self.assertFalse(any(self.root.glob('claude-shadow-consumed-*')))

    def test_failed_reviewer_does_not_restore_the_attempt(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'dummy-token'}), \
                patch.object(jobs, 'native_run', side_effect=ValueError('synthetic provider failure')) as run:
            with self.assertRaisesRegex(ValueError, 'synthetic provider failure'):
                self.review()
            with self.assertRaises(FileExistsError):
                self.review()
            run.assert_called_once()
        self.assertEqual(list(self.root.glob('claude-shadow-authorized-*')), [])
        self.assertFalse(self.destination.exists())

    def test_both_activation_cli_modes_reject_a_missing_arm(self):
        args = ['--bundle', str(self.bundle), '--refetched-dir', str(self.fresh), '--policy', str(self.baseline)]
        for mode in ('verify-activation', 'one-shot-review'):
            invoking = ['shadow_jobs', mode, *args, '--binary', 'dummy-cli', '--destination', str(self.destination)]
            with self.subTest(mode=mode), patch.object(jobs.sys, 'argv', invoking), \
                    patch.dict(os.environ, {'SHADOW_PILOT_ARM_SHA': ''}), \
                    patch.object(jobs, 'native_run') as provider, redirect_stderr(io.StringIO()):
                self.assertEqual(jobs.main(), 1)
                provider.assert_not_called()
        with patch.object(jobs.sys, 'argv', ['shadow_jobs', 'verify-activation', *args]):
            self.assertEqual(jobs.main(), 0)
