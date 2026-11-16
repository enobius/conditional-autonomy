# Trusted review guard — design draft, not an active gate

## Problem

The current `shadow-review-guard` runs tests from the proposed PR. A PR can
change both the policy and its tests or workflow, so its own green result cannot
certify that the policy was respected. The tests added in the current candidate
are useful drift and regression alarms, but do not solve that trust problem.

## Intended enforcement boundary

Before shadow enablement, require a separately protected publisher that:

1. Reads the current trusted base policy and the exact PR base and head object
   IDs, checks freshness and binds the result to the head being merged.
2. Treats PR contents exclusively as data: no checkout-and-execute, dependency
   install, tests, shell, or other code from the PR with privileged credentials.
3. Detects changes to the review workflow, its installer, guard and tests,
   policy and prompt, verdict validation/schema, and check publisher itself;
   default-denies changes to that protected set unless an independently
   authorized exception names the exact protected paths, base and head hashes.
4. Publishes a unique check from a dedicated GitHub App whose identity is
   selected as the required status-check source, so a PR-controlled GitHub
   Actions workflow cannot substitute its own green result. Verify this behavior
   with real adversarial scratch PRs before considering it enforced.
5. Fails closed on missing/incomplete diffs, stale or unavailable commits,
   ambiguous permissions, errors, superseded heads, and changed publisher policy.

The protected-path inventory and exact exception protocol need independent
security review; a path list that omits an indirect dependency is not safe.
An exception is a separate, attributable owner decision and must not be inferred
from the PR author's own changed files. Support for policy evolution and a
bootstrap procedure must be designed before making the check required, or the
guard can deadlock its own repair. The existing gates remain in force meanwhile.

## Trigger tradeoff

GitHub documents that `pull_request_target` uses trusted base workflow code,
but carries elevated trust and must not execute PR-controlled code. It also
documents a forthcoming default event-policy restriction for affected public
repositories. Do not add or rely on such a trigger without checking this
repository's actual policy and designing a minimal-permissions, data-only path.
Reference: https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target

A separately installed GitHub App is a candidate for stronger check-source
identity, not something this document claims already exists. The full design,
source binding, administrative settings, app installation, any exception and
turning the check on all require review and appropriate owner authorization.

## Status

No trusted publisher, independent required review-verdict check, or automatic
exception mechanism is implemented by this draft. The shadow workflow remains
disabled. This draft does not grant approval for repository settings changes,
credentials, provider calls, or experiments.
