import io
import json
import stat
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import urllib.error
import zipfile

from tools import shadow_result_download as download


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, body in entries:
            zipped.writestr(name, body)
    return output.getvalue()


class ResultDownloadTests(unittest.TestCase):
    def test_real_default_opener_refuses_redirect_and_ignores_environment_proxy(self):
        observed = []
        proxy_observed = []
        zip_body = archive([('result.json', b'{}')])
        storage_url = 'https://dummy.blob.core.windows.net/result?sig=dummy'
        class Local(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                observed.append((self.path, self.headers.get('Authorization')))
                body = b''
                if self.path in ('/redirect', '/zip'):
                    self.send_response(302)
                    self.send_header('Location', storage_url if self.path == '/zip' else
                                     f'http://127.0.0.1:{self.server.server_port}/storage')
                else:
                    self.send_response(200)
                    if self.path == '/metadata':
                        body = json.dumps({'id':42,'expired':False,'workflow_run':{'id':123},
                                           'size_in_bytes':len(zip_body)}).encode()
                    elif self.path == '/storage':
                        body = zip_body
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        class EnvProxy(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                proxy_observed.append(self.path)
                self.send_response(500)
                self.send_header('Content-Length', '0')
                self.end_headers()
        servers = [ThreadingHTTPServer(('127.0.0.1', 0), cls) for cls in (Local, EnvProxy)]
        workers = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for worker in workers: worker.start()
        try:
            address = f'http://127.0.0.1:{servers[0].server_port}'
            proxy_address = f'http://127.0.0.1:{servers[1].server_port}'
            with patch.dict('os.environ', {'http_proxy': proxy_address, 'HTTP_PROXY': proxy_address,
                                           'https_proxy': proxy_address, 'no_proxy': '', 'NO_PROXY': ''}, clear=True):
                opener = download.default_opener()  # Actual urllib handlers, not a mock opener.
                self.assertTrue(any(isinstance(handler, download.NoRedirect) for handler in opener.handlers))
                self.assertFalse(any(isinstance(handler, download.urllib.request.ProxyHandler) and handler.proxies
                                     for handler in opener.handlers))
                request = download.urllib.request.Request(address + '/redirect', headers={'Authorization': 'Bearer dummy-only'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(request, timeout=3)
                self.assertEqual(error.exception.code, 302)
                error.exception.close()
                self.assertEqual(observed, [('/redirect', 'Bearer dummy-only')])
                with opener.open(download.urllib.request.Request(address + '/storage'), timeout=3):
                    pass
                self.assertEqual(observed[-1], ('/storage', None))
                self.assertEqual(proxy_observed, [])
                observed.clear()
                original_request = download.urllib.request.Request
                def local_request(url, *args, **kwargs):
                    # Test-only address mapping. Real opener, redirect logic,
                    # requests and Authorization behavior remain in use; no
                    # request can escape loopback even if a regression follows.
                    base = 'https://api.github.com/repos/example/repo/actions/artifacts/42'
                    destinations = {base: '/metadata', base + '/zip': '/zip', storage_url: '/storage'}
                    if url not in destinations:
                        raise ValueError('unexpected nonlocal test URL')
                    return original_request(address + destinations[url], *args, **kwargs)
                with patch.object(download.urllib.request, 'Request', side_effect=local_request):
                    self.assertEqual(download.download('example/repo', '42', '123', 'dummy-only'), b'{}')
                self.assertEqual(observed, [('/metadata', 'Bearer dummy-only'),
                                            ('/zip', 'Bearer dummy-only'), ('/storage', None)])
                self.assertEqual(proxy_observed, [])
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for worker in workers: worker.join(2)

    def test_one_regular_result_is_read_without_extracting(self):
        raw = archive([('result.json', b'{"ok":true}')])
        self.assertEqual(download.result_bytes(raw), b'{"ok":true}')

    def test_traversal_extra_duplicate_links_nul_and_bombs_rejected(self):
        cases = [archive([(name, b'{}')]) for name in
                 ('x/../../../result.json', '../result.json', '/result.json', 'C:\\result.json', 'folder/result.json')]
        cases += [archive([('result.json', b'{}'), ('code.py', b'never execute')]),
                  archive([('result.json', b'{}'), ('result.json', b'{}')]),
                  archive([('result.json', b'x' * 1_000_001)]),
                  archive([('result.jsonXevil', b'{}')]).replace(b'result.jsonXevil', b'result.json\x00evil'),
                  b'not a zip', b'prefix' + archive([('result.json', b'{}')])]
        link = zipfile.ZipInfo('result.json')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append(archive([(link, b'/some/host/file')]))
        for raw in cases:
            with self.subTest(length=len(raw)), self.assertRaises((ValueError, zipfile.BadZipFile)):
                download.result_bytes(raw)

    def metadata(self, **changes):
        value = {'id': 42, 'expired': False, 'workflow_run': {'id': 123}, 'size_in_bytes': 100}
        value.update(changes)
        return io.BytesIO(json.dumps(value).encode())

    def test_member_defense_checks_run_before_reading(self):
        raw = archive([('result.json', b'{}')])
        for field, value in [('flag_bits', 1), ('compress_type', 99), ('file_size', 0),
                             ('file_size', 1_000_001), ('compress_size', 2_000_001)]:
            item = zipfile.ZipInfo('result.json')
            item.file_size, item.compress_size = 2, 2
            setattr(item, field, value)
            with self.subTest(field=field, value=value), \
                 patch.object(zipfile.ZipFile, 'infolist', return_value=[item]), \
                 patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('member must be rejected before reading')), \
                 self.assertRaises(ValueError):
                download.result_bytes(raw)

    def test_member_length_check_is_independent_of_zip_library(self):
        raw = archive([('result.json', b'{}')])
        item = zipfile.ZipInfo('result.json')
        item.file_size, item.compress_size = 3, 2
        with patch.object(zipfile.ZipFile, 'infolist', return_value=[item]), \
             patch.object(zipfile.ZipFile, 'open', return_value=io.BytesIO(b'{}')), \
             self.assertRaisesRegex(ValueError, 'length mismatch'):
            download.result_bytes(raw)

    def test_signed_storage_never_receives_github_token(self):
        location = 'https://dummy.blob.core.windows.net/test?sig=dummy'
        opener = Mock()
        opener.open.side_effect = [self.metadata(),
            urllib.error.HTTPError('https://api.github.com', 302, 'redirect', {'Location': location}, io.BytesIO()),
            io.BytesIO(archive([('result.json', b'{}')]))]
        self.assertEqual(download.download('example/repo', '42', '123', 'dummy-github-only', opener), b'{}')
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer dummy-github-only')
        self.assertIsNone(requests[2].get_header('Authorization'))
        self.assertEqual(requests[2].full_url, location)

    def test_wrong_run_size_or_redirect_fails_without_unbounded_download(self):
        for metadata in [dict(id=43), dict(workflow_run={'id': 999}), dict(expired=True), dict(size_in_bytes=2_000_001)]:
            opener = Mock()
            opener.open.return_value = self.metadata(**metadata)
            with self.assertRaises(ValueError):
                download.download('example/repo', '42', '123', 'dummy', opener)
            self.assertEqual(opener.open.call_count, 1)
        for location in ['http://dummy.blob.core.windows.net/x', 'https://evil.example/x',
                         'https://user:pass@dummy.blob.core.windows.net/x',
                         'https://dummy.blob.core.windows.net:8443/x']:
            opener = Mock()
            opener.open.side_effect = [self.metadata(), urllib.error.HTTPError(
                'https://api.github.com', 302, 'redirect', {'Location': location}, io.BytesIO())]
            with self.subTest(location=location), self.assertRaises(ValueError):
                download.download('example/repo', '42', '123', 'dummy', opener)
            self.assertEqual(opener.open.call_count, 2)
