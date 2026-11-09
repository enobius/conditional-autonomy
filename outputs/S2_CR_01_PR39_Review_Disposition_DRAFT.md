# PR 39 independent review disposition — draft

The supplied independent review covers PR 39 head
`eb1b6416cfaf53ba49cfa39ca201c7fd137475f0` and recommends revision required.
It reports one P0, one P1, eight P2 and four P3 findings. This note is not
acceptance of the review, a certification of its claimed tests, or authorization
to merge or run the workflow.

The owner reported removing the repository-level Claude OAuth secret after the
P0 finding. Removal has not been independently verified from this environment.
There is no evidence here that the credential was accessed. Do not restore a
credential until the environment's branch restrictions and access controls have
been configured and independently verified; assess revocation and replacement.

The draft adds an environment name (not protection by itself),
use the reviewed action's reported commit SHA, bound JSON-escaped prompt size,
reject recognizable binary diffs, randomize diff delimiters, and reject control
characters and untrimmed finding paths. The draft also requests the diff using
immutable base and head SHAs, records the merge base, and checks findings
against displayed old/new hunk ranges (the contract has no side field). The
workflow is explicitly disabled pending further review and live compatibility
testing. These are partial mitigations, not
closure of the findings. In particular, review input remains untrusted: random
delimiters do not eliminate prompt injection.

An offline recorder test used the pinned action source at
`61a9c274fa7110a66dfafc1bbbced03833eb25fe`, `shell-quote` 1.8.4, Node
24.11.1 and Agent SDK 0.3.319. It observed the standalone argument `--tools=`
and an intact separate `--json-schema` value. The reproducible probe is
`tests/offline_action_argv_probe.mjs`; pinned upstream inputs must be supplied
separately. It does not run the actual Claude CLI or establish that tools are
disabled at runtime.

Blocking work still includes validating actual CLI treatment of `--tools=`,
independent verification of the compare API behavior and the
location binding (including unsupported path handling), comprehensive workflow
security and boundary tests, and reconciliation of remaining stale project
records. The action commit and environment protections must be independently
verified. The reviewer also identified live
compatibility questions; no live run is authorized by this note. A new review
must examine the final revised head before merge.

## Re-review of `6c68041`

The supplied re-review recommended revision required: F-007 and F-009 were
merge blockers; F-001 remained an owner-settings check. It also reported a new
enablement blocker: `--max-turns 1` did not produce structured output in a
localhost test with CLI 2.0.62. That is not evidence about the pinned CLI
2.1.319. The workflow remains explicitly disabled, and the replacement token
and environment protections must not be configured on the assumption that
naming an environment protects it.

The subsequent candidate repair splits patch text only on LF, tests injected
Unicode/control separators, parses workflow YAML with a duplicate-key-rejecting
loader, and tests seven adversarial workflow mutations. Compare file-inventory
validation moved from an inline jq expression to a testable Python command;
fixtures cover absent files, incomplete patches, cap overflow, and invalid
merge-base IDs. The upstream argv probe is still a separate manual test, not
part of the default unit suite; it needs externally supplied pinned source and
SDK, and the probe does not itself authenticate those inputs. These repairs
require fresh independent review. The exact CLI
turn limit and tool behavior remain unverified; no live model invocation or
subscription usage was performed.

Local verification of this candidate: 251 unit tests passed; the focused
20-test review suite also passed with the newly pinned PyYAML 6.0.3 installed
in an isolated dependency directory. Remote CI and independent review apply
only to the exact revision they examine.
