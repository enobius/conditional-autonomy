# S2-CR-01: read-only local Git adapter

Base: protected main after PR #45, `5922382fc6c9fad378f7efe6a2de20f6c6240feb`.
This is an offline candidate only. No production workflow, provider policy,
credentials, protected settings, or scientific authority changed.

## Scope and evidence

- A trusted caller supplies an absolute Git executable, a locally provisioned
  repository, an independently configured repository identity and policy pin,
  and a current-PR observer. The adapter compares the requested policy ID
  against that pin and verifies it names a local commit with a readable root tree.
  A matching ID does not establish who approved it or prove the running code
  came from that commit.
- Read committed objects, never the worktree. Require SHA-1 object format and
  full IDs. Recompute commit and recursively visited tree IDs from their raw
  bytes; fail closed on missing, unsupported, malformed, ambiguous, oversized
  or truncated tree data. Verify ordinary leaf blob availability and type by
  object ID, without reading or hashing blob content. Gitlinks are opaque leaf
  pointers; no submodule fetch or recursive submodule inspection.
- Compare the complete base-tip and head leaf inventories through the merged
  guard. Observe and match repository, PR, base and head both before and after
  reads. This is not atomic with later publication and not a merge-tree
  attestation.
- The Git subprocess gets a small environment, disables replacement objects
  and lazy fetching, forbids Git protocols as a default, and uses only local
  read commands. No checkout, index update, dependency install, policy code
  from the PR, credentials, or network integration.

The executable and the object database, including its config, alternates and
storage lifecycle, must be provisioned and controlled outside the PR. This is
not a sandbox for opening arbitrary repositories supplied by a PR. Limits on
raw metadata, aggregate tree volume, depth, entries, tree count and Git time
fail closed rather than returning a partial result. Baseline checked with Git
2.47.1 on Windows; hosted parity is verified separately by CI.

## Independent review

Inspect the raw object traversal and identity checks, exact policy pin and
before/after subject checks. Local fixtures exercise a recursive real Git tree,
missing object and truncated tree cases, metadata hash/size failures, stale
subjects, wrong policy/object type, replacement refs and inherited environment.
Check that failures do not return usable partial evidence.

Still unbuilt: provisioned mirror and authenticated GitHub observation,
authenticated policy provisioning and execution provenance, authenticated
decision/exception sources, trusted App publishing and recheck/replay lifecycle.
No owner exceptions enter this adapter. Give separate offline-merge and
production-enablement verdicts.
