# Stage 2 RunPod host preflight

User-facing date: 2026-10-07, America/New_York.
Host: RunPod pod `3ia08l23zggb19`.
Status at initial inspection: SSH verified; deployment decision pending.
Follow-up: owner approved the replacement hardware, and synthetic smoke
testing completed. See `Stage_2_Deployment_Amendment_2026-10-07.md` and
`Stage_2_GPU_Smoke_Test_2026-10-07.md` for effective setup and results.

RunPod's SSH gateway requires an interactive PTY (`ssh -tt`). A connection
without a PTY returned an error. Authentication succeeded using the existing
local Ed25519 key; no key content was copied or recorded.

| Property | Supplied v5 requirement | Observed on replacement pod |
|---|---|---|
| GPU | Quadro RTX 6000, original Turing generation, 24 GB | NVIDIA RTX A6000, 49,140 MiB, compute capability 8.6 |
| Container OS | Ubuntu 22.04 | Ubuntu 24.04.3 LTS |
| Disk | 100 GB SSD | 30 GB overlay shown for both `/` and `/workspace` |
| CPU / RAM | 8 vCPU / 32 GB | `nproc` reports 128; host-visible memory reports 503 GiB; container allocation not established |
| Driver | Record at provisioning | 595.91.07 |
| CUDA toolkit | Record at provisioning | 12.8, V12.8.93 |
| Python | Record at provisioning | 3.12.3 |
| CMake | Record at provisioning | 3.28.3 |

`nvidia-smi` showed no running GPU processes and about 1 MiB used initially.
The driver reports CUDA compatibility 13.2, which is distinct from the installed
12.8 CUDA compiler toolkit.

At this initial inspection, no model weights were downloaded, runtime built,
or model episodes executed. The SSH session was closed after read-only
inspection. Subsequent authorized setup and synthetic requests are recorded
separately in the smoke-test report.

The replacement GPU is a different generation and memory class from the
approved v5 target. Timing results from it cannot establish the original host's
token-cap feasibility. Either record an owner-approved deployment amendment
before the pilots, or use a pod matching the specified target. The 16 GB
workload memory ceiling remains independent of the GPU's installed memory.
