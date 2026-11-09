# S2-CR-01 shadow workflow: enablement follow-up (draft)

PR #39 merged as `d3ced84c263cef926ef39904bcec52fd170deb22` after the
independent prose review of `b3f5cca` passed the disabled workflow subject to
the owner's reported secret removal. The review disposition was recorded in
the PR discussion. Remote schema, Stage 1 and runtime gates passed on the
merged commit. Neither the review nor the merge authorizes enabling the job.

This follow-up keeps the job unconditionally disabled and adds the main-ref
condition as a separate conjunct. It extends the runtime gate's path filters,
moves PyYAML to test-only requirements, strengthens workflow drift and mutation
tests, and checks compare base, patch hunks and file counts. These changes are
candidate code and require independent review; drift hashes are not a trust
boundary if a PR changes its own tests.

Still required before enabling: verify the protected GitHub environment's
main-only deployment restrictions and credential scope; independently verify
secret removal and consider revocation; test the pinned Claude CLI 2.1.319
against a local stub for `--tools=` and the minimum viable turn limit; settle
the full step-level security policy and test its enforcement; and separately
authorize any live provider call. The CLI currently has `--max-turns 1`; an
older CLI reportedly needed at least 3, which does not establish pinned CLI
behavior. No CLI or provider call is performed in this change.

Reviewer identity/provenance, durable retry and replay controls, authenticated
check publication, seeded-defect calibration, and owner approval before making
any review check required are also outstanding. This is not authorization for
Stage 2 pilots, spending, confirmatory collection, or enabling the workflow.
