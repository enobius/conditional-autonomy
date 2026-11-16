# Independent re-review handoff — November 16 repairs

Superseding follow-up: the default-opener and proxy lifecycle test gaps plus a
per-run request budget are covered in `S2_CR_01_Test_Gap_Repairs_2026-11-16.md`.
Use its new hash snapshot (including the workflow deletion) for current review;
the 33-file snapshot referenced below is the preceding candidate.

Status: uncommitted, disabled candidate. No settings/credentials were installed,
no remote workflow or real provider was called, and no commit/push/merge occurred.
Review the exact 33-file snapshot in
`S2_CR_01_Isolated_Repair_Hashes_2026-11-16.json`; it supersedes November 15
hash authority. The base and branch remain unchanged.

## Repairs to the latest findings

### Untrusted result archive

The validate job no longer extracts the provider artifact with download-artifact.
It grants read-only `actions` scope solely to fetch result metadata and ZIP via
the GitHub REST API. `tools/shadow_result_download.py` checks the explicit ID,
current workflow-run ID, expiry and size, refuses automatic redirects and never
forwards GitHub Authorization to signed storage. Allowed HTTPS storage hosts
are narrowly restricted; future provider-host changes fail closed.

The bounded ZIP is parsed in memory, not extracted. Exactly one regular
`result.json` member is accepted; extra/duplicate entries, traversal/absolute
paths, NUL names, links, encryption, unsupported compression and oversized
content are rejected. Only its bounded bytes are written to a new directory
under a fixed filename, then the existing final binding/schema checks run.
Tests cover malicious archives and signed-URL credential separation. They do
not establish actual GitHub artifact/cache semantics; remote canary tests remain.
The original trusted fetch artifact still uses the pinned ID-only action path,
with independently verified manifest/payload hashes after download.

### Proxy-only provider authentication

The isolated CLI command now receives only the fixed public placeholder
`sk-ant-oat01-shadow-placeholder`, never the real token or its file. The proxy
gets a read-only mount of the host tmpfs credential file, runs under the host's
non-root UID/GID so it can read mode 0600, and injects its Bearer credential
upstream. Caller auth headers are checked for ambiguity, then stripped/replaced;
the CLI cannot choose the upstream account by sending its own key.

The real-CLI/synthetic-upstream Docker test passed with the placeholder, and
the fake upstream asserted it received only the proxy's separate dummy token.
Container inspection confirmed no dummy provider token in CLI configuration.
The actual topology smoke test confirmed a read-only proxy credential mount,
no token in Docker Config.Env/configuration, readiness on the internal address,
no outward-interface listener, and cleanup. On Windows, the mount contains a
temporary dummy fixture; production Linux tmpfs creation was separately tested
earlier, not end-to-end against a Linux-host Docker socket in this run.

The value no longer enters Docker configuration through `--env-file` in the
isolated path. The proxy can still read it, privileged host/daemon access is
trusted, and memory/host/snapshot risks are not eliminated. The old direct and
no-egress helpers remain historical/test utilities, not active workflow paths.

### Policy flag and smaller findings

- Tests now use a valid DNS origin with `enabled: false`, and reject numeric,
  string and null flags. These no longer rely on a null origin for failure.
- Removed schema-gate's pip caching and set `--no-cache-dir`, with regression
  coverage alongside the two already-repaired runtime gates.
- Prefer IPv4 after checking all DNS answers; unsafe mixed answers still fail.
- Retired `.github/workflows/claude-review-shadow.yml` into
  `architecture/retired/claude-review-shadow.yml`. It remains recoverable as an
  audit fixture, but GitHub Actions no longer loads it. The only remaining
  Claude workflow candidate is hard-disabled and its policy remains false/null.
- The Windows invalid-request test now recognizes connection resets as rejection
  while still asserting no upstream request. Valid requests still require a
  valid response. Twelve consecutive repetitions passed; this does not prove
  the absence of every possible flake.

## Verification and remaining gates

Full local suite: 304/304 in 73.810 seconds. Schema gate green. Stage 1 gate
green, 16/16 invariants and 4/4 isolated seeded-defect proofs. Targeted repairs:
42 tests passed before the final reset-handling refinement; full regression
includes that refinement. Dummy-token Docker CLI/proxy and topology tests passed.
No live provider, real API token, remote CI or platform adversarial run occurred.

Please independently check all new parsing/redirect/authentication behavior,
the read-only actions permission, the proxy mount UID/lifetime, every active
entrypoint, and the retired-workflow state. Give separate integration-disabled
and enablement verdicts. The protected environment, trusted publisher/check,
remote artifact/cache/canary verification, origin approval and separately
authorized live-provider compatibility test remain gates. Do not enable or
install anything as part of this review.
