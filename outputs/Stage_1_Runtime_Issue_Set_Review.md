# Stage 1 Runtime Decomposition — Issue-Set Review

Status: **HUMAN APPROVAL REQUIRED BEFORE ISSUE FILING**  
Scope: Workstreams 1B–1E plus the Stage 1 keystone; no Stage 2+ work.

## Phase 0 gate status

| Ticket | Status | Evidence |
|---|---|---|
| T-01 | PASS | `origin/main` and the fresh clone resolved to `6032501`; the fresh-clone `--batch all` gate passed. The subsequent T-02 workflow commit was pushed as `e70784c`. |
| T-02 | PARTIAL | The canonical command is `python scripts/check_schemas.py --batch all`; `.github/workflows/schema-gate.yml` runs it for pull requests and `main`; local execution is green. GitHub branch protection and the seeded failing-then-green PR still require an authenticated GitHub session. |

Current local gate: 14 schemas, 14 positive fixtures, 45 negative fixtures, 8 active mutations detected, 16 complete deferred-invariant records; all checks green.

## Corrections to the proposed plan

The initial plan must not be filed verbatim:

1. `INV-015` is stored-content and event-log hash integrity at **ingest**. It is not the `HARD + UNKNOWN` reconciliation rule. The latter is already schema-enforced and must also be preserved by the runtime reconciliation function.
2. `INV-006` requires logical clocks to be strictly ordered under the declared concurrency policy. The register does not require gap-free clocks.
3. `INV-011` and `INV-013` are **promotion** invariants, not ingest invariants.
4. `INV-016` belongs in the replay cluster and covers episode membership plus unique, contiguous, ascending `step_index` values.
5. Fixture work is owned by each enforcement-phase ticket. This keeps one ticket per phase and avoids a disconnected “write all fixtures” ticket whose validators are not yet present.

## Proposed GitHub issues

Every issue below must include the named references, tier, dependencies, and exit test when filed.

### Workstream 1B — deterministic runtime core

#### T-03 — Implement append-only event and artifact store

- Tier: mid
- References: event, episode, and common-definition schemas; `INV-005`, `INV-015`
- Blocks: T-04, T-06, T-07, T-08
- Exit: atomic append survives forced interruption without a partial record; duplicate event IDs are rejected; canonical-content and event-log hashes verify; a one-byte stored-content mutation fails verification.

#### T-04 — Implement deterministic reducer and canonical-state versioning

- Tier: mid
- References: canonical-state and event schemas; `INV-007`, `INV-008`
- Depends on: T-03
- Blocks: T-05, T-07, T-09, T-11
- Exit: a fresh process replay produces byte-identical canonical state; illegal version transitions fail closed; repeated runs produce identical bytes.

#### T-05 — Implement access-scoped observation projector

- Tier: mid
- References: canonical-state and access-scoped-observation schemas; `INV-014`
- Depends on: T-04
- Blocks: T-08, T-14, T-17
- Exit: projected output validates; PRIVATE_ENVIRONMENT, EVALUATOR_ONLY, and VALIDATOR_VISIBLE canaries never appear in POLICY_VISIBLE output; lineage identifies the source projection.

#### T-06 — Implement typed artifact-reference resolver

- Tier: mid
- References: all schema `$ref`-bearing artifact fields; `INV-003`
- Depends on: T-03
- Blocks: T-07, T-08
- Exit: valid references resolve to the declared artifact type; dangling and wrong-type references return the registered failure resolution without partial execution.

#### T-07 — Implement replay, diff, and verify CLI

- Tier: mid
- References: episode and trace-step schemas; `INV-006`, `INV-007`, `INV-008`, `INV-016`
- Depends on: T-03, T-04, T-06
- Blocks: T-11, T-12, T-16, T-22
- Exit: a golden episode replays identically from a fresh process; diff identifies a single-byte ledger change; verify rejects illegal clock order and non-contiguous or cross-episode trace steps.

### Workstream 1C — deferred-invariant validators

Each phase ticket owns its named positive and negative fixtures from `deferred-invariants.md`.

#### T-08 — Implement ingest-phase validators

- Tier: mid; fixture slice is base-eligible
- References: `INV-003`, `INV-005`, `INV-014`, `INV-015`
- Depends on: T-03, T-05, T-06
- Blocks: T-13, T-17, T-19
- Exit: `INV-003/005/014/015-P` pass and `-N` fail through named validators; failures resolve to QUARANTINE; validator output is deterministic.

#### T-09 — Implement pre-execution validators and reconciliation decision function

- Tier: mid; pattern-setting and highest review scrutiny
- References: `INV-001`, `INV-004`, `INV-012`; validator-result schema; specification reconciliation table
- Depends on: T-04
- Blocks: T-10, T-15, T-18
- Exit: `INV-001/004/012-P` pass and `-N` fail with registered resolutions; every reconciliation-table row is tested; `HARD + UNKNOWN` can only resolve to QUERY or ESCALATE and never executes.

#### T-10 — Implement reconciliation-phase validators

- Tier: mid
- References: `INV-002`, `INV-009`, `INV-010`
- Depends on: T-09, T-15
- Blocks: T-13, T-18
- Exit: `INV-002/009/010-P` pass and `-N` fail; stale compensation authority escalates, unverified effects do not become canonical facts, and missed or unverifiable audits escalate.

#### T-11 — Implement replay-phase invariant adapters

- Tier: base
- References: `INV-006`, `INV-007`, `INV-008`, `INV-016`
- Depends on: T-04, T-07
- Blocks: T-13
- Exit: all four named validator functions resolve from the register; their `-P` fixtures pass and `-N` fixtures fail with QUARANTINE; adapters do not duplicate reducer or replay logic.

