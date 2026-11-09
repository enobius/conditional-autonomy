# Claude Code review integration — work in progress

Owner reports the Claude GitHub App is installed on this repository, Claude
plan is Pro. On 2026-11-08 the owner reported adding the Claude Code OAuth
credential to GitHub Actions, then removing the repository secret after the
independent review. Removal has not been independently verified here. Its value
was not requested or received here; its usability has not been tested.

## Implemented locally

- `runtime/conditional_autonomy/review_verdict.py` parses the approved
  full verdict structure; `review_shadow.py` constructs a shadow verdict
  from five model fields and separately supplied context, hashes the exact
  diff and model-response bytes, and derives the model-only JSON schema.
- `outputs/S2_CR_01_Claude_Review_Prompt_DRAFT.md` is the draft prompt.
- Focused tests cover schema mutation, malformed/duplicate/contradictory
  output, self-asserted identity/revision, stale snapshot bindings, paths,
  version and outcome handling.
  The 240-test full regression was historical; the latest local full run passed
  248 tests after the review repair work began, before the latest workflow-only edit.

The draft `claude-review-shadow.yml` workflow is manual-dispatch only and is
explicitly disabled pending CLI compatibility and independent review.
It pins actions, supplies the PR diff as untrusted data,
checks the PR snapshot before and after, validates output, and stores a
`shadow-unverified` result for one day. It does not publish a merge check or
prove reviewer identity, calibration, full context or replay protection. Its
integration received a revision-required independent review and has not run on GitHub.

These files are in draft PR #39; subsequent fixes may be local and uncommitted.
A structural verdict is not authenticated
review evidence. Caller-supplied repository, revision, run and model identity
must be obtained and verified by the eventual trusted integration. No live
review has run and no status has been published.

## Remaining implementation

1. Independently review the contract and local parser/assembler.
2. Independently review and test the manual shadow workflow, then implement a
   GitHub workflow that triggers for the intended PRs,
   uses an immutable, trusted base for the verifier/prompt and keeps PR data
   untrusted; connect Claude's `structured_output` to independent validation.
3. Authenticate reviewer execution, obtain authoritative current head/base,
   diff and provider identity, protect against replay/races and PR-authored
   verifier changes, and implement durable revision/deadlock state.
4. Implement and test an authenticated check publisher; do not map workflow
   success or skipped/neutral statuses to review approval.
5. Run the owner-approved seeded-defect and clean-control calibration under
   separately authorized usage/spending. Only then request required-check setup.

## Owner authentication step for the eventual live test

Anthropic documents `claude setup-token` for Pro/Max and configuring the value
as GitHub Actions secret `CLAUDE_CODE_OAUTH_TOKEN`:
https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md

Do not add a repository-level secret. A separately configured and verified
restricted environment is a prerequisite to any replacement credential.
The owner performs sign-in/token handling and secret entry directly; never put
the value in chat, a file, a commit or a PR. Confirm current Anthropic plan
usage and any extra-usage settings before enabling a live run. Merely adding a
secret does not install or activate the not-yet-completed review workflow.

Stage 2 S2-05 remains on hold. The $300 pilot compute ceiling does not authorize
API spending, and subscription usage is subject to plan limits and settings.
