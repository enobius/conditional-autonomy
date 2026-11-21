"""PR-CI-only synthetic advisory rehearsal. Never emits a merge verdict."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from tools import trusted_review_guard as guard
from tools.shadow_artifact_binding import read_regular
from tools.shadow_container import IMAGE, docker_env
from tools.shadow_result_download import download
from tools.trusted_github_transport import ScopedGitHubGet
from tools.trusted_review_observer import GitHubObserver, MirrorBinding, Repository, evaluate_registered


REPOSITORY = Repository('enobius', 'conditional-autonomy', 1315590853)
POLICY_PIN = '7c0fee2aac8f88167f167c330caac5eb120561d4'
LIMIT = 256_000
ROOT = Path(__file__).resolve().parents[1]
RUNNER_CREDENTIALS = ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                      'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
                      'ANTHROPIC_API_KEY')

_DUMMY = """
import hashlib, json, os, sys
assert not set(os.environ).intersection(RUNNER_CREDENTIALS)
raw = sys.stdin.buffer.read(LIMIT + 1)
assert 0 < len(raw) <= LIMIT
assert json.loads(raw)['kind'] == 'rehearsal-input-v1'
result = {'kind': 'synthetic-advisory-v1', 'input_sha256': hashlib.sha256(raw).hexdigest(),
          'provider_requests': 0}
print(json.dumps(result, sort_keys=True, separators=(',', ':')))
"""


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def positive_text(value):
    if not re.fullmatch('[1-9][0-9]{0,18}', value):
        raise ValueError('invalid workflow identity')
    return value


def snapshot(env, git=None):
    if (env['GITHUB_REPOSITORY'] != REPOSITORY.slug or
            env['GITHUB_REPOSITORY_ID'] != str(REPOSITORY.repository_id) or
            env['GITHUB_EVENT_NAME'] != 'pull_request'):
        raise ValueError('non-rehearsal workflow identity')
    run = positive_text(env['GITHUB_RUN_ID'])
    attempt = positive_text(env['GITHUB_RUN_ATTEMPT'])
    number = int(positive_text(env['PR_NUMBER']))
    subject = guard.Subject(REPOSITORY.repository_id, number, env['PR_BASE'], env['PR_HEAD'])
    guard._subject(subject)
    guard._require_oid(env['GITHUB_SHA'])
    get = ScopedGitHubGet(REPOSITORY, number, env['GH_TOKEN'].encode('ascii'))
    view = GitHubObserver(REPOSITORY, number, get)
    executable = Path(git or shutil.which('git')).resolve(strict=True)
    binding = MirrorBinding(REPOSITORY, executable, ROOT / '.git', POLICY_PIN)
    result = evaluate_registered(binding, observer=view, subject=subject,
                                 requested_policy_revision=POLICY_PIN)
    raw = encoded({'kind': 'rehearsal-input-v1', 'repository_id': subject.repository_id,
                   'pr': number, 'base': subject.base, 'head': subject.head,
                   'policy_pin': POLICY_PIN, 'workflow_sha': env['GITHUB_SHA'],
                   'run_id': run, 'run_attempt': attempt,
                   'protected_paths': list(result.protected_changes)})
    if not 0 < len(raw) <= LIMIT:
        raise ValueError('oversized rehearsal input')
    return raw


def dummy_output(raw):
    return encoded({'kind': 'synthetic-advisory-v1', 'input_sha256': sha256(raw).hexdigest(),
                    'provider_requests': 0})


def invoke_dummy(raw):
    if not 0 < len(raw) <= LIMIT:
        raise ValueError('oversized rehearsal input')
    if any(name in os.environ for name in RUNNER_CREDENTIALS):
        raise ValueError('review step received a credential variable')
    name = 'ca-shadow-' + uuid.uuid4().hex
    program = f'RUNNER_CREDENTIALS = {RUNNER_CREDENTIALS!r}\nLIMIT = {LIMIT}\n' + _DUMMY
    argv = ['docker', 'run', '--rm', '--name', name, '--pull', 'never',
            '--network', 'none', '--read-only', '--user', '65534:65534',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32',
            '--memory', '128m', '--cpus', '1', '--entrypoint', 'python',
            '-i', IMAGE, '-I', '-B', '-S', '-c', program]
    try:
        proc = subprocess.run(argv, input=raw, capture_output=True, env=docker_env(), timeout=45)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                       env=docker_env(), timeout=15)
        raise
    if proc.returncode or proc.stderr or proc.stdout != dummy_output(raw):
        raise ValueError('dummy reviewer failed or returned unbound output')
    return proc.stdout


def artifact(raw, output):
    if output != dummy_output(raw):
        raise ValueError('invalid dummy response')
    return encoded({'kind': 'shadow-rehearsal-evidence-v1', 'input': json.loads(raw),
                    'result': json.loads(output), 'mode': 'advisory-only'})


def verify_artifact(received, fresh):
    if received != artifact(fresh, dummy_output(fresh)):
        raise ValueError('rehearsal evidence did not match fresh observation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['capture', 'review', 'verify'])
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'verify':
            fresh = snapshot(os.environ)
            received = download(REPOSITORY.slug, os.environ['RESULT_ARTIFACT_ID'],
                                os.environ['GITHUB_RUN_ID'], os.environ['GH_TOKEN'])
            verify_artifact(received, fresh)
            print('PASS: independent exact-revision and run-bound advisory artifact verification')
        elif args.mode == 'capture':
            raw = snapshot(os.environ)
            args.directory.mkdir()
            with (args.directory / 'input.json').open('xb') as output:
                output.write(raw)
            print('PASS: exact PR and protected main observed before and after Git inspection')
        else:
            raw = read_regular(args.directory / 'input.json', LIMIT)
            evidence = artifact(raw, invoke_dummy(raw))
            with (args.directory / 'result.json').open('xb') as output:
                output.write(evidence)
            print('PASS: dummy reviewer returned input-bound advisory evidence')
    except Exception as exc:
        print('Rehearsal failed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
