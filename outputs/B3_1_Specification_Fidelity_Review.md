# B3-1 Independent Specification-Fidelity Review

**Review status:** Complete — ticket passes
**Reviewer:** Manny Reviewer
**Review date:** 2026-07-30

## Scope and authorities

This review covers `B3-1`, `trace-step.schema.json`, its valid fixture, seven
negative fixtures, mutation coverage, and deferred-invariant ownership.

Authorities reviewed:

- Thesis Architecture Formalization v1.1.2, Spec §4.
- Workstream 1A Plan Amendments, §§5–6.
- The reviewed Batch 1 and Batch 2 contracts composed by the trace-step
  schema.

## Findings

| Review area | Verdict | Evidence |
|---|---|---|
| Trace shape | PASS | The schema includes the complete Spec §4 trajectory: evaluator-only canonical-state reference, policy-visible observation and goal, policy/adapter versions, proposal, supervisor decision, validator results, tool result, transition difference, outcome vector, evaluator labels, and provenance. Trace ID, episode ID, and step index provide the stable identity and ordering required for composition. |
| Canonical-state separation | PASS | `canonical_state_ref` is a closed reference object with runtime access class fixed to `EVALUATOR_ONLY`; canonical state cannot be embedded. Both the access-class and embedded-state negative fixtures fail. |
| Access boundaries | PASS | The policy can receive only `actor_observation`, `goal_ref`, and policy-visible proposal/version data. Supervisor, validator, evaluator, and private data remain outside policy input in accordance with Spec §4 and Amendment §5. The private and evaluator leakage fixtures fail. |
| Contract composition | PASS | Observation, action proposal, supervisor decision, validator result, tool outcome, and outcome vector use closed `$ref` composition to their reviewed v1.0 contracts. The nested hard-UNKNOWN validator guard is exercised by an invalid fixture. |
| Requiredness and local constraints | PASS | The object is closed; all trace fields are required, absence-sensitive proposal/decision/tool/adapter fields are explicit null unions, and `step_index` is a nonnegative integer. |
| Deferred invariants | PASS | Referential integrity, version currency, replay equality, policy-input leakage, clarification reconciliation, and integrity hashes are non-local checks and are already assigned in `deferred-invariants.md`, consistent with Amendment §7. |
| Technical validation | PASS | `python architecture\\schemas\\v1.0\\scripts\\check_schemas.py --batch batch3` passed: 13 schemas, 1 positive fixture, 7 negative fixtures, 1 active mutation, and 15 deferred invariants. |

## Closure decision

B3-1 passes the independent specification-fidelity review and may be marked
`DONE`. This review does not integrate or merge B3-1. B3-2 remains blocked
until the completed B3-1 contract is integrated.
