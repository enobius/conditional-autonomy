"""Local unit tests for direct shadow execution, with a fake CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import run_claude_shadow as runner


class ShadowRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'cli'
        self.binary.write_bytes(b'fake pinned binary')
        self.destination = self.root / 'result.json'
        self.hash_patch = patch.object(runner, 'BINARY_SHA256', hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)

    def invoke(self, fake):
        with patch.dict(os.environ, {'GH_TOKEN': 'never-pass-github', 'GITHUB_TOKEN': 'never-pass-github',
                                     'HTTP_PROXY': 'http://not-allowed', 'GITHUB_OUTPUT': 'not-allowed'}), \
                patch.object(runner.subprocess, 'run', side_effect=fake):
            runner.run(self.binary, self.destination, prompt='untrusted diff data',
                       oauth_token='dummy-provider-token', runner_temp=self.root)

    def test_environment_is_allowlisted_and_output_extracted(self):
        value = {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 2,
                 'structured_output': {'outcome': 'escalate-to-human'}}

        def fake(cmd, **kwargs):
            env = kwargs['env']
            self.assertEqual(set(env), {'PATH', 'HOME', 'TMPDIR', 'CLAUDE_CONFIG_DIR',
                                        'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC',
                                        'DISABLE_TELEMETRY'})
            self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], 'dummy-provider-token')
            self.assertNotIn('never-pass-github', repr(env))
            self.assertEqual(kwargs['cwd'], env['HOME'])
            self.assertNotEqual(Path(kwargs['cwd']), Path.cwd())
            self.assertEqual(kwargs['input'], b'untrusted diff data')
            self.assertEqual(cmd[:-1], [str(self.binary.resolve()), '-p', '--output-format', 'json',
                                         '--model', 'claude-opus-5-5', '--max-turns', '2',
                                         '--tools=', '--disallowedTools', 'mcp__*', '--json-schema'])
            self.assertEqual(json.loads(cmd[-1]), {
                'type': 'object', 'additionalProperties': False,
                'required': ['outcome', 'findings', 'uncertainties', 'confidence', 'rationale'],
                'properties': {'outcome': {'enum': ['approve', 'revision-required', 'escalate-to-human']},
                    'findings': {'type': 'array', 'items': {'type': 'object'}},
                    'uncertainties': {'type': 'array', 'items': {'type': 'string'}},
                    'confidence': {'type': 'number'}, 'rationale': {'type': 'string'}}})
            self.assertEqual(kwargs['timeout'], 600)
            self.assertIs(kwargs['check'], False)
            kwargs['stdout'].write(json.dumps(value).encode())
            return SimpleNamespace(returncode=0)

        self.invoke(fake)
        self.assertEqual(json.loads(self.destination.read_text()), value['structured_output'])

    def test_fails_closed_for_invalid_result_and_no_output_is_written(self):
        good = {'subtype': 'success', 'is_error': False, 'num_turns': 2,
                'structured_output': {'outcome': 'approve'}}
        bad = [dict(good, subtype='error'), dict(good, is_error=True),
               dict(good, num_turns=3), dict(good, num_turns=True),
               dict(good, structured_output=None), {'other': 1},
               b'{"subtype":"success","subtype":"success","is_error":false,"num_turns":2,"structured_output":{}}',
               b'{"subtype":"success","is_error":false,"num_turns":2,"structured_output":{"confidence":NaN}}',
               b'x' * (1_000_001)]
        for item in bad:
            def fake(_cmd, **kwargs):
                kwargs['stdout'].write(item if isinstance(item, bytes) else json.dumps(item).encode())
                return SimpleNamespace(returncode=0)
            with self.subTest(item=str(item)[:100]), self.assertRaises((ValueError, UnicodeError)):
                self.invoke(fake)
            self.assertFalse(self.destination.exists())

    def test_proxy_transport_is_fixed_and_opt_in(self):
        def fake(_cmd, **kwargs):
            self.assertEqual(kwargs['env']['ANTHROPIC_BASE_URL'], 'http://shadow-egress:8080')
            self.assertNotIn('GH_TOKEN', kwargs['env'])
            kwargs['stdout'].write(b'{"subtype":"success","is_error":false,"num_turns":2,"structured_output":{}}')
            return SimpleNamespace(returncode=0)
        with patch.object(runner.subprocess, 'run', side_effect=fake):
            runner.run(self.binary, self.destination, prompt='test', oauth_token='dummy',
                       runner_temp=self.root, proxy_transport=True)
        with self.assertRaises(ValueError):
            runner.run(self.binary, self.destination, prompt='test', oauth_token='dummy',
                       runner_temp=self.root, proxy_transport='http://evil.example')

    def test_nonzero_timeout_hash_failure_and_stale_destination_fail_closed(self):
        def nonzero(_cmd, **_kwargs):
            return SimpleNamespace(returncode=1)
        with self.assertRaises(ValueError):
            self.invoke(nonzero)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke(lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('cli', 600)))
        self.binary.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.invoke(nonzero)
        self.assertFalse(self.destination.exists())
        self.binary.write_bytes(b'fake pinned binary')
        self.destination.write_text('existing data')
        def success(_cmd, **kwargs):
            kwargs['stdout'].write(b'{"subtype":"success","is_error":false,"num_turns":2,"structured_output":{}}')
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(ValueError, 'destination'):
            self.invoke(success)
        self.assertEqual(self.destination.read_text(), 'existing data')


if __name__ == '__main__':
    unittest.main()
