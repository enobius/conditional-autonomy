import json
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import shadow_network_run as network


class NetworkRunTests(unittest.TestCase):
    def test_proxy_mount_identity_and_cleanup_precede_secret_unlink(self):
        for fail_creation in (False, True):
            with self.subTest(fail_creation=fail_creation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / 'binary'
                binary.write_bytes(b'fixture')
                credential = root / 'proxy.env'
                events = []
                calls = []
                @contextmanager
                def secret(token):
                    self.assertEqual(token, 'dummy-owner-token')
                    credential.write_bytes(b'CLAUDE_CODE_OAUTH_TOKEN=dummy-owner-token\n')
                    events.append('secret-created')
                    try:
                        yield credential
                    finally:
                        events.append('secret-unlinked')
                        credential.unlink()
                def execute(args):
                    calls.append(args)
                    if args[:2] == ['network','inspect']:
                        return json.dumps([{'Internal':True,'EnableIPv6':False,'Options':{
                            'com.docker.network.bridge.gateway_mode_ipv4':'isolated'},'IPAM':{'Config':[{}]}}]).encode()
                    if args[0] == 'inspect':
                        name = calls[0][-1]
                        return json.dumps([{'NetworkSettings':{'Networks':{name:{'IPAddress':'172.30.0.2'}}}}]).encode()
                    return b'fixture'
                def docker(args, **kwargs):
                    if args[:3] == ['docker','rm','-f']:
                        events.append('proxy-removed' if args[3].startswith('ca-shadow-proxy-') else 'cli-removed')
                        self.assertTrue(credential.exists(), 'credential unlinked before container removal')
                    if args[:3] == ['docker','network','rm']:
                        events.append('network-removed')
                    if args[:2] == ['docker','create']:
                        self.assertNotIn('dummy-owner-token', repr(args))
                        return SimpleNamespace(returncode=int(fail_creation),stderr=b'')
                    return SimpleNamespace(returncode=0,stderr=b'')
                with patch.object(network, 'policy', return_value='provider.example'), \
                     patch.object(network, 'secret_file', side_effect=secret), \
                     patch.object(network, 'execute', side_effect=execute), \
                     patch.object(network.os, 'getuid', return_value=1001, create=True), \
                     patch.object(network.os, 'getgid', return_value=1002, create=True), \
                     patch.object(network.subprocess, 'run', side_effect=docker), \
                     patch.object(network, 'collect', return_value=b'{}') as collect:
                    if fail_creation:
                        with self.assertRaises(ValueError):
                            network.run(binary, Path('tools'), 'prompt', 'dummy-owner-token', 'unused')
                        collect.assert_not_called()
                    else:
                        self.assertEqual(network.run(binary, Path('tools'), 'prompt', 'dummy-owner-token', 'unused'), b'{}')
                create = next(args for args in calls if args[0] == 'create')
                self.assertEqual(create[create.index('--user')+1], '1001:1002')
                self.assertIn(f'type=bind,source={credential.resolve()},target=/run/shadow-provider.env,readonly', create)
                self.assertNotIn('--env-file', create)
                self.assertLess(events.index('cli-removed'), events.index('proxy-removed'))
                self.assertLess(events.index('proxy-removed'), events.index('secret-unlinked'))
                self.assertLess(events.index('network-removed'), events.index('secret-unlinked'))
                self.assertFalse(credential.exists())

    def test_root_identity_is_rejected_before_any_docker_operation(self):
        with patch.object(network.os, 'getuid', return_value=0, create=True), \
             patch.object(network, 'execute') as execute, self.assertRaises(ValueError):
            with network.topology(Path('tools'), 'provider.example', Path(__file__)):
                self.fail('root proxy allowed')
        execute.assert_not_called()

    def test_policy_is_disabled_by_default_and_rejects_urls_and_addresses(self):
        with self.assertRaises(ValueError):
            network.policy(Path('.github/shadow-provider-policy.json'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            for origin in ('http://evil.example', '127.0.0.1', 'host.docker.internal:80'):
                path.write_text(json.dumps({'version': 'shadow-provider-policy-1', 'enabled': True, 'origin': origin}))
                with self.subTest(origin=origin), self.assertRaises(ValueError):
                    network.policy(path)
            for enabled in (False, 0, 1, 'true', None):
                path.write_text(json.dumps({'version': 'shadow-provider-policy-1', 'enabled': enabled,
                                            'origin': 'provider.example'}))
                with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                    network.policy(path)
            path.write_text('{"version":"shadow-provider-policy-1","enabled":true,"origin":"provider.example"}')
            self.assertEqual(network.policy(path), 'provider.example')
        with patch.object(network, 'topology') as topology, self.assertRaises(ValueError):
            network.run('binary', 'tools', 'prompt', 'unused', '.github/shadow-provider-policy.json')
        topology.assert_not_called()

    def test_topology_binds_only_internal_alias_and_verifies_network(self):
        calls = []
        def execute(args):
            calls.append(args)
            if args[:2] == ['network', 'inspect']:
                return json.dumps([{'Internal': True, 'EnableIPv6': False, 'Options': {
                    'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'}, 'IPAM': {'Config': [{}]}}]).encode()
            if args[0] == 'inspect':
                name = calls[0][-1]
                return json.dumps([{'NetworkSettings': {'Networks': {name: {'IPAddress': '172.30.0.2'}}}}]).encode()
            return b'fixture'
        with patch.object(network, 'execute', side_effect=execute), \
             patch.object(network.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr=b'')):
            with network.topology(Path('tools'), 'provider.example', Path(__file__)) as name:
                self.assertTrue(name.startswith('ca-shadow-net-'))
        create = next(call for call in calls if call[0] == 'create')
        self.assertIn('/run/shadow-provider.env', create)
        self.assertNotIn('--env-file', create)
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN=', repr(create))
        self.assertFalse(any(arg in ('--privileged', '--publish', '-p') for arg in create))
        self.assertTrue(any(call[:3] == ['network', 'connect', 'bridge'] for call in calls))

    def test_nonisolated_network_fails_before_proxy_creation(self):
        calls = []
        def execute(args):
            calls.append(args)
            if args[:2] == ['network', 'inspect']:
                return b'[{"Internal":false}]'
            return b''
        with patch.object(network, 'execute', side_effect=execute), \
             patch.object(network.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr=b'')), \
             self.assertRaises(ValueError):
            with network.topology(Path('tools'), 'provider.example', Path(__file__)):
                self.fail('unsafe network yielded')
        self.assertFalse(any(call[0] == 'create' for call in calls))
