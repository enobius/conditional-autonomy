# S2-CR-01 guard policy candidate — not enablement approval

PR #40 merged as `f34aa966e491ff2fab56c2b9e49cf2bcee18d615`; its independent
review passed the still-disabled workflow and identified further prerequisites.
The three existing gates passed on the merged commit. The owner authorized
continuing safeguards but not enabling the workflow or contacting the provider.

This candidate adds an always-reporting `shadow-review-guard` workflow for all
pull requests, semantic workflow assertions tested with drift hashes disabled,
a pinned prompt, and a fully pinned and hash-locked Linux x86_64 CPython 3.11
validator wheel set. The lock was resolved from the public package index and a
local offline, hash-enforced dependency resolution succeeded. CI must still
install the locked set on the intended runner. Package hashes pin artifacts;
they do not independently establish package trust. The existing Claude action's
separate installer/network behavior is not locked by this file.

The guard is not automatically a required branch check. Its tests and workflow
are part of the PR under review, so a malicious PR could alter them; independent
review and protected branch rules remain necessary. No branch protection or
environment settings are changed here. The workflow stays unconditionally off.

CLI 2.1.319 was obtained from the public npm platform package and reported that
version locally. A credential-free test with a dummy key, isolated config and a
loopback stub timed out for turn limits 1–4 without any request reaching the
stub. A second isolated attempt at 3 turns likewise timed out. These are failed
probes, not evidence of tools being disabled, working structured output, or a
minimum turn limit. Keep `--max-turns 1` and `--tools=` unapproved until a
proper pinned-CLI stub test succeeds. No real provider call was made.

Before enablement: independently review this candidate; verify the `main`-only
protected environment and secret scope; arrange an always-reporting required
check under owner-approved settings; resolve the CLI proof, turn limit and
runtime installer risk; and obtain separate owner authorization for any live
call. Provenance, authenticated publishing, replay controls, calibration and
owner approval remain prerequisites for making review verdicts required.
