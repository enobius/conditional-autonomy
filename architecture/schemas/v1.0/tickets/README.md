# Workstream 1A Ticket Registry

All downstream tickets are filed but blocked on `B0-1`.

| Ticket | Tier | Artifact | Specification | Status | Depends on |
|---|---|---|---|---|---|
| B0-1 | Lead | Batch 0 conventions, checker, lint, mutations, CI | Amendment §§1-3, 7-10 | IN PROGRESS | - |
| B1-1 | Base | `validator-result.schema.json` | Spec §10.1 | BLOCKED | B0-1 |
| B1-2 | Base | `supervisor-decision.schema.json` | Spec §10.2 | BLOCKED | B0-1 |
| B1-3 | Base | `tool-outcome.schema.json` | Spec §§2.4, 10 | BLOCKED | B0-1 |
| B1-4 | Base | `outcome-vector.schema.json` | Spec §10.3 | BLOCKED | B0-1 |
| B1-5 | Base | `user-model.schema.json` | Spec §3.4 | BLOCKED | B0-1 |
| B1-6 | Base | `instance-manifest.schema.json` | Spec §8.4 | BLOCKED | B0-1 |
| B1-7 | Base | `adapter-manifest.schema.json` | Spec §6 | BLOCKED | B0-1 |
| B1-8 | Base | `event.schema.json` | Spec §§2.1-2.4 | BLOCKED | B0-1 |
| B2-1 | Mid | `action-proposal.schema.json` | Spec §2.3 | BLOCKED | B0-1 |
| B2-2 | Mid | `canonical-state.schema.json` | Spec §2.2 | BLOCKED | B0-1 |
| B2-3 | Mid | `access-scoped-observation.schema.json` | Spec §§2.1, 4 | BLOCKED | B0-1 |
| B3-1 | Mid | `trace-step.schema.json` | Spec §4 | BLOCKED | B1-1..8, B2-1..3 |
| B3-2 | Mid | `episode.schema.json` | Spec §§4-5 | BLOCKED | B3-1 |

## Required ticket content

Every downstream ticket must include:

1. Exact specification section.
2. Field inventory.
3. Access-class inventory.
4. Required/type/enum/pattern/bounds/conditional/composition constraint inventory.
5. At least one valid fixture.
6. One invalid fixture per constraint or justified equivalence class.
7. Primary and secondary validator results.
8. Independent specification-fidelity review.
9. Deferred runtime invariants created or updated.

No blocked ticket may merge before B0-1 is green and persisted in the repository.
