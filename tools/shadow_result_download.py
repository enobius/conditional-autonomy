"""Fetch an untrusted result ZIP; never extract archive-controlled paths."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

ZIP_LIMIT = 2_000_000
RESULT_LIMIT = 1_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def default_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def bounded(response, limit):
    raw = response.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('empty or oversized artifact response')
    return raw


def result_bytes(raw):
    if not raw or len(raw) > ZIP_LIMIT or not raw.startswith(b'PK\x03\x04'):
        raise ValueError('invalid result ZIP envelope')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != 1:
            raise ValueError('result ZIP must have exactly one entry')
        item = entries[0]
        kind = stat.S_IFMT(item.external_attr >> 16)
        if (item.filename != 'result.json' or item.orig_filename != 'result.json' or item.is_dir() or
                kind not in (0, stat.S_IFREG) or item.flag_bits & 1 or
                item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                not 0 < item.file_size <= RESULT_LIMIT or item.compress_size > ZIP_LIMIT):
            raise ValueError('unsupported or oversized result ZIP member')
        with archive.open(item) as source:
            value = bounded(source, RESULT_LIMIT)
        if len(value) != item.file_size:
            raise ValueError('result ZIP length mismatch')
        return value


def download(repository, artifact_id, run_id, token, opener=None):
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or
            not re.fullmatch('[1-9][0-9]*', artifact_id) or not re.fullmatch('[1-9][0-9]*', run_id) or
            not token or '\n' in token or '\r' in token):
        raise ValueError('invalid artifact request identity')
    opener = opener or default_opener()
    endpoint = f'https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'conditional-autonomy-shadow'}
    with opener.open(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
        metadata = json.loads(bounded(response, 64_000))
    if (not isinstance(metadata, dict) or not isinstance(metadata.get('workflow_run'), dict) or
            str(metadata.get('id')) != artifact_id or metadata.get('expired') is not False or
            str(metadata.get('workflow_run', {}).get('id')) != run_id or
            type(metadata.get('size_in_bytes')) is not int or not 0 < metadata['size_in_bytes'] <= ZIP_LIMIT):
        raise ValueError('artifact is unavailable, oversized or belongs to another run')
    try:
        response = opener.open(urllib.request.Request(endpoint + '/zip', headers=headers), timeout=30)
    except urllib.error.HTTPError as redirect:
        with redirect:
            if redirect.code != 302:
                raise
            location = redirect.headers.get('Location', '')
    else:
        with response:
            # Accept a direct API ZIP response without forwarding credentials.
            return result_bytes(bounded(response, ZIP_LIMIT))
    url = urllib.parse.urlsplit(location)
    if (url.scheme != 'https' or url.username or url.password or url.port not in (None, 443) or url.fragment or
            not url.hostname or not (url.hostname.endswith('.blob.core.windows.net') or
                                    url.hostname.endswith('.actions.githubusercontent.com'))):
        raise ValueError('unexpected artifact storage redirect')
    # A separate request: NEVER forward GitHub Authorization to signed storage.
    with opener.open(urllib.request.Request(location, headers={'User-Agent': 'conditional-autonomy-shadow'}), timeout=30) as response:
        return result_bytes(bounded(response, ZIP_LIMIT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = download(os.environ['GITHUB_REPOSITORY'], os.environ['RESULT_ARTIFACT_ID'],
                       os.environ['GITHUB_RUN_ID'], os.environ['GH_TOKEN'])
        args.destination_dir.mkdir()  # Never reuse an existing/symlinked directory.
        with (args.destination_dir / 'result.json').open('xb') as output:
            output.write(raw)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
        print('Result artifact rejected:', type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
