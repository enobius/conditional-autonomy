"""Exercise the hosted pilot's actual Bash fetch with a network-free fake gh."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'fetch_shadow_pr.sh'
BASE, HEAD, MERGE_BASE = 'a' * 40, 'b' * 40, 'c' * 40
SNAPSHOT = {'baseRefName': 'main', 'baseRefOid': BASE, 'headRefOid': HEAD, 'state': 'OPEN'}
OPEN = {**SNAPSHOT, 'number': 17, 'isCrossRepository': False}
DIFF = 'diff --git a/sample.txt b/sample.txt\n@@ -1 +1 @@\n-before\n+after\n'
OBSERVE = ['pr', 'view', '17', '--repo', 'example/repo', '--json',
           'number,baseRefName,baseRefOid,headRefOid,isCrossRepository,state']
COMPARE = f'repos/example/repo/compare/{BASE}...{HEAD}'
COMPARE_JSON = {'base_commit': {'sha': BASE}, 'merge_base_commit': {'sha': MERGE_BASE},
                'files': [{'patch': '@@ -1 +1 @@\n-before\n+after\n'}]}

FAKE_GH = """
import json
import os
from pathlib import Path
import sys

trace = Path(os.environ['FIXTURE_TRACE'])
index = len(trace.read_text().splitlines())
with trace.open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
plan = json.loads(Path(os.environ['FIXTURE_PLAN']).read_text())
if index >= len(plan) or plan[index][0] != sys.argv[1:]:
    sys.exit('unexpected gh call')
_, output = plan[index]
if output is None:
    sys.exit('simulated gh failure')
sys.stdout.write(output)
"""


@unittest.skipUnless(sys.platform.startswith('linux'), 'requires the hosted Linux Bash and ulimit')
class FetchShadowPRTests(unittest.TestCase):
    def fetch(self, before=OPEN, after=OPEN, *, env_update=None, diff=DIFF):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            binaries = directory / 'bin'
            binaries.mkdir()
            bash = shutil.which('bash')
            for command in ('mkdir', 'mktemp', 'mv'):
                (binaries / command).symlink_to(shutil.which(command))
            (binaries / 'python').symlink_to(sys.executable)
            fake_gh = binaries / 'gh'
            fake_gh.write_text(f'#!{bash}\nexec python "$FIXTURE_GH" "$@"\n', encoding='utf-8')
            fake_gh.chmod(0o700)
            program = directory / 'fake_gh.py'
            program.write_text(FAKE_GH, encoding='utf-8')
            plan = directory / 'plan.json'
            plan.write_text(json.dumps([
                (OBSERVE, json.dumps(before)), (['api', COMPARE], json.dumps(COMPARE_JSON)),
                (['api', '-H', 'Accept: application/vnd.github.v3.diff', COMPARE], diff),
                (OBSERVE, json.dumps(after)),
            ]), encoding='utf-8')
            trace = directory / 'trace.jsonl'
            trace.touch()
            destination = directory / 'fetched'
            # This PATH has no fallback gh (or other GitHub client). No host
            # variables, credentials, Bash startup files or proxy are inherited.
            env = {'PATH': str(binaries), 'HOME': temp, 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PR_NUMBER': '17', 'GITHUB_REPOSITORY': 'example/repo', 'RUNNER_TEMP': temp,
                   'SHADOW_BASE_SHA': BASE, 'SHADOW_HEAD_SHA': HEAD, 'SHADOW_FETCH_DEST': str(destination),
                   'FIXTURE_PLAN': str(plan), 'FIXTURE_TRACE': str(trace), 'FIXTURE_GH': str(program)}
            process = subprocess.run([bash, '--noprofile', '--norc', str(SCRIPT)], cwd=ROOT,
                                     env=env | (env_update or {}), capture_output=True, timeout=15)
            calls = [json.loads(line) for line in trace.read_text().splitlines()]
            files = {path.name: path.read_bytes() for path in destination.iterdir()} if destination.exists() else {}
        return process, calls, files

    def test_fetch_accepts_exact_pin_only_after_second_observation(self):
        process, calls, files = self.fetch()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(calls, [OBSERVE, ['api', COMPARE],
                                 ['api', '-H', 'Accept: application/vnd.github.v3.diff', COMPARE], OBSERVE])
        self.assertEqual(set(files), {'diff.patch', 'snapshot.json'})
        self.assertEqual(files['diff.patch'], DIFF.encode())
        self.assertEqual(json.loads(files['snapshot.json']), SNAPSHOT | {'mergeBaseOid': MERGE_BASE})

    def test_fetch_does_not_write_snapshot_after_revision_drift(self):
        for field, value in (('headRefOid', 'd' * 40), ('baseRefOid', 'e' * 40), ('state', 'CLOSED')):
            with self.subTest(field=field):
                process, calls, files = self.fetch(after=OPEN | {field: value})
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(len(calls), 4)
                self.assertEqual(calls[-1], OBSERVE)
                self.assertEqual(files, {'diff.patch': DIFF.encode()})

    def test_fetch_rejects_initial_fork_and_stale_revision_before_compare(self):
        for invalid in ({'isCrossRepository': True}, {'headRefOid': 'd' * 40}):
            with self.subTest(invalid=invalid):
                process, calls, files = self.fetch(before=OPEN | invalid)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(calls, [OBSERVE])
                self.assertEqual(files, {})

    def test_invalid_dispatch_pins_make_no_gh_calls(self):
        for invalid in ({'PR_NUMBER': '017'}, {'SHADOW_HEAD_SHA': HEAD.upper()},
                        {'SHADOW_BASE_SHA': '0' * 40}, {'SHADOW_HEAD_SHA': BASE}):
            with self.subTest(invalid=invalid):
                process, calls, files = self.fetch(env_update=invalid)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(calls, [])
                self.assertEqual(files, {})

    def test_compare_failure_never_yields_a_snapshot(self):
        process, calls, files = self.fetch(diff=None)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(len(calls), 3)
        self.assertNotIn('snapshot.json', files)
