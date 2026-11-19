"""Read-only local Git adapter for the offline review guard.

The executable, mirror location, repository identity, policy pin and PR-state
observer must come from trusted controller configuration. No remote discovery,
checkout, Git transport, PR-file execution, exception parsing or publishing.
"""
from hashlib import sha1
import os
from pathlib import Path
import subprocess
from time import monotonic
from typing import Callable

from tools import trusted_review_guard as guard


_MAX_OBJECT_BYTES = 2 * 1024 * 1024
_MAX_TREE_BYTES = 16 * 1024 * 1024
_MAX_TREES = 1024
_MAX_DEPTH = 64
_MAX_SECONDS = 60
_LIVE_MODES = {b'100644': '100644', b'100755': '100755',
               b'120000': '120000', b'160000': '160000'}


class LocalGit:
    """Only read Git objects from a locally provisioned, trusted mirror."""

    def __init__(self, git: Path, git_dir: Path):
        try:
            git, git_dir = Path(git), Path(git_dir)
            if not git.is_absolute() or not git_dir.is_absolute():
                raise guard.GuardError('Git executable and object database must be absolute')
            self.git, self.git_dir = git.resolve(strict=True), git_dir.resolve(strict=True)
        except OSError as exc:
            raise guard.GuardError('local Git input unavailable') from exc
        if not self.git.is_file() or not self.git_dir.is_dir():
            raise guard.GuardError('local Git input unavailable')
        self.deadline = monotonic() + _MAX_SECONDS
        # Do not forward inherited Git variables, proxy settings or credentials.
        self.env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TMP', 'TEMP')
                    if key in os.environ}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
        if self._run('rev-parse', '--show-object-format') != b'sha1\n':
            raise guard.GuardError('unsupported Git object format')

    def _run(self, *args, data=b''):
        timeout = min(self.deadline - monotonic(), 10)
        if timeout <= 0:
            raise guard.GuardError('Git evidence deadline exceeded')
        try:
            result = subprocess.run(
                [str(self.git), '--no-lazy-fetch', '--no-replace-objects',
                 '-c', 'protocol.allow=never',
                 '--git-dir=' + str(self.git_dir), *args],
                cwd=self.git_dir, env=self.env, input=data, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise guard.GuardError('local Git read failed') from exc
        if result.returncode:
            raise guard.GuardError('local Git read failed')
        return result.stdout

    def read_metadata_object(self, oid: str, kind: str) -> bytes:
        """Recompute commit/tree ID from exact object bytes; never peel a ref or tag."""
        guard._require_oid(oid)
        if kind not in ('tree', 'commit'):
            raise guard.GuardError('unsupported metadata object type')
        if self._run('cat-file', '-t', oid) != kind.encode() + b'\n':
            raise guard.GuardError('Git object type mismatch')
        size = self._run('cat-file', '-s', oid)
        if not size.endswith(b'\n') or len(size) > 10 or not size[:-1].isdigit():
            raise guard.GuardError('invalid Git object size')
        size = int(size)
        if size > _MAX_OBJECT_BYTES:
            raise guard.GuardError('Git metadata object too large')
        raw = self._run('cat-file', kind, oid)
        if len(raw) != size or sha1(f'{kind} {size}\0'.encode() + raw).hexdigest() != oid:
            raise guard.GuardError('Git metadata object integrity mismatch')
        return raw

    def commit_tree(self, oid):
        first, separator, _ = self.read_metadata_object(oid, 'commit').partition(b'\n')
        if not separator or not first.startswith(b'tree '):
            raise guard.GuardError('commit lacks tree header')
        try:
            tree = first[5:].decode('ascii')
        except UnicodeError as exc:
            raise guard.GuardError('invalid commit tree ID') from exc
        guard._require_oid(tree)
        return tree

    def _verify_blobs(self, entries):
        # Gitlinks name commits in separate repositories, not local blobs.
        oids = sorted({e.oid for e in entries if e.mode != '160000'})
        request = b''.join(oid.encode() + b'\n' for oid in oids)
        reply = self._run('cat-file', '--batch-check=%(objectname) %(objecttype)', data=request)
        if reply != b''.join(oid.encode() + b' blob\n' for oid in oids):
            raise guard.GuardError('inventory blob missing or wrong type')

    def inventory(self, commit):
        """Walk the entire declared tree. No filtering or partial inventory return."""
        queue = [(self.commit_tree(commit), '', 0)]
        trees, total_bytes = 0, 0
        leaves = []
        while queue:
            oid, folder, depth = queue.pop()
            trees += 1
            if trees > _MAX_TREES or depth > _MAX_DEPTH:
                raise guard.GuardError('Git tree traversal limit exceeded')
            raw = self.read_metadata_object(oid, 'tree')
            total_bytes += len(raw)
            if total_bytes > _MAX_TREE_BYTES or (folder and not raw):
                raise guard.GuardError('oversized inventory or unsupported empty subtree')
            cursor, names = 0, set()
            while cursor < len(raw):
                end = raw.find(b'\0', cursor)
                if end < 0 or end + 21 > len(raw):
                    raise guard.GuardError('incomplete Git tree record')
                mode, separator, name = raw[cursor:end].partition(b' ')
                if not separator or not name or b'/' in name:
                    raise guard.GuardError('invalid Git tree record')
                try:
                    name = name.decode('ascii')
                except UnicodeError as exc:
                    raise guard.GuardError('unsupported Git path encoding') from exc
                path = guard._path(folder + name)
                if name.lower() in names:
                    raise guard.GuardError('duplicate or case-ambiguous Git tree entry')
                names.add(name.lower())
                child = raw[end + 1:end + 21].hex()
                guard._require_oid(child)
                cursor = end + 21
                if mode == b'40000':
                    queue.append((child, path + '/', depth + 1))
                    if trees + len(queue) > _MAX_TREES:
                        raise guard.GuardError('Git tree traversal limit exceeded')
                elif mode in _LIVE_MODES:
                    leaves.append(guard.Entry(path, _LIVE_MODES[mode], child))
                    if len(leaves) > guard._MAX_PATHS:
                        raise guard.GuardError('Git inventory entry limit exceeded')
                else:
                    raise guard.GuardError('unsupported Git tree mode')
        self._verify_blobs(leaves)
        return guard.Inventory(commit, tuple(leaves))


def evaluate_local(git: LocalGit, *, repository_id: int, trusted_policy_revision: str,
                   requested_policy_revision: str, subject: guard.Subject,
                   observe_current: Callable[[], guard.Subject]) -> guard.Result:
    """Read-only comparison. The observer is trusted; the requested IDs are not."""
    guard._subject(subject)
    if type(repository_id) is not int or repository_id != subject.repository_id:
        raise guard.GuardError('local mirror repository mismatch')
    guard._require_oid(trusted_policy_revision)
    guard._require_oid(requested_policy_revision)
    if requested_policy_revision != trusted_policy_revision:
        raise guard.GuardError('policy revision does not match trusted pin')

    def observe():
        try:
            current = observe_current()
        except Exception as exc:
            raise guard.GuardError('current PR observation failed') from exc
        guard._subject(current)
        if current != subject:
            raise guard.GuardError('review subject changed')
        return current

    observe()
    # Verify that the independently provisioned policy pin names a commit and
    # identifies an available validly addressed root tree, not the PR's policy.
    tree = git.commit_tree(trusted_policy_revision)
    git.read_metadata_object(tree, 'tree')
    base = git.inventory(subject.base)
    head = git.inventory(subject.head)
    return guard.evaluate(subject, observe(), base, head, guard.Policy(trusted_policy_revision))
