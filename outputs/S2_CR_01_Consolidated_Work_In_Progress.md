# Consolidated safeguards — work in progress

Latest November 16 follow-up: real loopback/default-opener tests and fake-Docker
read-only/non-root/cleanup-order tests are implemented, along with an atomic
four-attempt per-run upstream budget. The placeholder CLI/proxy synthetic
integration passed. See `S2_CR_01_Test_Gap_Repairs_2026-11-16.md` and its updated
manifest for current scope, explicit workflow deletion and remaining gates.
No remote workflow, live credential/provider or settings change occurred.

2026-11-16 repairs: the untrusted provider ZIP is now fetched via REST and read
without archive-path extraction; provider authentication is mounted only into
the proxy, with a public placeholder in the CLI; policy-flag tests now use a
valid disabled origin. Schema-gate caching was removed, IPv4 is preferred, and
the legacy workflow was retired outside Actions. See
`S2_CR_01_Review_Repairs_2026-11-16.md` and its new 33-file hash snapshot for
current scope/limits. 304 tests and local schema/Stage 1 gates passed. Real
provider/platform verification and independent approval remain outstanding.

Newest 2026-11-15 integration: the real CLI/container/proxy path passed an
isolated synthetic-upstream test. A separate hard-disabled three-job candidate
is now wired with original fetch-job output hashes and IDs, mandatory private
network/container orchestration, a disabled/null-origin provider policy, and
independent final re-fetch/validation. See
`S2_CR_01_Isolated_Workflow_Handoff_2026-11-15.md` and its 30-file hash manifest.
298/298 tests, schema gate and Stage 1 gate passed locally. No remote workflow,
real provider call, credentials, settings, commits or pushes were used. Earlier
notes saying job/proxy wiring does not exist predate this integration. Platform
adversarial tests, real protocol compatibility and trusted publication remain
gates, and neither workflow may be enabled on this evidence alone.

Latest proxy delta: a fixed-origin, restricted-path reverse proxy is implemented
locally with TLS/public-address checks, no tunnels/redirects and bounded I/O.
Eight local tests pass without a real upstream. A disposable Docker isolated
bridge test reached the dummy proxy and denied direct external/metadata/host
bridge routes. See `S2_CR_01_Proxy_Prototype_2026-11-15.md` for hashes, exact
scope and limits. The proxy is not connected to the CLI or workflow, the
production egress topology and three-job wiring remain outstanding, and the
existing launcher remains network-none. No real provider call was made.

2026-11-15: a no-egress container launcher, trusted entrypoint, bounded pipe/
timeout handling and Linux tmpfs secret helper are now implemented locally.
Real Docker smoke tests passed boundary and container/descendant-removal checks
with dummy values. See `S2_CR_01_Container_Prototype_2026-11-15.md` for scope,
hashes, failures corrected and limitations. The main workflow is still disabled
and does not yet use this launcher. Proxy-only provider networking, three-job
wiring, platform tests and trusted publication remain outstanding. Historical
statements below saying the container is unimplemented predate this prototype.

Latest (2026-11-12): see `S2_CR_01_Isolation_Implementation_2026-11-12.md`.
The checker now rejects prefixes and mixed-success results, a new 13-case
rerun has raw JSONL stdout, a local fetch-manifest binding prototype and tests
exist, and the runtime/Stage 1 gate candidates no longer restore/use pip caches.
These changes require independent re-review. Actual three-job/container/proxy
wiring, platform adversarial tests, settings and trusted publication remain
outstanding. Historical test counts and review hashes below describe earlier
candidate states, not authority for the latest changes.

PR #41 merged as `80eb0c990bd07bf58de9f442be066b4360ec0baa` after owner
authorization and the independent PASS for the disabled workflow. All four
remote checks passed on that merged commit. No settings or credentials changed.

Working branch: `codex/s2-cr-01-consolidated`. Local candidate changes now
reject unapproved workflow/job/step keys in the guard, including shell/defaults,
conditional execution, error suppression and injected environment settings.
The focused three-module suite passes 26 tests. The full local regression
passed 257/257 tests on 2026-11-10 (99.083 seconds). These changes have not been
independently reviewed or committed; no new small PR has been opened.

