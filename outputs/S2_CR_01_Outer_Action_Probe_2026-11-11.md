# Outer-action local probe — 2026-11-11

**Result: functional synthetic entrypoint test passed; security enablement remains blocked.**

The source checkout reported commit `61a9c274fa7110a66dfafc1bbbced03833eb25fe`
and a clean Git status. Its Bun lockfile was installed in a separate Docker
volume with `bun install --production --frozen-lockfile`, before the isolated
test and with no credentials. The test container had no external network,
was read-only and non-root, dropped all capabilities, and mounted the action,
CLI, probe and disabled workflow read-only. A temporary Git checkout and all
action outputs were contained in its disposable `/tmp`.

The real outer `src/entrypoints/run.ts` ran with Bun 1.4.4, actual action
dependencies, the pinned CLI and synthetic GitHub and model endpoints on
loopback. It accepted the synthetic user, skipped its CLI download in favor of
the supplied executable, and returned the exact synthetic structured verdict
at the two-turn cap. One local GitHub request and one local model request were
observed. The only advertised tools were `DeferredToolPlaceholder` and
`StructuredOutput`. The executable hash was verified by the probe.

## Finding: the action persists the GitHub token

With the current action inputs, its agent-mode setup writes the supplied GitHub
token into the checkout's `.git/config` remote URL. The probe verified this
using a **dummy** token and a temporary test checkout. In a real invocation,
the workflow supplies `github.token` with configured read permissions. This
action behavior defeats the intended effect of checkout's
`persist-credentials: false`: that option prevents checkout from retaining its
credential, but the action subsequently writes one itself. The action also
uses the token in its process environment and emits it as an action output.

This is an exposure path, not proof of an actual leak: tools were disabled in
this scenario, and no real credentials or external model were used. Before any
enablement, independently review and resolve the credential-placement issue,
including whether the action is appropriate for this read-only review. Do not
assume that changing `allowed_non_write_users` alone is a safe fix; it changes
other action behavior and requires its own threat analysis.

## Limits and provenance

- This was the entrypoint with synthetic event inputs, not execution of every
  composite `action.yml` step or a GitHub-hosted run. The action's composite
  also sets up Bun and runs `bun install --production`; that exact setup and
  its supply-chain behavior remain separately unverified.
- Only dummy GitHub/API tokens were used. No real GitHub API, Anthropic call,
  authentication, billing, review verdict, or model behavior was tested.
- The test does not demonstrate complete tool isolation or an enforced guard.
- The locally built image is `sha256:d33b34b3d74f31f03904dd8d57c1e83090459f2d30bd52d0fe1896bb85c79420`,
  derived from Bun image `sha256:1d22548f177f4ff38e0c15baa3c2c46c6c2060ba2d1bc573bb4720b407548f1d`
  with Git installed from Debian packages. It is not a pinned production image.
- Observed SHA256: probe `d60d6c7df098ce4982410e0ba5e49b5df5c19a58836e5342ec00c93be1c30f7b`,
  entrypoint `47bfc23afbfcbac0ee1fb2bc3cd6d7cffc201f2266d6ae2322f0e683b52c0b31`,
  lock `7549e31aac705cddab36737571c9ad791c0ac15f23b431c3a2fc4c7c9af90906`,
  and workflow `a2b86cb3c3b273fd9fc919a460bd52a7c3dd88a665037ecfbac245c1a714146e`.

The shadow workflow remains disabled and these local changes are uncommitted.
