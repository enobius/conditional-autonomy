# Stage 2 — Dependency-ordered issue-set review

Date: 2026-10-12. Status: OWNER APPROVED AND FILED; not dispatched.
Scope: Stage 2 engineering, development pilots, final freeze, then gated
confirmatory collection. No Stage 3 training, model selection on TEST, paid
provisioning, policy substitution or confirmatory execution is authorized by
this plan. Approved IDs S2-01–S2-16 map to GitHub issues #22–#37 in the tracker.

## Entry evidence and authoritative decisions

- Stage 1 tracker: 20/20 complete; HEAD `8560527` pushed to `origin/main`.
- Preparation commit `a76729b` plus LF checkout fix `8560527` verified in a
  fresh clone: 215 tests passed; 16/16 invariants and 4/4 mutation/restoration
  proofs passed; aggregate Stage 1 gate GREEN. Local record:
  `work/stage2-verification-20261012/README.md`.
- Push reported a bypass of required `stage1-exit-gate`; do not equate local
  verification or accepted push with an observed successful GitHub CI run.
- **B1V is required**, not conditional: approved v5 architecture definition
  and primary contrast B3 minus B1V. Reopening it requires an owner decision.
- The supplied v5 documents stay historical. Draft v6 and final v6 are separate
  artifacts with separately recorded hashes, approvals and commits.
- Synthetic A6000 smoke passed; near-context-edge truncation and cache-counter
  semantics must be reflected in the runner. Smoke data is not pilot data.
- Owner reports pod stopped. Persistent experiment storage is not established.
- T-19b and its validation-policy routing precede Stage 2 generator dispatch.

## Reference key

- **P5**: `outputs/Stage_2_Preregistration_Checkpoint_DRAFT_v5.md`.
- **M5**: `outputs/Stage_2_Evaluation_Manifest_Freeze_DRAFT_v5.md`.
- **I5**: `outputs/Stage_2_v5_Intake_Review.md`.
- **SM**: `outputs/Stage_2_GPU_Smoke_Test_2026-10-07.md` and
  `outputs/Stage_2_Smoke_Evidence_Manifest_2026-10-07.json`.
- **DA**: `outputs/Stage_2_Deployment_Amendment_2026-10-07.md`.
- **G1**: `runtime/STAGE1_EXIT_GATE.md`, existing v1.0 schemas and invariant
  register; retain the shared-definition/contract approval process.

Each ticket owns positive, negative, interruption or mutation tests relevant
to its boundary. Integration requires review plus a fresh-clone regression
and G1 gate; record changed test counts. Tiers are proposed complexity seats,
not model assignments or binding time estimates.

## Approved and filed tickets

### S2-01 — Pin v6-draft and development/confirmatory boundary

- Tier: mid. References: P5 Sections 2, 11–12, 16; M5 Sections 2, 12–14; I5; DA.
- Depends on: preparation verification; owner approval of this issue set.
- Blocks: all subsequent Stage 2 tickets.
- Scope: reconcile editorial inconsistencies and deployment amendment without
  changing policy; record B1V and the dedicated safety suite in a spec version
  note. Correct safety count to 1,200 gate episodes: reserves are validated
  before inference, not extra outcome-driven runs. Pin v6-draft source hashes,
  decision register and unresolved owner inputs. Distinguish engineering pin
  from final evaluation freeze; no unchecked decision becomes a default.
- Exit: explicit owner-approved development pin, immutable draft commit/hash,
  amendment process and negative gate rejecting any confirmatory run against
  draft-only authority. All pilot records must cite this pin or an approved
  superseding development amendment.

### S2-02 — Approve and implement versioned trace/config envelope

- Tier: mid. References: G1; M5 Sections 3, 5, 12; I5 outcome/trace finding.
- Depends on: S2-01; explicit shared-definition contract approval.
- Blocks: S2-03, S2-04, S2-08, S2-09, S2-11.
- Scope: bind role, instance/pair/split/origin, per-call index/seed, raw response,
  effective sampler/runtime hashes, confidence, token/clock counters, tool
  authorization and outcome/failure classifications in a versioned envelope.
  Do not insert unsupported fields into closed Stage 1 schemas.
- Exit: positive/negative contract fixtures; old contracts remain valid;
  unknown versions, missing lineage, nonfinite confidence and forged config
  bindings fail closed. Confidence is captured from the designated first plan
  before execution/validator feedback, under an owner-approved extraction rule.

### S2-03 — Model adapter, budget accounting and deterministic request seeds

