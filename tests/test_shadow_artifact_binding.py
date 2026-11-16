import json
import os
from pathlib import Path
import tempfile
import unittest

from tools import shadow_artifact_binding as binding


class ArtifactBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = {'repository': 'example/repo', 'run_id': '123', 'run_attempt': '1',
                        'trusted_sha': 'a' * 40, 'pr_number': '42'}
        self.snapshot = {'baseRefName': 'main', 'state': 'OPEN', 'baseRefOid': 'b' * 40,
                         'headRefOid': 'c' * 40, 'mergeBaseOid': 'd' * 40}
        self.diff = b'diff --git a/f b/f\n@@ -1 +1 @@\n-a\n+b\n'
        (self.root / 'prompt.txt').write_bytes(b'Trusted instructions and untrusted diff')
        (self.root / 'diff.patch').write_bytes(self.diff)
        (self.root / 'snapshot.json').write_text(json.dumps(self.snapshot), encoding='utf-8')
        self.trusted = binding.seal(self.root, self.context)

    def verify(self, **overrides):
        args = dict(trusted_digest=self.trusted, trusted_context=self.context,
                    refetched_snapshot=self.snapshot, refetched_diff=self.diff)
        args.update(overrides)
        return binding.verify(self.root, **args)

    def test_valid_and_each_context_field_bound(self):
        self.assertEqual(self.verify()['context'], self.context)
        for key in self.context:
            changed = dict(self.context)
            changed[key] = {'repository': 'other/repo', 'trusted_sha': 'f' * 40}.get(key, '999')
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(trusted_context=changed)

    def test_provider_cannot_reseal_against_fetch_digest(self):
        (self.root / 'prompt.txt').write_bytes(b'forged instructions')
        with self.assertRaises(ValueError):
            self.verify()
        (self.root / 'manifest.json').unlink()
        forged = binding.seal(self.root, self.context)
        self.assertNotEqual(forged, self.trusted)
        with self.assertRaises(ValueError):
            self.verify()

    def test_independent_refetch_and_exact_inventory(self):
        with self.assertRaises(ValueError):
            self.verify(refetched_diff=b'different')
        with self.assertRaises(ValueError):
            self.verify(refetched_snapshot=dict(self.snapshot, headRefOid='f' * 40))
        (self.root / 'extra.txt').write_bytes(b'unexpected')
        with self.assertRaises(ValueError):
            self.verify()
        (self.root / 'extra.txt').unlink()
        (self.root / 'diff.patch').unlink()
        with self.assertRaises(ValueError):
            self.verify()

    def test_sizes_noncanonical_duplicate_and_stale_manifest(self):
        raw = (self.root / 'manifest.json').read_bytes()
        (self.root / 'manifest.json').write_bytes(b' ' + raw)
        with self.assertRaises(ValueError):
            self.verify(trusted_digest=binding.digest(b' ' + raw))
        with self.assertRaises(ValueError):
            binding.parse(b'{"a":1,"a":2}')
        (self.root / 'manifest.json').write_bytes(raw)
        with self.assertRaises(ValueError):
            binding.seal(self.root, self.context)
        (self.root / 'prompt.txt').write_bytes(b'x' * 100_001)
        with self.assertRaises(ValueError):
            self.verify()

    def test_directory_and_hardlink_entries_are_rejected(self):
        prompt = self.root / 'prompt.txt'
        prompt.unlink()
        prompt.mkdir()
        with self.assertRaises(ValueError):
            self.verify()
        prompt.rmdir()
        original = self.root.parent / (self.root.name + '-canary')
        try:
            original.write_bytes(b'outside bundle')
            os.link(original, prompt)
            with self.assertRaises(ValueError):
                self.verify()
        finally:
            if prompt.exists():
                prompt.unlink()
            if original.exists():
                original.unlink()
