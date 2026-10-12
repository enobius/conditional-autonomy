# Stage 2 v5 intake and implementation review

Date: 2026-10-05. Status: imported, reviewed, NOT FROZEN.

## Source and approval record

The two supplied v5 texts are saved without substantive edits as:

- `Stage_2_Preregistration_Checkpoint_DRAFT_v5.md`
- `Stage_2_Evaluation_Manifest_Freeze_DRAFT_v5.md`

The original unversioned drafts remain historical working files. The checked
P-01 through P-11 and M-01 through M-06 decisions are retained as recorded in
the supplied documents; the final freeze approval remains unchecked. No model
episode or pilot was executed during this intake.

## Completed prerequisite

The request-seed byte encoding is implemented in
`runtime/conditional_autonomy/stage2_seeds.py`. Its test suite verifies all
three supplied reference vectors, byte-length handling for a non-ASCII ID,
and rejection of invalid integer counters or instance IDs. The helper derives
only seeds; episode call indexing and trace recording remain runner work.

Command: `python -m unittest tests.test_stage2_seeds -v`.
Result: four tests passed.

Full regression command: `python -m unittest discover -s tests`.
Result: 215 tests passed. Saved v5 texts match their attachment contents after
line-ending normalization; diff hygiene passed.

## Editorial fixes for the next revision

1. The manifest's normative reference still points to preregistration **v4**;
   it should point to v5.
2. Both introductions say approval boxes remain unchecked although the policy
   decisions are checked. Clarify that the **final freeze approval** remains
   unchecked, while the policy approvals are recorded.
3. Historical v3/v4 notes and deployment-row labels still call now-approved
   settings PROPOSED or awaiting confirmation. Distinguish history from the
   effective v5 decision record.
4. The safety run-count table and preregistration Section 11.5 still say
   'up to 1,320 with the full reserve'. The approved rule selects exactly the
   first 300 valid bases *before inference*, so the gate has exactly 1,200
   episodes across four conditions. Invalid reserve candidates consume
   validation work, not model episodes. Additional robustness runs require
   their own stated count.

## Remaining specifications before freeze

These are additions to the four-item summary in preregistration Section 16;
they already follow from requirements elsewhere in the supplied texts.

| Item | Missing specification or evidence |
|---|---|
| Safety distribution | Exact template mix, sampling weights, counterfactual variant-selection rule and evaluator mapping |
| Safety labels | Explicitly bind the binomial unsafe flag to the intended executed hard-violation measurement; retain unsafe proposals and external adverse outcomes separately |
| Sampler order | Record the actual ordered sampler list, not only a requirement to send one |
| ECE | Deterministic tie handling and confidence extraction/invalid-value behavior |
| Bootstrap tests | Exact null-centering, finite-resample p-value construction, CI method and numeric analysis seed |
| Protected regression | Distinguish all-pass deterministic tests from empirical episode suites; the 2-point population regression bound needs an explicit reference population and adequate sample size |
| Content-origin reporting | Specify how the primary all-family macro endpoint coexists with the rule calling combined-origin summaries secondary |
| Outcome and trace contracts | Put confidence, runtime-config and counter data in a versioned envelope or approved schema extension; existing schemas reject extra fields |
| Freeze sequencing | Record a draft-artifact stage for pilot execution before the final freeze so pilot inputs are pinned without claiming a completed confirmatory freeze |

## Generator capacity finding

`generate_thanksgiving_instance()` currently constructs
`initial_thanksgiving_state()` and `thanksgiving_actions()` and computes graphs
from that fixed state. Seed and difficulty metadata do not produce new entity
or constraint graphs. It therefore does not establish 100 distinct generated
P6/P9 bases or 330 safety bases satisfying the v5 requirement for distinct
templates, entity graphs and seeds.

The existing counterfactual tooling validates single-fact verdict-changing
pairs. It is a useful building block, but a case-distribution generator and
independence checks are still needed. J1/J2 execution support and the five
baseline runners also need implementation before the pilots can run.

## GPU smoke-test dependency

Follow-up, 2026-10-07: the owner supplied SSH access and approved replacement
A6000 / Ubuntu 24.04 hardware. Synthetic deployment smoke checks passed,
subject to the recorded exact-context-edge caveat. See
`Stage_2_GPU_Smoke_Test_2026-10-07.md` and the deployment amendment. The
following paragraphs describe the original intake state, not the current
availability of the host. Final freeze, pilots and remaining runner work are
still outstanding.

The required target is the dedicated Ubuntu 22.04 Quadro RTX 6000 host from
M-06. This Windows workspace exposes SSH but did not expose `nvidia-smi` or
`llama-server` in PATH, and no target connection was supplied with the v5
documents. This intake does not establish the specified host's availability,
model compatibility, memory ceiling, sampler telemetry or cache behavior.

The next host-dependent step needs its SSH endpoint, user and existing access
method. Provisioning a paid host is a separate external action.

Smoke-test evidence must include pinned source weights and GGUF hashes,
conversion/quantization commands, actual runtime commit, driver/CUDA versions,
32,768-context peak memory, sampling configuration and zero prompt reuse.

## External identity checks

The pinned Granite revision resolves and reports `GraniteForCausalLM`,
3,402,836,480 BF16 parameters, Apache-2.0 and no access gate:

<https://huggingface.co/api/models/ibm-granite/granite-4.1-3b/revision/c0650403e44e78ec0262dab1c90914c65b196c4e>

The llama.cpp b11433 release page resolves and links commit 50569eb:

<https://github.com/ggml-org/llama.cpp/releases/tag/b11433>

These identity checks are not evidence of successful conversion or inference.
The full runtime commit must still be checked in the actual build checkout.
