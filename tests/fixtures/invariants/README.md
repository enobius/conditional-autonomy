# Deferred-invariant fixture corpus

`corpus.json` is the fixture-first contract for the sixteen runtime invariants
registered in `architecture/schemas/v1.0/deferred-invariants.md`. It is not part
of the JSON Schema valid/invalid fixture manifest: every case is structurally
valid runtime context, and the named validator decides the verdict.

Each invariant has exactly two stable test IDs:

- `INV-nnn-P` expects `PASS` and no failure resolution.
- `INV-nnn-N` expects `FAIL` and the register's exact failure resolution.

Clause-isolating cases use IDs such as `INV-nnn-N.clause-name`. They supplement
the one registered positive/negative pair; they do not replace or multiply the
register's canonical `positive_test` and `negative_test` records. Every
supplemental case declares `coverage_clause`.

Validator implementations should accept a case's `input` object without
depending on object-key order, wall-clock time, randomness, external services,
or files outside the fixture. `expected_failure_resolution` is invariant
enforcement metadata. In particular, `QUARANTINE` is an outcome outside the
`validator-result.permitted_resolution` enum; implementations must not force it
into that schema. A later orchestration boundary may translate the outcome but
must not silently change the fixture expectation.

`INV-001` uses the canonical action-proposal compensation shape:
`compensation_action.prevalidation_id`. The obsolete fixture-only top-level
`compensation_prevalidation_id` alias is intentionally rejected.

`INV-015` uses the Stage 1 canonical JSON profile: UTF-8, lexicographically
sorted object keys, compact separators, and non-finite numbers forbidden.
Event-log integrity hashes cover canonical JSON Lines bytes: one canonical
event per line, each terminated by `\n`, including the final line. The profile
is intentionally narrower than RFC 8785 and does not claim its float or
Unicode-normalization behavior.

Supplemental negatives isolate each independently enforceable clause in the
multi-clause invariants. `INV-006-P` deliberately uses clocks 1 and 3 to guard the requirement for
strict ordering without accidentally imposing gap-free clocks.

Supplemental coverage is pinned by the checker:

- `INV-002`: stale state version and false current precondition (the canonical
  negative isolates missing capability).
- `INV-003`: dangling reference (the canonical negative isolates wrong type).
- `INV-004`: plan identity and plan version (the canonical negative isolates
  state version).
- `INV-010`: on-time missing and on-time unverifiable audits (the canonical
  negative isolates a missed deadline).
- `INV-011`: USER_RESPONSE count (the canonical negative isolates QUERY count).
- `INV-012`: target modules and runtime (the canonical negative isolates base
  model hash).
- `INV-013`: template, graph, and disruption overlap (the canonical negative
  isolates seed overlap).
- `INV-014`: EVALUATOR_ONLY and VALIDATOR_VISIBLE (the canonical negative
  isolates PRIVATE_ENVIRONMENT).
- `INV-015`: event-log hash (the canonical negative isolates artifact hash).
- `INV-016`: uniqueness, contiguity, and ascending order (the canonical
  negative isolates episode membership).

The corpus checker independently recomputes both `INV-015` hash forms. It also
pins the artifact negative to an artifact-content-only mutation and the
event-log negative to an integrity-hash-only mutation, preventing one failure
from masking the other clause.

Run the corpus-only shape and register-consistency check from the repository
root:

```powershell
python tests/fixtures/invariants/check_corpus.py
```

The checker deliberately does not execute validator logic and does not alter
the existing schema gate.
