# Stage 2 GPU smoke test

Status: PASS for synthetic deployment smoke checks, with an exact-context-edge
caveat recorded below. Synthetic inputs only; no confirmatory trace collection.

## Pinned setup

- Owner-approved replacement pod: `3ia08l23zggb19`, NVIDIA RTX A6000.
- Deployment amendment: `Stage_2_Deployment_Amendment_2026-10-07.md`.
- llama.cpp tag `b11433`, verified commit
  `50569eb87df530daff11afda229ceb9ab8e6cae8`.
- Source model: `ibm-granite/granite-4.1-3b`, revision
  `c0650403e44e78ec0262dab1c90914c65b196c4e`.
- Source weights downloaded at that revision. Conversion uses the same pinned
  llama.cpp checkout; target is Q8_0 with FP16 KV and 32,768 context.
- Build: CUDA enabled, compute architecture 86, Release, eight build jobs;
  targets `llama-server` and `llama-quantize`.
- Conversion dependencies isolated in a dedicated virtual environment.
  A pod-wide fast-download environment flag required disabling because its
  optional helper was absent; the ordinary pinned download succeeded.

## Probe protocol

`tools/stage2_smoke_probe.py` is the reusable synthetic-only probe.

Three identical 8,192-input / 256-output requests warm the resident model;
their timings are excluded from performance results. A 32,511-input /
256-output request stresses the configured 32,768 context with one token of
headroom. A separate exact-boundary 32,512-input / 256-output test is retained
as diagnostic evidence. A consecutive identical
request without erasing the slot checks that `cache_prompt=false` itself
prevents cross-request reuse. Slot erasure is also tested explicitly.

Synthetic length tests force `ignore_eos=true` to obtain exactly 256 output
tokens. This is not a proposed experimental decoding setting. A separate
short functional request uses normal EOS behavior and the model chat template.

Smoke sampler order is explicitly `top_p`, then `temperature`. It is a
smoke-test choice, not a frozen policy decision. Temperature 0.2, top_p 0.95,
top_k 0, min_p 0, repeat penalty 1, and other optional modifiers disabled;
each response's effective settings are checked. Seed 11 is a synthetic probe
seed, not an evaluation episode seed.

GPU memory is sampled every 200 ms from before model load through probing.
The ceiling is checked
against 16,000,000,000 bytes, conservatively distinguishing decimal GB from
GiB. Source and GGUF SHA-256 hashes are saved with raw responses.

## Results

| Check | Measured result |
|---|---|
| Load and normal chat-template generation | PASS; normal EOS response to synthetic arithmetic prompt was `4` |
| Three identical warm-ups | PASS; each 8,192 input / 256 output, zero reused input, no truncation |
| Near-full context | PASS; 32,511 input / 256 output, no truncation |
| Consecutive identical request without slot erasure | PASS; full prompt processed again, `timings.cache_n=0`; output token arrays identical |
| Explicit cache clearing | PASS; slot erase endpoint succeeded, including after warm-ups and final functional request |
| Effective samplers | PASS; server reported `top_p`, `temperature` in order and checked numeric settings |
| GPU peak, including load and stress | 6,430 MiB = 6,742,343,680 bytes, about 6.28 GiB; below 16 decimal GB |
| Server host RSS snapshot | 757,420 KiB, about 740 MiB; separate from GPU usage, not a sampled host-memory peak |
| Runtime identity | Binary and checkout verified against b11433 commit |

Non-warm-up synthetic timings:

| Request | Prefill tokens/s | Decode tokens/s | Prefill seconds | Decode seconds |
|---|---:|---:|---:|---:|
| Near-full context | 4,163.26 | 81.95 | 7.809 | 3.112 |
| Identical cache-isolation repeat | 4,110.67 | 81.84 | 7.909 | 3.116 |

These two synthetic requests are not a performance distribution, a token-cap
selection pilot, an architecture comparison, or evidence of task accuracy.

## Runtime caveats found and resolved in the probe

1. The slot erase endpoint requires `--slot-save-path`, not just `--slots`.
   A dedicated directory enabled the endpoint; no slot snapshots were saved.
2. In this pinned implementation, `tokens_cached` is the retained KV size
   after generation. `timings.cache_n` is the reused-input count. The source
   assigns `n_tokens_cached = slot.prompt.n_tokens()` in `server-context.cpp`.
   The initial probe's counter assertion was corrected; failed attempts are
   retained, not presented as successful runs.
3. At the exact boundary, 32,512 input plus 256 output produced all requested
   tokens but returned `truncated=true`. With one token of headroom the flag
   was false. Context shifting was disabled throughout. The experimental
   runner must budget conservatively and reject any flagged/truncated result;
   this smoke test does not certify unrestricted exact-boundary requests.

## Artifacts and reproducibility

- Q8_0 GGUF: 3,619,691,008 bytes.
- Q8_0 SHA-256:
  `a99e246b0a3d429d632cd869a039471b8ec3563875a91c67b7af759e39b583ea`.
- Full source-shard and intermediate hashes: local evidence
  `Stage_2_Smoke_Evidence_2026-10-07/evidence/artifact_hashes.json`.
- Raw responses, effective settings, memory samples, build/conversion/
  quantization logs, failed attempts, exact-boundary response and runtime argv
  are preserved in `Stage_2_Smoke_Evidence_2026-10-07/` and the matching ZIP.
- Evidence ZIP SHA-256:
  `fcc28fa684bb3a83643b300fecf790739cb33f2600f2328669ce38d6b7428ac7`.
  Local download hash matched the remote archive hash.
- Server: GPU layers 99, Flash Attention on, FP16 K/V, eight inference and
  batch threads, batch 2,048, microbatch 512, one slot, RAM prompt cache off,
  context shifting off, localhost-only port 18080. Full argv is in provenance.
- Conversion: `convert_hf_to_gguf.py model --outtype f16 --outfile
  granite-4.1-3b-f16.gguf`; quantization: `llama-quantize` with `Q8_0`.

The test server and memory monitor were stopped after evidence collection;
GPU usage returned to 1 MiB. The pod itself was not stopped or terminated and
can still incur charges. Source weights, compiled runtime and GGUF files
remain in `/workspace/conditional-autonomy-smoke` (about 11 GB free on the
30 GB overlay after setup).

Overall Stage 2 freeze is still pending. This supplies deployment evidence,
not approval for confirmatory runs or selection of token caps/sampler order.