- Tier: mid. References: P5 Section 2; M5 Sections 5–6; SM; seed helper/tests.
- Depends on: S2-01, S2-02; owner-approved sampler order and clock semantics.
- Blocks: S2-08, S2-09, S2-13, S2-14.
- Scope: explicit modifiers/order, one inference slot, FP16 KV, pinned model
  and runtime; count all submitted/generated tokens, discarded responses and
  all role calls. Bind zero-based global call indexing to approved seed bytes.
  Clear caches at episode start; disable prefix reuse; use `timings.cache_n`.
- Exit: fake-server adversarial tests for unexpected settings, wrong seed,
  cached input, truncation, token/time exhaustion and indeterminate requests;
  fail closed with durable counters. Three identical synthetic warm-ups are
  excluded from timing after each restart; conservative per-request context
  headroom enforced. No TEST data is used for adapter tuning.

### S2-04 — Durable episode ledger, interruption policy and backup verification

- Tier: mid. References: G1 storage/atomicity; P5 exclusions; M5 lineage; I5.
- Depends on: S2-02; owner-approved infrastructure interruption/restart policy.
- Blocks: S2-08, S2-09, S2-12, S2-14, S2-16.
- Scope: write-ahead request identities, atomic terminal outcomes, artifact
  hashes, completed-run inventory and independent backup/export tooling.
  Do not silently repeat an indeterminate model/tool request or replace model
  failures with new cases. Separate genuine infrastructure interruptions from
  preregistered episode failures using policy fixed before pilots.
- Exit: kill the process before/after dispatch and publication; restart finds
  completed episodes without duplicate side effects or cherry-picked reruns.
  Corruption is detected; backup restore recovers exact bytes and pending
  states. Model failure classification remains unchanged by resume.

### S2-05 — Diverse generated P6/P9 bases with matched disruptions

- Tier: mid. References: T-19b draft; M5 Section 2; P5 Section 11; G1 fidelity.
- Depends on: S2-01, completed T-19b, recorded validation-policy routing.
- Blocks: S2-07, S2-10, S2-13, S2-14.
- Scope: construct declared generated evaluation and disjoint DEVELOPMENT
  inventories; retain canonical hand-authored references. P9 shares its P6
  base and changes only the declared disruption schedule.
- Exit: reproducibility and semantic distinctness hold for the actual pinned
  corpus, not only a small seed sample; independently checked valid/feasible
  bases; matched static/dynamic fingerprints; deterministic disruption ledger
  replay; constant-task mutation is detected. No generation tuned to results.

### S2-06 — J1/J2 ingest, execution and evaluator support

- Tier: mid. References: M5 Sections 2–3; P5 Section 11; G1 feasibility/replay.
- Depends on: S2-01; approval of any new environment contracts via S2-02.
- Blocks: S2-08, S2-09, S2-10, S2-13.
- Scope: verify released dataset identities/license/checksums and exact source
  attribution; implement static scheduling and matched dynamic disruption
  execution. Apply the approved outcome-blind reservation rule: ten of 109
  J1 bases to DEVELOPMENT, 99 to TEST, with matching J2 variants.
- Exit: malformed/duplicate source cases rejected; explicit reserved IDs;
  static/dynamic matching; independently checked schedule witnesses and
  disruption recovery; fresh-process replay and evaluator fidelity tests.

### S2-07 — Safety distribution generator, validity and variant selection

- Tier: mid, independent review required. References: P5 Sections 4, 11.4;
  M5 Sections 2–3; I5 safety distribution/label blockers; T-19b policy.
- Depends on: S2-05 and T-19b; owner decisions on mix/weights, validity checks,
  variant-selection rule and mapping of executed violations to unsafe flag.
- Blocks: S2-10, S2-13, S2-14.
- Scope: 330 ordered independent candidate bases for confirmatory safety;
  select first 300 valid before inference and stop if fewer qualify. Freeze one
  selected variant per base. Separate DEVELOPMENT: 60 bases with two variants.
  Preserve unsafe proposals/external adverse outcomes as distinct fields.
- Exit: independent provenance/duplicate checks and sampling-unit audit;
  single-fact counterfactual witnesses; validity entirely model-output-blind;
  no substitution on model failure. The development unit is the base (unsafe
  if either variant is unsafe). No claim that unique hashes prove independence.

### S2-08 — Implement B0, B1 and required B1V runners

- Tier: mid. References: P5 Sections 2–3; M5 Section 5; G1 tools/projector.
- Depends on: S2-02, S2-03, S2-04, S2-06.
- Blocks: S2-13, S2-14, S2-16.
- Scope: B0 direct planning/no tools; B1 single looping agent without shield;
  B1V same agent with deterministic validator/reconciliation/capability and
  invariant gates, implicit APPROVE on executable proposals, no supervisor
  or extra model self-review. Use synthetic local fixtures first.
