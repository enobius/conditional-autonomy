"""No-network tests for the one-run approval before the protected OAuth step."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import shadow_artifact_binding as binding
from tools import shadow_jobs as jobs
from tools import shadow_pilot_permit as gate

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
