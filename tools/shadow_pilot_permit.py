"""Narrow approval check for one synthetic advisory pilot; does not enable it."""
from datetime import datetime, timedelta, timezone
import re

from tools import shadow_artifact_binding as binding

REPOSITORY = 'enobius/conditional-autonomy'
REPOSITORY_ID = '1315590853'
FIXTURE_PR = '53'
FIXTURE_DIFF = '0ad0a64edf21751af79788a62dcc03552b2143cb233eaffd6f5e1d3024c2eb80'
ORIGIN = 'api.anthropic.com'
VERSION = 'shadow-pro-pilot-permit-1'
MAX_VALID_FOR = timedelta(minutes=30)


def require_permit(raw, manifest, env, *, now=None):
    """Bind an expiring human permit to the run and independently sealed input.

    Caller must verify the manifest against trusted fetch-job outputs first.
    GitHub's separate protected-environment approval is also required. Neither
    control attests a provider account or bounds encrypted HTTP requests.
    """
    if (env.get('GITHUB_REPOSITORY') != REPOSITORY or env.get('GITHUB_REPOSITORY_ID') != REPOSITORY_ID or
            env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or
            env.get('GITHUB_ACTOR') != 'enobius' or env.get('GITHUB_RUN_ATTEMPT') != '1' or
            env.get('PR_NUMBER') != FIXTURE_PR):
        raise ValueError('pilot requires the owner-dispatched fixture on the first attempt from main')
    run, workflow = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_SHA', '')
    snapshot = manifest['snapshot']
    base, head = snapshot['baseRefOid'], snapshot['headRefOid']
    if (not re.fullmatch(r'[1-9][0-9]{0,19}', run) or workflow != base or
            any(not re.fullmatch(r'(?!0{40}\Z)[0-9a-f]{40}', pin) for pin in (base, head)) or base == head or
            (env.get('SHADOW_BASE_SHA'), env.get('SHADOW_HEAD_SHA')) != (base, head) or
            manifest['files']['diff.patch']['sha256'] != FIXTURE_DIFF):
        raise ValueError('pilot subject is not the immutable synthetic diff from this dispatch')
    if not isinstance(raw, str) or not 0 < len(raw) <= 2048 or not raw.isascii():
        raise ValueError('pilot permit missing or malformed')
    permit = binding.parse(raw.encode('ascii'))
    if not isinstance(permit, dict):
        raise ValueError('expected a JSON pilot permit')
    expected = {'version': VERSION, 'origin': ORIGIN, 'run_id': run, 'run_attempt': '1',
                'pr_number': FIXTURE_PR, 'base_sha': base, 'head_sha': head, 'diff_sha256': FIXTURE_DIFF}
    expires = permit.get('expires_at')
    if permit != (expected | {'expires_at': expires}):
        raise ValueError('pilot permit does not match this run, revision, or origin')
    if not isinstance(expires, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', expires):
        raise ValueError('pilot permit expiry must be UTC')
    expiry = datetime.strptime(expires, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    current = datetime.now(timezone.utc) if now is None else now
    if not current < expiry <= current + MAX_VALID_FOR:
        raise ValueError('pilot permit expired or exceeds its approval window')
