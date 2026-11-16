"""Run the pinned CLI with an allowlisted environment; never authorize a merge."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from tools.install_claude_shadow import BINARY_SHA256

MAX_OUTPUT = 1_000_000
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['outcome', 'findings', 'uncertainties', 'confidence', 'rationale'],
    'properties': {
        'outcome': {'enum': ['approve', 'revision-required', 'escalate-to-human']},
        'findings': {'type': 'array', 'items': {'type': 'object'}},
        'uncertainties': {'type': 'array', 'items': {'type': 'string'}},
        'confidence': {'type': 'number'}, 'rationale': {'type': 'string'},
    },
}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate result key')
        value[key] = item
    return value


def reject_constant(_value):
    raise ValueError('invalid JSON constant')


def run(binary, destination, *, prompt, oauth_token, runner_temp, proxy_transport=False):
    if type(proxy_transport) is not bool:
        raise ValueError('invalid proxy transport selector')
    if not prompt or len(prompt.encode('utf-8')) > 100_000 or not oauth_token:
        raise ValueError('missing or oversized input')
    if Path(destination).exists() or Path(destination).is_symlink():
        raise ValueError('output destination already exists')
    binary = Path(binary).resolve(strict=True)
    with binary.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != BINARY_SHA256:
        raise ValueError('CLI checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='claude-shadow-run-', dir=runner_temp) as isolated:
        # Deliberately do not inherit GitHub tokens, runner command files, proxy
        # settings, local configuration, workspace path, or other host variables.
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': isolated,
               'TMPDIR': isolated, 'CLAUDE_CONFIG_DIR': isolated,
               'CLAUDE_CODE_OAUTH_TOKEN': oauth_token,
               'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'DISABLE_TELEMETRY': '1'}
        if proxy_transport:
            # Fixed internal alias only; never accept a model/PR-supplied URL.
            env['ANTHROPIC_BASE_URL'] = 'http://shadow-egress:8080'
        cmd = [str(binary), '-p', '--output-format', 'json', '--model', 'claude-opus-5-5',
               '--max-turns', '2', '--tools=', '--disallowedTools', 'mcp__*',
               '--json-schema', json.dumps(SCHEMA, separators=(',', ':'))]
        with tempfile.TemporaryFile(dir=isolated) as output, tempfile.TemporaryFile(dir=isolated) as errors:
            proc = subprocess.run(cmd, input=prompt.encode('utf-8'), stdout=output, stderr=errors,
                                  cwd=isolated, env=env, timeout=600, check=False)
            output.seek(0, os.SEEK_END)
            if proc.returncode or output.tell() > MAX_OUTPUT:
                raise ValueError('CLI failed or exceeded output limit')
            output.seek(0)
            value = json.loads(output.read().decode('utf-8'), object_pairs_hook=unique_object,
                               parse_constant=reject_constant)
        if (not isinstance(value, dict) or value.get('subtype') != 'success' or
                value.get('is_error') is not False or type(value.get('num_turns')) is not int or
                not 1 <= value['num_turns'] <= 2 or not isinstance(value.get('structured_output'), dict)):
            raise ValueError('CLI did not return a bounded successful structured result')
        raw = json.dumps(value['structured_output'], ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(raw) > MAX_OUTPUT:
            raise ValueError('structured result exceeds size limit')
        with Path(destination).open('xb') as result:
            result.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    try:
        run(args.binary, args.destination, prompt=os.environ.get('CLAUDE_SHADOW_PROMPT', ''),
            oauth_token=os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', ''),
            runner_temp=os.environ['RUNNER_TEMP'])
    except (OSError, ValueError, UnicodeError, KeyError, subprocess.SubprocessError) as exc:
        print('Shadow CLI failed closed:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
