"""Read-only credential consumer for the isolated native Claude reviewer."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from tools.run_claude_shadow import run
from tools.shadow_artifact_binding import read_regular

TOKEN_FILE = '/run/shadow-provider.env'
FORBIDDEN = {'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_WORKSPACE', 'GITHUB_OUTPUT',
             'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL',
             'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
             'ANTHROPIC_BASE_URL', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_EXTRA_CA_CERTS'}


def load_token(path):
    raw = read_regular(Path(path), 4192)
    match = re.fullmatch(rb'CLAUDE_CODE_OAUTH_TOKEN=([A-Za-z0-9_.-]{1,4096})\n', raw)
    if match is None:
        raise ValueError('invalid native OAuth credential file')
    return match[1].decode('ascii')


def main():
    try:
        if FORBIDDEN.intersection(key.upper() for key in os.environ):
            raise ValueError('unexpected credential or transport override in reviewer')
        prompt = sys.stdin.buffer.read(100_001)
        if not 0 < len(prompt) <= 100_000:
            raise ValueError('invalid prompt size')
        with tempfile.TemporaryDirectory(prefix='native-shadow-entry-', dir='/tmp') as directory:
            destination = Path(directory) / 'result.json'
            run('/cli/claude', destination, prompt=prompt.decode('utf-8'),
                oauth_token=load_token(TOKEN_FILE), runner_temp=directory)
            sys.stdout.buffer.write(read_regular(destination, 1_000_000))
    except (OSError, ValueError, KeyError, RecursionError, subprocess.SubprocessError) as exc:
        print('Native shadow review failed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