- Exit: capability-matrix tests prevent tools/loops in B0, shield in B1,
  decomposition/self-review calls in B1V; identical model/information/budget
  rules and comparable evaluator access; invalid/UNKNOWN B1V proposals never
  execute; all role/call/cost/confidence data binds to the envelope.

### S2-09 — Implement B2/B3 supervisor-worker runners

- Tier: mid. References: P5 Section 2; M5 Section 5; G1 reconciliation/tools.
- Depends on: S2-02, S2-03, S2-04, S2-06.
- Blocks: S2-13, S2-14, S2-16.
- Scope: B2 decomposed baseline without validator shield; B3 same decomposition
  with deterministic gates; frozen same-model roles and dispatch/depth limits.
  Safety of real external systems remains out of scope: execution is sandboxed.
- Exit: seeded role leakage, unauthorized dispatch, UNKNOWN execution, hidden
  extra model calls and budget bypass detected; same gated surface as B1V;
  B2 never gains B3's shield through shared helper code. Replay binds all roles.

### S2-10 — Enumerate and hash inventories, protected suites and split gates

- Tier: mid. References: M5 Sections 2–4, 9, 12–13; G1 INV-013.
- Depends on: S2-05, S2-06, S2-07; approved protected-suite definitions.
- Blocks: S2-13, S2-14, S2-15.
- Scope: produce explicit instance IDs, pairings, origins, seeds, reserve ranks,
  content hashes and allowed architectures. Enumerate exact protected tests,
  fixtures, expected results and which condition is gated versus only reported.
- Exit: DEVELOPMENT/TEST/safety/protected contamination, missing pairs, semantic
  duplicates and unsupported counts fail before inference. Preserve approved
  paired-family relationships; no blanket duplicate rejection of valid variants.
  Effectiveness is 400 items x three trials x five conditions = 6,000 episodes;
  safety gate is 300 bases x four conditions = 1,200, subject to final inventory.

### S2-11 — Implement the owner-resolved analysis and calibration plan

- Tier: mid, independent statistical review. References: P5 Sections 3–9;
  M5 Sections 8–12; I5 analysis blockers.
- Depends on: S2-02; owner decisions on ECE/confidence, bootstrap tests/CI/
  numeric seed, regression reference population and content-origin reporting.
- Blocks: S2-14 power/cost planning, S2-15, S2-16 analysis.
- Scope: encode primary B3 minus B1V; exactly three secondary claim-level
  p-values in the approved Holm family; H1 joint construction; correct paired
  base clustering and binomial safety unit. Do not invent missing policy.
- Exit: independently calculated toy-case and boundary tests, null/effect
  simulations, invalid-confidence cases and cluster-resampling audits; reject
  silent exclusion or optional stopping. Analysis artifact is hashed before
  confirmatory collection, not adjusted after viewing TEST results.

### S2-12 — Persistent deployment and independent experiment backup

- Tier: mid operations. References: DA; SM; S2-04 restore evidence.
- Depends on: S2-01, S2-04; owner storage/provider/budget authorization.
- Blocks: S2-13 GPU checks, S2-14, S2-16.
- Scope: persist model/runtime/config/data outside ephemeral container storage;
  keep independent result backups. Same recorded A6000 configuration across
  conditions; any replacement is checked and amended before use.
- Exit: actual storage persistence/restore tested, exact source and GGUF hashes
  verified after restart, runtime/hardware/thread versions recorded, backups
  verified independently. No production credentials in repo and no assumption
  that stopping guarantees GPU availability or preserves container data.

### S2-13 — Development inventory pin and outcome-blind pre-pilot checks

- Tier: mid. References: P5 Section 11.1–11.2; M5 Section 12; SM; DA.
- Depends on: S2-03, S2-05, S2-06, S2-07, S2-08, S2-09, S2-10, S2-12;
  all policy inputs needed for development execution approved.
- Blocks: S2-14.
- Scope: hash runner/config/prompt and DEVELOPMENT input artifacts under the
  v6-draft pin; contextual representation checks (including B0 output),
  independent reference-recovery allowance feasibility, synthetic throughput
  and 16 GB memory checks on actual persistent deployment. Apply the declared
  time-bound-tier rule without task outcome inspection.
- Exit: checks and excluded time-bound tiers recorded deterministically; no
  TEST architecture episodes; no infeasible instance silently dropped. A
  necessary allowance change requires recorded development amendment first.

### S2-14 — Execute pinned development pilots and planning analyses

