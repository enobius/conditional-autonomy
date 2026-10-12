# T-19b — Pair reproducibility with structural generator distinctness

Date: 2026-10-12. Status: OWNER APPROVED AND FILED; ready, not dispatched.
GitHub: https://github.com/enobius/conditional-autonomy/issues/21.
Stage 1 regression follow-up to completed T-19; not a
retroactive edit of the 20/20 completion record.

- Tier: mid, with independent adversarial review.
- References: `outputs/stage_1_issue_drafts.json` (T-19),
  `runtime/conditional_autonomy/generation.py`, `tests/test_generation.py`,
  `outputs/Stage_2_v5_Intake_Review.md` (generator capacity finding),
  v5 manifest Sections 2 and 7, Stage 1 replay/feasibility/split gates.
- Depends on: completed T-19 and the pushed, fresh-clone-verified preparation
  commits `a76729b` and `8560527`.
- Blocks: S2-05, S2-07, S2-10, and all generator-dependent pilots.

## Evidence and defect

`generate_thanksgiving_instance()` always constructs
`initial_thanksgiving_state()` and `thanksgiving_actions()` before computing
entity and constraint graphs. Seed affects recorded identity, not those graphs.
The existing `test_changed_inputs_change_only_relevant_hash_domains` explicitly
expects equal graph hashes for seeds 42 and 43. Reproducibility therefore
passes while semantic diversity is untested. Distinct IDs or whole-envelope
hashes cannot certify distinct task instances.

## Proposed scope

1. Define a versioned semantic task fingerprint over meaningful entity,
   constraint, initial-state and action relationships/values. Exclude seed,
   instance ID, split, lineage, timestamps and other identity-only metadata.
   Trivial identifier relabeling must not certify a new task. Document the
   canonicalization rule and its independent checker.
2. Introduce actual seeded variation within an explicitly allowed task domain;
   verify validity and feasibility independently of the generator. Preserve
   the approved canonical hand-authored P6/P9 facts as explicit fixtures.
   Do not rewrite Table 6 or conflate generated variants with that reference.
3. Update the old seed-change expectation, while retaining legitimate
   hash-domain isolation assertions for metadata and oracle-private changes.
   Version the changed generator; do not silently reinterpret old manifests.
4. Add paired reproducibility AND distinctness regression tests. The grid below
   is a proposed regression fixture, not an approved experiment distribution.

## Exit tests

- For each proposed seed `[11, 29, 47, 101, 103, 107, 109, 113]`, identical full
  generation inputs yield byte-identical instance and manifest in fresh
  processes with at least two Python hash seeds.
- Within that declared seed grid, meaningful task fingerprints differ across
  bases, independently recomputed from serialized task content; variations
  are valid and feasible. This is a finite-grid test, not a claim that all
  possible seeds can be collision-free or statistically independent.
- Seed/ID-only edits to a constant task, graph-preserving renaming, or a
  forged graph hash do NOT satisfy distinctness. A seeded constant-generator
  mutation makes this test red, and restoring it returns green.
- Existing canonical P6/P9 environment facts, disruption replay, oracle
  privacy, manifest tamper detection and split hygiene remain green.
- Full regression and the complete Stage 1 seeded-defect exit gate pass from
  a fresh clone. Record the new test count rather than requiring exactly 215.

## Validation-policy routing payload

Before any Stage 2 generator ticket dispatch, route this rule into the actual
validation policy: "A seeded generator must prove both fixed-input
reproducibility and declared-corpus semantic distinctness. Metadata or identity
hash variation is insufficient. Independently verify task validity and
feasibility, reject structural duplicates, and demonstrate that a constant
generator mutation fails the exit test. Distinctness does not by itself prove
statistical independence. Preserve canonical reference fixtures and version
changed generation semantics."

Owner approved the repository-local policy home on 2026-10-12. The paired rule
is routed to `architecture/validation-policy.md` (version 1.0). No Codex skill
was installed or modified. S2-05/S2-07 still require completed T-19b.

## Approval gate

- [x] Approve T-19b scope and the proposed regression seed grid.
- [x] Approve repository-local validation policy and record routing.
- [x] Authorize filing the Stage 1 regression issue.
- [ ] Dispatch implementation (separate next action).
