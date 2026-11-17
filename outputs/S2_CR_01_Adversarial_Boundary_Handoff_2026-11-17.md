# Hostile-client container-boundary test increment

Base: merged PR 43, `914972beacd20efda54d48a4e41b4f10e656e288`.
New increment requires independent review; earlier review does not cover it.

## Scope

A Python malicious-CLI stand-in runs using the production `proxied_command`
container restrictions, production `topology` and bounded `collect`. Only the
container executable/entrypoint is replaced, to avoid installing a real CLI or
bypassing its checksum in production. No production helper is modified. The
stand-in therefore tests the **container boundary**, not the production runner's
environment allowlist or actual CLI compatibility.

Host environment and a host-only file carry random disposable dummy canaries.
The actual platform tokens are not inspected or injected. The stand-in attempts
environment access, reads host/proxy secret/socket/workspace paths, writes root
and read-only tool mounts, and connects/sends requests toward host-only synthetic
artifact/cache service paths. A real host HTTP listener has a successful loopback
positive control. The host oracle requires no subsequent service traffic and an
exact all-denials result. Connection refusal is not accepted as isolation proof.
No stream, credential, signed URL or host environment dump is emitted.

Unit tests inject inherited host environment, readable files, writable mounts,
reachable services and connection refusal. Each must fail the host oracle.
Production workflow/policy remain untouched and disabled. Existing hosted
artifact round-trip remains in its separate runner; the new probe emits no artifact.

## Explicit limits

These are synthetic cache/artifact endpoints, **not** GitHub's live runtime/cache
services. No real runtime token is used. This does not prove cache poisoning or
artifact substitution resistance, arbitrary exfiltration resistance, isolation
against Docker/kernel compromise, or secrecy from a privileged daemon/host.
The proxy's permitted provider channel remains a residual exfiltration route.
This stand-in does not call it. The prior synthetic proxy route test remains.
Actual CLI/OAuth/TLS, protected environment, trusted required-check publisher,
exception policy and owner origin/request-budget/live-call gates remain open.

Review the new client, host oracle, unit fault injections and workflow wiring.
Separate merge acceptance from enablement; no merge or enablement is requested
without independent review and owner authority. No provider secret, repository
setting change, real provider request, pilot or rented compute is used.
