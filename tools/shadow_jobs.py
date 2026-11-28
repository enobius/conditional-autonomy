"""Data-only helpers for the guarded three-job candidate; never a merge gate."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile

from tools import shadow_artifact_binding as binding
from tools.claude_shadow_workflow import prepare, validate
from tools.shadow_native_tls import native_policy, run as native_run
from tools.shadow_network_run import run as isolated_run, policy
from tools.shadow_pilot_permit import ORIGIN, require_permit

PROVIDER_POLICY_VERSION = 'shadow-provider-policy-1'


def context():
    return {'repository': os.environ['GITHUB_REPOSITORY'], 'run_id': os.environ['GITHUB_RUN_ID'],
            'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'trusted_sha': os.environ['GITHUB_SHA'],
            'pr_number': os.environ['PR_NUMBER']}


def fetch_bundle(directory, prompt_source):
    directory = Path(directory)
    prepare(directory / 'diff.patch', directory / 'snapshot.json', Path(prompt_source),
            directory / 'prompt.txt', raw_file=True)
    digest = binding.seal(directory, context())
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write('manifest_sha256=' + digest + '\n')


def verify_input(directory):
    return binding.verify_transport(directory, trusted_digest=os.environ['FETCH_MANIFEST_SHA256'],
                                    trusted_context=context())


def verify_pilot(directory):
    manifest = verify_input(directory)
    require_permit(os.environ.get('SHADOW_PILOT_PERMIT', ''), manifest, os.environ)


def verify_fresh(directory, refetched_dir):
    directory, refetched_dir = map(Path, (directory, refetched_dir))
    snapshot = binding.parse(binding.read_regular(refetched_dir / 'snapshot.json', 2000))
    diff = binding.read_regular(refetched_dir / 'diff.patch', 200_000)
    return binding.verify(directory, trusted_digest=os.environ['FETCH_MANIFEST_SHA256'], trusted_context=context(),
                          refetched_snapshot=snapshot, refetched_diff=diff)


def verify_activation(directory, refetched_dir, checked_in_policy):
    if not os.environ.get('SHADOW_PILOT_ARM_SHA') or os.environ['SHADOW_PILOT_ARM_SHA'] != os.environ['GITHUB_SHA']:
        raise ValueError('no repository arm for the exact main workflow commit')
    manifest = verify_fresh(directory, refetched_dir)
    require_permit(os.environ.get('SHADOW_PILOT_PERMIT', ''), manifest, os.environ)
    baseline = binding.parse(binding.read_regular(Path(checked_in_policy), 4096))
    if (not isinstance(baseline, dict) or baseline.get('enabled') is not False or
            baseline != {'version': PROVIDER_POLICY_VERSION, 'enabled': False, 'origin': None}):
        raise ValueError('checked-in provider policy must remain disabled')


def write_review(raw, destination):
    if not raw or len(raw) > 1_000_000 or not isinstance(binding.parse(raw), dict):
        raise ValueError('invalid isolated output')
    with Path(destination).open('xb') as output:
        output.write(raw)


def review(directory, binary, policy_path, destination, *, native=False):
    (verify_pilot if native else verify_input)(directory)
    (native_policy if native else policy)(policy_path)  # Fail before reading a credential.
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('result destination exists')
    prompt = binding.read_regular(Path(directory) / 'prompt.txt', 100_000).decode('utf-8')
    raw = (native_run if native else isolated_run)(
        binary, Path(__file__).resolve().parent, prompt, os.environ['CLAUDE_CODE_OAUTH_TOKEN'], policy_path)
    write_review(raw, destination)


def one_shot_review(directory, refetched_dir, binary, checked_in_policy, destination):
    verify_activation(directory, refetched_dir, checked_in_policy)
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('result destination exists')
    prompt = binding.read_regular(Path(directory) / 'prompt.txt', 100_000).decode('utf-8')
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    # Claim this first attempt before accessing credentials. The job is not a
    # durable ledger: GitHub's attempt and permit checks protect other runners.
    with (runner_temp / f'claude-shadow-consumed-{os.environ["GITHUB_RUN_ID"]}').open('xb'):
        pass
    with tempfile.TemporaryDirectory(prefix='claude-shadow-authorized-', dir=runner_temp) as temp:
        authorized = Path(temp) / 'provider.json'
        with authorized.open('xb') as output:
            output.write(binding.canonical({'version': PROVIDER_POLICY_VERSION, 'enabled': True, 'origin': ORIGIN}))
        raw = native_run(binary, Path(__file__).resolve().parent, prompt,
                         os.environ['CLAUDE_CODE_OAUTH_TOKEN'], authorized)
    write_review(raw, destination)


def validate_result(directory, response_dir, refetched_dir, destination):
    directory, response_dir, refetched_dir = map(Path, (directory, response_dir, refetched_dir))
    if not response_dir.is_dir() or response_dir.is_symlink() or {p.name for p in response_dir.iterdir()} != {'result.json'}:
        raise ValueError('unexpected provider result inventory')
    raw = binding.read_regular(response_dir / 'result.json', 1_000_000)
    verify_fresh(directory, refetched_dir)
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('validation destination exists')
    validate(raw, directory / 'snapshot.json', refetched_dir / 'snapshot.json', directory / 'diff.patch',
             Path(destination), repository=os.environ['GITHUB_REPOSITORY'],
             pr_number=os.environ['PR_NUMBER'], run_id=os.environ['GITHUB_RUN_ID'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fetch', 'verify', 'verify-pilot', 'verify-activation',
                                         'review', 'native-review', 'one-shot-review', 'validate'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--prompt-source', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--response-dir', type=Path)
    parser.add_argument('--refetched-dir', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'fetch':
            fetch_bundle(args.bundle, args.prompt_source)
        elif args.mode == 'verify':
            verify_input(args.bundle)
        elif args.mode == 'verify-pilot':
            verify_pilot(args.bundle)
        elif args.mode == 'verify-activation':
            verify_activation(args.bundle, args.refetched_dir, args.policy)
        elif args.mode == 'one-shot-review':
            one_shot_review(args.bundle, args.refetched_dir, args.binary, args.policy, args.destination)
        elif args.mode in ('review', 'native-review'):
            review(args.bundle, args.binary, args.policy, args.destination, native=args.mode == 'native-review')
        else:
            validate_result(args.bundle, args.response_dir, args.refetched_dir, args.destination)
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        print('Isolated shadow job failed closed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
