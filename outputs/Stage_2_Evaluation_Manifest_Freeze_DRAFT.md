# Stage 2 Evaluation Manifest Freeze

**Document status:** DRAFT - NOT FROZEN  
**Decision owner:** Thesis owner / principal investigator  
**Depends on:** Approved Stage 2 Preregistration Checkpoint  
**Applies to:** B0-B3 on P6, P9, J1, J2 and protected micro-suites  
**Draft date:** 2026-09-10  
**Episode execution state:** PROHIBITED until the final manifest inventory is hashed and frozen

## 1. Purpose of this freeze

This document fixes exactly which episodes, architecture configurations,
budgets, scoring artifacts, and protected suites constitute Stage 2. It is the
human-readable authority for the machine-readable evaluation manifest that
will enumerate every runnable item.

The freeze prevents four avoidable validity failures:

1. Selecting favorable instances after observing results.
2. Giving architectures materially different compute or context budgets.
3. Changing scoring, retry, timeout, or exclusion rules mid-comparison.
4. Allowing evaluation or protected-regression cases into training selection.

## 2. Proposed core benchmark inventory

| Family | Condition | Proposed inventory | Pairing unit | Scientific role |
|---|---|---:|---|---|
| P6 | Static Thanksgiving/event logistics | 100 generated evaluation instances plus the canonical hand-authored case | Template + entity graph + seed | Static planning and coordination |
| P9 | Matched P6 instances with declared disruptions | 100 generated disruption variants plus the canonical P9 case | Same P6 base; only disruption schedule differs | Replanning and recovery |
| J1 | Static job-shop scheduling | All 109 released instances | Dataset instance ID | Static constraint scheduling |
| J2 | J1 instances with dynamic disruptions | All 109 released matched variants | Same J1 base instance ID | Dynamic scheduling and recovery |

The final manifest must enumerate instance IDs; counts alone are not a freeze.

### 2.1 P6/P9 pairing rule

Each generated P9 item must bind to exactly one P6 base with identical:

- Generator ID and version.
- Base seed and difficulty parameters.
- Entity graph hash.
- Pre-disruption constraint graph hash.
- User-model version and private-state construction.
- Evaluator and feasibility-oracle versions.

The P9 member differs only through its declared disruption schedule and the
state transitions causally produced by that schedule. The disruption schedule
hash is mandatory. Unpaired or multiply paired variants are rejected.

### 2.2 Proposed P6/P9 seed policy

Before freeze, the machine-readable manifest will contain 100 explicit TEST
seeds derived deterministically from a fixed namespace:

```text
seed_i = uint64_be(first_8_bytes(SHA256(
    "stage2-core-p6p9-v1" || uint32_be(i)
))) & 0x7fffffffffffffff
for i in 0..99
```

The resulting signed-safe integer list is stored explicitly; runtime code does
not regenerate or substitute it. Split-hygiene validation must prove that no
constraint graph, entity graph, template/seed pair, or near-duplicate appears
in TRAIN, DEVELOPMENT, TRANSFER, or PROTECTED_REGRESSION.

### 2.3 J1/J2 selection rule

Use all 109 released J1 instances and their 109 matched J2 disruption variants.
Before freeze:

- Pin the upstream dataset revision or immutable content hash.
- Store the complete sorted instance-ID list.
- Verify one-to-one J1/J2 base-instance pairing.
- Record benchmark family (DMU, TA, ABZ, SWV, or YN), dimensions, and source
  metadata for stratified reporting.
- Preserve upstream licensing and provenance metadata.
- Reject any instance with a duplicate normalized job graph or missing
  disruption definition.

**Owner decision M-01:**

- [ ] Approve the proposed family inventory and pairing rules.
- [ ] Revise counts or selection rule before freeze: _______________________

## 3. Original, generated, and thesis-extension labels

Every evaluation item receives exactly one content-origin label:

| Label | Meaning |
|---|---|
| `ORIGINAL_BENCHMARK` | Unmodified released benchmark instance |
| `DETERMINISTIC_GENERATED` | Generated from a frozen thesis generator and explicit seed |
| `THESIS_EXTENSION` | Safety, clarification, revision, compensation, or other architecture-specific case |

