import hashlib
import json
from pathlib import Path
import unittest

import yaml
from tests.test_claude_shadow_workflow import UniqueBaseLoader

DOWNLOAD = 'actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
CHECKOUT = 'actions/checkout@11d5960a326750d5838078e36cf38b85af677262'
PYTHON = 'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065'
DISABLED = ("${{ false && github.repository_id == '1315590853' && github.ref == 'refs/heads/main' "
            "&& github.run_attempt == '1' }}")


def safe(test, workflow):
    test.assertEqual(set(workflow), {'name', 'on', 'permissions', 'jobs'})
    test.assertEqual(set(workflow['on']), {'workflow_dispatch'})
    dispatch = workflow['on']['workflow_dispatch']
    test.assertEqual(set(dispatch), {'inputs'})
    test.assertEqual(set(dispatch['inputs']), {'pr_number', 'base_sha', 'head_sha'})
    for field in dispatch['inputs'].values():
        test.assertEqual(set(field), {'description', 'required', 'type'})
        test.assertEqual((field['required'], field['type']), ('true', 'string'))
    test.assertEqual(workflow['permissions'], {})
    jobs = workflow['jobs']
    test.assertEqual(set(jobs), {'fetch', 'provider', 'validate'})
    test.assertEqual(jobs['provider']['needs'], 'fetch')
    test.assertEqual(jobs['validate']['needs'], ['fetch', 'provider'])
    test.assertEqual(jobs['fetch']['outputs'], {
        'manifest_sha256': '${{ steps.bundle.outputs.manifest_sha256 }}',
        'artifact_id': '${{ steps.upload.outputs.artifact-id }}',
        'artifact_digest': '${{ steps.upload.outputs.artifact-digest }}'})
    test.assertEqual(jobs['provider']['outputs'], {'artifact_id': '${{ steps.upload.outputs.artifact-id }}'})
    for key, job in jobs.items():
        test.assertEqual(set(job), {'if', 'runs-on', 'timeout-minutes', 'permissions', 'steps'} |
                         ({'outputs'} if key == 'fetch' else {'needs', 'environment', 'outputs'} if key == 'provider' else {'needs'}))
        test.assertEqual(job['if'], DISABLED)
        test.assertEqual(job['runs-on'], 'ubuntu-24.04')
        test.assertEqual(job['permissions'], {'contents': 'read'} if key == 'provider' else
                         {'contents': 'read', 'pull-requests': 'read', **({'actions': 'read'} if key == 'validate' else {})})
        if key == 'provider':
            test.assertEqual(job['environment'], 'claude-shadow-review')
        for step in job['steps']:
            test.assertLessEqual(set(step), {'name', 'id', 'uses', 'with'} if 'uses' in step else {'name', 'id', 'env', 'run'})
            test.assertNotIn('${{', step.get('run', ''))
            if 'uses' in step:
                test.assertIn(step['uses'], {CHECKOUT, PYTHON, DOWNLOAD, UPLOAD})
                if step['uses'] == CHECKOUT:
                    test.assertEqual(step['with'], {'ref': '${{ github.sha }}', 'persist-credentials': 'false'})
                elif step['uses'] == PYTHON:
                    test.assertEqual(step['with'], {'python-version': '3.11'})
                elif step['uses'] == DOWNLOAD:
                    test.assertEqual(set(step['with']), {'artifact-ids', 'path', 'merge-multiple'})
                    test.assertEqual(step['with']['merge-multiple'], 'true')
                else:
                    test.assertEqual(step['with']['overwrite'], 'false')
                    test.assertEqual(step['with']['if-no-files-found'], 'error')
                    test.assertEqual(step['with']['retention-days'], '1')
            for name, value in step.get('env', {}).items():
                if 'secrets.' in value:
                    test.assertEqual((key, step['name'], name, value), ('provider', 'Run mandatory native TLS reviewer',
                        'CLAUDE_CODE_OAUTH_TOKEN', '${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}'))
                if name == 'GH_TOKEN':
                    test.assertIn(step['name'], {'Fetch bounded PR data', 'Independently re-fetch current PR',
                                                 'Download bounded provider ZIP without extraction'})
                if name == 'FETCH_MANIFEST_SHA256':
                    test.assertEqual(value, '${{ needs.fetch.outputs.manifest_sha256 }}')
    provider = jobs['provider']['steps']
    check = next(s for s in provider if s['name'] == 'Require one fetch artifact ID')
    test.assertEqual(check['run'], '[[ "$FETCH_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]] || exit 1')
    for key in ('provider', 'validate'):
        steps = jobs[key]['steps']
        downloads = [s for s in steps if s.get('uses') == DOWNLOAD]
        test.assertEqual(downloads[0]['with']['artifact-ids'], '${{ needs.fetch.outputs.artifact_id }}')
        if key == 'validate':
            test.assertEqual(len(downloads), 1)
            result = next(s for s in steps if s['name'] == 'Download bounded provider ZIP without extraction')
            test.assertEqual(result['env'], {'GH_TOKEN': '${{ github.token }}',
                                            'RESULT_ARTIFACT_ID': '${{ needs.provider.outputs.artifact_id }}'})
            test.assertEqual(result['run'], 'python -m tools.shadow_result_download --destination-dir "$RUNNER_TEMP/provider-output"')
            ids = next(s for s in steps if s['name'] == 'Require explicit single artifact IDs')
            test.assertIn('[[ "$FETCH_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]] || exit 1', ids['run'])
            test.assertIn('[[ "$RESULT_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]] || exit 1', ids['run'])
            test.assertLess(steps.index(ids), steps.index(downloads[0]))
        else:
            test.assertLess(steps.index(check), steps.index(downloads[0]))
    policy_check = next(s for s in provider if s['name'] == 'Verify original fetch bytes and disabled provider policy')
    test.assertIn('from tools.shadow_native_tls import native_policy; native_policy(', policy_check['run'])
    review = next(s for s in provider if s['name'] == 'Run mandatory native TLS reviewer')
    test.assertEqual(review['run'], 'python -m tools.shadow_jobs native-review --bundle "$RUNNER_TEMP/fetch-input" --binary "$SHADOW_BINARY" --policy .github/shadow-provider-policy.json --destination "$RUNNER_TEMP/provider-output/result.json"')
    test.assertEqual(set(review['env']), {'PR_NUMBER', 'FETCH_MANIFEST_SHA256', 'CLAUDE_CODE_OAUTH_TOKEN', 'SHADOW_BINARY'})
    for job, name, destination in (('fetch', 'Fetch bounded PR data', 'fetch-input'),
                                   ('validate', 'Independently re-fetch current PR', 'refetched')):
        fetch = next(s for s in jobs[job]['steps'] if s['name'] == name)
        test.assertEqual(fetch['run'], 'bash tools/fetch_shadow_pr.sh')
        test.assertEqual(fetch['env'], {'GH_TOKEN': '${{ github.token }}', 'PR_NUMBER': '${{ inputs.pr_number }}',
                                        'SHADOW_BASE_SHA': '${{ inputs.base_sha }}',
                                        'SHADOW_HEAD_SHA': '${{ inputs.head_sha }}',
                                        'SHADOW_FETCH_DEST': '${{ runner.temp }}/' + destination})
    test.assertEqual(jobs['validate']['steps'][-2]['run'], 'python -m tools.shadow_jobs validate --bundle "$RUNNER_TEMP/fetch-input" --response-dir "$RUNNER_TEMP/provider-output" --refetched-dir "$RUNNER_TEMP/refetched" --destination "$RUNNER_TEMP/isolated-shadow-result.json"')


