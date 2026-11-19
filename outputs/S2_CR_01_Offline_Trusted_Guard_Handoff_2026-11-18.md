# S2-CR-01: offline guard candidate

Base: protected main after PR #44, `631df2703994f8db2421570de31122c6513734d1`.
This is an offline candidate for the future dedicated App, not an active
check, check publisher, exception authority, or enablement request.

## What this tests

The pure decision function compares two verified, complete leaf inventories
using exact path, object ID and mode. It checks that both inventory revisions
match the intended repository/PR/base/head subject and that a fresh trusted
observation matches that subject. Renames appear as deletion plus addition;
mode and type changes cannot be skipped. Invalid or ambiguous inventory
shape fails closed. No PR file is opened or executed.

**Every changed path is protected.** The focused repair removes path exemptions
entirely: a link or another dependency can be unchanged in Git while a change
to its target affects it. The guard does not resolve links and never discounts
a changed leaf based on its name or file type. Future narrowing would require
a separately reviewed dependency-aware design; it is not configurable here.

The comparison is between the observed base tip and PR head, not a prediction
or verification of a synthesized merge tree. Base-only edits can appear in
the protected set. A production integration must define the exact candidate
it authorizes, and must not treat this result as a merge-tree attestation.

A pre-authenticated external owner decision can cover a protected change only
when repository, PR, base, head, trusted policy revision and the entire set of
protected paths match. It is not a GitHub approval or a review verdict.
Do not construct an owner decision from PR text, artifacts, or a caller's
unverified assertion. An absent decision leaves protected changes blocked; a
supplied but mismatched decision raises an error.

## What remains outside this code

- **Provenance and completeness:** the adapter must obtain full inventories
  from trusted Git objects, reject partial/paginated or truncated evidence
  that cannot be completed, and bind it to the observed PR revisions. The
  controller must independently pin and verify the trusted policy revision;
  a well-formed object ID is not a trust decision. A
  tuple passed to this function does not itself establish completeness.
- **Authentication and lifecycle:** obtain exceptions through an external
  authenticated, revocable owner channel, with durable replay/freshness
  controls. Verify reviewer provenance separately; require both appropriate
  guard disposition and authenticated verdict. Decide bootstrap, expiry,
  policy updates and recovery before enabling enforcement.
- **Publication:** trusted execution outside PR control, a fresh pre-write
  check, head-bound writes, ordering/idempotency and an owner-installed App.
  Verify check-source restrictions through independently reviewed platform
  acceptance. This code does not read GitHub, issue credentials or publish.
- **Enablement:** protected environment, authorized provider compatibility,
  runtime-token/cache isolation and reviewer calibration remain separate
  gates. PR #44's hosted tests exercised only synthetic fixtures. Production
  and scientific authority are unchanged.

## Review requested

Review the policy kernel and synthetic tests. Evaluate whether exact binding
and the fail-closed assumptions match the trust design; explicitly distinguish
acceptance of offline code from production readiness. No production or CI
workflow was altered to install this kernel.