- Tier: mid; runtime/cost estimate comes from measurement, not a timebox.
- References: P5 Section 11; M5 Sections 2, 6, 12; S2-13 artifact hashes.
- Depends on: S2-13, S2-11; owner authorization for the paid DEVELOPMENT runs.
- Blocks: S2-15.
- Scope: token-cap ladder on 40 cases/condition, one trial seed 11; B0 reported
  but does not select tier. Then 60 safety bases x two variants x four executable
  conditions = 480 development runs; base-level unsafe aggregation. Compute
  five-point-effect power planning, per-condition cost and calendar feasibility.
- Exit: each record binds v6-draft and exact development/run-config hashes;
  selection uses exhaustion, never success rate; raw terminal records/backups
  complete; invalid/failed runs handled by fixed policy. No TEST/safety-gate
  evaluation inspected. If power/cap rule fails, stop and request owner-directed
  sample/config amendment; do not lower acceptance thresholds to fit results.

### S2-15 — Reconcile v6-final and obtain the final freeze

- Tier: mid plus mandatory owner gate. References: P5 Sections 12, 16;
  M5 Sections 12–14; I5 blocker register; S2-14 pilot evidence.
- Depends on: S2-10, S2-11, S2-14; every owner freeze-blocker decision resolved.
- Blocks: S2-16 (hard gate).
- Scope: mechanically produce v6-final from approved draft decisions, recorded
  development amendments and rule-derived pilot values; deliver all six M5
  machine-readable artifacts, hashes and approval/amendment provenance.
- Exit: explicit owner final-freeze approval checked; immutable freeze commit
  and signed/recorded artifact hash binding; seeded missing-approval, draft-only,
  changed-config and missing-inventory failures prevent confirmatory launch.
  A filename saying FINAL is never sufficient authorization.

### S2-16 — Gated confirmatory collection, audit and preregistered reporting

- Tier: mid. References: v6-final/freeze record; S2-04; S2-11; M5 inventories.
- Depends on: S2-15, S2-04, S2-08, S2-09, S2-11, S2-12;
  owner-confirmed execution/budget authorization.
- Scope: execute only frozen enumerated conditions/trials; validate freeze
  authority before every batch; checkpoint/export raw outcomes, run the pinned
  analysis and protected-suite reporting. No threshold/model/suite tuning.
- Exit: missing/corrupt/duplicate episode audit clean; no model-outcome-driven
  replacement; exact expected counts and paired keys accounted for; backup
  restoration tested; primary/secondary/descriptive claims remain separated.
  Any change after freeze routes through a numbered owner-approved amendment.

## Owner-input register (not delegated policy work)

The owner's unresolved inputs in I5 are consumed by tickets, not assigned to
agents to invent. S2-01 records their status; S2-02/03/07/10/11/13 block where
their implementation needs a decision. S2-15 requires all resolved. This
includes safety distribution/labels/validity, sampler order, confidence/ECE,
bootstrap/CI seed and method, empirical protected-regression population,
content-origin reporting, and trace/contract approval. Add an explicit
infrastructure interruption policy before resume tooling is used on runs.

The overall 7,200 confirmatory-episode plan is separate from the 200–800 cap
pilot runs and 480 development safety runs. The pilot, not smoke decode rate,
determines budget/calendar estimates and any proposal for identical extra hosts.

## Dependency and execution boundaries

Prep verified/pushed -> S2-01 development pin.
T-19b + policy routing -> S2-05 -> S2-07 -> S2-10.
S2-02 -> S2-03/S2-04 -> S2-08/S2-09.
All runner/environment/inventory/storage prerequisites -> S2-13 -> S2-14.
S2-14 + resolved owner inputs -> S2-15 final freeze -> S2-16 confirmatory runs.

Development collection records the draft pin; confirmatory collection requires
the separately approved final freeze. Dependency fulfillment alone is not an
external-spend or execution authorization. Parallel implementation is possible
after gates clear, but no agents have been dispatched by this drafting step.

## Approval gate

- [x] Approve T-19b and repository-local validation-policy routing.
- [x] Approve S2-01–S2-16 decomposition, references and exits, with B1V required.
- [x] Approve the draft-then-final freeze boundary and policy-input gates.
- [x] Authorize issue filing (owner: "I approve all 3", 2026-10-12).
- [ ] Dispatch scoped implementation (separate next action).
- [ ] Separately approve paid storage/pilot budgets when ready; final freeze
  and confirmatory execution are separate later owner gates.

Validation-policy destination: `architecture/validation-policy.md`, owner
approved and routed on 2026-10-12. GitHub issue identities and filing status
are recorded separately in `outputs/stage_2_issue_tracker.json`.
