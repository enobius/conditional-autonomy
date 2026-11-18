"""Host-side fault injections: the stand-in can claim success in every case."""
from contextlib import contextmanager, ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from tests import shadow_adversarial_host as host


class HostTests(unittest.TestCase):
    def exercise(self, fault=''):
        root = Path(host.__file__).resolve().parents[1]
        isolated = 'ca-shadow-net-' + '1' * 32
        controls, inspected, collected, cleanup = [], [], [], []
        good = {'kind': 'hostile-client-v1', 'clean_environment': True,
                'readonly_mount_view': True,
                'placeholder_only': True, 'host_files_hidden': True, 'writes_blocked': True,
                'routes_blocked': {'artifact': True, 'cache': True}}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            credential = Path(directory) / 'fixture'

            @contextmanager
            def secret(token):
                credential.write_text(token)
                try:
                    yield credential
                finally:
                    if fault != 'credential':
                        credential.unlink()

            @contextmanager
            def topology(*args):
                # No actual runner values are read: main has overlaid these names.
                for key in ('ACTIONS_RUNTIME_TOKEN', 'ACTIONS_CACHE_URL', 'ACTIONS_RESULTS_URL',
                            'GH_TOKEN', 'GITHUB_TOKEN', 'GITHUB_OUTPUT', 'GITHUB_ENV'):
                    self.assertTrue(os.environ[key] == credential.read_text())
                yield isolated

            def fake_url(url):
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=3) as r:
                    self.assertEqual(r.read(), b'synthetic endpoint only')

            def execute(args):
                if args[:2] == ['network', 'inspect']:
                    return b'[{"IPAM":{"Config":[{"Gateway":"127.0.0.1"}]}}]'
                if args[:2] == ['image', 'inspect']:
                    return b'[{"Id":"image","Config":{"Env":["PATH=/bin"]}}]'
                if args[0] == 'run':
                    self.assertEqual(args[args.index('--network') + 1], 'bridge')
                    self.assertNotIn('--mount', args)
                    controls.append(args[-1])
                    if fault != 'control':
                        fake_url(args[-1])
                    return b''
                self.assertEqual(args[0], 'inspect')
                inspected.append(args[1])
                mounts = [{'Type': 'bind', 'Source': str(root / p), 'Destination': dest, 'RW': False}
                          for p, dest in [('tools', '/sandbox/tools'),
                                          ('tests/shadow_adversarial_client.py', '/cli/claude')]]
                env = ['PATH=/bin', 'PYTHONPATH=/sandbox', 'SHADOW_PROXY_TRANSPORT=1',
                       'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-shadow-placeholder']
                cfg = {'NetworkMode': isolated, 'Privileged': False, 'ReadonlyRootfs': True,
                       'CapAdd': None, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'Tmpfs': {'/tmp': 'rw,exec,nosuid,nodev,size=64m'}}
                networks = {isolated: {}}
                if fault == 'mount': mounts.append(dict(mounts[0], Destination='/unexpected'))
                if fault == 'source': mounts[0]['Source'] = '/wrong'
                if fault == 'rw': mounts[0]['RW'] = True
                if fault == 'env': env.append('UNEXPECTED=dummy')
                if fault == 'placeholder': env[-1] = 'CLAUDE_CODE_OAUTH_TOKEN=wrong'
                if fault == 'rootfs': cfg['ReadonlyRootfs'] = False
                if fault == 'cap': cfg['CapDrop'] = []
                if fault == 'privileged': cfg['Privileged'] = True
                if fault == 'network': networks['bridge'] = {}
                return json.dumps([{'Image': 'image', 'Mounts': mounts,
                                    'HostConfig': cfg, 'Config': {'Env': env,
                                    'User': '0' if fault == 'user' else '65534:65534'},
                                    'NetworkSettings': {'Networks': networks}}]).encode()

            def docker(args, **kwargs):
                if args[1] == 'rm':
                    cleanup.append(args[-1])
                    return subprocess.CompletedProcess(args, int(fault == 'cleanup'), b'', b'')
                self.assertEqual(args[1], 'create')
                return subprocess.CompletedProcess(args, 0)

            def collect(args, payload, *rest, **kw):
                collected.append(True)
                self.assertEqual(inspected, [args[-1]])
                if fault == 'traffic':
                    fake_url(controls[0].replace('/bridge-control', '/unexpected'))
                if fault == 'output':
                    return credential.read_bytes()
                return json.dumps(good).encode()

            for obj, name, value in [(host, 'secret_file', secret), (host.network, 'topology', topology),
                                     (host.network, 'execute', execute), (host, 'collect', collect),
                                     (host.subprocess, 'run', docker)]:
                stack.enter_context(patch.object(obj, name, value))
            stack.enter_context(patch('sys.stdout', new=io.StringIO()))
            try:
                host.main()
            finally:
                if inspected:
                    self.assertEqual(cleanup, inspected)
            self.assertEqual(len(controls), 1)
            self.assertEqual(collected, [True])

    def test_success(self):
        self.exercise()

    def test_main_rejects_host_faults(self):
        for fault, error in [('traffic', 'reached dummy'), ('output', 'leaked into output'),
                             ('credential', 'credential survived'), ('cleanup', 'cleanup unconfirmed'),
                             ('control', 'control not observed')]:
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, error):
                self.exercise(fault)

    def test_main_rejects_inspection_drift(self):
        for fault in ('mount', 'source', 'rw', 'env', 'placeholder', 'user', 'rootfs',
                      'cap', 'privileged', 'network'):
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, 'client .*rejected'):
                self.exercise(fault)
