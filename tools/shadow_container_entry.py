"""Trusted entrypoint; intentionally no production networking yet."""
import os
from pathlib import Path
import sys
import subprocess
import tempfile

from tools.run_claude_shadow import run


def main():
    try:
        prompt = sys.stdin.buffer.read(100_001)
        if not prompt or len(prompt) > 100_000:
            raise ValueError('prompt size')
        with tempfile.TemporaryDirectory(prefix='shadow-entry-', dir='/tmp') as directory:
            destination = Path(directory) / 'result.json'
            run('/cli/claude', destination, prompt=prompt.decode('utf-8'),
                oauth_token=os.environ['CLAUDE_CODE_OAUTH_TOKEN'], runner_temp=directory,
                proxy_transport=os.environ.get('SHADOW_PROXY_TRANSPORT') == '1')
            # The host and later validation treat even this data as untrusted.
            sys.stdout.buffer.write(destination.read_bytes())
    except (OSError, ValueError, KeyError, RecursionError, subprocess.SubprocessError) as exc:
        print('Container review failed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
