# Validation policy: seeded instance generators

Version: 1.0. Owner approved repository-local policy on 2026-10-12.
Scope: T-19b and every subsequent Stage 2 seeded generator or corpus validator.
This is a repository policy, not a Codex skill installation.

## Paired acceptance rule

A seeded generator must prove BOTH:

1. **Reproducibility:** identical full generation inputs produce byte-identical
   instance and manifest in fresh processes with different Python hash seeds.
2. **Semantic distinctness:** the declared corpus contains genuinely distinct
   task bases under an independently recomputed, versioned semantic fingerprint.
   Seed, instance ID, split, lineage and identity-only metadata do not establish
   distinctness. Trivial graph-preserving identifier renaming does not qualify.

Check meaningful entities, constraints, state and action relationships/values.
Verify validity and feasibility independently of the generation procedure.
Reject structural duplicates, except explicitly declared matched/counterfactual
relationships governed by the manifest. Matched variants must share the intended
base while differing only in their declared intervention/disruption.

## Mandatory adversarial evidence

- A constant-task generator mutation must fail the distinctness exit test.
- Metadata-only changes and forged graph hashes must not evade the checker.
- Restoring the implementation must return the same test to green.
- Preserve canonical hand-authored P6/P9 facts, environment fidelity, privacy,
  replay, integrity and split-hygiene checks.
- Version changed generation semantics; do not reinterpret historical manifests.

The approved T-19b regression grid is `[11, 29, 47, 101, 103, 107, 109, 113]`.
It is a finite engineering fixture, not an evaluation sampling distribution or
proof that all seeds are collision-free. Stage 2 corpus tests cover the actual
enumerated inventory, not just this grid. Distinctness alone does not establish
statistical independence: distribution, sampling-unit and lineage audits remain
separate requirements.

## Dispatch and authority

Policy routing is recorded here before S2-05/S2-07 dispatch. Those tickets still
depend on completed T-19b and their owner decision gates. This policy does not
authorize implementation dispatch, paid infrastructure, pilot execution, final
freeze or confirmatory collection. See the approved issue-set review and tracker.
