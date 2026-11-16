# S2-CR-01 isolation proposal — owner decision pending

Status: design only. This is not a sandbox implementation, authorization to
change GitHub settings, or permission to use a provider credential.

## Proposed boundary

Keep PR retrieval and snapshot rechecking on the trusted runner. Run the
verified reviewer CLI in a separate, short-lived container. Supply only the
review prompt, a provider credential, the fixed verdict schema, and a place for
the bounded result. Never mount the repository, runner home, Git metadata,
Docker socket, runner command files, other credentials, or host process tree.
Run as a non-root user, with a read-only root filesystem, dropped capabilities,
no-new-privileges, a small temporary filesystem, and CPU, memory, process,
output and time limits. Kill the entire container on timeout.

The provider token must be accessible to the CLI; this boundary does not
protect that token from a compromised CLI, malicious model output that gains
execution, or a malicious provider endpoint. Never expose it in command-line
arguments or logs. The exact secret-delivery mechanism must be reviewed: Docker
environment values can be inspected by privileged host users, and mounted
secret files can be read by processes inside the container. The user, network
policy and secret lifetimes must be explicit rather than assumed.

## Network boundary: open design issue

Docker's normal bridge network does **not** restrict a container to one domain.
A provider-only claim requires an independently enforced egress policy or
proxy, default-denying all other destinations, including DNS rebinding, direct
IP access, redirects and host/metadata endpoints. A proxy must not become a
general tunnel; preserve TLS verification and define the actual provider/OAuth
endpoints needed after product and account compatibility have been verified.
No such policy or proxy is currently implemented or enabled.

An outbound proxy itself may see sensitive destinations or traffic depending
on its design. The implementation and provider terms must be reviewed before
choosing one. The container shares the host kernel: it reduces exposure but
is not a guarantee against a container escape or a privileged-host compromise.

## Required evidence before owner enablement decision

1. Tests using dummy credentials prove that the container cannot read host
   workspace, Git config, runner process environment, Docker socket, or a
   GitHub-token canary, including after simulated tool execution.
2. Network tests prove default-deny and only the explicitly approved provider
   destinations, including redirects, DNS/IP alternatives and metadata paths.
   Local stub tests must use a separate test configuration, never open a route
   to the real provider while testing.
3. Verify tool restrictions against the deferred placeholder and supported
   built-ins; a model/tool execution test must not see a real secret.
4. Tests verify entire-container timeout termination, output quotas, cleanup,
   non-root identity, capability removal and image/executable provenance.
5. Independent security review covers the implementation and bypass tests.
   A trusted check publisher and owner-approved enforcement and exception
   protocol are separately required; this proposal does not implement them.

## Owner decision later

After the implementation and tests are ready, approve or reject this isolation
design, the provider/network endpoints and the independent review. GitHub
environment configuration, credentials, the first live call, and any required
check are separate approvals. Until then the shadow workflow remains disabled.