The pinned Windows CLI probe still timed out without a stub request after
isolating its working directory and closing stdin. Temporary-directory cleanup
also reported a directory-not-empty error; no broad cleanup was attempted.
Docker was initially unavailable; after the owner started it, the isolated
Linux probe completed successfully on 2026-11-10. No real provider call was
substituted. See `S2_CR_01_CLI_Stub_Probe_2026-11-10.md` and the companion JSON
evidence for the seven cases, hashes, reproduction command and limitations.

The exact pinned Linux CLI accepts `--tools=`. Without a schema it advertises
no tools; with a schema it advertises `DeferredToolPlaceholder` and
`StructuredOutput`. An unsolicited Bash request was explicitly rejected, with
no marker file created. Both the minimal and actual workflow verdict schemas
returned the synthetic structured result. Structured output reported two turns
even at cap one. The pinned action rejects successful results exceeding its
cap, so the current one-turn workflow setting is incompatible with that
observed result. A cap of two passed the normal CLI schema cases, but full
action/SDK integration and real-model behavior have not been established.
At that point the workflow was unchanged and disabled; the later candidate
changes below do not authorize enablement or prove model quality or exhaustive
tool isolation.

Source inspection of the pinned action confirms that a supplied executable
path skips its installer. Consolidated remaining work is therefore:

Update 2026-11-11: the disabled candidate now uses a two-turn cap and a pinned
installer that verifies both the npm archive and executable before the action
credential step. It extracts only one regular `package/claude` member, refuses
redirects, caps sizes, and removes its private temporary directory on failure.
Three offline installer tests and the installer drift alarm were added; the
real downloaded archive and binary were verified without executing them.
The focused suite passes 30 tests. A separate synthetic-SDK probe executed the
pinned action's actual parser and result handler: cap 1 rejected, cap 2 accepted
a synthetic two-turn result. This is not an actual SDK/CLI integration run.
The CLI probe from 2026-11-10 tested the previous workflow file (same verdict
schema); its recorded workflow hash intentionally does not match this candidate.
The final full local regression passed 261/261 in 68.512 seconds. The schema
gate and Stage 1 exit gate also passed locally, including 16/16 registered
invariants and 4/4 seeded-defect proofs. No remote CI has run for this work.

Docker Desktop did not start through a background launch on 2026-11-11, but the
owner started it afterwards. The isolated local-stub base-action/SDK/CLI test
then passed: cap 1 rejected the two-turn result and cap 2 accepted the exact
synthetic workflow-schema verdict. The evidence and limits are in
`S2_CR_01_Action_SDK_CLI_Probe_2026-11-11.json`. This does not test the complete
outer GitHub Action or GitHub-hosted workflow, real authentication, reviewer
quality, or exhaustive tool isolation. `S2_CR_01_Trusted_Guard_Design_DRAFT.md`
records the unimplemented trusted-publisher design and bootstrap concerns; the
existing PR-controlled guard must not be treated as a trusted enforcement gate.
The `tests/offline_action_sdk_cli_probe.mjs` and TypeScript loader verify four
action source hashes, SDK version and entrypoint hash, and the CLI hash, check
that only loopback is present, use a dummy token and local protocol stub, then
test caps 1 and 2. The container had no external network and no credential-bearing
host mounts. The CLI's synthetic cost estimate did not represent a provider call.

Outer-entrypoint update: an isolated Bun 1.4.4 test ran the actual pinned action
entrypoint with its installed dependencies, a dummy GitHub user service, and a
dummy model service. It passed the synthetic structured-output and custom-CLI
path checks. It also confirmed that the action writes the supplied dummy GitHub
token into the temporary checkout's remote URL; in the proposed workflow the
equivalent input is the read-scoped `github.token`. Thus checkout's
`persist-credentials: false` is undone by the action. This is an exposure path,
not a demonstrated leak. It is a blocker pending independent review and a safe
resolution. See `S2_CR_01_Outer_Action_Probe_2026-11-11.md`; the composite setup
steps, production supply chain and real GitHub-hosted execution remain untested.

