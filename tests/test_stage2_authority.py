"""S2-01 control-plane tests use synthetic approval fixtures only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import unittest

from runtime.conditional_autonomy.stage2_authority import (
    Stage2AuthorityError, artifact_set_hash, require_stage2_authority,
    verify_development_pin_integrity,
)


class Stage2AuthorityTests(unittest.TestCase):
    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def fixture(self, root):
        self.git(root, 'init')
        self.git(root, 'config', 'user.name', 'Synthetic Test')
        self.git(root, 'config', 'user.email', 'synthetic@example.invalid')
        self.git(root, 'config', 'core.autocrlf', 'false')
        (root / 'draft.md').write_bytes(b'SYNTHETIC DEVELOPMENT ONLY\n')
        self.git(root, 'add', 'draft.md')
        self.git(root, '-c', 'commit.gpgsign=false', 'commit', '-m', 'Synthetic draft')
        commit = self.git(root, 'rev-parse', 'HEAD')
        data = (root / 'draft.md').read_bytes()
        artifacts = [{'path': 'draft.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}]
        binding = artifact_set_hash(artifacts)
        return {'schema_version': '1.0', 'scope': 'DEVELOPMENT_CANDIDATE',
                'artifacts': artifacts, 'artifact_set_hash': binding,
                'owner_approval': {'approved': True, 'owner': 'synthetic-test-owner',
                                   'statement': 'Synthetic fixture, not a real owner approval',
                                   'draft_commit': commit, 'artifact_set_hash': binding}}

    def test_nonexistent_commit_and_noncommit_object_block(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            record = self.fixture(root)
            for oid in ('a' * 40, self.git(root, 'rev-parse', 'HEAD:draft.md'),
                        self.git(root, 'rev-parse', 'HEAD^{tree}')):
                changed = deepcopy(record)
                changed['owner_approval']['draft_commit'] = oid
                with self.assertRaises(Stage2AuthorityError):
                    require_stage2_authority(root, changed, phase='development')

    def test_existing_commit_with_changed_or_missing_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            record = self.fixture(root)
            (root / 'draft.md').write_bytes(b'DIFFERENT COMMITTED BYTES\n')
            self.git(root, 'add', 'draft.md')
            self.git(root, '-c', 'commit.gpgsign=false', 'commit', '-m', 'Different bytes')
            wrong_commit = self.git(root, 'rev-parse', 'HEAD')
            self.git(root, 'rm', 'draft.md')
            self.git(root, '-c', 'commit.gpgsign=false', 'commit', '-m', 'Missing artifact')
            missing_commit = self.git(root, 'rev-parse', 'HEAD')
            (root / 'draft.md').write_bytes(b'SYNTHETIC DEVELOPMENT ONLY\n')
            for commit in (wrong_commit, missing_commit):
                changed = deepcopy(record)
                changed['owner_approval']['draft_commit'] = commit
                with self.assertRaises(Stage2AuthorityError):
                    require_stage2_authority(root, changed, phase='development')
            # Authority binds the approved historical commit, not current HEAD.
            require_stage2_authority(root, record, phase='development')

    def test_draft_pin_is_never_confirmatory_authority(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            record = self.fixture(root)
            require_stage2_authority(root, record, phase='development')
            for phase in ('confirmatory', 'FINAL', ''):
                with self.assertRaises(Stage2AuthorityError):
                    require_stage2_authority(root, record, phase=phase)

    def test_missing_unbound_or_non_boolean_approval_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            record = self.fixture(root)
            for key, value in [('approved', False), ('approved', 1), ('owner', ''),
                               ('statement', ''), ('draft_commit', None),
                               ('artifact_set_hash', '0' * 64)]:
                changed = deepcopy(record)
                changed['owner_approval'][key] = value
                with self.assertRaises(Stage2AuthorityError):
                    require_stage2_authority(root, changed, phase='development')

    def test_changed_bytes_missing_inventory_and_path_escape_block(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            record = self.fixture(root)
            (root / 'draft.md').write_bytes(b'CHANGED')
            with self.assertRaises(Stage2AuthorityError):
                verify_development_pin_integrity(root, record)
            for path in ('../outside', '/outside', 'C:/outside', 'a\\b'):
                changed = deepcopy(record)
                changed['artifacts'][0]['path'] = path
                changed['artifact_set_hash'] = artifact_set_hash(changed['artifacts'])
                with self.assertRaises(Stage2AuthorityError):
                    verify_development_pin_integrity(root, changed)
            record['artifacts'] = []
            record['artifact_set_hash'] = artifact_set_hash([])
            with self.assertRaises(Stage2AuthorityError):
                verify_development_pin_integrity(root, record)

    def test_actual_v6_candidate_is_intact_but_not_approved(self):
        root = Path(__file__).resolve().parents[1]
        record = json.loads((root / 'outputs/Stage_2_Development_Pin_v6.json').read_text())
        verify_development_pin_integrity(root, record)
        for phase in ('development', 'confirmatory'):
            with self.assertRaises(Stage2AuthorityError):
                require_stage2_authority(root, record, phase=phase)


if __name__ == '__main__':
    unittest.main()
