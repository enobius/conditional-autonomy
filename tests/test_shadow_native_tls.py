import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from tools import shadow_native_tls as native
from tools import shadow_native_tls_relay as relay
from tools.shadow_native_tls_entry import TOKEN_FILE, load_token


class NativeTLSBoundaryTests(unittest.TestCase):
    def test_native_policy_cannot_use_a_different_origin_or_disabled_policy(self):
        for origin, enabled in ((None, False), (relay.ORIGIN, False), ('provider.example', True)):
            with self.subTest(origin=origin, enabled=enabled), tempfile.TemporaryDirectory() as temp:
                policy = Path(temp) / 'policy.json'
                policy.write_text(json.dumps({'version': 'shadow-provider-policy-1',
                                              'enabled': enabled, 'origin': origin}))
                with patch.object(native, 'secret_file') as secret, patch.object(native, 'topology') as topology, \
                        self.assertRaises(ValueError):
                    native.run('unused', 'unused', 'prompt', 'synthetic', policy)
                secret.assert_not_called()
                topology.assert_not_called()

    def test_reviewer_has_no_token_in_arguments_and_only_a_read_only_mount(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'credential'
            file.write_bytes(b'CLAUDE_CODE_OAUTH_TOKEN=dummy-native-only\n')
            self.assertEqual(load_token(file), 'dummy-native-only')
            name, network = 'ca-shadow-' + 'a' * 32, 'ca-shadow-net-' + 'a' * 32
            args = native.reviewer_command(name, file, Path('tools'), file, network, '172.30.0.2', 1001, 1002)
            self.assertEqual(args[args.index('--network') + 1], network)
            self.assertEqual(args[args.index('--user') + 1], '1001:1002')
            self.assertIn('api.anthropic.com:172.30.0.2', args)
            self.assertIn(f'type=bind,source={file.resolve()},target={TOKEN_FILE},readonly', args)
            self.assertEqual(args[-1], 'tools.shadow_native_tls_entry')
            self.assertNotIn('--env-file', args)
            self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN=', repr(args))
            self.assertNotIn('dummy-native-only', repr(args))
            for address, uid in (('8.8.8.8', 1001), ('127.0.0.1', 1001), ('172.30.0.2', 0)):
                with self.subTest(address=address, uid=uid), self.assertRaises(ValueError):
                    native.reviewer_command(name, file, Path('tools'), file, network, address, uid, 1002)
            file.write_bytes(b'CLAUDE_CODE_OAUTH_TOKEN=dummy\nSECOND=unexpected\n')
            with self.assertRaises(ValueError):
                load_token(file)

    def test_review_container_inspection_rejects_extraneous_network_mount_and_env(self):
        network = 'native-net'
        info = {'NetworkSettings': {'Networks': {network: {}}}, 'Config': {'Env': ['PYTHONPATH=/sandbox']},
                'Mounts': [{'Destination': path, 'RW': False}
                           for path in ('/cli/claude', '/sandbox/tools', TOKEN_FILE)]}
        native.assert_reviewer(info, network)
        for mutation in (
            {'NetworkSettings': {'Networks': {network: {}, 'bridge': {}}}},
            {'Mounts': [*info['Mounts'], {'Destination': '/workspace', 'RW': False}]},
            {'Mounts': [*info['Mounts'][:-1], {'Destination': TOKEN_FILE, 'RW': True}]},
            {'Config': {'Env': ['actions_runtime_token=synthetic']}},
            {'Config': {'Env': ['NODE_EXTRA_CA_CERTS=/tmp/ca.pem']}},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                native.assert_reviewer(info | mutation, network)

    def test_live_relay_resolves_only_fixed_public_ipv4_and_fixture_has_fixed_private_peer(self):
        def answer(*addresses):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses]
        with patch.object(relay.socket, 'getaddrinfo', return_value=answer('1.1.1.1')) as dns:
            self.assertEqual(relay.upstream('live'), ('1.1.1.1', 443))
            dns.assert_called_once_with(relay.ORIGIN, 443, socket.AF_INET, socket.SOCK_STREAM)
        for addresses in ((), ('1.1.1.1', '127.0.0.1'), ('169.254.169.254',), ('224.0.0.1',)):
            with self.subTest(addresses=addresses), patch.object(relay.socket, 'getaddrinfo',
                    return_value=answer(*addresses)), self.assertRaises(ValueError):
                relay.upstream('live')
        with patch.object(relay.socket, 'gethostbyname', return_value='172.30.0.2') as dns:
            self.assertEqual(relay.upstream('fixture'), ('172.30.0.2', 8443))
            dns.assert_called_once_with('native-tls-endpoint')
        with patch.object(relay.socket, 'getaddrinfo') as dns, self.assertRaises(ValueError):
            relay.upstream('unrecognized')
        dns.assert_not_called()
