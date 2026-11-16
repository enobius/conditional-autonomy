# Direct CLI shadow candidate — local evidence

Status: disabled, uncommitted, and awaiting independent review. This is not an
authorization for a provider call, an experiment, or a required review check.

The candidate removes the outer Claude GitHub Action from the review step. The
workflow fetches PR data using the read-only GitHub token in separate steps,
then invokes a checksum-verified Claude CLI directly in a fresh temporary working
directory. The runner constructs an explicit child environment containing the
provider credential and basic runtime settings, but no GitHub token, GitHub
runner command-file paths, workspace path, proxy variables, or inherited host
environment. It passes the prompt through standard input, requests no general
tools and disallows MCP tools, and writes only the extracted structured result
to a new file. The existing validator then checks that file against the same
before/after snapshots, schema and finding-location rules. No real verdict is
published or used to authorize a merge.

The runner rejects missing inputs, a changed CLI hash, stale output destination,
nonzero exit, malformed/duplicate-key JSON, unsuccessful result, missing
structured output and a reported turn count outside 1–2. Its timeout is 600
seconds and it checks the output-file length after the process exits; that is
not a live disk-usage quota. Errors do not print the CLI transcript or token.

## Isolated local test

In a non-root, read-only Docker container with network disabled and only
loopback, the real pinned CLI produced the expected synthetic verdict. A dummy
GitHub token in the parent environment was absent from the child environment.
A synthetic unsolicited Bash request was explicitly rejected by the CLI, the
runner failed closed, and no marker command executed. The probe injects a
loopback transport override **only in its test adapter**; the production runner
does not accept that override. The provider token was a dummy and its acceptance
by a real provider was not tested.

Observed SHA256: runner `0084fc2a32f728a76a435a67833b0a9e9af795ad77b3a707a6c9e7c94e1ee07c`,
probe `a9fb4ca9cd07086b5649c009aeca8df3935117686ca5d39e9d209878c4529669`,
workflow `596940b5758de86d15cf9c37e9ffa6280c480e18ad93f54cc8795255aac231d4`.
CLI version 2.1.319 SHA256
`dabafec82ca1319fa43d8be36a10fc61b1d11821cb98ad5df04ad95e199b8eed`.
The container image was
`python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39`.

After this change the focused suite passed 35/35, the final full regression
passed 266/266 in 64.495 seconds, and the schema and Stage 1 exit gates were
green locally. The exit gate verified 16/16 invariants and 4/4 seeded-defect
proofs. No remote CI result is claimed.

## Important limits

- An environment allowlist is **not an OS sandbox**. On a real runner the CLI
  executes under the runner's OS identity and may be able to access other files
  or processes. A fresh working directory does not guarantee filesystem,
  process, or network isolation. Tool disabling is not an exhaustive proof.
- The provider credential is intentionally available to the CLI. Real OAuth,
  provider behavior, GitHub-hosted operation, and model quality are untested.
- The existing PR-controlled guard is not an independently trusted gate. The
  trusted-publisher design and required-check configuration remain open.
- The installer hashes, direct runner, schema transport, error paths and new
  architecture need independent adversarial review before any enablement.

The local regression and gate outcomes are recorded in the work-in-progress
handoff. No GitHub settings, credentials, commits or PRs were changed here.
