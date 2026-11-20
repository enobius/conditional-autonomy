"""Read-only GitHub observation and mirror binding; no live transport.

The controller must provision both the authenticated GET transport and mirror
configuration outside the PR. A response-shaped object is not authentication.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable

from tools import trusted_review_adapter as adapter
from tools import trusted_review_guard as guard


_MAX_RESPONSE = 2 * 1024 * 1024
_API = 'https://api.github.com'
_OWNER = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,38}')
_REPO = re.compile(r'[a-zA-Z0-9_.-]{1,100}')


def _positive_int(value):
    return type(value) is int and value > 0


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str
    repository_id: int

    def __post_init__(self):
        if (type(self.owner) is not str or not _OWNER.fullmatch(self.owner) or
                type(self.name) is not str or not _REPO.fullmatch(self.name) or
                self.name in ('.', '..') or not _positive_int(self.repository_id)):
            raise guard.GuardError('invalid trusted repository identity')

    @property
    def slug(self):
        return f'{self.owner}/{self.name}'


@dataclass(frozen=True)
class ReadResponse:
    status: int
    body: bytes


# Supply a fresh authenticated GitHub GET only: no redirect, no cached or
# conditional response, bounded body, fixed deadline and verified HTTPS.
AuthenticatedGet = Callable[[str], ReadResponse]


def _unique_object(items):
    value = {}
    for key, member in items:
        if key in value:
            raise guard.GuardError('duplicate key in GitHub observation')
        value[key] = member
    return value


def _invalid_constant(_value):
    raise guard.GuardError('invalid numeric constant in GitHub observation')


def _object(value):
    if type(value) is not dict:
        raise guard.GuardError('invalid GitHub observation shape')
    return value


def _read(get: AuthenticatedGet, url: str) -> dict:
    try:
        reply = get(url)
    except Exception:
        # Never surface transport messages that could embed credentials.
        raise guard.GuardError('authenticated GitHub read failed') from None
    if (type(reply) is not ReadResponse or type(reply.status) is not int or
            reply.status != 200 or type(reply.body) is not bytes or
            not 0 < len(reply.body) <= _MAX_RESPONSE):
        raise guard.GuardError('GitHub observation unavailable or oversized')
    try:
        value = json.loads(reply.body.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise guard.GuardError('malformed GitHub observation') from None
    return _object(value)


def _verify_repository(value, expected: Repository):
    item = _object(value)
    identifier, name = item.get('id'), item.get('full_name')
    if (not _positive_int(identifier) or identifier != expected.repository_id or
            type(name) is not str or not name.isascii() or name.lower() != expected.slug.lower()):
        raise guard.GuardError('GitHub repository identity mismatch')


@dataclass(frozen=True)
class GitHubObserver:
    repository: Repository
    number: int
    get: AuthenticatedGet

    def __post_init__(self):
        if (type(self.repository) is not Repository or not _positive_int(self.number) or
                not callable(self.get)):
            raise guard.GuardError('invalid observer configuration')

    def __call__(self) -> guard.Subject:
        root = f'{_API}/repos/{self.repository.slug}'
        pr = _read(self.get, f'{root}/pulls/{self.number}')
        if (not _positive_int(pr.get('number')) or pr['number'] != self.number or
                pr.get('state') != 'open' or pr.get('merged') is not False):
            raise guard.GuardError('GitHub PR identity or state mismatch')
        base, head = _object(pr.get('base')), _object(pr.get('head'))
        # Initial scope: same-repository PRs targeting protected main. A fork,
        # deleted source repository or retargeted PR is not acceptable evidence.
        _verify_repository(base.get('repo'), self.repository)
        _verify_repository(head.get('repo'), self.repository)
        if base.get('ref') != 'main':
            raise guard.GuardError('GitHub PR does not target main')
        subject = guard.Subject(self.repository.repository_id, self.number,
                                base.get('sha'), head.get('sha'))
        guard._subject(subject)
        branch = _read(self.get, f'{root}/branches/main')
        tip = _object(branch.get('commit')).get('sha')
        guard._require_oid(tip)
        if branch.get('name') != 'main' or branch.get('protected') is not True or tip != subject.base:
            raise guard.GuardError('GitHub protected main observation mismatch')
        return subject


@dataclass(frozen=True)
class MirrorBinding:
    """Controller-owned registration, not a claim derived from Git remote config."""
    repository: Repository
    git: Path
    git_dir: Path
    policy_revision: str

    def __post_init__(self):
        if type(self.repository) is not Repository:
            raise guard.GuardError('invalid mirror registration')
        guard._require_oid(self.policy_revision)


def evaluate_registered(mirror: MirrorBinding, *, observer: GitHubObserver,
                        subject: guard.Subject, requested_policy_revision: str) -> guard.Result:
    """Recheck the expected subject before and after reading the registered mirror."""
    if (type(mirror) is not MirrorBinding or type(observer) is not GitHubObserver or
            mirror.repository != observer.repository):
        raise guard.GuardError('observer does not match registered mirror')
    guard._subject(subject)
    if subject.repository_id != mirror.repository.repository_id or subject.pull_request != observer.number:
        raise guard.GuardError('subject does not match registered mirror or PR')
    return adapter.evaluate_local(
        adapter.LocalGit(mirror.git, mirror.git_dir),
        repository_id=mirror.repository.repository_id,
        trusted_policy_revision=mirror.policy_revision,
        requested_policy_revision=requested_policy_revision,
        subject=subject, observe_current=observer,
    )
