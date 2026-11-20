from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

from tools import trusted_review_observer as observer
from tools import trusted_review_guard as guard


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.repository = observer.Repository('owner', 'repo', 123)
        self.base, self.head, self.pin = '1' * 40, '2' * 40, '3' * 40
        identity = {'id': 123, 'full_name': 'Owner/Repo'}
        self.pr = {'number': 4, 'state': 'open', 'merged': False,
                   'base': {'ref': 'main', 'repo': identity.copy(), 'sha': self.base},
                   'head': {'repo': identity.copy(), 'sha': self.head}}
        self.branch = {'name': 'main', 'protected': True, 'commit': {'sha': self.base}}
        self.subject = guard.Subject(123, 4, self.base, self.head)
        self.urls = [call('https://api.github.com/repos/owner/repo/pulls/4'),
                     call('https://api.github.com/repos/owner/repo/branches/main')]

    @staticmethod
    def reply(payload):
        return observer.ReadResponse(200, json.dumps(payload).encode())

    def build(self, *payloads):
        get = Mock(side_effect=[self.reply(item) for item in payloads])
        return observer.GitHubObserver(self.repository, 4, get)

    def test_exact_api_paths_and_protected_main(self):
        view = self.build(self.pr, self.branch)
        self.assertEqual(view(), self.subject)
        self.assertEqual(view.get.call_args_list, self.urls)

    def test_pr_mismatches_stop_before_branch_read(self):
        for key, value in [(('number',), True), (('number',), 5), (('state',), 'closed'),
                           (('merged',), True), (('merged',), None), (('base', 'ref'), 'other'),
                           (('base', 'repo', 'id'), 124), (('base', 'repo', 'full_name'), 'other/repo'),
                           (('head', 'repo'), None), (('head', 'repo', 'id'), 999),
                           (('head', 'sha'), 'refs/heads/main'), (('base', 'sha'), '0' * 40)]:
            payload = deepcopy(self.pr)
            node = payload
            for part in key[:-1]:
                node = node[part]
            node[key[-1]] = value
            view = self.build(payload)
            with self.subTest(key=key, value=value), self.assertRaises(guard.GuardError):
                view()
            self.assertEqual(view.get.call_args_list, self.urls[:1])

    def test_branch_identity_protection_and_tip_must_match(self):
        for key, value in [('name', 'another'), ('protected', False), ('protected', 1),
                           ('commit', {'sha': self.head}), ('commit', {'sha': 'unknown'})]:
            view = self.build(self.pr, self.branch | {key: value})
            with self.subTest(key=key, value=value), self.assertRaises(guard.GuardError):
                view()

    def test_invalid_or_unavailable_read_fails(self):
        for response in (observer.ReadResponse(403, b'{}'), observer.ReadResponse(200, b''),
                         observer.ReadResponse(200, b'[]'), observer.ReadResponse(200, b'\xff'),
                         observer.ReadResponse(200, b'{')):
            with self.subTest(status=response.status, size=len(response.body)), self.assertRaises(guard.GuardError):
                observer.GitHubObserver(self.repository, 4, Mock(return_value=response))()
        view = observer.GitHubObserver(self.repository, 4, Mock(side_effect=OSError('fixture credential')))
        with self.assertRaisesRegex(guard.GuardError, '^authenticated GitHub read failed$') as caught:
            view()
        self.assertTrue(caught.exception.__suppress_context__)

    def observe_response(self, response):
        # A valid branch response is available, so later checks cannot mask
        # acceptance of an invalid PR response.
        get = Mock(side_effect=(response, self.reply(self.branch)))
        return observer.GitHubObserver(self.repository, 4, get)

    def assert_pr_read_rejected(self, response, error):
        view = self.observe_response(response)
        with self.assertRaisesRegex(guard.GuardError, error):
            view()
        self.assertEqual(view.get.call_args_list, self.urls[:1])

    def test_redirect_and_not_modified_reject_otherwise_valid_pr(self):
        valid = self.reply(self.pr)
        self.assertEqual(self.observe_response(valid)(), self.subject)
        for status in (302, 304):
            with self.subTest(status=status):
                self.assert_pr_read_rejected(replace(valid, status=status), 'observation unavailable')

    def test_size_limit_rejects_valid_json_one_byte_over(self):
        valid = self.reply(self.pr)
        at_limit = valid.body.ljust(observer._MAX_RESPONSE, b' ')
        self.assertEqual(self.observe_response(replace(valid, body=at_limit))(), self.subject)
        self.assert_pr_read_rejected(replace(valid, body=at_limit + b' '), 'or oversized')

    def test_duplicate_key_rejects_otherwise_valid_pr(self):
        valid = self.reply(self.pr)
        duplicate = b'{"number": 4, ' + valid.body[1:]
        self.assertEqual(json.loads(duplicate), self.pr)
        self.assert_pr_read_rejected(replace(valid, body=duplicate), 'duplicate key')

    def test_nan_in_ignored_field_rejects_otherwise_valid_pr(self):
        self.assertEqual(self.observe_response(self.reply(self.pr | {'ignored': 0}))(), self.subject)
        invalid = self.reply(self.pr | {'ignored': float('nan')})
        self.assert_pr_read_rejected(invalid, 'invalid numeric constant')

    def test_configuration_rejects_invalid_path_segments_and_ids(self):
        for owner, name, rid in [('owner/other', 'repo', 123), ('owner', '..', 123),
                                 ('owner', 'repo?x', 123), ('owner', 'repo', True)]:
            with self.subTest(owner=owner, name=name, rid=rid), self.assertRaises(guard.GuardError):
                observer.Repository(owner, name, rid)
        for number in (False, 0, '4'):
            with self.subTest(number=number), self.assertRaises(guard.GuardError):
                observer.GitHubObserver(self.repository, number, Mock())

    def mirror(self):
        return observer.MirrorBinding(self.repository, Path('git'), Path('mirror'), self.pin)

    def test_registration_mismatches_fail_before_opening_local_mirror(self):
        view = self.build()
        for mirror, subject in [(replace(self.mirror(), repository=replace(self.repository, repository_id=444)),
                                 self.subject), (self.mirror(), replace(self.subject, pull_request=7)),
                                (self.mirror(), replace(self.subject, repository_id=444))]:
            with self.subTest(mirror=mirror, subject=subject):
                with patch.object(observer.adapter, 'LocalGit') as git, self.assertRaises(guard.GuardError):
                    observer.evaluate_registered(mirror, observer=view, subject=subject,
                                                 requested_policy_revision=self.pin)
                git.assert_not_called()
        view.get.assert_not_called()

    def test_same_id_mirror_requires_matching_owner_and_name(self):
        for drift in ({'owner': 'other'}, {'name': 'other'}):
            with self.subTest(drift=drift):
                view = self.build(self.pr, self.branch)
                mirror = replace(self.mirror(), repository=replace(self.repository, **drift))
                with patch.object(observer.adapter, 'LocalGit') as git:
                    with self.assertRaisesRegex(guard.GuardError, 'observer does not match registered mirror'):
                        observer.evaluate_registered(mirror, observer=view, subject=self.subject,
                                                     requested_policy_revision=self.pin)
                    git.assert_not_called()
                view.get.assert_not_called()

    def test_integration_pins_policy_and_observes_before_and_after_inventory(self):
        for fresh in (True, False):
            with self.subTest(fresh=fresh):
                last = deepcopy(self.pr)
                if not fresh:
                    last['head']['sha'] = '4' * 40
                view = self.build(self.pr, self.branch, last, self.branch)
                timeline = Mock()
                with patch.object(observer.adapter, 'LocalGit') as local:
                    git = local.return_value
                    timeline.attach_mock(view.get, 'get')
                    timeline.attach_mock(git, 'git')
                    git.commit_tree.return_value = '5' * 40
                    git.inventory.side_effect = [guard.Inventory(self.base, ()),
                        guard.Inventory(self.head, (guard.Entry('new.md', '100644', '6' * 40),))]
                    if fresh:
                        result = observer.evaluate_registered(self.mirror(), observer=view,
                            subject=self.subject, requested_policy_revision=self.pin)
                        self.assertEqual(result.decision, guard.Decision.PROTECTED_CHANGE)
                        self.assertEqual(result.protected_changes, ('new.md',))
                    else:
                        with self.assertRaisesRegex(guard.GuardError, 'review subject changed'):
                            observer.evaluate_registered(self.mirror(), observer=view,
                                subject=self.subject, requested_policy_revision=self.pin)
                    self.assertEqual(timeline.mock_calls,
                        [call.get(*rpc.args) for rpc in self.urls] + [
                            call.git.commit_tree(self.pin), call.git.read_metadata_object('5' * 40, 'tree'),
                            call.git.inventory(self.base), call.git.inventory(self.head),
                        ] + [call.get(*rpc.args) for rpc in self.urls])
        view = self.build()
        with patch.object(observer.adapter, 'LocalGit') as local:
            with self.assertRaisesRegex(guard.GuardError, 'trusted pin'):
                observer.evaluate_registered(self.mirror(), observer=view, subject=self.subject,
                                             requested_policy_revision=self.head)
            local.return_value.inventory.assert_not_called()
        view.get.assert_not_called()
