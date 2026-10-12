# Stage 2 spec version note — v6 development candidate

S2-01, 2026-10-12. Owner-approved v5 architecture decisions add B1V and the
dedicated safety suite to the original v1.1.2 B0–B3 Stage 2 core. B1V is the
validated single-agent control, not B4 (which remains a training-stage label).
Primary contrast: B3 minus B1V. Effectiveness uses all five conditions; safety
uses B1, B1V, B2 and B3. Model, thresholds and scientific endpoints are not
changed by this note.

The 2026-10-07 replacement deployment amendment is operative: A6000/Ubuntu
24.04, unchanged 16 GB workload ceiling. Confirmatory gate count is 1,200
(300 valid bases selected before inference, four conditions), not 1,320.

v6-draft is pinned for owner review and development engineering; its exact
artifact set has NOT yet received development-pin approval. v6-final requires
pilot evidence, resolved owner inputs and a separate explicit final-freeze
approval and commit. No confirmatory runs, paid provisioning or policy choice
are authorized by this note. Historical v5 artifacts are preserved.
