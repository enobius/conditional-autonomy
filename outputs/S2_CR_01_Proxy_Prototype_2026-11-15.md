# Fixed-origin proxy prototype — 2026-11-15

Status: local prototype, not connected to the CLI runner or GitHub workflow.
No provider origin is enabled by default, and no provider was contacted.

Final local verification: 288/288 unit tests in 139.503 seconds, eight focused
proxy tests, and the schema gate passed. The isolated-network Docker probe
passed. `git diff --check` passed apart from line-ending warnings. No new
remote CI, Stage 1 exit-gate run or independent review is claimed for this delta.

## Implemented

`tools/shadow_egress_proxy.py` implements a reverse proxy, not an arbitrary
CONNECT tunnel. A trusted caller must specify one fixed DNS origin. Requests
cannot choose another host, port or URL: only POST to the message/count-token
paths and the exact `beta=true` query are supported. Authorization and protocol
headers have an explicit allowlist; Host is replaced with the configured origin.
Ambiguous length/authentication headers and transfer encodings are rejected.
Request/response bodies are bounded, streams are time-limited, redirects are
refused, and logs do not print request bodies or credentials.

Before an upstream connection, DNS answers are checked for non-global,
metadata, gateway, scoped IPv6 or mapped-address destinations; mixed unsafe
answers are rejected. The connection uses the checked numeric address, while
TLS uses the fixed origin for SNI and certificate verification. Thus a second
hostname resolution is not used for the connection. Tests use fake resolver
results and mocked HTTPS upstreams, never a real provider.

This concretizes the allowlisting proxy as a fixed-origin API adapter. The CLI
would require an internal base-URL transport to use it. This change from a
generic forwarding proxy must be independently reviewed for protocol and OAuth
compatibility. The current CLI runner does not yet use it.

## Tests

Eight local unit/integration tests cover exact forwarding/header filtering,
CONNECT and alternate-URL rejection, redirects, duplicate lengths and auth,
request/response bounds, streaming truncation, certificate verification,
checked-IP connection, metadata/private destinations and IPv6 alternatives.
The small HTTP test servers run on loopback and the HTTPS upstream is mocked.

A real Docker probe created a disposable `--internal` bridge with
`com.docker.network.bridge.gateway_mode_ipv4=isolated`, a dummy proxy container,
and an unprivileged client. Neither container had an external network or real
credential. The client reached the dummy API but direct TCP routes to
`169.254.169.254`, `168.63.129.16`, `8.8.8.8` and the host's ordinary bridge
address `172.17.0.1` returned errno 101 (network unreachable). Connection-refused
responses would have failed the test. Test containers/network were removed.
An initial probe assumed a gateway existed and failed; in isolated mode no
gateway is assigned, so the corrected test asserts its absence and uses the
ordinary bridge address only as a blocked target, never attaching to it.

Observed successful probe output:

```json
{"status":"PASS","proxy_stub":{"local_stub":true},"blocked_direct_routes":[{"address":"169.254.169.254","error":"OSError","errno":101},{"address":"168.63.129.16","error":"OSError","errno":101},{"address":"8.8.8.8","error":"OSError","errno":101},{"address":"172.17.0.1","error":"OSError","errno":101}]}
```

An ordinary internal bridge still permits gateway/host service access. The
Docker documentation describes the isolated gateway mode and this distinction:
https://docs.docker.com/engine/network/port-publishing/

## Remaining limits and work

The production dual-network proxy topology, actual external HTTPS access,
CLI-to-proxy adapter, OAuth protocol compatibility, DNS/external-query leakage
and additional host-service bypass tests remain unverified. The mocked proxy
upstream proves local routing/functionality only, not real-provider behavior.
The proxy can see provider authentication and the internal CLI-to-proxy HTTP
traffic is not encrypted. No GitHub/runtime tokens should enter that network;
the host and proxy remain trusted, and residual exfiltration to the provider
origin is still possible if the CLI is compromised. Endpoint approval is still
an owner decision; a hostname allowlist does not remove provider-token risks.

The three jobs, original fetch-output artifact ID/hash wiring and trusted
publisher are still outstanding. The existing disabled workflow has neither
this network topology nor this proxy. The no-egress launcher remains no-egress.

Input SHA256:

- Proxy: `d89e3c6ed23443af48adf3d5682a3971c80759d15c8ebcc11e3a5fac0311b205`
- Tests: `29ce994c39f7bedb671aebe216aaa634936bc9c5dc198bcf114d820f0c3554cc`
- Docker probe: `db3d1c011f333f31bad626652b92d261e6a08a24f7e6fd87110d1ae668b2f7cc`

All changes are local/uncommitted, require independent review, and do not
authorize settings/credentials/provider calls or enabling the workflow.
