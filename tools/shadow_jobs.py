"""Data-only helpers for the disabled three-job candidate; never a merge gate."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

from tools import shadow_artifact_binding as binding
from tools.claude_shadow_workflow import prepare, validate
from tools.shadow_network_run import run as isolated_run, policy


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


def review(directory, binary, policy_path, destination):
    verify_input(directory)
    policy(policy_path)  # Disabled policy fails before any provider credential use/resources.
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('result destination exists')
    prompt = binding.read_regular(Path(directory) / 'prompt.txt', 100_000).decode('utf-8')
    raw = isolated_run(binary, Path(__file__).resolve().parent, prompt,
                       os.environ['CLAUDE_CODE_OAUTH_TOKEN'], policy_path)
    if not raw or len(raw) > 1_000_000 or not isinstance(binding.parse(raw), dict):
        raise ValueError('invalid isolated output')
    with Path(destination).open('xb') as output:
        output.write(raw)


def validate_result(directory, response_dir, refetched_dir, destination):
    directory, response_dir, refetched_dir = map(Path, (directory, response_dir, refetched_dir))
    if not response_dir.is_dir() or response_dir.is_symlink() or {p.name for p in response_dir.iterdir()} != {'result.json'}:
        raise ValueError('unexpected provider result inventory')
    raw = binding.read_regular(response_dir / 'result.json', 1_000_000)
    snapshot = binding.parse(binding.read_regular(refetched_dir / 'snapshot.json', 2000))
    fresh_diff = binding.read_regular(refetched_dir / 'diff.patch', 200_000)
    binding.verify(directory, trusted_digest=os.environ['FETCH_MANIFEST_SHA256'], trusted_context=context(),
                   refetched_snapshot=snapshot, refetched_diff=fresh_diff)
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('validation destination exists')
    validate(raw, directory / 'snapshot.json', refetched_dir / 'snapshot.json', directory / 'diff.patch',
             Path(destination), repository=os.environ['GITHUB_REPOSITORY'],
             pr_number=os.environ['PR_NUMBER'], run_id=os.environ['GITHUB_RUN_ID'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fetch', 'verify', 'review', 'validate'))
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
        elif args.mode == 'review':
            review(args.bundle, args.binary, args.policy, args.destination)
        else:
            validate_result(args.bundle, args.response_dir, args.refetched_dir, args.destination)
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        print('Isolated shadow job failed closed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
