import io
import json
import os
import ssl
import subprocess
import unittest
from unittest.mock import Mock, patch

from tools import trusted_github_transport as transport
from tools import trusted_review_observer as observer


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.repository = observer.Repository('owner', 'repo', 123)
        self.token = b'dummy-fixture-token'
        self.get = transport.ScopedGitHubGet(self.repository, 4, self.token)
        self.pr_path = '/repos/owner/repo/pulls/4'
        self.branch_path = '/repos/owner/repo/branches/main'
        self.pr_url = 'https://api.github.com' + self.pr_path

    def test_parent_only_accepts_two_exact_https_urls(self):
        for url in ('http://api.github.com' + self.pr_path, self.pr_url + '?x=1',
                    self.pr_url + '#frag', self.pr_url.replace('/4', '/5'),
                    self.pr_url.replace('/repo/', '/other/'),
                    self.pr_url.replace('/pulls/4', '/issues/4'),
                    self.pr_url.replace('github.com', 'github.com.example.invalid'),
                    self.pr_url.replace('github.com', 'github.com:443'),
                    self.pr_url.replace('/pulls/4', '/pulls/%34')):
            with self.subTest(url=url), patch.object(transport.subprocess, 'run') as run:
                with self.assertRaisesRegex(transport.GitHubTransportError, 'outside the read scope'):
                    self.get(url)
                run.assert_not_called()

    def test_parent_passes_secret_on_stdin_only_and_drops_inherited_overrides(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'fixture', 'SSL_CERT_FILE': 'fixture',
                                    'SSLKEYLOGFILE': 'fixture', 'GITHUB_TOKEN': 'fixture',
                                    'PYTHONPATH': 'fixture'}):
            with patch.object(transport.subprocess, 'run',
                              return_value=subprocess.CompletedProcess([], 0, stdout=b'{}')) as run:
                result = self.get(self.pr_url)
        self.assertEqual(result, observer.ReadResponse(200, b'{}'))
        self.assertEqual(run.call_count, 1)
        argv, kw = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(argv[1:3], ['-I', '-S'])
        self.assertEqual(argv[-1], self.pr_path)
        self.assertNotIn(self.token, repr(argv).encode())
        self.assertNotIn(self.token, repr(kw['env']).encode())
        self.assertLessEqual(set(kw['env']), {'SystemRoot', 'WINDIR'})
        self.assertEqual(kw['input'], self.token)
        self.assertEqual(kw['timeout'], 15)
        self.assertEqual(kw['stderr'], subprocess.DEVNULL)

    def test_worker_errors_are_not_retried_or_revealed(self):
        for result in (subprocess.CompletedProcess([], 1, stdout=self.token),
                       subprocess.CompletedProcess([], 0, stdout=b''),
                       subprocess.CompletedProcess([], 0, stdout=b'x' * (transport._MAX_RESPONSE + 1)),
                       subprocess.TimeoutExpired('fixture', 15, output=self.token),
                       OSError(self.token.decode())):
            with self.subTest(kind=type(result)), patch.object(transport.subprocess, 'run') as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                with self.assertRaises(transport.GitHubTransportError) as caught:
                    self.get(self.pr_url)
                self.assertNotIn(self.token.decode(), str(caught.exception))
                run.assert_called_once()

    def test_invalid_token_cannot_start_worker_or_request(self):
        for token in (b'', b'a\r\nb', b'bearer x', b'x' * 2049, 'not bytes'):
            with self.subTest(token_type=type(token)), patch.object(transport, 'HTTPSConnection') as connect:
                with self.assertRaises(transport.GitHubTransportError):
                    transport.ScopedGitHubGet(self.repository, 4, token)
                with self.assertRaises(transport.GitHubTransportError):
                    transport._read_once(self.pr_path, token)
                connect.assert_not_called()

    @staticmethod
    def response(status, body=b'{}', **headers):
        reply = Mock()
        reply.status = status
        saved = {'Content-Type': 'application/json; charset=utf-8'} | headers
        reply.getheader.side_effect = lambda key, fallback=None: saved.get(key, fallback)
        reply.read.side_effect = io.BytesIO(body).read
        return reply

    def test_http_client_sends_only_bearer_get_on_verified_https(self):
        with patch.object(transport, 'HTTPSConnection') as connect:
            connection = connect.return_value
            response = self.response(200)
            connection.getresponse.return_value.__enter__.return_value = response
            self.assertEqual(transport._read_once(self.pr_path, self.token), b'{}')
        self.assertEqual(connect.call_args.args, ('api.github.com', 443))
        ctx = connect.call_args.kwargs['context']
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(connect.call_args.kwargs['timeout'], 5)
        self.assertEqual(connection.request.call_args.args, ('GET', self.pr_path))
        headers = connection.request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer dummy-fixture-token')
        self.assertEqual(headers['X-GitHub-Api-Version'], '2022-11-28')
        self.assertEqual(headers['Cache-Control'], 'no-cache, no-store')
        self.assertNotIn('If-None-Match', headers)
        self.assertNotIn('If-Modified-Since', headers)
        response.read.assert_called_once_with(transport._MAX_RESPONSE + 1)
        connection.close.assert_called_once()

    def test_worker_rejects_non_ok_without_read_redirect_or_retry(self):
        for status in (302, 304, 401, 403, 429, 500):
            with self.subTest(status=status), patch.object(transport, 'HTTPSConnection') as connect:
                connection = connect.return_value
                response = self.response(status, Location='https://other.example.invalid')
                connection.getresponse.return_value.__enter__.return_value = response
                with self.assertRaisesRegex(transport.GitHubTransportError, 'did not return OK'):
                    transport._read_once(self.pr_path, self.token)
                response.read.assert_not_called()
                connect.assert_called_once()
                connection.request.assert_called_once()
                connection.close.assert_called_once()

    def test_worker_rejects_invalid_framing_type_and_body_sizes(self):
        for headers, body, error in (
            ({'Content-Type': 'text/html'}, b'{}', 'not JSON'),
            ({'Content-Encoding': 'gzip'}, b'{}', 'response encoding'),
            ({'Content-Length': '2', 'Transfer-Encoding': 'chunked'}, b'{}', 'framing'),
            ({'Transfer-Encoding': 'unknown'}, b'{}', 'framing'),
            ({'Content-Length': str(transport._MAX_RESPONSE + 1)}, b'{}', 'response length'),
            ({'Content-Length': '4'}, b'{}', 'response body'),
            ({}, b'', 'response body'),
            ({}, b' ' * (transport._MAX_RESPONSE + 1), 'response body'),
        ):
            with self.subTest(headers=headers, size=len(body)):
                with self.assertRaisesRegex(transport.GitHubTransportError, error):
                    transport._bounded_json(self.response(200, body, **headers))
        body = b'{}' + b' ' * (transport._MAX_RESPONSE - 2)
        self.assertEqual(transport._bounded_json(self.response(200, body)), body)
        self.assertEqual(transport._MAX_RESPONSE, observer._MAX_RESPONSE)

    def test_observer_reads_exact_subject_with_transport_fixture(self):
        base, head = 'a' * 40, 'b' * 40
        repo = {'full_name': 'owner/repo', 'id': 123}
        pr = {'state': 'open', 'number': 4, 'merged': False,
              'base': {'ref': 'main', 'sha': base, 'repo': repo},
              'head': {'sha': head, 'repo': repo}}
        branch = {'name': 'main', 'protected': True, 'commit': {'sha': base}}
        replies = [subprocess.CompletedProcess([], 0, stdout=json.dumps(body).encode())
                   for body in (pr, branch)]
        with patch.object(transport.subprocess, 'run', side_effect=replies) as run:
            got = observer.GitHubObserver(self.repository, 4, self.get)()
        self.assertEqual((got.repository_id, got.pull_request, got.base, got.head), (123, 4, base, head))
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], [self.pr_path, self.branch_path])

    def test_invalid_path_worker_exits_silently_without_network(self):
        # Run the actual isolated child, but give it no admissible target.
        result = subprocess.run(
            [transport.sys.executable, '-I', '-S', transport.__file__, '/invalid'],
            input=self.token, capture_output=True, timeout=10, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((result.stdout, result.stderr), (b'', b''))