class IsolatedWorkflowTests(unittest.TestCase):
    def workflow(self):
        return yaml.load(Path('.github/workflows/claude-review-isolated.yml').read_text(encoding='utf-8'), Loader=UniqueBaseLoader)

    def test_candidate_is_disabled_and_bound_to_fetch_outputs(self):
        safe(self, self.workflow())
        # Local drift alarm only, not a trusted check against PR edits to tests.
        canonical = json.dumps(self.workflow(), sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         'feaa5d34c04fb1749b3a79a1d9bacb5aee53e030fe3d1d46f05143bef5a8dcfb')
        self.assertEqual(json.loads(Path('.github/shadow-provider-policy.json').read_text()),
                         {'version': 'shadow-provider-policy-1', 'enabled': False, 'origin': None})

    def test_boundary_mutations_fail(self):
        for key, value in [('if', "${{ github.ref == 'refs/heads/main' }}"),
                           ('runs-on', 'self-hosted'), ('permissions', {'contents': 'write'}),
                           ('defaults', {'run': {'shell': 'true {0}'}})]:
            candidate = self.workflow()
            candidate['jobs']['provider'][key] = value
            with self.subTest(key=key), self.assertRaises((AssertionError, KeyError)):
                safe(self, candidate)
        candidate = self.workflow()
        step = next(s for s in candidate['jobs']['validate']['steps'] if s.get('uses') == DOWNLOAD)
        step['with']['artifact-ids'] = '${{ needs.provider.outputs.fetch_id }}'
        with self.assertRaises(AssertionError):
            safe(self, candidate)
        candidate = self.workflow()
        fetch = next(s for s in candidate['jobs']['validate']['steps'] if s['name'] == 'Independently re-fetch current PR')
        fetch['env'].pop('SHADOW_HEAD_SHA')
        with self.assertRaises(AssertionError):
            safe(self, candidate)
