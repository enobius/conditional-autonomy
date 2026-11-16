"""Offline installer tests: no downloaded code or network calls."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import install_claude_shadow as installer


def package(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, contents, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(contents) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(contents) if member.size else None)
    return output.getvalue()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ShadowInstallerTests(unittest.TestCase):
    def test_valid_archive_only_installs_verified_binary(self):
        binary = b'fixture, never executed'
        data = package([('package/claude', binary, tarfile.REGTYPE),
                        ('../../outside', b'not extracted', tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory() as directory:
            result = installer.install_from_stream(io.BytesIO(data), directory,
                                                   archive_hash=digest(data), binary_hash=digest(binary))
            self.assertEqual(result.read_bytes(), binary)
            self.assertEqual([path.name for path in result.parent.iterdir()], ['claude'])
            self.assertFalse((Path(directory) / 'outside').exists())

    def test_rejects_forgery_missing_duplicate_and_link(self):
        binary = b'fixture'
        cases = [
            (package([('package/claude', binary, tarfile.REGTYPE)]), 'bad-archive', digest(binary)),
            (package([('package/claude', binary, tarfile.REGTYPE)]), None, 'bad-binary'),
            (package([('other', binary, tarfile.REGTYPE)]), None, digest(binary)),
            (package([('package/claude', binary, tarfile.REGTYPE)] * 2), None, digest(binary)),
            (package([('package/claude', b'', tarfile.SYMTYPE)]), None, digest(binary)),
            (b'not a tar', None, digest(binary)),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for data, archive_hash, binary_hash in cases:
                with self.subTest(archive_hash=archive_hash, binary_hash=binary_hash):
                    with self.assertRaises((ValueError, tarfile.TarError)):
                        installer.install_from_stream(io.BytesIO(data), directory,
                                                      archive_hash=archive_hash or digest(data),
                                                      binary_hash=binary_hash)
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stream_size_limit_and_redirect_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'size limit'):
                installer.copy_checked(io.BytesIO(b'1234'), Path(directory) / 'x', 'irrelevant', 3)
        with self.assertRaisesRegex(ValueError, 'redirects'):
            installer.RejectRedirects().redirect_request(None, None, None, None, None, 'http://example.invalid')

    def test_main_uses_exact_https_package_and_redirect_rejecting_opener(self):
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        binary = b'fixture'
        data = package([('package/claude', binary, tarfile.REGTYPE)])
        original_install = installer.install_from_stream
        with tempfile.TemporaryDirectory() as directory:
            response = io.BytesIO(data)
            opener = SimpleNamespace(open=unittest.mock.Mock(return_value=response))
            with patch.dict('os.environ', {'RUNNER_TEMP': directory}), \
                 patch.object(installer.urllib.request, 'build_opener', return_value=opener) as build, \
                 patch.object(installer, 'install_from_stream', side_effect=lambda source, root: original_install(
                     source, root, archive_hash=digest(data), binary_hash=digest(binary))), \
                 redirect_stdout(io.StringIO()):
                installer.main()
            self.assertIsInstance(build.call_args.args[0], installer.RejectRedirects)
            opener.open.assert_called_once_with(
                'https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.319.tgz',
                timeout=120)


if __name__ == '__main__':
    unittest.main()