Results are first reported separately by origin. A combined result may be
reported only as a declared secondary aggregation. The canonical P6/P9
micro-environment is a thesis-specific executable encoding grounded in the
benchmark specification and must not be represented as copied original
instance data.

## 4. Required instance record

Each manifest entry must include the existing schema fields:

```text
generator_id
generator_version
scenario_family
seed
difficulty_parameters
constraint_graph_hash
entity_graph_hash
disruption_schedule_hash
user_model_version
source_dataset_lineage
feasibility_oracle_version
split_assignment
```

The Stage 2 envelope adds:

```text
evaluation_instance_id
base_pair_id
content_origin
source_revision
source_content_hash
environment_version
schema_version
scorer_version
protected_suite_ids
allowed_architectures
expected_oracle_status
license_id
```

All hashes use the repository's canonical content-hash convention. Every core
evaluation item uses `split_assignment = TEST`; protected cases use
`PROTECTED_REGRESSION`. Neither assignment may be used for training or model
selection.

## 5. Frozen B0-B3 configurations

| ID | Included capabilities | Explicitly excluded |
|---|---|---|
| B0 | Prompt, frozen model, bounded output parser | Tools, loop, supervisor, workers, deterministic validator |
| B1 | Single model loop, frozen tool surface, bounded memory/state projection | Supervisor/worker decomposition and B3 validator shield |
| B2 | Supervisor, workers, B1 tool surface, shared typed contracts | B3 deterministic validator shield |
| B3 | B2 plus deterministic validator, reconciliation, capability and invariant gates | Training-time adaptation or post-Stage-2 adapters |

B0's lack of tools is the intended ablation. Equal-compute reporting must not
silently convert B0 into a tool-using condition.

### 5.1 Owner-supplied deployment fields

These fields cannot be responsibly inferred and must be completed before
freeze:

| Field | Frozen value |
|---|---|
| Primary student model ID and immutable revision/hash | **OWNER DECISION REQUIRED** |
| Quantization format and implementation | **OWNER DECISION REQUIRED** |
| Inference runtime and version | **OWNER DECISION REQUIRED** |
| Hardware class | **OWNER DECISION REQUIRED** |
| Context limit | **OWNER DECISION REQUIRED** |
| Per-episode input/output token budget | **OWNER DECISION REQUIRED** |
| Per-episode wall-time budget | **OWNER DECISION REQUIRED** |
| Temperature / sampling parameters | **OWNER DECISION REQUIRED** |
| Repeated inference trials per instance | **OWNER DECISION REQUIRED** |
| Supervisor/worker model sharing rule | Proposed: same frozen student model in all roles |
| Tool versions and capability-policy version | Populate from frozen Stage 1 registry |
| State, schema, environment, and reducer versions | Populate from frozen Stage 1 registry |

**Owner decision M-02:**

- [ ] Approve the architecture definitions and same-model role rule.
- [ ] Complete the deployment fields above.

## 6. Pairing, order, and randomization

1. Every included instance is assigned to every allowed B0-B3 architecture.
2. The same instance, private user state, evaluator state, and inference seed
   are used for paired architecture comparisons wherever the condition permits.
3. Architecture execution order is deterministically randomized within each
   base instance using a frozen scheduling seed.
4. Repeated trials remain grouped beneath the base instance for confidence
   intervals and effective-sample calculations.
5. P6/P9 and J1/J2 pairs remain linked during sampling and family-stratified
   analysis.
6. Failures do not change the run order, remaining seed list, or retry budget.

Proposed analysis seed namespace: `stage2-analysis-v1`.  
Proposed scheduling seed namespace: `stage2-run-order-v1`.

**Owner decision M-03:**

- [ ] Approve the pairing and deterministic randomization policy.
- [ ] Revise before freeze: ________________________________________________

## 7. Budget parity

The final manifest records both equal-resource and architecture-native views:

- **Equal-token comparison:** identical total model input/output token budget
  per episode across B0-B3.
- **Equal-wall-time comparison:** identical episode wall-time ceiling.
- **Architecture-native efficiency:** actual tokens, latency, calls, and cost
  consumed under the frozen condition.

Supervisor and worker calls count against B2/B3's shared episode budget. Retry,
repair, clarification, and compensation calls also count. Tool calls are
reported separately but their model-generated arguments and observations count
toward the context/token budget.

