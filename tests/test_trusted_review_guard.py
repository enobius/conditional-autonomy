from dataclasses import replace
import unittest

from tools.trusted_review_guard import (
    Decision, Entry, GuardError, Inventory, OwnerException, Policy, Subject, evaluate,
)


class TrustedReviewGuardTests(unittest.TestCase):
    def setUp(self):
        self.subject = Subject(123, 45, 'a' * 40, 'b' * 40)
        self.policy = Policy('c' * 40)
        self.file = Entry('.github/workflows/shadow-review-guard.yml', '100644', '1' * 40)
        self.notes = Entry('notes.md', '100644', '2' * 40)
        self.base = Inventory(self.subject.base, (self.file, self.notes))
        self.changed = replace(self.file, oid='3' * 40)
        self.head = Inventory(self.subject.head, (self.changed, self.notes))
        self.exception = OwnerException(self.subject, self.policy.revision, (self.file.path,))

    def run_guard(self, **overrides):
        return evaluate(**({'subject': self.subject, 'current': self.subject, 'base': self.base,
                            'candidate': self.head, 'policy': self.policy} | overrides))

    def test_default_protects_changes_even_if_other_files_match(self):
        self.assertEqual(self.run_guard().decision, Decision.PROTECTED_CHANGE)
        self.assertEqual(self.run_guard().protected_changes, (self.file.path,))
        current = replace(self.head, entries=self.base.entries[::-1])
        self.assertEqual(self.run_guard(candidate=current).decision, Decision.NO_PROTECTED_CHANGE)

    def test_path_exemption_is_exact_and_only_for_regular_content_changes(self):
        policy = replace(self.policy, exempt_paths=(self.notes.path,))
        changed = replace(self.notes, oid='4' * 40)
        def check(*entries):
            return self.run_guard(policy=policy, candidate=replace(self.head, entries=entries))
        self.assertEqual(check(self.file, changed).decision, Decision.NO_PROTECTED_CHANGE)
        for entry in (replace(self.notes, mode='100755'), replace(self.notes, mode='120000'),
                      replace(self.notes, mode='160000'), replace(changed, path='Notes.md'),
                      replace(changed, path='sub/notes.md')):
            with self.subTest(entry=entry):
                self.assertEqual(check(self.file, entry).decision, Decision.PROTECTED_CHANGE)
        self.assertEqual(check(self.file).protected_changes, (self.notes.path,))
        self.assertEqual(check(self.file, self.notes, Entry('new.md', '100644', '2' * 40))
                         .protected_changes, ('new.md',))
        with self.assertRaises(GuardError):
            self.run_guard(policy=replace(policy, exempt_paths=('**',)))

    def test_rename_protects_both_endpoints_even_with_identical_blob(self):
        new = replace(self.file, path='tools/renamed.yml')
        renamed = replace(self.head, entries=(new, self.notes))
        self.assertEqual(self.run_guard(candidate=renamed).protected_changes, (self.file.path, new.path))

    def test_exact_external_exception_not_a_merge_verdict(self):
        result = self.run_guard(owner_exception=self.exception)
        self.assertEqual(result.decision, Decision.COVERED_BY_EXCEPTION)
        self.assertEqual(result.protected_changes, (self.file.path,))
        with self.assertRaises(GuardError):
            self.run_guard(owner_exception={'subject': self.subject})

    def test_exception_must_match_identity_policy_and_entire_protected_set(self):
        for changed in (
            replace(self.exception, subject=replace(self.subject, repository_id=456)),
            replace(self.exception, subject=replace(self.subject, pull_request=46)),
            replace(self.exception, subject=replace(self.subject, base='e' * 40)),
            replace(self.exception, subject=replace(self.subject, head='d' * 40)),
            replace(self.exception, policy_revision='9' * 40),
            replace(self.exception, protected_changes=()),
            replace(self.exception, protected_changes=(self.file.path, self.file.path)),
            replace(self.exception, protected_changes=(self.file.path, self.notes.path)),
        ):
            with self.subTest(changed=changed), self.assertRaises(GuardError):
                self.run_guard(owner_exception=changed)
        no_changes = replace(self.head, entries=self.base.entries)
        with self.assertRaises(GuardError):
            self.run_guard(owner_exception=self.exception, candidate=no_changes)

    def test_current_subject_and_inventory_revision_must_match(self):
        for key in ('head', 'base', 'pull_request', 'repository_id'):
            value = 'd' * 40 if key in ('head', 'base') else 60
            with self.subTest(key=key), self.assertRaisesRegex(GuardError, 'subject changed'):
                self.run_guard(current=replace(self.subject, **{key: value}))
        with self.assertRaisesRegex(GuardError, 'revision mismatch'):
            self.run_guard(candidate=self.base)

    def test_malformed_tree_entries_fail_closed(self):
        for path in ('a/../b', '/absolute', 'a//b', '.git/config', 'a/./b',
                     'a\\b', 'bad path', 'a./b', 'a\nb'):
            with self.subTest(path=path), self.assertRaises(GuardError):
                self.run_guard(candidate=replace(self.head, entries=(replace(self.file, path=path),)))
        for entries in ((self.file, self.file),
                        (self.file, replace(self.file, path='.GITHUB/policy.json')),
                        (self.notes, replace(self.file, path='notes.md/child')),
                        (replace(self.file, mode='040000'),),
                        (replace(self.file, oid='0' * 40),),
                        (replace(self.file, oid='xyz'),)):
            with self.subTest(entries=entries), self.assertRaises(GuardError):
                self.run_guard(candidate=replace(self.head, entries=entries))

    def test_same_revision_cannot_supply_two_different_inventories(self):
        subject = replace(self.subject, head=self.subject.base)
        with self.assertRaisesRegex(GuardError, 'inconsistent inventories'):
            self.run_guard(subject=subject, current=subject,
                           candidate=replace(self.head, revision=subject.head))
