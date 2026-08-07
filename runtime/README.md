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

`AppendOnlyStore.verify_artifact_inventory()` enumerates the complete artifact
directory under the store lock. It rejects unexpected entries and verifies
every filename-to-ID binding, strict canonical envelope, artifact type, and
content hash; callers cannot hide a corrupt artifact by supplying a partial ID
list.

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

## Ingest validation

`conditional_autonomy.ingest` provides the named `INV-003`, `INV-005`,
`INV-014`, and `INV-015` validators. Every failure is deterministic and uses
the register's exact `QUARANTINE` resolution. The adapters resolve artifacts
through `ArtifactReferenceResolver`, read only verified event IDs and hashes
through `AppendOnlyStore`, use the shared canonical byte/hash functions, and
validate projection inputs at the public schema boundary.

`artifact_integrity_check(store)` always verifies that complete artifact
inventory and the global event log. Optional artifact IDs are additional
required references, never a narrower verification scope. Broken iterators and
unavailable storage boundaries produce stable fail-closed outcomes rather than
escaping the validator.

The policy-input validator accepts only a complete `ObservationProjection`
plus its canonical source state. It verifies a bijection between every
`/visible_facts/{index}` and exactly one lineage record, then checks the actual
source value, source path, episode, state version, and effective access class.
Detached observations and missing, duplicate, stale, extra, protected, or
value-mismatched lineage fail closed.

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

## Replay-phase invariant adapters

`conditional_autonomy.replay_invariants` exposes the four exact validator names
registered for `INV-006`, `INV-007`, `INV-008`, and `INV-016`. These adapters
consume the compact invariant corpus, fail closed to `QUARANTINE`, and delegate
clock/trace ordering to the replay layer and state transition/replay semantics
to the reducer. Clock gaps are valid under the declared total order; trace-step
contiguity is relative to the first supplied index.

## Deterministic oracle user simulator

`conditional_autonomy.oracle.OracleUserSimulator` validates the v1.0 user
model, holds both model and private world state as detached canonical bytes,
and derives each answer template from SHA-256 over the declared seed, turn,
question ID, and requested fact ID. Recreating a simulator with the same
inputs therefore produces a byte-identical answer sequence without depending
on Python hash order or process-local random state.

One simulator instance represents one stateful conversation. Repeated calls
share an absolute cumulative turn counter and `maximum_turns` budget. Each
batch is preflighted and generated under a conversation lock before the
counter advances, so a failed batch consumes no turns and cannot cause public
ID reuse. Observation and response-fact IDs derive only from policy-visible
episode/question/fact data and the absolute turn; evaluator-only seed material
affects response-template selection but never public identifiers.

Answers cross the boundary only as schema-valid `ObservationProjection`
aggregates. The simulator reveals only the requested answerable fact, keeps
unrequested private facts and evaluator-only model fields out of policy input,
and runs `INV-014` before returning each response. Turn bounds and protected
content fail closed. The current runtime explicitly supports the schema
fixture's `template:p6-oracle` family and rejects unknown families.

## Pre-execution validation and reconciliation

`conditional_autonomy.preexecution` provides pure, fail-closed implementations
of `INV-001`, `INV-004`, and `INV-012`. Its deterministic reconciliation
function encodes Specification section 3.1. A learned approval cannot override
hard evidence, and `HARD + UNKNOWN` can resolve only to `QUERY` or `ESCALATE`.
Soft non-pass evidence requires the caller to supply the result of the declared
action-specific residual-risk ceiling; omission raises an explicit error.
Registered invariant failures use the separate `InvariantDisposition` type;
`QUARANTINE` is therefore neither a supervisor `Resolution` nor a validator-
result `permitted_resolution`.

## Thanksgiving micro-environment

`conditional_autonomy.thanksgiving` is the deterministic, hand-authored static
P6 environment grounded in REALM-Bench v2 Table 6. It encodes the five family
members, 18:00 dinner, four-hour turkey, two-hour sides, continuous cooking
supervision, airport and Grandma pickups, and the published travel times. It is
explicitly a thesis-specific executable encoding; P9's James flight delay is
reserved for T-16.

Internal time is integer UTC minutes. Boundary events use normalized timestamps;
reservations are half-open and deadlines inclusive. Immutable constraints cover
PREVENTABLE, PREDICTIVE, and DETECTABLE enforcement. The fixed schedule executes
only through ordered reducer-compatible `SET` events and emits schema-valid
action proposals, canonical states, a policy-visible observation with lineage,
and an outcome vector. Tool calls, disruptions, user interventions, and recovery
remain zero or null because later Stage 1 tickets own those behaviors.
Cooking proposals are marked `IRREVERSIBLE`; the environment never implies that
prepared food can be undone. `optimality_gap` remains `null` until T-20's
feasibility oracle can establish an optimization reference.

## Capability-gated tool surface

`conditional_autonomy.tools.ToolSurface` is the sole runtime dispatch boundary
for registered tool adapters. Every attempt validates the pinned action,
supervisor-decision, validator-result, and tool-outcome contracts; adds hard
capability and current-version evidence; and sends all evidence through T-09
reconciliation before an adapter can run. APPROVE is the contract term for a
permit and REJECT is the contract term for a denial. QUERY, REPAIR, REJECT, and
ESCALATE attempts dispatch zero tool calls.

Repair proposals and compensation templates are materialized as complete action
proposals and re-enter the same validation, capability, version, and
reconciliation gates. COMPENSATABLE originals additionally require T-09
`INV-001` prevalidation. Successful adapter results advance one state version,
are verified without direct canonical-state mutation, and validate as tool
outcomes. Idempotency keys suppress repeated side effects and reject conflicting
reuse. The external evidence set is closed over T-09's registered
`current_version_check` and `adapter_compatibility_check`, plus
`compensation_prevalidation_check` for compensatable actions, and every result
must observe the proposal's exact state version. Adapter execution is claimed
under a lock before dispatch. A completed exact retry returns the recorded
outcome; a post-dispatch validation failure leaves an indeterminate claim that
cannot be retried automatically. Recovery accepts only the byte-identical
recorded successful outcome and rechecks action, tool, version, capability, and
idempotency linkage. Because the pinned compensation template has no effects
field, recovery compilation requires an explicit strict-JSON expected-effect
set before it can re-enter the gate. A successful outcome requires exact
multiset equality across declared, normalized, and verified effects.
Current compensation authority and effect-promotion audits
remain T-10 work; exogenous disruptions remain T-16 work.