Direct-runner update: after owner approval, the disabled candidate no longer
uses that outer action. It invokes the pinned CLI in a fresh temporary working
directory with an explicit child environment that omits GitHub credentials and
runner command files, and sends the extracted result through the existing
snapshot/response validator as a file. The real CLI passed an isolated local
stub test using a dummy provider token; a dummy parent GitHub token was not
forwarded and an unsolicited Bash request was rejected with no marker and a
fail-closed result. See `S2_CR_01_Direct_CLI_Candidate_2026-11-11.md` for
hashes, controls and limits. This is not an OS sandbox, real OAuth/provider
test, GitHub-hosted run, independent review, or trusted guard.
The focused suite passed 35/35, the final full local regression 266/266, the
schema gate passed, and the Stage 1 exit gate passed with 16/16 invariants and
4/4 seeded-defect proofs. A draft independent-review handoff is in
`S2_CR_01_Direct_CLI_Review_Handoff_DRAFT.md`; it records the uncommitted file
hashes and does not imply that a review has occurred.

Reviewer-follow-up: strengthened semantic tests assert the full CLI command,
schema, model, timeout and installer URL/redirect-rejecting opener, and repair
the duplicate-key and NaN test fixtures so they are otherwise valid results.
The npm-published SHA-512 integrity value exactly matched the previously
downloaded archive. The real installer entrypoint subsequently completed
against public npm in a credential-free local process and verified the binary;
this was not a CI run and did not execute the binary. Docker was unavailable
for additional local adversarial CLI tests. A proposed container boundary and
its unresolved egress and provider-token risks are recorded in
`S2_CR_01_Container_Isolation_Proposal_DRAFT.md`; no sandbox or trusted
publisher has been implemented or enabled.
The updated focused suite passed 36/36 and full local regression 267/267.
After the owner started Docker, the new network-none, non-root tool matrix ran
13 representative names. All 13 returned tool errors and the runner failed
closed; no marker file was created. This included `DeferredToolPlaceholder`
and a representative MCP name. Raw summarized evidence and limits are in
`S2_CR_01_Tool_Matrix_Evidence_2026-11-11.json`. One payload per name is not an
exhaustive list of tools or attack paths and is no substitute for a production
isolation boundary. No provider request or real credential was used.
The runner and installer test files have changed since the independent review;
the prior review remains valid only for its exact recorded hashes, and these
follow-up changes need a re-review.

Latest follow-up: the matrix now invokes a separate rejection oracle that
requires explicit failure, an error for the attempted tool, the exact advertised
tool inventory and no destination/marker. Regression tests demonstrate that
accepted results and missing/wrong errors fail the oracle. All 13 cases passed
the stricter network-none rerun; see
`S2_CR_01_Strict_Tool_Matrix_Rerun_2026-11-11.md`. The revised probe, new oracle,
its tests and guard-test inclusion are newer than the prior independent review.
`S2_CR_01_Job_Isolation_Evaluation_DRAFT.md` evaluates separate standard VM jobs
plus a provider container and explicitly identifies artifact runtime credentials
as an additional risk. This remains design-only; the production topology,
network isolation and trusted publisher are not implemented or enabled.
Final local verification for this repair: focused suite 37/37, full regression
268/268 in 68.668 seconds, and `git diff --check` clean apart from line-ending
warnings. No new remote gate or independent-review result is claimed.

- Independently review the direct-runner replacement, its credential and OS
  isolation boundaries, CLI installer and provider compatibility before any
  enablement. The removed action's Bun/dependency steps are no longer in the
  candidate workflow.
- Independently review the implemented pre-credential pinned installer and its
  adversarial tests, including provenance of the chosen hashes.
- Enforce policy from trusted base code, never execute PR code with authority;
  ensure checks cannot certify themselves merely by editing their own tests.
- Review the consolidated result before enabling; owner-controlled environment
  rules and required-check settings remain separate approvals.

The shadow job remains disabled. No provider call was made.
