"""Hosted synthetic probes only: no provider policy, real token or review verdict.

The GitHub token is used only by the artifact verifier on its separate runner.
No log or output contains the generated dummy credential. No caches are used;
that is not evidence of adversarial cache isolation or arbitrary exfiltration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

from tools import shadow_network_run as network
from tools.shadow_container import secret_file
from tools.shadow_result_download import download


def probe(directory):
    directory = Path(directory)
    directory.mkdir()  # Refuse reuse, including a preexisting symlink.
    token = 'dummy-hosted-' + secrets.token_hex(32)
    with secret_file(token) as credential:
        credential = Path(credential)
        with network.topology(Path('tools'), 'provider.example', credential) as name:
            info = json.loads(network.execute(['network', 'inspect', name]))[0]
            if len(info['Containers']) != 1:
                raise ValueError('unexpected topology membership')
            proxy_id = next(iter(info['Containers']))
            proxy = json.loads(network.execute(['inspect', proxy_id]))[0]
            if token in json.dumps(proxy):
                raise ValueError('dummy credential exposed in Docker configuration')
            if not any(m['Destination'] == '/run/shadow-provider.env' and not m['RW']
                       for m in proxy['Mounts']):
                raise ValueError('missing read-only credential mount')
            logs = network.execute(['logs', proxy_id])
            if token.encode() in logs:
                raise ValueError('dummy credential exposed in proxy logs')
        # Production topology must have removed the containers/network before
        # secret_file exits. The file stays present until then.
        if not credential.is_file():
            raise ValueError('credential removed before topology teardown')
    if credential.exists():
        raise ValueError('temporary credential survived context exit')
    result = {
        'kind': 'hosted-dummy-evidence-v1',
        'run_id': os.environ['GITHUB_RUN_ID'],
        'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'commit': os.environ['GITHUB_SHA'],
        'dummy_sha256': hashlib.sha256(token.encode()).hexdigest(),
        'config_and_log_canary_absent': True,
        'credential_unlinked': True,
        'provider_requests': 0,
    }
    raw = (json.dumps(result, sort_keys=True) + '\n').encode()
    if token.encode() in raw:
        raise ValueError('dummy credential exposed in result')
    (directory / 'result.json').write_bytes(raw)
    print('Hosted topology and dummy-credential lifecycle passed; synthetic result sealed.')


def verify_artifact():
    repository, artifact, run, token = (os.environ[key] for key in
        ('GITHUB_REPOSITORY', 'RESULT_ARTIFACT_ID', 'GITHUB_RUN_ID', 'GH_TOKEN'))
    # Exercise real GitHub metadata, ZIP redirect/storage, and bounded parser.
    raw = download(repository, artifact, run, token)
    result = json.loads(raw)
    if (result.get('kind') != 'hosted-dummy-evidence-v1' or
            result.get('run_id') != run or
            result.get('run_attempt') != os.environ['GITHUB_RUN_ATTEMPT'] or
            result.get('commit') != os.environ['GITHUB_SHA'] or
            result.get('config_and_log_canary_absent') is not True or
            result.get('credential_unlinked') is not True or
            result.get('provider_requests') != 0):
        raise ValueError('synthetic artifact binding mismatch')
    if token.encode() in raw or b'dummy-hosted-' in raw:
        raise ValueError('credential canary in downloaded result')
    try:
        download(repository, artifact, str(int(run) + 1), token)
    except ValueError:
        pass
    else:
        raise ValueError('wrong-run artifact was accepted')
    print('Real hosted artifact round-trip and wrong-run rejection passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['probe', 'artifact'])
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'probe':
            if args.directory is None:
                parser.error('--directory required for probe')
            probe(args.directory)
        else:
            verify_artifact()
    except Exception as exc:
        # Do not emit HTTP exception URLs, response bodies or dummy canaries.
        print('Hosted dummy probe failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
