# T-19b implementation candidate: P6 generator v2

The default generator version is 2.0. Explicit 1.0 retains the canonical
hand-authored state and historical manifest bytes; Table 6 and P9 fixtures are
not edited. Existing environment validators and feasibility solver/checker
remain unchanged. Independent review is required before integration.

## Finite engineering domain, not an evaluation distribution

Seed modulo 120 shifts the earliest side-preparation release by 0..119 whole
minutes from the canonical 14:00 local baseline. The two-hour reference task
still starts at 16:00; turkey duration, dinner deadline, travel, arrivals and
all other original facts are preserved. This changes an executable HARD time
window, not an identity field. A projected POLICY_VISIBLE fact mirrors that
window so the policy can observe the declared variant.

The approved eight-seed regression grid yields distinct operative windows.
Different arbitrary seeds can collide (11 and 131, for example); the corpus
checker rejects those collisions. This 120-case domain does NOT establish
the eventual 100-case evaluation corpus, 330 safety bases, their sampling
distribution, template diversity or statistical independence. S2-05/S2-07
must implement and audit their approved inventory requirements separately.

## Independent checks

`generation_validation.check_variant_state` inspects serialized input without
calling the generator. It checks bounds, seed binding, the public release fact
and exact preservation of every out-of-domain canonical fact. Generation's
existing feasibility oracle uses its independent witness checker.

`semantic_task_fingerprint` reads operative state/action content, not supplied
graph hashes. It excludes top-level seed/identity/lineage metadata and removes
the duplicated release projection from the fingerprint. Node signatures use
semantic entity/obligation/deadline properties and action/resource roles, so
consistent identifier renaming does not create a new task. Ambiguous node
signatures fail closed. This is a conservative P6-domain normalizer, not a
general graph-isomorphism solution for arbitrary future environments.

`verify_distinct_instances` validates integrity/domain first, then rejects
repeated fingerprints. It admits independent bases, not a collection of
matched/counterfactual variants; those require explicit manifest relationships.

## Acceptance evidence

Tests include meaningful window verdict change, fixed-input/fresh-process
reproduction, metadata/hash/ID-renaming attacks, zero-offset canonical
equivalence, and legacy byte comparison to the verified pre-change clone.
`python -m runtime.conditional_autonomy.generation_distinctness_exit` copies
production inputs into an isolated checkout, seeds `offset = 0`, requires
the paired exit test red, restores original bytes and requires green.
