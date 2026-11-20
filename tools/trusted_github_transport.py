"""Scoped GitHub GET transport for a trusted controller, not a live workflow.

The controller supplies a short-lived, read-scoped token independently of PR
input. This module neither provisions credentials nor verifies their grants.
"""
from http.client import HTTPSConnection
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys


_HOST = 'api.github.com'
_ORIGIN = 'https://' + _HOST
_API_VERSION = '2022-11-28'
_MAX_RESPONSE = 2 * 1024 * 1024
_IO_TIMEOUT = 5
_WORKER_TIMEOUT = 15
_MAX_TOKEN = 2048
_TOKEN = re.compile(rb'[A-Za-z0-9_.~+/-]{1,2048}=*')
_PATH = re.compile(r'/repos/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}'
                   r'/(?:branches/main|pulls/[1-9][0-9]{0,18})')


class GitHubTransportError(ValueError):
    """Read failed; raw response and credential material are not surfaced."""


def _valid_token(token):
    return type(token) is bytes and len(token) <= _MAX_TOKEN and _TOKEN.fullmatch(token)


def _bounded_json(response):
    if response.status != 200:
        raise GitHubTransportError('GitHub did not return OK')
    if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
        raise GitHubTransportError('unsupported GitHub response encoding')
    mime = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
    if mime not in ('application/json', 'application/vnd.github+json'):
        raise GitHubTransportError('GitHub content type is not JSON')
    length = response.getheader('Content-Length')
    transfer = response.getheader('Transfer-Encoding')
    if transfer is not None and (transfer.lower() != 'chunked' or length is not None):
        raise GitHubTransportError('ambiguous GitHub response framing')
    if length is not None:
        if not re.fullmatch(r'[0-9]{1,7}', length) or not 0 < int(length) <= _MAX_RESPONSE:
            raise GitHubTransportError('invalid or oversized GitHub response length')
    body = response.read(_MAX_RESPONSE + 1)
    if not 0 < len(body) <= _MAX_RESPONSE or (length is not None and len(body) != int(length)):
        raise GitHubTransportError('invalid or oversized GitHub response body')
    return body


def _read_once(path, token):
    if (not _PATH.fullmatch(path) or path.split('/')[3] in ('.', '..') or
            not _valid_token(token)):
        raise GitHubTransportError('invalid scoped GitHub request')
    # Direct HTTPSConnection does not consult proxy env, follow redirects,
    # cache, retry, or pick up a lower-trust caller-supplied HTTP method/host.
    context = ssl.create_default_context()
    connection = HTTPSConnection(_HOST, 443, timeout=_IO_TIMEOUT, context=context)
    try:
        connection.request('GET', path, headers={
            'Authorization': 'Bearer ' + token.decode('ascii'),
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': _API_VERSION,
            'User-Agent': 'conditional-autonomy-review',
            'Accept-Encoding': 'identity',
            'Cache-Control': 'no-cache, no-store',
        })
        with connection.getresponse() as response:
            return _bounded_json(response)
    finally:
        connection.close()


def _worker(argv):
    if len(argv) != 2:
        return 1
    try:
        token = sys.stdin.buffer.read(_MAX_TOKEN + 1)
        body = _read_once(argv[1], token)
        sys.stdout.buffer.write(body)
    except Exception:
        # One exit status; no remote body, header or exception diagnostics.
        return 1
    return 0


class ScopedGitHubGet:
    """AuthenticatedGet callable bound to exactly one repository and PR."""

    def __init__(self, repository, number, token: bytes):
        from tools.trusted_review_observer import Repository, ReadResponse

        if (type(repository) is not Repository or type(number) is not int or
                not 0 < number < 10**19 or not _valid_token(token)):
            raise GitHubTransportError('invalid GitHub transport configuration')
        root = f'/repos/{repository.slug}'
        self._paths = frozenset((f'{root}/pulls/{number}', f'{root}/branches/main'))
        self._token = token
        self._response = ReadResponse

    def __call__(self, url: str):
        if type(url) is not str or not url.startswith(_ORIGIN) or url[len(_ORIGIN):] not in self._paths:
            raise GitHubTransportError('GitHub URL is outside the read scope')
        # The whole worker has a deadline, including slow headers and DNS.
        # Stdin alone carries the token; do not inherit proxy or TLS overrides.
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR')
               if key in os.environ}
        script = Path(__file__).resolve()
        try:
            result = subprocess.run(
                [sys.executable, '-I', '-S', str(script), url[len(_ORIGIN):]],
                input=self._token, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=script.parent, env=env, timeout=_WORKER_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError):
            raise GitHubTransportError('GitHub read worker failed or timed out') from None
        if result.returncode != 0 or not 0 < len(result.stdout) <= _MAX_RESPONSE:
            raise GitHubTransportError('GitHub read did not yield a bounded response')
        return self._response(200, result.stdout)


if __name__ == '__main__':
    raise SystemExit(_worker(sys.argv))
