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
ARMED_ONLY = ("${{ github.repository_id == '1315590853' && github.ref == 'refs/heads/main' "
              "&& github.actor == 'enobius' && github.run_attempt == '1' && inputs.pr_number == '53' "
              "&& inputs.base_sha == github.sha && vars.CLAUDE_SHADOW_PILOT_ARM_SHA == github.sha }}")


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
        test.assertEqual(job['if'], ARMED_ONLY)
        test.assertEqual(job['runs-on'], 'ubuntu-24.04')
        test.assertEqual(job['permissions'], {'contents': 'read', 'pull-requests': 'read',
                                             **({'actions': 'read'} if key == 'validate' else {})})
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
                        'CLAUDE_CODE_OAUTH_TOKEN', '${{ secrets.CLAUDE_SHADOW_PRO_ONCE_OAUTH }}'))
                if name == 'GH_TOKEN':
                    test.assertIn(step['name'], {'Fetch bounded PR data', 'Independently re-fetch current PR',
                                                 'Re-fetch the exact fixture after environment approval',
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
    permit_check = next(s for s in provider if s['name'] == 'Verify the arm, fresh fixture, permit, and disabled policy')
    permit_env = {'PR_NUMBER': '${{ inputs.pr_number }}', 'SHADOW_BASE_SHA': '${{ inputs.base_sha }}',
                  'SHADOW_HEAD_SHA': '${{ inputs.head_sha }}', 'SHADOW_PILOT_PERMIT': '${{ vars.CLAUDE_SHADOW_ONE_RUN_PERMIT }}',
                  'SHADOW_PILOT_ARM_SHA': '${{ vars.CLAUDE_SHADOW_PILOT_ARM_SHA }}',
                  'FETCH_MANIFEST_SHA256': '${{ needs.fetch.outputs.manifest_sha256 }}'}
    test.assertEqual(permit_check['env'], permit_env)
    test.assertEqual(permit_check['run'], 'python -m tools.shadow_jobs verify-activation --bundle "$RUNNER_TEMP/fetch-input" '
                     '--refetched-dir "$RUNNER_TEMP/provider-refetched" --policy .github/shadow-provider-policy.json')
    review = next(s for s in provider if s['name'] == 'Run mandatory native TLS reviewer')
    test.assertEqual(review['run'], 'python -m tools.shadow_jobs one-shot-review --bundle "$RUNNER_TEMP/fetch-input" --refetched-dir "$RUNNER_TEMP/provider-refetched" --binary "$SHADOW_BINARY" --policy .github/shadow-provider-policy.json --destination "$RUNNER_TEMP/provider-output/result.json"')
    test.assertEqual(review['env'], permit_env | {'CLAUDE_CODE_OAUTH_TOKEN': '${{ secrets.CLAUDE_SHADOW_PRO_ONCE_OAUTH }}',
                                                  'SHADOW_BINARY': '${{ steps.binary.outputs.path }}'})
    refresh = next(s for s in provider if s['name'] == 'Re-fetch the exact fixture after environment approval')
    installer = next(step for step in provider if step.get('id') == 'binary')
    test.assertLess(provider.index(refresh), provider.index(permit_check))
    test.assertLess(provider.index(permit_check), provider.index(installer))
    test.assertLess(provider.index(installer), provider.index(review))
    for job, name, destination in (('fetch', 'Fetch bounded PR data', 'fetch-input'),
                                   ('provider', 'Re-fetch the exact fixture after environment approval', 'provider-refetched'),
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

    def test_candidate_is_owner_armed_only_and_bound_to_fetch_outputs(self):
        safe(self, self.workflow())
        # Local drift alarm only, not a trusted check against PR edits to tests.
        canonical = json.dumps(self.workflow(), sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         '227b576bdbd51f347a680ec0a5fcfb7242b953b0ba19eb4cdcaf3336e3df6597')
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
        candidate = self.workflow()
        candidate['jobs']['fetch']['if'] = ARMED_ONLY.replace(' && vars.CLAUDE_SHADOW_PILOT_ARM_SHA == github.sha', '')
        with self.assertRaises(AssertionError):
            safe(self, candidate)
        candidate = self.workflow()
        steps = candidate['jobs']['provider']['steps']
        steps.remove(next(s for s in steps if s['name'] == 'Re-fetch the exact fixture after environment approval'))
        with self.assertRaises((AssertionError, StopIteration)):
            safe(self, candidate)
