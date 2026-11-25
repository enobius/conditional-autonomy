from contextlib import contextmanager, nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from tools import shadow_native_tls as native
from tools import shadow_native_tls_entry as entry
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
            self.assertEqual(args[args.index('--dns') + 1], '127.0.0.1')
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

    def test_fixture_peer_refuses_nonprivate_or_special_addresses(self):
        for address in ('8.8.8.8', '127.0.0.1', '169.254.169.254', '0.0.0.0'):
            with self.subTest(address=address), patch.object(relay.socket, 'gethostbyname',
                    return_value=address), self.assertRaises(ValueError):
                relay.upstream('fixture')

    def test_root_host_stops_before_reading_credentials_or_starting_docker(self):
        for uid, gid in ((0, 1002), (1001, 0)):
            with self.subTest(uid=uid, gid=gid), patch.object(native, 'native_policy'), \
                    patch.object(native.os, 'getuid', return_value=uid, create=True), \
                    patch.object(native.os, 'getgid', return_value=gid, create=True), \
                    patch.object(native, 'secret_file') as secret, patch.object(native, 'execute') as execute, \
                    self.assertRaisesRegex(ValueError, 'non-root Linux'):
                native.run('unused', 'unused', 'prompt', 'dummy', 'unused')
            secret.assert_not_called()
            execute.assert_not_called()

    def test_entrypoint_rejects_forbidden_environment_before_reading_token(self):
        prompt = b'Review this synthetic fixture.\n'
        verdict = b'{"synthetic":true}'
        for variable in (None, 'ACTIONS_RUNTIME_TOKEN', 'github_token', 'https_proxy',
                         'NODE_EXTRA_CA_CERTS', 'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as directory:
                source, output, errors = io.BytesIO(prompt), io.BytesIO(), io.StringIO()
                io_streams = SimpleNamespace(stdin=SimpleNamespace(buffer=source),
                                             stdout=SimpleNamespace(buffer=output), stderr=errors)

                def fake_run(_binary, destination, **_kwargs):
                    destination.write_bytes(verdict)

                variables = {'PYTHONPATH': '/sandbox'}
                if variable is not None:
                    variables[variable] = 'dummy-forbidden-value'
                with patch.dict(os.environ, variables, clear=True), patch.object(entry, 'sys', io_streams), \
                        patch.object(entry, 'tempfile', SimpleNamespace(
                            TemporaryDirectory=lambda **_: nullcontext(directory))), \
                        patch.object(entry, 'load_token', return_value='dummy-native-only') as token, \
                        patch.object(entry, 'run', side_effect=fake_run) as run:
                    status = entry.main()
                if variable is None:
                    self.assertEqual(status, 0, errors.getvalue())
                    token.assert_called_once_with(TOKEN_FILE)
                    run.assert_called_once_with('/cli/claude', Path(directory) / 'result.json',
                                                prompt=prompt.decode(), oauth_token='dummy-native-only',
                                                runner_temp=directory)
                    self.assertEqual(output.getvalue(), verdict)
                else:
                    self.assertEqual(status, 1)
                    self.assertEqual(source.tell(), 0, 'rejected environment must stop before reading the prompt')
                    token.assert_not_called()
                    run.assert_not_called()
                    self.assertEqual(output.getvalue(), b'')

    def test_topology_rejects_bridge_or_relay_drift_and_always_cleans_up(self):
        suffix = 'a' * 32
        front, name = 'ca-shadow-net-' + suffix, 'ca-shadow-tls-' + suffix
        bridge = {'Internal': True, 'EnableIPv6': False,
                  'Options': {'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'},
                  'IPAM': {'Config': [{}]}}
        healthy = {'NetworkSettings': {'Networks': {front: {'IPAddress': '172.30.0.2'}, 'bridge': {}}},
                   'Mounts': [{'Destination': '/relay.py'}]}
        scenarios = (
            (bridge, healthy, True),
            (bridge | {'Internal': False}, healthy, False),
            (bridge | {'EnableIPv6': True}, healthy, False),
            (bridge | {'IPAM': {'Config': [{'Gateway': '172.30.0.1'}]}}, healthy, False),
            (bridge, healthy | {'NetworkSettings': {'Networks': {front: {'IPAddress': '172.30.0.2'},
                                                                'other-network': {}}}}, False),
            (bridge, healthy | {'Mounts': [{'Destination': '/unexpected'}]}, False),
        )
        for net_info, relay_info, allowed in scenarios:
            calls = []

            def execute(args):
                calls.append(args)
                if args[:2] == ['network', 'inspect']:
                    return json.dumps([net_info]).encode()
                if args == ['inspect', name]:
                    return json.dumps([relay_info]).encode()
                return b'READY\n' if args[0] == 'logs' else b''

            with self.subTest(bridge=net_info, relay=relay_info), patch.object(native, 'execute',
                    side_effect=execute), patch.object(native, 'remove', side_effect=lambda cmd, _: calls.append(cmd)):
                if allowed:
                    with native.topology(Path('tools'), suffix) as topology:
                        self.assertEqual(topology, (front, '172.30.0.2'))
                else:
                    with self.assertRaises(ValueError), native.topology(Path('tools'), suffix):
                        self.fail('unsafe topology yielded')
                self.assertEqual(calls[-2:], [['rm', '-f', name], ['network', 'rm', front]])
                if net_info != bridge:
                    self.assertFalse(any(call[0] == 'create' for call in calls))

    def test_run_inspects_reviewer_before_start_and_removes_it_before_unlink(self):
        for unexpected in (False, True):
            with self.subTest(unexpected=unexpected), tempfile.TemporaryDirectory() as temp:
                file = Path(temp) / 'credential'
                calls = []
                network = 'ca-shadow-net-' + 'a' * 32

                @contextmanager
                def secret(token):
                    file.write_text(token, encoding='ascii')
                    try:
                        yield file
                    finally:
                        calls.append('unlink')
                        file.unlink()

                @contextmanager
                def topology(_tools, _suffix):
                    try:
                        yield network, '172.30.0.2'
                    finally:
                        calls.append('topology-cleanup')

                def execute(args):
                    calls.append(args[0])
                    self.assertNotIn('dummy-native-only', repr(args))
                    if args[0] == 'inspect':
                        network_set = {network: {}}
                        if unexpected:
                            network_set['bridge'] = {}
                        return json.dumps([{
                            'NetworkSettings': {'Networks': network_set}, 'Config': {'Env': []},
                            'Mounts': [{'Destination': mount, 'RW': False}
                                       for mount in (TOKEN_FILE, '/cli/claude', '/sandbox/tools')],
                        }]).encode()
                    return b''

                with patch.object(native, 'native_policy'), patch.object(native, 'secret_file', secret), \
                        patch.object(native, 'topology', topology), patch.object(native, 'execute', side_effect=execute), \
                        patch.object(native.os, 'getuid', return_value=1001, create=True), \
                        patch.object(native.os, 'getgid', return_value=1002, create=True), \
                        patch.object(native, 'remove', side_effect=lambda *_: calls.append('reviewer-removed')), \
                        patch.object(native, 'collect', side_effect=lambda *_: calls.append('collect') or b'{}'):
                    if unexpected:
                        with self.assertRaisesRegex(ValueError, 'unexpected network'):
                            native.run(file, Path('tools'), 'prompt', 'dummy-native-only', 'unused')
                    else:
                        self.assertEqual(native.run(file, Path('tools'), 'prompt', 'dummy-native-only', 'unused'), b'{}')
                prefix = ['create', 'inspect'] if unexpected else ['create', 'inspect', 'collect']
                self.assertEqual(calls, prefix + ['reviewer-removed', 'topology-cleanup', 'unlink'])


def record(data, content_type=22):
    return bytes([content_type]) + b'\x03\x03' + len(data).to_bytes(2, 'big') + data


def vector(data, width=2):
    return len(data).to_bytes(width, 'big') + data


def extension(kind, value):
    return kind.to_bytes(2, 'big') + vector(value)


def hello_body(extensions):
    body = b'\x03\x03' + b'\x01' * 32 + b'\x00\x00\x02\x13\x01\x01\x00' + vector(extensions)
    return b'\x01' + vector(body, 3)


def sni(name):
    return extension(0, vector(b'\x00' + vector(name.encode('ascii'))))


class InputSocket:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def recv(self, size):
        return self.stream.read(min(size, 3))  # Independent TCP-read fragmentation.

    def settimeout(self, seconds):
        if seconds <= 0:
            raise AssertionError('nonpositive timeout passed to socket')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class NativeTLSRelayTests(unittest.TestCase):
    def test_visible_sni_accepts_a_real_clienthello_and_tls_record_fragmentation(self):
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        client = ssl.create_default_context().wrap_bio(incoming, outgoing, server_hostname=relay.ORIGIN)
        with self.assertRaises(ssl.SSLWantReadError):
            client.do_handshake()
        actual_hello = outgoing.read()
        deadline = time.monotonic() + 2
        self.assertEqual(relay.read_client_hello(InputSocket(actual_hello), deadline), actual_hello)
        hello = hello_body(sni(relay.ORIGIN))
        split = record(hello[:2]) + record(hello[2:19]) + record(hello[19:])
        self.assertEqual(relay.read_client_hello(InputSocket(split), deadline), split)

    def test_hostname_and_bounds_are_checked_even_when_other_fields_are_valid(self):
        exact = sni(relay.ORIGIN)
        variants = (
            b'plain input', record(hello_body(exact), content_type=23),
            record(hello_body(b'')), record(hello_body(sni('other.invalid'))),
            record(hello_body(exact + exact)), record(hello_body(exact + extension(0xFE0D, b'opaque'))),
            record(hello_body(exact)[:-1]), record(hello_body(exact) + b'x'),
            record(b'\x01\x01\x00\x00'), record(b'a' * (relay.MAX_RECORD_BYTES + 1)),
            b''.join(record(bytes([byte])) for byte in hello_body(exact)),
        )
        for wire in variants:
            with self.subTest(prefix=wire[:12]), self.assertRaises(ValueError):
                relay.read_client_hello(InputSocket(wire), time.monotonic() + 2)
        with self.assertRaises(TimeoutError):
            relay.read_client_hello(InputSocket(record(hello_body(exact))), time.monotonic() - 1)

    def test_relay_pins_upstream_only_after_validation_and_caps_total_connections(self):
        exact = record(hello_body(sni(relay.ORIGIN)))
        incoming = [b'invalid', record(hello_body(sni('other.invalid'))), exact,
                    record(hello_body(sni(relay.ORIGIN) + extension(0xFE0D, b'opaque'))), exact]
        listener, remote = MagicMock(), MagicMock()
        listener.__enter__.return_value = listener
        remote.__enter__.return_value = remote
        listener.accept.side_effect = [(InputSocket(wire), ()) for wire in incoming]
        peer = ('172.30.0.2', 8443)
        with patch.object(relay.socket, 'gethostbyname', return_value='172.30.0.3'), \
                patch.object(relay.socket, 'create_server', return_value=listener) as bind, \
                patch.object(relay.socket, 'create_connection', return_value=remote) as connect, \
                patch.object(relay, 'upstream', return_value=peer), patch.object(relay, 'pump') as pump, \
                patch.object(relay.time, 'monotonic', return_value=100), \
                redirect_stdout(io.StringIO()):
            relay.main('fixture')
        bind.assert_called_once_with(('172.30.0.3', 443))
        self.assertEqual(listener.accept.call_count, 4)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args, (peer,))
        remote.sendall.assert_called_once_with(exact)
        self.assertEqual(pump.call_args.kwargs['remaining'], 4_000_000 - len(exact))
        self.assertEqual(pump.call_args.kwargs['deadline'], 130)

    def test_listener_rejects_wrong_address_before_resolving_upstream(self):
        for address in ('127.0.0.1', '8.8.8.8', '0.0.0.0', '169.254.169.254'):
            with self.subTest(address=address), patch.object(relay.socket, 'gethostbyname',
                    return_value=address), patch.object(relay, 'upstream') as upstream, \
                    self.assertRaisesRegex(ValueError, 'private review bridge'):
                relay.main('fixture')
            upstream.assert_not_called()

    def test_pump_stops_on_expired_deadline_or_excess_bytes(self):
        one, two = Mock(), Mock()
        with patch.object(relay.select, 'select') as select:
            relay.pump(one, two, deadline=time.monotonic() - 1, remaining=3)
        select.assert_not_called()
        one.recv.return_value = b'abcd'
        with patch.object(relay.select, 'select', side_effect=[([one], [], []), ([], [], [])]):
            relay.pump(one, two, deadline=time.monotonic() + 2, remaining=3)
        two.sendall.assert_not_called()
        one.recv.assert_called_once_with(4)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Unix socket pairs on the Linux runner')
    def test_pump_copies_in_both_directions_within_budget_over_local_sockets(self):
        outside_left, left = socket.socketpair()
        outside_right, right = socket.socketpair()
        with outside_left, left, outside_right, right:
            for peer, data in ((outside_left, b'one'), (outside_right, b'two')):
                peer.settimeout(2)
                peer.sendall(data)
                peer.shutdown(socket.SHUT_WR)
            relay.pump(left, right, deadline=time.monotonic() + 2, remaining=6)
            self.assertEqual(outside_left.recv(3), b'two')
            self.assertEqual(outside_right.recv(3), b'one')
