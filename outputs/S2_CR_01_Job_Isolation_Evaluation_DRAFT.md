# Job-separated isolation — evaluation, not enablement approval

## Implementation constraints accepted from the latest independent review

- Pin all three eventual jobs to `ubuntu-24.04`; do not use self-hosted or
  single-CPU runners for this boundary. Production jobs are not yet created.
- Feed the original manifest hash and artifact identity to validation through
  `needs.fetch.outputs`, not provider-controlled names or listing results.
  Independently re-fetch and hash the diff. The local prototype in
  `tools/shadow_artifact_binding.py` now implements byte/context checking,
  but actual upload/download action ID/digest support and wiring remain to test.
- Make the provider container mandatory. The artifact and cache runtime tokens
  must remain outside it. The runtime gate workflow candidates no longer restore
  pip caches and use `--no-cache-dir`; actual cache-token reach is still an
  inference requiring dummy-token GitHub-hosted adversarial tests.
- Use an internal-only container network whose only outbound route is a
  hostname-allowlisting proxy. Block direct IP/DNS bypass, host access and metadata
  endpoints including `169.254.169.254` and `168.63.129.16`. This is not yet
  implemented. A provider-domain route still permits residual exfiltration to
  the provider domain; a domain allowlist alone cannot eliminate that risk.
- The provider host job may use `contents: read` alone to acquire the trusted
  code rather than assuming checkout works with `permissions: {}`. No token
  is passed into the container. Deliver provider authentication through an env
  file on host tmpfs, delete it on every exit, and never put values on command
  lines. That secret mechanism and cleanup still require implementation/tests.

These constraints supersede the earlier empty-permissions/optional-container
alternatives below. They are implementation requirements, not claims of an
enforced production boundary or permission to activate it.

## Recommendation for independent review

Use three separate standard GitHub-hosted VM jobs, with an isolated CLI
container inside the provider job. A job split reduces exposure to the fetch
job's repository token; the container separately restricts access to the
provider job's runner processes, files and artifact credentials. Neither change
has been implemented in the disabled candidate yet.

1. **Fetch:** read-only contents/PR permissions, no provider secret. Check out
   only the trusted revision and retrieve the PR as data. Produce a bounded
   prompt file plus a manifest binding repository, run, trusted revision,
   base/head/merge-base and content hashes. Never upload credentials, Git config
   or arbitrary workspace directories.
2. **Provider:** `permissions: {}`, separate protected environment. Receive
   only the exact same-run, named input artifact and trusted executable code.
   Verify size, shape, provenance and hashes before the credential is exposed.
   Never execute code from the PR or an artifact supplied by an untrusted run.
   Invoke the CLI inside a non-root container with no host credentials, runner
   files, Docker socket or repository mount. Provide only provider authentication
   and bounded input; enforce network and resource policy outside the container.
   Treat every provider-job artifact as attacker-controlled afterwards.
3. **Validate:** fresh VM, read-only PR permissions, no provider secret. Obtain
   the original fetch manifest directly, not a provider job's rewritten copy.
   Re-fetch current PR metadata and compare every bound field and digest.
   Read only bounded result data; do not execute anything from either artifact.
   Produce an advisory result, never a merge-authorizing review by itself.

The provider job must not be able to replace the original fetch artifact or
convince validation to select a different run/name/ID. Use explicit identities,
small exact file inventories, no archive traversal or symlinks, independent
hash checks and failing closed on missing, duplicate or ambiguous artifacts.
These are requirements to implement and test, not existing protections.

## Important corrections to the simple job-split argument

GitHub documents that standard GitHub-hosted jobs use separate fresh VMs
(single-CPU runners are an exception). Limit this proposal to standard VM
labels, not self-hosted or single-CPU runners. Source:
https://docs.github.com/en/actions/reference/runners/github-hosted-runners

An empty `permissions` map restricts the repository `GITHUB_TOKEN`; it should
not be described as removing every Actions capability. GitHub's artifact
toolkit also consumes `ACTIONS_RUNTIME_TOKEN` and `ACTIONS_RESULTS_URL`.
Inference: compromising the provider VM may expose artifact-service capabilities
as well as provider authentication, even if repository permissions are empty.
Actual token scope, cross-job access and artifact substitution must be verified
with dummy-secret GitHub-hosted adversarial tests before trusting the boundary.
Sources:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
https://github.com/actions/toolkit/blob/main/packages/artifact/src/internal/shared/config.ts

A job split does not implement provider-only egress, prevent provider-token
theft, prove container isolation, or create an independently trusted required
check. The container proposal's egress, secret-delivery, cleanup and bypass
tests remain prerequisites. A compromised provider job may destroy or falsify
its output; the downstream validator must reject it, not trust job success.

## Decisions and next engineering gate

Before altering the production workflow topology, obtain independent review of
this combined boundary and the bootstrap/required-check design. Owner approval
for the environment, secret placement, enforcement settings and a first live
call remains separate. Local work can prototype the artifact manifest and
container boundary with dummy tokens meanwhile. The workflow stays disabled;
this draft creates no jobs, artifacts, environments, secrets or checks.
