import http.client
import io
import socket
import ssl
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer

from tools import shadow_egress_proxy as proxy


class ProxyTests(unittest.TestCase):
    def test_proxy_file_parser_and_ipv4_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'provider.env'
            path.write_bytes(b'CLAUDE_CODE_OAUTH_TOKEN=dummy-proxy-only\n')
            self.assertEqual(proxy.proxy_token(path), 'dummy-proxy-only')
            for raw in (b'CLAUDE_CODE_OAUTH_TOKEN=dummy\r\n', b'wrong-format\n',
                        b'CLAUDE_CODE_OAUTH_TOKEN=dummy\nGH_TOKEN=bad\n'):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    proxy.proxy_token(path)
        def resolve(*_a, **_kw):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:4860:4860::8888',443,0,0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8',443))]
        self.assertEqual(proxy.public_addresses('provider.example', resolve)[0], '8.8.8.8')
    def test_origin_and_dns_block_host_metadata_and_rebinding(self):
        for origin in ('localhost', '127.0.0.1', 'provider.example:443', 'https://provider.example',
                       'provider.example.', 'a..example', 'Provider.example'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                proxy.check_origin(origin)
        def resolve(*ips):
            return lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ips]
        self.assertEqual(proxy.public_addresses('provider.example', resolve('8.8.8.8')), ['8.8.8.8'])
        for ip in ('127.0.0.1', '10.0.0.1', '172.17.0.1', '169.254.169.254', '168.63.129.16', '0.0.0.0'):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                proxy.public_addresses('provider.example', resolve('8.8.8.8', ip))
        with self.assertRaises(ValueError):
            proxy.public_addresses('provider.example', lambda *_a, **_kw: [])

    def test_numeric_connection_is_pinned_but_tls_checks_origin(self):
        conn = proxy.FixedHTTPS('provider.example')
        self.assertTrue(conn._context.check_hostname)
        self.assertEqual(conn._context.verify_mode, ssl.CERT_REQUIRED)
        with patch.object(proxy, 'public_addresses', return_value=['8.8.8.8']) as resolve, \
             patch.object(proxy.socket, 'create_connection', return_value=Mock()) as connect, \
             patch.object(conn._context, 'wrap_socket', return_value=Mock()) as wrap:
            conn.connect()
            resolve.assert_called_once_with('provider.example')
            connect.assert_called_once_with(('8.8.8.8', 443), timeout=30)
            self.assertEqual(wrap.call_args.kwargs['server_hostname'], 'provider.example')
        conn.close()

    def setUp(self):
        self.response = Mock(status=200)
        self.response.getheader.side_effect = lambda key: {'Content-Type': 'application/json'}.get(key)
        self.response.read1.side_effect = [b'{"ok":true}', b'']
        self.upstream = Mock()
        self.upstream.getresponse.return_value = self.response
        self.factory = Mock(return_value=self.upstream)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), proxy.handler_for('provider.example', self.factory, token='proxy-only-canary'))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=b'{}', headers=headers or {'Authorization': 'dummy-only'})
            response = client.getresponse()
            return response.status, response.read()
        except ConnectionError:
            # Invalid requests may be reset while the client is still sending
            # their body (notably Windows); valid-request tests still require 200.
            return 0, b''
        finally:
            client.close()

    def test_forwarding_only_to_fixed_origin_and_header_allowlist(self):
        status, raw = self.request('POST', '/v1/messages?beta=true',
                                   {'Authorization': 'dummy-only', 'GH_TOKEN': 'must-not-forward',
                                    'Host': 'evil.example', 'anthropic-version': '2023-06-01'})
        self.assertEqual((status, raw), (200, b'{"ok":true}'))
        self.factory.assert_called_once_with('provider.example')
        args, kwargs = self.upstream.request.call_args
        self.assertEqual(args, ('POST', '/v1/messages?beta=true'))
        self.assertEqual(kwargs['body'], b'{}')
        self.assertEqual(kwargs['headers'], {'Content-Type': 'application/json', 'Connection': 'close',
                         'Host': 'provider.example', 'authorization': 'Bearer proxy-only-canary',
                         'anthropic-version': '2023-06-01'})

    def test_cli_cannot_choose_upstream_account(self):
        self.assertEqual(self.request('POST', '/v1/messages', {'x-api-key': 'attacker-key'})[0], 200)
        headers = self.upstream.request.call_args.kwargs['headers']
        self.assertNotIn('x-api-key', headers)
        self.assertNotIn('attacker-key', repr(headers))
        self.assertEqual(headers['authorization'], 'Bearer proxy-only-canary')

    def test_no_tunnels_urls_alternate_paths_or_ambiguous_auth(self):
        for method, path, headers in [
            ('CONNECT', 'evil.example:443', None), ('GET', '/v1/messages', None),
            ('POST', 'http://evil.example/v1/messages', None), ('POST', '//evil.example/v1/messages', None),
            ('POST', '/v1/messages/../secrets', None), ('POST', '/v1/messages?url=evil', None),
            ('POST', '/v1/messages', {'Authorization': 'dummy', 'x-api-key': 'also-dummy'}),
            ('POST', '/v1/messages', {'Transfer-Encoding': 'chunked', 'Authorization': 'dummy'}),
        ]:
            with self.subTest(method=method, path=path):
                self.assertNotEqual(self.request(method, path, headers)[0], 200)
        self.factory.assert_not_called()

    def test_redirect_is_rejected_not_followed(self):
        self.response.status = 302
        self.assertEqual(self.request('POST', '/v1/messages')[0], 502)
        self.assertEqual(self.factory.call_count, 1)
        self.response.read1.assert_not_called()

    def test_response_size_type_and_stream_limits(self):
        for headers in ({'Content-Length': '1000001'}, {'Content-Length': 'not-a-number'},
                        {'Content-Type': 'text/html'}, {'Content-Type': 'application/json\r\nx-evil: value'}):
            self.response.getheader.side_effect = lambda key, h=headers: h.get(key)
            with self.subTest(headers=headers):
                self.assertEqual(self.request('POST', '/v1/messages')[0], 502)

    def test_stream_limit_truncates_without_forwarding_excess_bytes(self):
        self.response.getheader.side_effect = lambda key: {'Content-Type': 'text/event-stream'}.get(key)
        self.response.read1.side_effect = [b'x' * 600000, b'x' * 600000, b'']
        status, raw = self.request('POST', '/v1/messages')
        self.assertEqual(status, 200)  # Already streaming: close instead of sending a second status.
        self.assertEqual(len(raw), 600000)
        self.upstream.close.assert_called()

    def test_request_budget_is_shared_across_clients_endpoints_and_keys(self):
        self.assertEqual(proxy.REQUEST_BUDGET, 4)
        self.response.read1.side_effect = lambda _size: b''
        for index in range(4):
            path = '/v1/messages' if index % 2 else '/v1/messages/count_tokens'
            self.assertEqual(self.request('POST', path, {'Authorization': 'dummy-' + str(index)})[0], 200)
        for path in ('/v1/messages', '/v1/messages/count_tokens'):
            self.assertEqual(self.request('POST', path)[0], 429)
        self.assertEqual(self.factory.call_count, 4)

    def test_failed_upstream_attempts_do_not_refund_budget(self):
        self.factory.side_effect = OSError('synthetic failure')
        for _ in range(4):
            self.assertEqual(self.request('POST', '/v1/messages')[0], 502)
        self.assertEqual(self.request('POST', '/v1/messages')[0], 429)
        self.assertEqual(self.factory.call_count, 4)

    def test_dns_ipv6_mapped_and_scope_destinations_are_rejected(self):
        for address, scope in [('::1', 0), ('fe80::1', 2), ('::ffff:8.8.8.8', 0)]:
            with self.subTest(address=address), self.assertRaises(ValueError):
                proxy.public_addresses('provider.example', lambda *_a, **_kw:
                    [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', (address, 443, 0, scope))])

    def test_duplicate_length_missing_auth_and_oversize_rejected(self):
        raw = (b'POST /v1/messages HTTP/1.1\r\nHost: local\r\nAuthorization: dummy\r\n'
               b'Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}')
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as stream:
            try:
                stream.sendall(raw)
                response = stream.recv(4096)
                self.assertIn(b'502', response.split(b'\r\n')[0])
            except ConnectionError:
                pass  # A connection abort is rejection; never forward upstream.
        self.assertNotEqual(self.request('POST', '/v1/messages', {'Content-Type': 'application/json'})[0], 200)
        self.assertNotEqual(self.request('POST', '/v1/messages', {'Authorization': 'dummy', 'Content-Length': '1000001'})[0], 200)
        self.factory.assert_not_called()
