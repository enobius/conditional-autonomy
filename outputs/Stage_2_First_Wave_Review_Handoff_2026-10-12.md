# First-wave review handoff: T-19b and S2-01

Date: 2026-10-12. Status: implementation candidates VERIFIED LOCALLY;
independent review/development-pin approval still pending. Neither issue closed.

## Repository and authorization

- Approved policy, issue plan, filing tracker and screenshots committed/pushed
  to `origin/main` as `14e99c1e1758cc615d925f3ebb7eb5c162bc55ed`.
- Implementation is on local branch `codex/t19b-s201`, final candidate
  `dd7edd9b48cd4d500b5ad82f057f85a4929dcc87` (commits `ff2b306`, `92baf4e`,
  `dd7edd9`). Not pushed or integrated into main.
- Only T-19b (#21) and S2-01 (#22) were dispatched, under the owner's "yes".
  GitHub now shows both open with `status:in-progress`; fifteen successors
  remain blocked. Historical Stage 1 20/20 completion is unchanged.
- Unrelated modified Stage 1 DOCX and other local work were preserved.

## T-19b candidate

- Version 2.0 varies a meaningful HARD side-preparation release window within
  a finite engineering domain. It does not select the eventual evaluation
  distribution or establish full Stage 2 template diversity/independence.
- Explicit generator 1.0 preserves historical bytes and canonical Table 6
  facts; the old-byte digest was measured in the pre-change verified clone.
- Independent serialized-content domain checker; semantic fingerprint ignores
  identity-only metadata, supplied graph hashes and graph-preserving renaming.
  Corpus admission rejects duplicate operative tasks; ambiguous role signatures
  fail closed. A zero-offset mirror is not a new canonical task.
- A runtime-only defect was caught in the new fact's observation encoding:
  required `epistemic_status`/`evidence_refs` were initially absent. Fixed in
  `dd7edd9`; the required paired grid now projects every variant through the
  existing observation contract, not only through state/manifest validation.
- Paired reproducibility/distinctness is included in the required Stage 1
  invariant-test category; the CI job also runs the constant-generator proof.
- Domain and limits: `architecture/generator-distinctness-domain-v2.md`.

## S2-01 candidate

v6-draft preregistration and manifest copies preserve v5 history while recording
B1V, the A6000 amendment, exact 1,200-episode safety count, corrected normative
reference and distinct development/final approval boundaries. The spec version
note records B1V and the dedicated safety suite without changing thresholds.

Artifacts to review:

- `outputs/Stage_2_Preregistration_Checkpoint_DRAFT_v6.md`
- `outputs/Stage_2_Evaluation_Manifest_Freeze_DRAFT_v6.md`
- `outputs/Stage_2_Development_Blockers_v6.json`
- `outputs/Stage_2_Spec_Version_Note_v6.md`
- Binding: `outputs/Stage_2_Development_Pin_v6.json`

Artifact-set hash:
`5723aedc74ea2b1a31ef08e80547acc0bc6bc067fe9c9f4822980ea1b69741cc`.

The pin's owner approval remains FALSE. Candidate-integrity verification passes;
development authority without exact pin approval is rejected. Draft authority
can NEVER authorize confirmatory collection. S2-15 owns the later final gate.
Approval of this engineering pin would not resolve the blocker register or
authorize paid storage/pilots; those retain their separate decision gates.

## Final fresh-clone evidence

Clean local clone: `work/first-wave-fresh-clone-dd7edd9`, exact final commit.
Python 3.11.5, CI-pinned validator dependencies installed in ignored `.vendor`.
Tracked working tree was clean before and after checks.

- Full regression: **229 tests passed**, 44.229 seconds, exit 0.
- Stage 1: all four categories PASS; **16/16 invariants VERIFIED**;
  **4/4 isolated fail-and-restore proofs PASS**; aggregate GREEN, exit 0.
- T-19b constant-generator proof: pristine PASS, seeded constant RED, restored
  PASS, exit 0.
- v6 candidate artifact integrity PASS in the fresh clone. Authority negative
  cases (draft-only confirmatory request, missing/unbound owner approval,
  changed bytes/inventory and unsafe paths) are included in the regression.
- Raw final logs: `work/first-wave-verification-dd7edd9/`. Earlier clone logs
  are retained separately; their results are not substituted for this commit.

## Next gates

1. Independent adversarial review of T-19b, its finite variation domain,
   checker/fingerprint and required-gate coverage. No independent review has
   been claimed or waived by this author's own checks.
2. Owner review/approval of the exact v6 DEVELOPMENT pin artifact set and commit
   (not final freeze), plus ordinary implementation review of S2-01's guard.
3. Integrate/close only after those gates, then recompute successor readiness.
   No successor was unlocked prematurely. No GPU spending, model pilot,
   confirmatory trace collection or final-freeze approval occurred.

This report and the status screenshot are local handoff outputs created after
verification, not part of the already verified candidate commits.

## Independent review and S2-01 repair (2026-10-12)

The owner supplied independent review of exact commit
`dd7edd9b48cd4d500b5ad82f057f85a4929dcc87`: T-19b PASS within its finite
engineering-domain scope; S2-01 FAIL because a syntactically valid commit SHA
was accepted without verifying its existence or artifact-byte binding.

The local, uncommitted repair reads actual Git objects with replacement refs
disabled. It requires the pin root to be the repository root, verifies that
the SHA names a commit, and compares every pinned regular-file blob's raw
length and SHA256 against the inventory. Shell interpolation is not used.
Missing Git objects, missing paths, non-commit objects and byte mismatches
fail closed. Approval may name a historical commit; matching current HEAD
is not required, but current artifact integrity remains required.

Synthetic tests now create real temporary Git commits rather than approving
`"a" * 40`. All six authority tests passed, including nonexistent commits,
blob/tree objects, existing commits with different or missing artifacts, and
the valid historical-commit case. Candidate integrity still passes; the real
pin remains unapproved. The earlier
fresh-clone evidence above covers dd7edd9 only, not this uncommitted repair.

Post-repair full working-checkout regression: **231 tests passed**, 68.285
seconds, exit 0. Tests ran outside the restricted Windows sandbox because
temporary Git initialization was denied there. This is not a new fresh-clone
or seeded-defect-campaign claim. No commits were pushed or tickets closed.

The owner subsequently supplied independent re-review: **S2-01 commit-binding
repair PASS**, with no remaining implementation finding. T-19b's PASS at
dd7edd9 stands. The reviewer did not rerun tests or change files. This PASS
covers the uncommitted repair, not integrated or fresh-clone verification.
Exact owner development-pin approval remains pending; neither ticket is
closed and no successor is unlocked.