If an architecture exhausts a budget, the episode terminates with the declared
budget-exhaustion status and counts as unsuccessful. Budgets are not increased
after seeing which condition exhausts them.

**Owner decision M-04:**

- [ ] Approve both equal-token and equal-wall-time comparisons.
- [ ] Approve another parity rule before freeze: ___________________________

## 8. Frozen scoring contract

The episode scorer emits the complete existing outcome vector:

- `goal_success`
- `constraint_score`
- `hard_violation_count`
- `optimality_gap`
- `recovery_success`
- `execution_cost`
- `latency`
- `token_count`
- `tool_calls`
- `user_interventions`
- All six clarification counters
- `evaluator_disagreement`

### 8.1 Family-specific scoring

| Family | Goal-success basis | Mandatory secondary outcomes |
|---|---|---|
| P6 | Required obligations completed under the environment's executable semantics | Constraint score, completion time, tool/user overhead |
| P9 | Required obligations completed after disruption | Recovery success, latency, preserved-plan fraction, hard violations |
| J1 | Complete valid schedule emitted | Makespan, oracle/upper-bound gap, constraint score |
| J2 | Complete valid reschedule after disruption | Recovery success, revised makespan, stability, hard violations |

The feasibility oracle or deterministic evaluator determines validity; model
self-report never establishes success. Evaluator artifacts must be isolated
from candidate modification.

### 8.2 Terminal failure mapping

| Condition | `goal_success` | Included in denominator? |
|---|---:|---:|
| Timeout | `false` | Yes |
| Malformed or schema-invalid output | `false` | Yes |
| Budget exhaustion | `false` | Yes |
| Tool error not recovered within budget | `false` | Yes |
| Hard violation with apparent goal completion | Recorded independently; safety fails | Yes |
| Pre-inference harness failure affecting all conditions | No score; pairwise technical exclusion | Reported separately |

**Owner decision M-05:**

- [ ] Approve the scoring and terminal-failure mapping.
- [ ] Revise before freeze: ________________________________________________

## 9. Protected-regression inventory

The machine-readable manifest must enumerate, not merely name, every protected
test and fixture. At minimum it includes the exact tests currently bound by the
Stage 1 exit gate:

### Deterministic replay

- `tests.test_reducer.DeterministicReducerTests.test_replay_is_byte_identical_and_does_not_mutate_inputs`
- `tests.test_reducer.DeterministicReducerTests.test_fresh_process_replay_produces_identical_bytes`
- `tests.test_replay_cli.ReplayCliTests.test_golden_episode_replays_identically_in_fresh_process`
- `tests.test_disruptions.ThanksgivingDisruptionTests.test_exact_p9_delay_is_one_mid_episode_ledger_transition`
- `tests.test_disruptions.ThanksgivingDisruptionTests.test_all_state_changes_replay_from_ledger_byte_identically`
- `tests.test_disruptions.ThanksgivingDisruptionTests.test_disrupted_episode_is_identical_across_fresh_processes`

### Leakage

- `tests.test_projection.ObservationProjectorTests.test_protected_root_canaries_fail_closed`
- `tests.test_projection.ObservationProjectorTests.test_nested_protected_canary_in_value_fails_closed`
- `tests.test_projection.ObservationProjectorTests.test_each_named_protected_ancestor_fails_closed`
- `tests.test_oracle.OracleUserSimulatorTests.test_private_simulator_state_is_absent_from_policy_inputs`
- `tests.test_oracle.OracleUserSimulatorTests.test_injected_private_state_is_detected_by_policy_leakage_validator`

### HARD + UNKNOWN

- `tests.test_preexecution.ReconciliationTests.test_hard_unknown_can_never_execute`
- `tests.test_tools.ToolSurfaceTests.test_deny_query_repair_unknown_missing_grant_and_stale_never_dispatch`
- `tests.test_tools.ToolSurfaceTests.test_incomplete_verification_is_indeterminate_and_cannot_advance`

### Invariant binding and split hygiene

- `tests.test_invariant_register.InvariantRegisterTests.test_live_named_test_evidence_verifies_all_sixteen`
- `tests.test_split_hygiene.GenerationSplitHygieneTests.test_each_prohibited_cross_split_overlap_uses_canonical_inv_013`

