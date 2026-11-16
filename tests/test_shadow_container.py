import os
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import shadow_container as container

NAME = 'ca-shadow-' + 'f' * 32


class ContainerTests(unittest.TestCase):
    def test_creation_confirmed_before_start_and_cleanup_on_failed_creation(self):
        with patch.object(container, 'secret_file', return_value=nullcontext(Path('dummy'))), \
             patch.object(container, 'command', return_value=['docker', 'create', 'fixture']), \
             patch.object(container, 'collect', return_value=b'{}') as collect, \
             patch.object(container.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as execute:
            self.assertEqual(container.run('binary', 'tools', 'prompt', 'dummy'), b'{}')
            name = collect.call_args.args[2]
            self.assertEqual(collect.call_args.args[0], ['docker', 'start', '-a', '-i', name])
            self.assertEqual(execute.call_args.args[0], ['docker', 'rm', '-f', name])
        with patch.object(container, 'secret_file', return_value=nullcontext(Path('dummy'))), \
             patch.object(container, 'command', return_value=['docker', 'create', 'fixture']), \
             patch.object(container, 'collect') as collect, \
             patch.object(container.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):
                container.run('binary', 'tools', 'prompt', 'dummy')
            collect.assert_not_called()

    def test_fixed_command_has_no_network_or_runner_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'cli'
            credential = root / 'secret.env'
            binary.write_bytes(b'fixture')
            credential.write_text('dummy fixture')
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'shadow_container_entry.py').write_text('fixture')
            args = container.command(NAME, binary, tools, credential)
            self.assertEqual(args[:7], ['docker', 'create', '--name', NAME, '-i', '--pull', 'never'])
            for flag, expected in [('--network', 'none'), ('--user', '65534:65534'),
                                   ('--pids-limit', '64'), ('--memory', '2g'), ('--cpus', '2'),
                                   ('--security-opt', 'no-new-privileges'), ('--cap-drop', 'ALL'),
                                   ('--ulimit', 'fsize=1048576:1048576')]:
                self.assertEqual(args[args.index(flag) + 1], expected)
            self.assertIn('--read-only', args)
            self.assertEqual(args[args.index('--env-file') + 1], str(credential.resolve()))
            self.assertEqual(sum(arg == '--mount' for arg in args), 2)
            self.assertEqual(args[-3:], [container.IMAGE, '-m', 'tools.shadow_container_entry'])
            self.assertFalse(any('docker.sock' in arg or 'GITHUB' in arg for arg in args))
            network = 'ca-shadow-net-' + 'a' * 32
            proxied = container.proxied_command(NAME, binary, tools, credential, network)
            self.assertEqual(proxied[proxied.index('--network') + 1], network)
            self.assertIn('SHADOW_PROXY_TRANSPORT=1', proxied)
            self.assertNotIn('--env-file', proxied)
            self.assertNotIn(str(credential.resolve()), proxied)
            self.assertIn('CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-shadow-placeholder', proxied)
            with self.assertRaises(ValueError):
                container.proxied_command(NAME, binary, tools, credential, 'host')
            with self.assertRaises(ValueError):
                container.command('user-container', binary, tools, credential)

    def test_client_environment_does_not_inherit_credentials_or_context(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'canary', 'ACTIONS_RUNTIME_TOKEN': 'canary',
                                     'DOCKER_HOST': 'tcp://evil', 'CLAUDE_CODE_OAUTH_TOKEN': 'canary'}):
            self.assertEqual(container.docker_env(), {'PATH': '/usr/local/bin:/usr/bin:/bin',
                                                      'HOME': '/nonexistent', 'DOCKER_CONFIG': '/nonexistent'})

    def test_live_pipes_timeout_overflow_and_cleanup_confirmation(self):
        for script, timeout, should_pass in [
            ('print("ok")', 5, True),
            ('import time; time.sleep(30)', 0.2, False),
            ('import sys; sys.stdout.write("x" * 1100000)', 5, False),
            ('import sys; sys.stderr.write("x" * 1100000)', 5, False),
        ]:
            with self.subTest(script=script), patch.object(container.subprocess, 'run',
                    return_value=SimpleNamespace(returncode=0, stderr=b'')) as cleanup:
                if should_pass:
                    self.assertEqual(container.collect([sys.executable, '-c', script], b'input', NAME,
                                                       timeout=timeout).strip(), b'ok')
                else:
                    with self.assertRaises(ValueError):
                        container.collect([sys.executable, '-c', script], b'input', NAME, timeout=timeout)
                self.assertEqual(cleanup.call_args.args[0], ['docker', 'rm', '-f', NAME])
        with patch.object(container.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=b'daemon error')):
            with self.assertRaises(ValueError):
                container.collect([sys.executable, '-c', 'print("ok")'], b'input', NAME, timeout=5)

    def test_invalid_secret_encoding_never_writes_a_file(self):
        for token in ('', 'secret\nGH_TOKEN=oops', 'bad token', 'x' * 4097):
            with self.subTest(token=token[:20]), self.assertRaises(ValueError):
                with container.secret_file(token):
                    self.fail('invalid credential accepted')
        with patch.object(container.subprocess, 'Popen') as spawn:
            for prompt, timeout in [(b'', 10), (b'x' * 100001, 10), (b'x', 0), (b'x', 601)]:
                with self.subTest(size=len(prompt), timeout=timeout), self.assertRaises(ValueError):
                    container.collect([], prompt, NAME, timeout=timeout)
            spawn.assert_not_called()
