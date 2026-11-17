# Hosted dummy validation: first increment

Base: merged disabled candidate `9bb5413c93832c0f74d3b60d6b1ad22f35b6e856`.
Owner requested proceeding with GitHub-hosted dummy testing. This separate
PR-triggered workflow uses no repository/provider secrets, no paid provider,
no check publisher and no environment/settings changes. Production workflow
and provider policy are untouched and remain disabled.

## Implemented tests

- Production `secret_file` and `topology` on a Linux hosted runner: random
  disposable dummy credential in tmpfs, read-only proxy mount, no credential
  value in Docker configuration/proxy logs, teardown and file unlink.
- Existing real Docker isolated-route/synthetic-proxy probe, including external
  DNS and metadata/public/host routes. It must fail if observed isolation differs.
- Upload one synthetic `result.json`; pass its explicit artifact ID to a fresh
  runner. Use the production downloader with an actions-read GitHub job token
  to exercise actual artifact metadata, ZIP layout and storage behavior.
- Check run/attempt/commit bindings and reject the same artifact under a wrong
  run identity. Do not print tokens, signed URLs or downloaded payloads.

## Limits and remaining gates

This is not full enablement acceptance. No actual CLI, OAuth or provider TLS
request runs here. The only production proxy connection is internal readiness;
its origin is the reserved `provider.example`. The network probe uses a fake
upstream. No cache action is used; adversarial cache substitution, full malicious
CLI credential exfiltration, arbitrary log/artifact canaries and cache-service
credential isolation remain unproven. Artifact success establishes compatibility,
not a new cryptographic trust root. The GitHub token exists only in the separate
artifact verification step, not in either Docker probe.

Independent review of this new workflow/harness remains required before merge.
Do not close S2-CR-01, enable production or dispatch experiments from these tests.
