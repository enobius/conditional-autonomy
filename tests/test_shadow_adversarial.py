import copy
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.shadow_adversarial_client import inspect_boundary, readonly_mount_view
from tests.shadow_adversarial_host import check_report


class AdversarialBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.config = {'host': '172.17.0.1', 'port': 12345, 'forbidden_paths': ['/host-canary']}
        self.report = {'kind': 'hostile-client-v1', 'clean_environment': True,
                       'readonly_mount_view': True,
                       'placeholder_only': True, 'host_files_hidden': True,
                       'writes_blocked': True, 'routes_blocked': {'artifact': True, 'cache': True}}

    def inspect(self, *, extra_env=None, files=None, connect=None):
        env = {'CLAUDE_CODE_OAUTH_TOKEN': 'sk-ant-oat01-shadow-placeholder', **(extra_env or {})}
        with patch.dict(os.environ, env, clear=True), patch('builtins.open',
                side_effect=files or PermissionError()), patch(
                'tests.shadow_adversarial_client.socket.create_connection',
                side_effect=connect or OSError(101, 'no route')) as connection:
            with patch('tests.shadow_adversarial_client.Path.read_text', return_value=self.mounts()):
                result = inspect_boundary(self.config)
            self.assertEqual(connection.call_count, 2)
            return result

    @staticmethod
    def mounts():
        return '\n'.join('1 0 0:1 / ' + p + ' ro - tmpfs tmpfs rw'
                         for p in ('/', '/cli/claude', '/sandbox/tools'))

    def test_mount_view_fails_closed(self):
        rows = self.mounts().splitlines()
        for bad in (rows[1:], rows + rows[:1], [rows[0].replace(' ro ', ' rw '), *rows[1:]]):
            self.assertFalse(readonly_mount_view('\n'.join(bad)))

    def test_wrong_placeholder_root_write_and_unexpected_read_error(self):
        with self.assertRaises(ValueError):
            check_report(json.dumps(self.inspect(extra_env={'CLAUDE_CODE_OAUTH_TOKEN': 'wrong'})))
        def root_writable(path, mode):
            if path == '/hostile-marker' and mode == 'xb':
                return io.BytesIO()
            raise PermissionError()
        with self.assertRaises(ValueError):
            check_report(json.dumps(self.inspect(files=root_writable)))
        with self.assertRaisesRegex(OSError, 'unexpected'):
            self.inspect(files=OSError('unexpected'))

    def test_denial_report_and_exact_oracle(self):
        result = self.inspect()
        self.assertEqual(result, self.report)
        check_report(json.dumps(result).encode())

    def test_oracle_rejects_each_missing_or_false_check(self):
        for key in self.report:
            for replacement in [None, False, 1]:
                value = copy.deepcopy(self.report)
                value[key] = replacement
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                    check_report(json.dumps(value).encode())
        for name in ['cache', 'artifact']:
            value = copy.deepcopy(self.report)
            value['routes_blocked'][name] = False
            with self.assertRaises(ValueError):
                check_report(json.dumps(value).encode())

    def test_host_environment_inheritance_fails(self):
        for name in ['GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_CACHE_URL',
                     'ACTIONS_RESULTS_URL', 'GITHUB_ENV', 'GITHUB_OUTPUT']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_report(json.dumps(self.inspect(extra_env={name: 'dummy'})).encode())

    def test_readable_host_file_and_writable_mount_fail(self):
        def readable(path, mode):
            if mode == 'rb':
                return io.BytesIO(b'dummy')
            raise PermissionError()

        def writable(path, mode):
            if mode == 'xb':
                return io.BytesIO()
            raise FileNotFoundError()

        for files in [readable, writable]:
            with self.subTest(files=files.__name__), self.assertRaises(ValueError):
                check_report(json.dumps(self.inspect(files=files)).encode())

    def test_reachable_service_and_refused_connection_are_not_isolation(self):
        for connect in [lambda *_a, **_k: MagicMock(), OSError(111, 'refused')]:
            with self.subTest(connect=type(connect).__name__), self.assertRaises(ValueError):
                check_report(json.dumps(self.inspect(connect=connect)).encode())


if __name__ == '__main__':
    unittest.main()
