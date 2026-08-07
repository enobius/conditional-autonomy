# Stage 1 runtime

`conditional_autonomy.storage` provides the append-only persistence boundary.

`conditional_autonomy.contracts.validate_contract` is the shared public schema
boundary. It loads the pinned validator implementation (preferring the vendored
runtime), validates against the named v1.0 contract with format checking, and
returns a detached strict-JSON object. Reducer, projection, replay, and
pre-execution code all use this boundary.

## Canonical bytes and hash domains

- Canonical JSON is UTF-8 with keys sorted lexicographically, compact `,` and
  `:` separators, Unicode preserved, and non-finite numbers rejected.
- A contract object's canonical content hash is SHA-256 over those bytes after
  removing only the object's top-level `content_hash` field. The returned form
  is `sha256:<64 lowercase hex characters>`.
- Artifact envelopes always record that canonical content hash. If the domain
  object declares its own top-level hash, it must match; contracts without that
  field remain unmodified.
- The event-log hash is SHA-256 over the exact canonical JSONL bytes, including
  one trailing newline per event. Verification rejects noncanonical bytes,
  partial lines, duplicate event IDs, or invalid event content hashes.

Artifact and event-log updates use a flushed temporary file in the destination
directory followed by atomic replacement. Failed staging or interruption before
replacement leaves the preceding complete version visible. A shared-root file
lock serializes the complete durable read/check/write transaction across store
instances and processes, and supported platforms flush the destination directory
after replacement so its new entry is durable.

## Deterministic reducer

`conditional_autonomy.reducer` accepts only schema-valid `STATE_TRANSITION`
events whose five-field payload describes a `SET` of an existing canonical-
state object member. Each accepted event advances `state_version` exactly once,
advances the logical clock, and appends its `event_id` to `revision_chain`.
No-op values are compared as canonical JSON, so JSON types remain distinct.

`INV-015` continues to own ingest-time and durable event-log integrity. The
reducer additionally verifies the self-hash of a directly supplied event as a
defense-in-depth boundary; this does not replace the ingest validator.

## Access-scoped observation projection

`conditional_autonomy.projection` selects complete policy-labelled fact objects
from schema-valid canonical state by explicit JSON Pointer. It rejects missing
or duplicate sources and blocks non-policy access labels on every traversed
ancestor and throughout the selected fact before validating the result against
`access-scoped-observation.schema.json`. Because that schema is closed and has
no lineage field, the immutable `ObservationProjection` aggregate keeps typed
source/output lineage inseparable from the observation and returns defensive
observation copies.

The aggregate alone is not the ingest invariant. Downstream T-08 must accept
the complete `ObservationProjection`, never a detached observation, and enforce
a bijection: every `/visible_facts/{index}` has exactly one lineage entry, no
lineage entry targets any other output, and each entry agrees with its actual
source path, source episode, state version, and effective `POLICY_VISIBLE`
access class. A missing, duplicate, stale, or extra lineage entry must resolve
to `QUARANTINE` under `INV-014`.

Run the runtime suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

# Replay CLI

The runtime exposes store-backed replay and verification plus an exact byte
ledger diff:

```text
python -m runtime.conditional_autonomy.replay replay STORE INITIAL_STATE_REF
python -m runtime.conditional_autonomy.replay diff LEFT_LEDGER RIGHT_LEDGER
python -m runtime.conditional_autonomy.replay verify STORE EPISODE_REF INITIAL_STATE_REF RECORDED_STATE_REF
```

`verify` checks the episode's declared event-log hash, typed state references,
strict event clock order, legal reducer transitions, deterministic final state,
and trace-step episode membership and contiguous ordering. A failed check exits
2; `diff` exits 1 when it finds a difference and prints its zero-based byte
offset plus one-based line and column.

The two event-log hashes have deliberately different domains:
`AppendOnlyStore.event_log_hash()` covers every canonical JSONL event in the
store, while `episode.event_log_hash` covers only that episode's events in
durable order, still including one trailing newline per event. Verification
checks store-wide integrity first and then compares the per-episode subset hash,
so appending an event for another episode changes the store hash without
invalidating the completed episode.

## Pre-execution validation and reconciliation

`conditional_autonomy.preexecution` provides pure, fail-closed implementations
of `INV-001`, `INV-004`, and `INV-012`. Its deterministic reconciliation
function encodes Specification section 3.1. A learned approval cannot override
hard evidence, and `HARD + UNKNOWN` can resolve only to `QUERY` or `ESCALATE`.
Soft non-pass evidence requires the caller to supply the result of the declared
action-specific residual-risk ceiling; omission raises an explicit error.
