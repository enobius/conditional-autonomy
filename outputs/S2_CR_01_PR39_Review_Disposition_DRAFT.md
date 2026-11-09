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

Local changes in progress add an environment name (not protection by itself),
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
