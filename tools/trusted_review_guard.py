"""Offline policy kernel. No input here establishes identity or authorizes merging.

Only a future trusted controller may construct these inputs after verifying
Git objects, complete inventories, current PR state and any owner exception.
Never instantiate an OwnerException directly from PR-supplied data.
"""
from dataclasses import dataclass
from enum import Enum
import re


_OID = re.compile(r'[0-9a-f]{40}')
_MAX_PATHS = 10_000
_MODES = {'100644', '100755', '120000', '160000'}


class GuardError(ValueError):
    """Invalid evidence; callers must fail closed."""


@dataclass(frozen=True)
class Subject:
    repository_id: int
    pull_request: int
    base: str
    head: str


@dataclass(frozen=True)
class Entry:
    path: str
    mode: str
    oid: str


@dataclass(frozen=True)
class Inventory:
    """Complete recursive leaf inventory, attested by the caller, not this module."""
    revision: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Policy:
    revision: str
    # Exact paths only. Everything else is protected unless explicitly listed.
    exempt_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class OwnerException:
    """Already-authenticated external decision, not an authentication format."""
    subject: Subject
    policy_revision: str
    protected_changes: tuple[str, ...]


class Decision(str, Enum):
    NO_PROTECTED_CHANGE = 'no-protected-change'
    COVERED_BY_EXCEPTION = 'covered-by-exception'
    PROTECTED_CHANGE = 'protected-change'


@dataclass(frozen=True)
class Result:
    decision: Decision
    protected_changes: tuple[str, ...]


def _require_oid(value):
    if type(value) is not str or not _OID.fullmatch(value) or value == '0' * 40:
        raise GuardError('invalid Git object ID')


def _subject(subject):
    if (type(subject) is not Subject or type(subject.repository_id) is not int or
            subject.repository_id < 1 or type(subject.pull_request) is not int or
            subject.pull_request < 1):
        raise GuardError('invalid repository or PR identity')
    _require_oid(subject.base)
    _require_oid(subject.head)


def _path(path):
    # Deliberately narrow grammar for this repository. Unsupported names block
    # rather than being silently normalized or omitted from comparison.
    if type(path) is not str or not 0 < len(path) <= 1024:
        raise GuardError('invalid inventory path')
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or
           part in {'.', '..'} or part.endswith('.') or part.lower() == '.git'
           for part in path.split('/')):
        raise GuardError('noncanonical inventory path')
    return path


def _record_prefixes(path, prefixes):
    current = ''
    for part in path.split('/'):
        current = current + '/' + part
        key = current.lower()
        if prefixes.setdefault(key, current) != current:
            raise GuardError('case-ambiguous inventory paths')


def _paths(paths):
    if type(paths) is not tuple or len(paths) > _MAX_PATHS:
        raise GuardError('invalid path list')
    seen, prefixes = set(), {}
    for path in paths:
        _path(path)
        _record_prefixes(path, prefixes)
        if path in seen:
            raise GuardError('duplicate path')
        seen.add(path)
    return seen


def _inventory(inventory, revision):
    if type(inventory) is not Inventory or inventory.revision != revision:
        raise GuardError('inventory revision mismatch')
    if type(inventory.entries) is not tuple or len(inventory.entries) > _MAX_PATHS:
        raise GuardError('invalid inventory size')
    result, prefixes = {}, {}
    for entry in inventory.entries:
        if type(entry) is not Entry or type(entry.mode) is not str or entry.mode not in _MODES:
            raise GuardError('invalid tree entry or mode')
        path = _path(entry.path)
        _record_prefixes(path, prefixes)
        _require_oid(entry.oid)
        if path in result:
            raise GuardError('duplicate inventory entry')
        result[path] = (entry.mode, entry.oid)
    for path in result:
        parts = path.split('/')
        if any('/'.join(parts[:i]) in result for i in range(1, len(parts))):
            raise GuardError('file and directory conflict')
    return result


def evaluate(subject: Subject, current: Subject, base: Inventory, candidate: Inventory,
             policy: Policy, *, owner_exception: OwnerException | None = None) -> Result:
    """Compare exact inventories; outcome covers protected changes only.

    `current` is a fresh trusted observation from the caller; it does not provide
    atomicity with a later publication. Caller must recheck before publication.
    """
    _subject(subject)
    _subject(current)
    if current != subject:
        raise GuardError('review subject changed')
    if type(policy) is not Policy:
        raise GuardError('invalid policy')
    _require_oid(policy.revision)
    exemptions = _paths(policy.exempt_paths)
    old = _inventory(base, subject.base)
    new = _inventory(candidate, subject.head)
    if subject.head == subject.base and old != new:
        raise GuardError('inconsistent inventories for same object')
    changed = {p for p in old.keys() | new.keys() if old.get(p) != new.get(p)}
    # Exemption applies only to modifications of an existing ordinary file;
    # additions, deletions and type/mode changes always require independent review.
    exempt = {p for p in changed & exemptions if p in old and p in new and
              old[p][0] == new[p][0] == '100644'}
    protected = tuple(sorted(changed - exempt))
    if owner_exception is not None:
        if type(owner_exception) is not OwnerException:
            raise GuardError('invalid exception decision')
        _subject(owner_exception.subject)
        _require_oid(owner_exception.policy_revision)
        approved = _paths(owner_exception.protected_changes)
        if (not protected or owner_exception.subject != subject or
                owner_exception.policy_revision != policy.revision or approved != set(protected)):
            raise GuardError('exception does not bind exact protected change')
        return Result(Decision.COVERED_BY_EXCEPTION, protected)
    return Result(Decision.PROTECTED_CHANGE if protected else Decision.NO_PROTECTED_CHANGE,
                  protected)
