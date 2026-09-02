# Stage 1 exit gate

Run the required keystone check from the repository root:

```console
python -m runtime.conditional_autonomy.stage1_exit --verify-seeded-defects
```

The single runner reports the four authoritative v1.1.2 exit categories:
deterministic replay, leakage prevention, HARD+UNKNOWN handling, and invariant
tests. It also separately requires the computed invariant register to report
16/16 VERIFIED.

The seeded-defect campaign copies `runtime`, `tests`, and `architecture` into
isolated temporary checkouts. For each of Workstreams 1B, 1C, 1D, and 1E it
changes one production source file or workstream-owned evidence artifact, runs
the exact aggregate gate command and requires the intended exit category to
fail, restores the original bytes, and reruns the exact command green. It
neither edits the working checkout nor invokes Git. `stage1-exit-gate` runs
this command after a clean GitHub checkout.

The four defects alter the 1B reducer version transition, a 1C canonical
corpus-to-validator binding, the 1D P9 arrival transition, and the 1E
generation split-hygiene enforcement boundary. The campaign requires both the
owned exit category and a mutation-specific failed-test or runtime-error signal.
The 1D mutation remains structurally valid but changes the approved 16:00 local
P9 arrival to 17:00; the exact environment-fidelity test must catch that fact.