#### T-12 — Implement promotion-phase validators

- Tier: mid
- References: `INV-011`, `INV-013`
- Depends on: T-07, T-19
- Blocks: T-13, T-21
- Exit: clarification counters exactly match classified QUERY and USER_RESPONSE events; prohibited cross-split seed, template, graph, and disruption reuse is rejected; both invariant fixture pairs behave as registered.

#### T-13 — Compute invariant-register status from test evidence

- Tier: base
- References: `deferred-invariants.md`, `INV-001`–`INV-016`
- Depends on: T-08, T-10, T-11, T-12
- Blocks: T-22
- Exit: automation reports OPEN, IMPLEMENTED, or VERIFIED without hand-editing source records; 16/16 VERIFIED is possible only when every named positive and negative test passes in CI; removing one test drops the count.

### Workstream 1D — research environment

#### T-14 — Implement Thanksgiving micro-environment

- Tier: mid; standing early-QUERY instruction
- References: canonical-state, event, action-proposal, and outcome-vector schemas; Stage 1 environment specification
- Depends on: T-04, T-05
- Blocks: T-15, T-16, T-17, T-18, T-19, T-20
- Exit: resources, obligations, time windows, predictive effects, and constraint classes execute in a deterministic hand-authored episode; ambiguous requirements are resolved in the issue before merge.

#### T-15 — Implement capabilities and tool surface

- Tier: mid
- References: action-proposal, supervisor-decision, validator-result, and tool-outcome schemas
- Depends on: T-09, T-14
- Blocks: T-10, T-16, T-18
- Exit: permit, deny, query, repair, execute, verify, and compensate paths are exercised end-to-end; no tool call bypasses pre-execution reconciliation.

#### T-16 — Implement exogenous disruption schedule

- Tier: mid
- References: event and episode schemas; `INV-006`–`INV-008`
- Depends on: T-07, T-14, T-15
- Blocks: T-18, T-20
- Exit: a mid-episode disruption enters only through the ledger, forces replanning, and replays byte-identically.

#### T-17 — Implement deterministic oracle user simulator

- Tier: mid
- References: user-model and access-scoped-observation schemas; `INV-014`
- Depends on: T-05, T-08, T-14
- Blocks: T-18, T-19
- Exit: identical seeds produce identical answer sequences; private simulator state is absent from policy inputs and detected by the policy-leakage validator if injected.

#### T-18 — Add counterfactual safety pairs

- Tier: mid
- References: instance-manifest, action, decision, and validator schemas; T-09 reconciliation table
- Depends on: T-09, T-10, T-14, T-15, T-16, T-17
- Blocks: T-22
- Exit: every pair differs in exactly one declared safety-critical fact; that fact flips the expected validator or reconciliation verdict; unrelated serialized fields remain identical.

### Workstream 1E — instance generation

#### T-19 — Implement instance generator and manifest emission

- Tier: mid
- References: instance-manifest schema; `INV-013`, `INV-015`
- Depends on: T-08, T-14, T-17
- Blocks: T-12, T-20, T-21
- Exit: fixed seeds reproduce byte-identical instances and manifests; graph hashes, lineage, and split assignment validate; a changed generation input changes the relevant hash.

#### T-20 — Implement solver-backed feasibility oracle

- Tier: mid
- References: canonical-state, action, and instance-manifest schemas; Stage 1 constraint semantics
- Depends on: T-14, T-16, T-19
- Blocks: T-22
- Exit: a reviewed hand-authored feasible corpus is accepted and infeasible corpus rejected; solver witnesses are deterministic and independently checked against environment constraints.

#### T-21 — Enforce split hygiene during generation

- Tier: mid
- References: `INV-013`, instance-manifest schema
- Depends on: T-12, T-19
- Blocks: T-22
- Exit: generation rejects prohibited seed, template, graph-structure, or disruption-composition overlap before artifact promotion; allowed overlap cases remain accepted.

### Keystone

#### T-22 — Add required Stage 1 exit suite

- Tier: mid
- References: the four Stage 1 specification exit tests; `INV-001`–`INV-016`
- Depends on: T-03 through T-21
- Exit: one required CI check runs all four specification exit tests from a clean checkout and reports 16/16 VERIFIED; one seeded defect in each workstream makes the check fail; reverting each defect restores green.

## Dependency and dispatch summary

Primary critical path:

`T-03 → T-04 → T-07 → T-11 → T-13 → T-22`

Additional keystone paths:

- `T-04 → T-05 → T-14 → T-15 → T-16 → T-18 → T-22`
- `T-14 → T-17 → T-19 → T-20 → T-22`
- `T-19 → T-12 → T-21 → T-22`
- `T-09 → T-10 → T-13 → T-22`

Immediate parallel work after approval: T-03 implementation and the fixture-first slices of T-08 through T-12. Validator implementation remains blocked by the dependencies above.

## Tripwire counter

Initial weekly values: unresolved QUERY blockers over two days = 0; second-review failures = 0; scope violations = 0. Any category reaching 3 triggers decomposition review. Counts must be updated by the orchestrator from issue events; they are diagnostic signals, not worker-performance scores.

## Human decisions required

- [ ] Approve the Stage 1 boundary: 1B–1E plus T-22 only; no Stage 2+ issues.
- [ ] Approve clustering 1C by enforcement phase, with fixtures owned by each phase ticket.
- [ ] Confirm the reconciliation decision function remains in T-09, while `INV-015` correctly remains in T-08.
- [ ] Approve ticket sizing, exit-test attribution, and dependency edges above for GitHub filing.

After approval, file the 20 issues, apply tier/workstream/blocking labels, encode dependency edges, and start T-03 plus the unblocked fixture slices.
