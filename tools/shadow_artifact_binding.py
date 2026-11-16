"""Local prototype for data-only fetch-artifact binding, not a check publisher.

The expected digest/context MUST come directly from trusted fetch-job outputs,
never from the provider job or an artifact listing. Not yet wired to Actions.
"""
import hashlib
import json
from pathlib import Path
import re
import stat

LIMITS = {'prompt.txt': 100_000, 'diff.patch': 200_000, 'snapshot.json': 2_000}
CONTEXT_KEYS = {'repository', 'run_id', 'run_attempt', 'trusted_sha', 'pr_number'}
SNAPSHOT_KEYS = {'baseRefName', 'baseRefOid', 'headRefOid', 'mergeBaseOid', 'state'}


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate manifest key')
        value[key] = item
    return value


def parse(raw):
    def reject(_value):
        raise ValueError('non-finite JSON')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=reject)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def check_context(context):
    if not isinstance(context, dict) or set(context) != CONTEXT_KEYS:
        raise ValueError('invalid trusted context')
    if (not isinstance(context['repository'], str) or
            not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', context['repository']) or
            not isinstance(context['trusted_sha'], str) or
            not re.fullmatch('[0-9a-f]{40}', context['trusted_sha']) or
            any(not isinstance(context[key], str) or not re.fullmatch('[1-9][0-9]*', context[key])
                for key in ('run_id', 'run_attempt', 'pr_number'))):
        raise ValueError('invalid trusted context fields')


def read_regular(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('artifact entry is not a unique regular file')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('artifact entry empty or oversized')
    return raw


def read_bundle(directory, *, include_manifest):
    directory = Path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError('artifact root is not a real directory')
    names = set(LIMITS) | ({'manifest.json'} if include_manifest else set())
    if {path.name for path in directory.iterdir()} != names:
        raise ValueError('unexpected or missing artifact files')
    return {name: read_regular(directory / name, limit) for name, limit in LIMITS.items()}


def make_manifest(files, context):
    check_context(context)
    snapshot = parse(files['snapshot.json'])
    if (not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS or
            snapshot['baseRefName'] != 'main' or snapshot['state'] != 'OPEN' or
            any(not isinstance(snapshot[key], str) or not re.fullmatch('[0-9a-f]{40}', snapshot[key])
                for key in ('baseRefOid', 'headRefOid', 'mergeBaseOid'))):
        raise ValueError('invalid fetch snapshot')
    return {'version': 'shadow-fetch-prototype-1', 'context': context, 'snapshot': snapshot,
            'files': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in files.items()}}


def seal(directory, context):
    """Fetch-side creation. Return digest to bind through needs.fetch.outputs."""
    files = read_bundle(directory, include_manifest=False)
    raw = canonical(make_manifest(files, context))
    with (Path(directory) / 'manifest.json').open('xb') as output:
        output.write(raw)
    return digest(raw)


def verify_transport(directory, *, trusted_digest, trusted_context):
    """Check fetch-output-bound artifact bytes; does not establish PR freshness."""
    check_context(trusted_context)
    if not isinstance(trusted_digest, str) or not re.fullmatch('[0-9a-f]{64}', trusted_digest):
        raise ValueError('missing trusted manifest digest')
    files = read_bundle(directory, include_manifest=True)
    raw = read_regular(Path(directory) / 'manifest.json', 8_000)
    if digest(raw) != trusted_digest:
        raise ValueError('manifest differs from trusted fetch output')
    manifest = parse(raw)
    expected = make_manifest(files, trusted_context)
    if manifest != expected or raw != canonical(expected):
        raise ValueError('artifact contents or context changed')
    return expected


def verify(directory, *, trusted_digest, trusted_context, refetched_snapshot, refetched_diff):
    """Validate-side verification. Re-fetch inputs must be independently obtained."""
    expected = verify_transport(directory, trusted_digest=trusted_digest, trusted_context=trusted_context)
    if (refetched_snapshot != expected['snapshot'] or not isinstance(refetched_diff, bytes) or
            digest(refetched_diff) != expected['files']['diff.patch']['sha256']):
        raise ValueError('independent PR re-fetch differs from fetch artifact')
    return expected
