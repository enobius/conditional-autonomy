# Independent re-review: redirect, secret lifecycle, and request budget

Status: local/uncommitted and disabled. No real token, provider request, remote
workflow, repository setting or merge was used. Review the current 33-file
snapshot plus explicit deleted path in
`S2_CR_01_Test_Gap_Repair_Hashes_2026-11-16.json`. Prior review hashes do not
cover these edits. The original base remains `80eb0c9` on the same branch.

Verification: final local suite 312/312 in 72.781 seconds; targeted repair suite
43/43; schema gate green; Stage 1 gate green with 16/16 invariants and 4/4
seeded-defect proofs. The real CLI/dummy-proxy integration passed. No remote CI
or independent approval is claimed for this delta.

## A. Real default opener

The downloader now constructs its production opener through `default_opener()`.
The new test uses actual urllib handlers and two loopback HTTP servers, not an
injected mock opener: one answers with a redirect, and one is a canary environment
proxy. It verifies that the redirect is not followed automatically, the separate
storage request carries no Authorization, and the canary proxy receives nothing.

The test also calls the actual `download()` with its default opener. A test-only
Request URL mapper directs the fixed API/storage URLs to the local server,
preserving headers and redirect handling. The observed sequence is authenticated
metadata, authenticated ZIP redirect, then unauthenticated storage. Unknown URLs
are rejected so no test request can escape loopback. This exercises real HTTP,
not real HTTPS/GitHub/storage; TLS and real artifact compatibility remain gates.

## B. Fake Docker lifecycle

A new fake-Docker test records actual orchestrator create arguments and call
order through `run()`/`topology()`, using a dummy temporary credential. It
requires the exact read-only secret mount, non-root UID/GID 1001:1002, no token
in command arguments, CLI removal before proxy removal, and proxy/network
removal before credential unlink. It covers normal completion and failed CLI
creation. A separate test rejects root identity before any Docker operation.
These tests do not replace the earlier Docker probes or pending hosted run.

## Per-run budget

The proxy now admits at most four upstream attempts per proxy process/run,
atomically shared across clients, auth headers, endpoints and connections.
Attempts are charged before upstream connection and are not refunded on error.
Excess attempts get 429 without a new upstream request. Count-token requests
also consume budget. Existing concurrent-slot, body, stream and time limits
remain. Tests cover exhausted budget, mixed endpoints/keys and upstream errors.

Four is a conservative engineering candidate for review, not authorization for
live spend. It is a request-count limit, not a monetary or token-usage ceiling.
The real CLI/proxy/synthetic-upstream Docker probe still passed, with one
upstream message and placeholder-only CLI authentication. No real provider was
used; real OAuth behavior and retry compatibility within the budget are untested.

## Additional coverage and cleanup

- Added explicit ZIP defense tests for encryption/compression flags and declared
  sizes before library reads, independent length checking, prefixed ZIP signature
  rejection, and artifact-ID mismatch. Some use controlled ZIP metadata mocks;
  this is not evidence of every malicious archive exploit reproduced in vivo.
- Marked the old `shadow_container.run` env-file helper **test-only**, with an
  explicit warning to use only dummy tokens because it persists them in Docker
  configuration. The isolated workflow does not call it.
- Replaced stale CI filter paths with the retired audit fixture path, keeping
  the isolated workflow and tools under test coverage.
- The new manifest explicitly records the old active workflow's deletion; its
  recoverable archive remains under `architecture/retired/`.

## Still blocked before enablement

Protected environment, trusted publisher/check and exception protocol, hosted
dummy-secret artifact/cache/canary tests, real artifact layout/redirect behavior,
approved provider origin and a separately authorized live compatibility call
remain. The candidate workflow and provider policy stay disabled/null-origin.
Please separately assess integration-disabled versus enablement and inspect
the new tests rather than relying on this narrative or prior passes.
