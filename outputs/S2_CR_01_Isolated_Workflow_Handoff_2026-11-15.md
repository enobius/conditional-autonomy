# Independent review: wired isolated workflow candidate

Superseding November 16 repair: begin with
`S2_CR_01_Review_Repairs_2026-11-16.md` and the corresponding 33-file repair
hash snapshot. The earlier 30-file hashes and descriptions below are historical:
provider ZIP handling, credential placement, policy tests and legacy-workflow
retirement have changed and require a new independent review.

Status: uncommitted, all jobs hard-disabled, provider policy disabled with a
null origin. No real provider, GitHub workflow run, secret installation,
repository setting change, push or merge occurred. This is implementation for
review, not an enablement request or authenticated reviewer verdict.

Review exact bytes in `S2_CR_01_Isolated_Candidate_Hashes_2026-11-15.json`
(30 files, base `80eb0c990bd07bf58de9f442be066b4360ec0baa`). Earlier hashes and
review verdicts do not cover this major delta. Also inspect transitive runtime
validators, trusted prompt and dependency locks from the existing base. Files
outside the manifest include unrelated user edits and historical evidence;
do not change them. Do not run a real provider or enable either workflow.

## Implemented wiring

The new `.github/workflows/claude-review-isolated.yml` has fetch, provider and
validate jobs, each hard-disabled and pinned to `ubuntu-24.04`. The older
single-job shadow workflow remains hard-disabled for transition/audit and is
not a bypass or fallback to enable. The new provider job is the only job that
references the provider environment/credential, and has contents-read only.
Fetch and validate have read-only repository/PR access and no provider secret.

Fetch acquires bounded PR data through trusted code and writes the prompt to a
file, not an environment string/log. It seals an exact prompt/diff/snapshot
inventory with a canonical manifest. The manifest hash and upload artifact ID
are passed through the fetch job's outputs. Provider and validate download that
specific fetch ID; IDs must be single positive integers before download, so a
missing ID cannot silently request every artifact. The pinned upload action
exposes ID/digest outputs and the pinned download action supports `artifact-ids`.
The download action has no digest input, so the code independently verifies the
fetch-output-bound manifest and every payload hash. No name/listing fallback.

Provider verifies the original input again, checks a separately disabled
trusted policy, installs the pinned CLI/image before the credential-bearing
step, and invokes the mandatory container path. The policy must be explicitly
changed under review/owner approval before a real origin can be reached.
The CLI child gets a fixed internal base URL, `http://shadow-egress:8080`, only
through an explicit Boolean transport selector; arbitrary URLs are rejected.

The host orchestrator creates a private internal bridge in isolated gateway
mode with IPv6 disabled, verifies its configuration, and starts a restricted
proxy with two network interfaces. The proxy listens only at its internal alias,
not its outward-facing interface. The CLI is attached only to the internal
bridge, has no host/Git/Docker/runner mounts, and uses the same non-root,
read-only, capability/resource and cleanup controls as the no-egress prototype.
Only the proxy has an outward route; its fixed-origin API adapter performs
checked-IP TLS connections, path/header filtering, bounds and redirect denial.

Provider output is an explicitly untrusted single result file. A fresh validate
job downloads the original fetch artifact directly from fetch outputs, obtains
the provider result separately, and independently re-fetches current PR data.
It checks original run/revision/PR bindings, hashes, snapshot and diff freshness,
then the existing full verdict and location checks. Only an advisory
`shadow-unverified` result is uploaded. No merge-authorizing check is published.

## Local evidence

- Final regression 298/298 in 76.268 seconds; schema gate green; Stage 1 exit
  gate green with 16/16 invariants and 4/4 isolated seeded-defect proofs.
- Job-helper tests cover data-only prompt creation, valid fetch/result handoff,
  provider resealing/tampering, altered re-fetch, cross-attempt replay, unexpected
  result files and disabled-policy rejection before provider invocation.
- New workflow tests enforce all three disabled conditions, runner labels,
  permissions, secret placement, ID-only downloads, trusted fetch outputs,
  mandatory review command and no checkout credentials/cache. Canonical hashes
  are drift alarms only; PR-controlled tests do not implement the trusted gate.
- `python -m tests.shadow_proxy_cli_probe`: real pinned CLI, real container
  entrypoint/runner and real proxy together on an isolated Docker bridge,
  with a synthetic SSE upstream and dummy token. Exact structured result passed;
  proxy observed exactly one message request with only the two expected tools.
  The fake connection replaces external HTTPS only; this is not an OAuth test.
- `python -m tests.shadow_topology_probe`: actual orchestrator startup/readiness,
  isolated plus outward proxy interfaces, refused connection on its outward
  listening address, and confirmed cleanup. Reserved `provider.example` only,
  no API requests. Windows Docker-client environment adaptation was test-only.
- `python -m tests.shadow_proxy_network_probe`: dummy proxy reachable; direct
  metadata, external-IP and ordinary host-bridge routes unreachable (errno 101);
  external `example.com` DNS resolution failed on this isolated network.

Observed integration output:

```json
{"status":"PASS","exact_structured_output":true,"real_cli_and_proxy":true,"synthetic_upstream":true,"proxy_requests":[{"stub_request":true,"path":"/v1/messages?beta=true","tools":["DeferredToolPlaceholder","StructuredOutput"]}]}
```

## Mandatory review questions and remaining gates

1. Review topology, alias resolution, IPv4/IPv6, DNS, proxy protocol parsing,
   host/metadata/public routes, TLS binding/rebinding and response-size/timeout
   behavior. Local tests are representative, not an exhaustive isolation proof.
2. Review secret env-file creation/cleanup, Docker configuration, daemon/race
   and cleanup failures, timeout termination, worker/artifact/cache token
   exposure, and possible leakage of credentials into untrusted outputs.
3. Verify original fetch job-output binding, artifact ID/digest semantics,
   upload/download contents and result parsing against an actual dummy-secret
   GitHub-hosted run before trusting them. None has run remotely. Platform
   artifact/cache substitution and credential-canary tests remain outstanding.
4. Independently review the fixed-origin reverse proxy and internal plaintext
   HTTP transport. The trusted proxy sees provider authentication. A compromised
   CLI may exfiltrate to the provider origin; no domain allowlist eliminates that
   residual risk. Real OAuth, TLS/provider protocol compatibility and supported
   model access remain untested. No real policy origin is configured.
5. The protected environment and trusted required-check publisher/exception
   process remain unimplemented or unverified platform gates. Both workflows
   must stay disabled. Owner approval for settings/credentials and the first
   live call remains separate; approving this disabled code is not activation.

Please give separate verdicts for integrating the disabled candidate and for
enablement, with exact evidence and blocking findings. Do not infer a platform
security guarantee from the local helper functions or green unit suite.