The freeze also records hashes for the invariant corpus, schema package,
negative fixtures, mutation registry, and all added Stage 2 protected cases.

## 10. Trace-completeness gate

Every scored episode must validate against the episode and trace-step contracts
and include:

- Stable episode, environment, schema, generator-manifest, and user-model IDs.
- Exact policy versions for all participating roles.
- At least one typed trace step.
- Final outcome vector.
- Split assignment.
- Event-log content hash.
- Terminal status.
- Actor-visible observations without EVALUATOR_ONLY or PRIVATE_ENVIRONMENT
  leakage.
- Proposal, decision, validator, tool, transition, and provenance evidence when
  applicable to the condition.

An architecture cannot receive a valid score from an incomplete or
non-replayable trace. Trace-completeness failures are reported as harness
failures and block the Stage 2 exit criterion until resolved and rerun across
all affected paired conditions.

## 11. Exclusion, retry, and rerun policy

1. No model-behavior failure is excluded.
2. A technical exclusion must originate before inference or be proven external
   to the architecture under test.
3. A technical exclusion removes the full paired B0-B3 unit and is logged with
   an evidence artifact.
4. An infrastructure rerun reuses byte-identical inputs, versions, seeds, and
   budgets; the original failed attempt remains in the audit log.
5. No evaluator correction is applied only to one architecture. Scorer changes
   require a manifest version bump and rerun of every affected condition.
6. The final report includes all exclusions, reruns, and deviations.

## 12. Machine-readable deliverables required before freeze

| Artifact | Required contents |
|---|---|
| `stage2-evaluation-manifest.json` | Every instance, architecture allowance, pairing key, seed, version, hash, split, and origin |
| `stage2-run-config.json` | Model, quantization, runtime, prompts, budgets, decoding, tool and validator versions |
| `stage2-protected-suites.json` | Exact test/fixture IDs, hashes, expected results, and gate grouping |
| `stage2-analysis-plan.json` | Endpoints, contrasts, thresholds, resampling seed, CI method, multiplicity, exclusions |
| `stage2-freeze-record.json` | Artifact hashes, freeze commit, owner approval, timestamp, and amendment pointer |

These artifacts are generated only after M-01 through M-05 and the
preregistration decisions are approved. Generation is mechanical; policy
substitution is prohibited.

## 13. Pre-freeze validation checklist

- [ ] M-01 through M-05 are resolved.
- [ ] All owner-supplied deployment fields are complete.
- [ ] P6/P9 seed list is explicit and split-hygiene checks pass.
- [ ] J1/J2 revision, hashes, IDs, and one-to-one pairing are verified.
- [ ] Original/generated/extension labels are complete.
- [ ] Every instance validates against the instance-manifest contract.
- [ ] Every run configuration has immutable artifact versions.
- [ ] B0-B3 budget parity is machine checked.
- [ ] Protected suites enumerate exact IDs and hashes.
- [ ] Scoring, terminal mapping, exclusion, retry, and rerun rules are encoded.
- [ ] Dry-run validation uses synthetic smoke fixtures only, permanently
      excluded from evaluation.
- [ ] No core evaluation outcome has been inspected.
- [ ] All freeze artifacts are committed and SHA-256 hashed.

## 14. Owner approval block

**Decision:** [ ] APPROVED AND FROZEN  [ ] REVISE  [ ] REJECT  
**Approved by:** ______________________________  
**Approval date:** ____________________________  
**Freeze commit:** ____________________________  
**Manifest SHA-256:** _________________________  
**Related preregistration SHA-256:** __________  
**Notes:** _________________________________________________________________

## 15. Normative references

- `outputs/Stage_2_Preregistration_Checkpoint_DRAFT.md`
- `outputs/Thesis_Architecture_Formalization_v1.1.2.docx`
- `architecture/schemas/v1.0/instance-manifest.schema.json`
- `architecture/schemas/v1.0/episode.schema.json`
- `architecture/schemas/v1.0/outcome-vector.schema.json`
- `runtime/conditional_autonomy/stage1_exit.py`
- REALM-Bench repository: <https://github.com/genglongling/REALM-Bench>
- REALM-Bench JSSP dataset: <https://huggingface.co/datasets/GloriaGeng/REALM-Bench>
