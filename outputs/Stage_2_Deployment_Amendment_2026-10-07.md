# Stage 2 deployment amendment: replacement RunPod host

Status: owner approved in chat on 2026-10-07; overall Stage 2 freeze remains pending.

The owner approved use of RunPod pod `3ia08l23zggb19` after being informed of
its hardware and OS differences from draft v5.

- GPU: NVIDIA RTX A6000, Ampere generation, 48 GB nominal (49,140 MiB reported).
- Container OS: Ubuntu 24.04.3 LTS.
- Storage: 30 GB overlay observed, accepted for setup subject to available-space checks.
- Container CPU quota: 13.6 CPU equivalents (`cpu.max`: 1360000 / 100000).
- Container RAM limit: 61,999,996,928 bytes (about 57.74 GiB), from `memory.max`.
  Host-visible CPU counts and RAM are not the container allocation.
- Workload memory ceiling: remains 16 GB.
- Runtime/model: retain llama.cpp b11433 and Granite 4.1-3B revisions from v5,
  Q8_0 weights, FP16 KV, 32,768 context and one request at a time.
- Throughput and cap-selection pilot: must run on the replacement hardware.
  Measurements from it do not establish performance on the original Turing GPU.
- Confirmatory comparisons: use the same recorded hardware configuration
  across baseline conditions; any future deployment change must be recorded.

This amendment supersedes the Quadro RTX 6000 / Ubuntu 22.04 deployment values
in the saved v5 drafts. It does not approve final evaluation, choose token caps,
or establish smoke-test success. CPU and RAM allocation above were measured
on the actual container; execution thread counts will be recorded separately.
