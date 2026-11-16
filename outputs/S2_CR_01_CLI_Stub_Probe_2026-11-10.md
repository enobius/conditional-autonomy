# Pinned CLI local protocol probe — 2026-11-10

Status: seven local cases passed; **not shadow enablement approval**.

Local verification also passed the 26-test focused review suite and full
257-test regression (99.083 seconds). No new remote CI evidence is claimed.

The probe ran Claude Code Linux x64 2.1.319 in Docker with no external network,
no credentials, a read-only filesystem, a non-root user, all capabilities
dropped, and no-new-privileges. Only the executable directory, test script and
disabled workflow were mounted, read-only. The script checked that loopback
was the only network interface and verified the executable SHA256 before
running it. Its HTTP stub returned synthetic Anthropic protocol messages.

## Results

| Case | Observed result |
| --- | --- |
| Minimal schema, caps 1, 2, 3, 4 | CLI success and exact synthetic object; reported two turns in every case |
| No schema, cap 3 | CLI success, one turn, no advertised tools |
| Unsolicited Bash, cap 4 | Explicit disabled-tool error; no shell marker; recovered synthetic object in three turns |
| Actual workflow verdict schema, cap 2 | CLI success and exact synthetic verdict; reported two turns |

Schema cases advertised only `DeferredToolPlaceholder` and `StructuredOutput`.
The placeholder means it would be inaccurate to say that literally no tools
are present when requesting structured output. The Bash test is one specific
rejection proof, not exhaustive coverage of tool/deferred-tool behavior.

The pinned action's `base-action/src/run-claude-sdk.ts` rejects successful
results when `num_turns > maxTurns`. Therefore the observed two-turn result
would fail its current one-turn configuration. This is a source-based inference,
not a run of the action itself. Two was the smallest tested cap consistent with
that condition for normal synthetic output; it is not a measured minimum for
real model reviews. The disabled workflow was not changed by this probe.

## Evidence and reproduction

`S2_CR_01_CLI_Stub_Evidence_2026-11-10.json` records the output summaries,
executable/archive/probe/workflow hashes, container digest and isolation flags.
The synthetic `approve` result is **not an independent review verdict**.
No provider authentication, billing, reviewer quality, or action integration
was tested. Installing/downloads before the isolated run used public artifacts;
the tested CLI itself had no external network route.

The executable was extracted from the public npm package
`@anthropic-ai/claude-code-linux-x64@2.1.319`. For reproduction, first obtain
that archive, verify its SHA256 against the evidence file, and extract its
`package/claude` executable into `work/claude-linux-stub/claude`. Do not mount
your home directory, Docker socket, credentials, or entire repository.

Run from the repository root in PowerShell:

```powershell
$probeRoot = (Get-Location).Path
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --memory 2g --cpus 2 --tmpfs /tmp:rw,exec,nosuid,size=512m --mount "type=bind,source=$probeRoot\work\claude-linux-stub,target=/cli,readonly" --mount "type=bind,source=$probeRoot\tests\claude_cli_stub_probe.py,target=/probe.py,readonly" --mount "type=bind,source=$probeRoot\.github\workflows\claude-review-shadow.yml,target=/workflow.yml,readonly" python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 python -u /probe.py --cli /cli/claude --sha256 dabafec82ca1319fa43d8be36a10fc61b1d11821cb98ad5df04ad95e199b8eed --workflow /workflow.yml
```

Expected exit code: zero, with seven case records. This probe is explicit opt-in,
not part of normal unittest discovery, and requires the isolated Linux container.

## Remaining before enablement

- Action/SDK integration and the turn-limit repair, still in a disabled candidate.
- Checksum-verified installation before the secret-bearing action step.
- Trusted-base policy enforcement rather than PR code certifying itself.
- Independent review of the consolidated candidate.
- Separately authorized owner-controlled environment protection, credential
  placement and required-check settings.

No PR, merge, repository setting, credential or paid/provider operation was
performed as part of this probe.
