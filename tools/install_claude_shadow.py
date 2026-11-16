"""Install the pinned shadow CLI before any provider credential is available.

Only authenticated-by-hash bytes are extracted; the package is never executed.
This is not a substitute for independent provenance review of the pinned hashes.
"""
import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

URL = ('https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/'
       '-/claude-code-linux-x64-2.1.319.tgz')
ARCHIVE_SHA256 = '9b7b53954b8ffb886fafeefe9ef1e0e9e5c15e8aaf2f54d65ba64d0cca795dc7'
BINARY_SHA256 = 'dabafec82ca1319fa43d8be36a10fc61b1d11821cb98ad5df04ad95e199b8eed'
ARCHIVE_LIMIT = 250 * 1024 * 1024
BINARY_LIMIT = 400 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('CLI package redirects are not allowed')


def copy_checked(source, target, expected_hash, limit):
    digest = hashlib.sha256()
    total = 0
    with target.open('xb') as output:
        while True:
            block = source.read(CHUNK_SIZE)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError('CLI package exceeded size limit')
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != expected_hash:
        raise ValueError('CLI package checksum mismatch')


def install_from_stream(source, runner_temp, *, archive_hash=ARCHIVE_SHA256,
                        binary_hash=BINARY_SHA256):
    """Return a private installed path; remove our private directory on failure."""
    root = Path(tempfile.mkdtemp(prefix='claude-shadow-', dir=runner_temp))
    try:
        archive = root / 'package.tgz'
        binary = root / 'claude'
        copy_checked(source, archive, archive_hash, ARCHIVE_LIMIT)
        with tarfile.open(archive, 'r:gz') as package:
            matches = [member for member in package if member.name == 'package/claude']
            if len(matches) != 1 or not matches[0].isreg():
                raise ValueError('package must contain one regular CLI binary')
            if matches[0].size > BINARY_LIMIT:
                raise ValueError('CLI binary exceeded size limit')
            with package.extractfile(matches[0]) as member:
                copy_checked(member, binary, binary_hash, BINARY_LIMIT)
        binary.chmod(0o700)
        archive.unlink()
        return binary
    except BaseException:
        shutil.rmtree(root)
        raise


def main():
    runner_temp = os.environ['RUNNER_TEMP']
    opener = urllib.request.build_opener(RejectRedirects())
    with opener.open(URL, timeout=120) as response:
        binary = install_from_stream(response, runner_temp)
    print(binary)


if __name__ == '__main__':
    main()
