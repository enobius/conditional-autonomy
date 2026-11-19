from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import trusted_review_adapter as adapter
from tools import trusted_review_guard as guard


class LocalGitAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.repo = Path(temp.name)
        cls.exe = Path(shutil.which('git')).resolve(strict=True)
        cls.fixture_env = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith('GIT_')}
        cls.fixture_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        cls.git_cmd('init', '--object-format=sha1')
        (cls.repo / 'nested').mkdir()
        (cls.repo / 'nested' / 'notes.md').write_bytes(b'first\n')
        cls.git_cmd('add', '.')
        cls.git_cmd('commit', '-m', 'base')
        cls.base = cls.git_cmd('rev-parse', 'HEAD').strip().decode()
        (cls.repo / 'nested' / 'notes.md').write_bytes(b'updated\n')
        (cls.repo / 'new.md').write_bytes(b'new\n')
        cls.git_cmd('add', '.')
        cls.git_cmd('commit', '-m', 'candidate')
        cls.head = cls.git_cmd('rev-parse', 'HEAD').strip().decode()
        cls.subject = guard.Subject(10, 2, cls.base, cls.head)

    @classmethod
    def git_cmd(cls, *args, data=b''):
        return subprocess.run([str(cls.exe), '-c', 'user.name=Test', '-c',
                               'user.email=test@example.invalid', *args],
                              cwd=cls.repo, env=cls.fixture_env, input=data,
                              capture_output=True, check=True, timeout=10).stdout

    @classmethod
    def obj(cls, kind, raw):
        return cls.git_cmd('hash-object', '--literally', '-w', '-t', kind,
                           '--stdin', data=raw).strip().decode()

    @classmethod
    def commit(cls, tree):
        return cls.obj('commit', (f'tree {tree}\n'
                                 'author Test <test@example.invalid> 1700000000 +0000\n'
                                 'committer Test <test@example.invalid> 1700000000 +0000\n'
                                 '\nfixture\n').encode())

    def run_adapter(self, **overrides):
        return adapter.evaluate_local(**({
            'git': adapter.LocalGit(self.exe, self.repo / '.git'),
            'repository_id': 10, 'trusted_policy_revision': self.base,
            'requested_policy_revision': self.base, 'subject': self.subject,
            'observe_current': lambda: self.subject,
        } | overrides))

    def test_real_git_complete_inventory_and_no_index_or_worktree_change(self):
        index = (self.repo / '.git/index').read_bytes()
        before = (self.repo / 'nested/notes.md').read_bytes()
        observer = Mock(return_value=self.subject)
        result = self.run_adapter(observe_current=observer)
        self.assertEqual(result.decision, guard.Decision.PROTECTED_CHANGE)
        self.assertEqual(result.protected_changes, ('nested/notes.md', 'new.md'))
        self.assertEqual(observer.call_count, 2)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        self.assertEqual((self.repo / 'nested/notes.md').read_bytes(), before)

    def test_stale_head_and_base_are_rejected_before_or_after_read(self):
        for changed in (replace(self.subject, head=self.base), replace(self.subject, base=self.head)):
            for sequence in ([changed], [self.subject, changed]):
                observer = Mock(side_effect=sequence)
                with self.subTest(sequence=sequence), self.assertRaisesRegex(guard.GuardError, 'changed'):
                    self.run_adapter(observe_current=observer)
        with self.assertRaisesRegex(guard.GuardError, 'observation failed'):
            self.run_adapter(observe_current=Mock(side_effect=OSError('unavailable')))

    def test_policy_must_match_external_pin_and_name_real_commit(self):
        with self.assertRaisesRegex(guard.GuardError, 'trusted pin'):
            self.run_adapter(requested_policy_revision=self.head)
        blob = self.obj('blob', b'not a commit')
        with self.assertRaisesRegex(guard.GuardError, 'type mismatch'):
            self.run_adapter(trusted_policy_revision=blob, requested_policy_revision=blob)
        with self.assertRaisesRegex(guard.GuardError, 'repository mismatch'):
            self.run_adapter(repository_id=11)

    def test_non_oid_ref_and_missing_commit_are_rejected(self):
        with self.assertRaisesRegex(guard.GuardError, 'object ID'):
            self.run_adapter(subject=replace(self.subject, head='HEAD'))
        missing = replace(self.subject, head='1' * 40)
        with self.assertRaisesRegex(guard.GuardError, 'Git read failed'):
            self.run_adapter(subject=missing, observe_current=lambda: missing)

    def test_missing_tree_blob_or_incomplete_record_never_yields_inventory(self):
        missing = bytes.fromhex('2' * 40)
        for raw, error in ((b'40000 nested\0' + missing, 'Git read failed'),
                           (b'100644 notes.md\0' + missing, 'blob missing'),
                           (b'100644 notes.md\0' + missing[:19], 'incomplete Git tree record')):
            subject = replace(self.subject, head=self.commit(self.obj('tree', raw)))
            with self.subTest(error=error), self.assertRaisesRegex(guard.GuardError, error):
                self.run_adapter(subject=subject, observe_current=lambda: subject)

    def test_replace_refs_and_inherited_git_environment_do_not_change_objects(self):
        self.git_cmd('replace', self.head, self.base)
        try:
            with patch.dict(os.environ, {'GIT_DIR': 'not-the-mirror', 'GIT_OBJECT_DIRECTORY': 'missing'}):
                self.assertEqual(self.run_adapter().protected_changes, ('nested/notes.md', 'new.md'))
        finally:
            self.git_cmd('replace', '-d', self.head)

    def test_metadata_hash_and_size_mismatch_fails_closed(self):
        git = adapter.LocalGit(self.exe, self.repo / '.git')
        with patch.object(git, '_run', side_effect=[b'commit\n', b'3\n', b'bad']):
            with self.assertRaisesRegex(guard.GuardError, 'integrity mismatch'):
                git.read_metadata_object(self.head, 'commit')
        with patch.object(git, '_run', side_effect=[b'commit\n', b'99999999\n']) as run:
            with self.assertRaisesRegex(guard.GuardError, 'too large'):
                git.read_metadata_object(self.head, 'commit')
            self.assertEqual(run.call_count, 2)

    def test_tree_walk_cannot_skip_limit_failure(self):
        git = adapter.LocalGit(self.exe, self.repo / '.git')
        with patch.object(adapter, '_MAX_TREES', 1):
            with self.assertRaisesRegex(guard.GuardError, 'traversal limit'):
                git.inventory(self.head)
