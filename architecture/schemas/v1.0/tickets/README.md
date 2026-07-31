# Workstream 1A Ticket Registry

`B0-1` passed the technical gate and was persisted in commit `6fb0289`.
Batch 1 and Batch 2 have passed their technical gates and independent
specification-fidelity review and are committed on `main`. B3-1 and B3-2 have
passed their technical gates and independent specification-fidelity review.
Workstream 1A's schema ticket set is complete.

| Ticket | Tier | Artifact | Specification | Status | Depends on |
|---|---|---|---|---|---|
| B0-1 | Lead | Batch 0 conventions, checker, lint, mutations, CI | Amendment §§1–3, 7–10 | DONE | - |
| B1-1 | Base | `validator-result.schema.json` | Spec §10.1 | DONE | B0-1 (satisfied) |
| B1-2 | Base | `supervisor-decision.schema.json` | Spec §10.2 | DONE | B0-1 (satisfied) |
| B1-3 | Base | `tool-outcome.schema.json` | Spec §2.4; §10.4 | DONE | B0-1 (satisfied) |
| B1-4 | Base | `outcome-vector.schema.json` | Spec §10.3 | DONE | B0-1 (satisfied) |
| B1-5 | Base | `user-model.schema.json` | Spec §3.4 | DONE | B0-1 (satisfied) |
| B1-6 | Base | `instance-manifest.schema.json` | Spec §8.4 | DONE | B0-1 (satisfied) |
| B1-7 | Base | `adapter-manifest.schema.json` | Spec §6 | DONE | B0-1 (satisfied) |
| B1-8 | Base | `event.schema.json` | Spec §§2.1–2.4 | DONE | B0-1 (satisfied) |
| B2-1 | Mid | `action-proposal.schema.json` | Spec §§2.3–2.4 | DONE | B0-1 (satisfied) |
| B2-2 | Mid | `canonical-state.schema.json` | Spec §§2.1–2.2, 2.4 | DONE | B0-1 (satisfied) |
| B2-3 | Mid | `access-scoped-observation.schema.json` | Spec §§2.1, 4 | DONE | B0-1 (satisfied) |
| B3-1 | Mid | `trace-step.schema.json` | Spec §4 | DONE | B1-1..8, B2-1..3 (satisfied) |
| B3-2 | Mid | `episode.schema.json` | Spec §§4–5 | DONE | B3-1 (integrated) |

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

`REVIEW REQUIRED` means the schema, fixtures, ticket evidence, and mutation
coverage are implemented and technically green, but the independent review
required by the definition of done has not occurred. It does not authorize
merge or unblock Batch 3.

## Technical gate commands

```powershell
python scripts/check_schemas.py --batch batch0
python scripts/check_schemas.py --batch batch1
python scripts/check_schemas.py --batch batch2
python scripts/check_schemas.py --batch batch3
python scripts/check_schemas.py --batch all
```
