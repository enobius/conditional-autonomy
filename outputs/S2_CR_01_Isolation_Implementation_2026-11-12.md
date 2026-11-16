# Isolation implementation progress — 2026-11-12

The workflow remains disabled and all work is local/uncommitted. No settings,
secrets, provider calls, or required checks were changed.

Final local verification: 275/275 unit tests passed in 124.245 seconds; schema
gate green; Stage 1 exit gate green with 16/16 invariants and 4/4 seeded-defect
proofs. `git diff --check` passed apart from line-ending warnings. No remote CI
or independent approval is claimed for the new edits.

## Implemented locally

- Tightened `require_rejection`: a tool-name prefix no longer suffices, every
  returned tool result must be an error, and extra/missing advertised tools are
  tested independently. New tests exercise mixed success and rejection results.
- All 13 tool cases passed a new network-none, read-only, non-root Docker run
  with dummy provider authentication. The exact stdout JSON lines were retained
  at `S2_CR_01_Tool_Matrix_Raw_2026-11-12.jsonl` (SHA256
  `dba8a9396ae4d23313861d2f5bf373cafbbc2893b03d2633ff8ea33e33dd914b`).
  The checker hash was
  `06cfee19090edbde459a8567d9f3d52d4ba1ef1a823671c32861834c5e1bea55`;
  the unchanged probe hash was
  `3e2e5fec4d59b7d1c901c3b8927d7d626d306b8d537d142f987dbce5042278d8`.
  The run used the previously pinned Python image and CLI, a 300-second outer
  timeout, no network except loopback, no credentials except a dummy token,
  readonly code/CLI mounts, no-new-privileges, dropped capabilities and user
  65534. This remains representative coverage, not exhaustive isolation proof.
- Implemented a local artifact-binding prototype. It enforces an exact bounded
  file inventory, rejects non-regular/hardlinked entries, hashes canonical
  manifest bytes, binds repository/run/attempt/trusted-revision/PR and snapshot,
  and compares the digest against a caller-supplied trusted fetch output.
  Validation also requires independently re-fetched PR metadata and diff.
  Tests cover context substitution, provider resealing, changed bytes, wrong
  re-fetch, extra/missing files, noncanonical/duplicate JSON, bounds, directories
  and hardlinks. It is not wired into Actions or a trusted publisher.
  Implementation SHA256:
  `3a5ec383ef18e167f5945dfc2445883bfee62fbde78a01baf360ce2040fe454d`;
  test SHA256:
  `515bb9c876cb3762a11fcd96c3ed572e9d2c7ca7d871e5350fd6cdfd1d8a3764`.
- Removed pip-cache setup/restoration from `runtime-invariant-gate.yml` and
  `stage1-exit-gate.yml`, and set installs to `--no-cache-dir`. Added a policy
  regression test. This avoids relying on a shared pip cache; it is not proof
  that all cache or artifact capabilities are contained.

## Still required

After the live synthetic rerun, a further name-boundary refinement rejects
`Task.Output` as well as `TaskOutput` when testing `Task`. Current checker
SHA256 is `0e63dee5737d8496366ad0d9098dd54a64e388f49e73dcb769f10e7779589466`.
The 13 saved raw records were replayed successfully through this refined
checker; no new live CLI rerun is claimed for the refinement. Destination-file
absence was asserted during the original run and is not encoded in its raw
stdout records. The new unit case independently exercises that refinement.

The three-job workflow, trusted fetch-job output wiring and artifact ID checks,
mandatory CLI container, hostname-allowlisting proxy, host/metadata blocking,
tmpfs secret delivery/cleanup, container timeout/resource controls, real
dummy-token artifact/cache adversarial tests and trusted publisher are not
implemented yet. No existing job has acquired these protections just because
the helper functions exist. File checks presume the validator's private trusted
job directory; they are not a same-user filesystem race boundary.

The latest A–E review conditions are incorporated into the job-isolation draft.
The protected environment, enforcement/exception process and first live call
remain separate owner decisions after implementation and independent review.
