# Independent review handoff — direct CLI candidate

Newest 2026-11-15 delta: see `S2_CR_01_Proxy_Prototype_2026-11-15.md` for the
fixed-origin API reverse proxy, its tests and isolated-network Docker probe.
This is not the full production network/CLI/job wiring. The guard test list was
extended again. Earlier reviews and hashes do not cover these new edits. In
addition to earlier review questions, examine fixed-IP/TLS/DNS checks, request
framing, body bounds, redirect/header handling, internal-HTTP credential risk,
isolated gateway-mode behavior, and the as-yet-unverified real OAuth protocol.

2026-11-15 delta: new no-egress container launcher/entrypoint and boundary tests
are described in `S2_CR_01_Container_Prototype_2026-11-15.md`, including current
file hashes. They are not integrated into the main disabled workflow, and have
no proxy/provider route. The guard's explicit test list and its policy test
were extended to include the new unit suite. This delta has not been reviewed
and does not inherit approval from the earlier candidate hashes.

2026-11-12 implementation delta: the checker was refined again, raw matrix
stdout was saved, `tools/shadow_artifact_binding.py` and its tests were added,
and pip-cache restoration/use was removed from the runtime and Stage 1 gate
workflow candidates with a policy regression test. See
`S2_CR_01_Isolation_Implementation_2026-11-12.md` for scope, hashes and limits.
These edits supersede the prior file-hash review authority and require a new
review before integration. Actual three-job/container/proxy wiring is still
outstanding; this is not a completed isolation implementation.

Latest re-review scope: the matrix assertion repair and job-isolation evaluation
are now newer than the follow-up review. Read
`S2_CR_01_Strict_Tool_Matrix_Rerun_2026-11-11.md` for the three new probe/oracle
hashes and results, and `S2_CR_01_Job_Isolation_Evaluation_DRAFT.md` for the
design evaluation. The guard workflow additionally changed to run the new tests:
SHA256 `27981feaa619f3c1c09bff29c2c1f1fd5179f9dd47a745544526769f23accdfd`;
its test file SHA256 is
`603f78343419f2499f3dc90cd88717af5e76e477ea32a2f062e3b5205fda2b33`.
Historical hashes below are retained as prior candidate records, not current
review authority for the changed files. The main disabled shadow workflow,
direct runner and installer remain unchanged in this repair.

Status: **draft; not independently reviewed or approved**. The shadow workflow
is disabled. Please review source and tests, not just this summary. No reviewer
should treat the synthetic `approve` emitted by a local stub as a real verdict.

Follow-up notice: the candidate described below was independently reviewed,
but `tests/test_run_claude_shadow.py` and `tests/test_install_claude_shadow.py`
have since changed, and a new `tests/direct_cli_tool_matrix_probe.py`
was added. The old hashes and verdict do not cover those edits. Current hashes:
runner tests `36b2ae49657a447acc727ce1d018e06ecfb63ce735893820ee69bd0b7dd8c221`,
installer tests `e9c25c5d4a2c4a55cefbc6602c1c42fcfde6f6e963c1fc14c108ca27c1661884`,
tool probe `95ba484f831171cee92c2ec40afffe25beed6bb7974c2dc1e993768bc7d4993f`.
An updated re-review is needed after follow-up work and testing are complete.
The matrix later ran 13 representative names in a network-none container; see
`S2_CR_01_Tool_Matrix_Evidence_2026-11-11.json` for results and limits.

Candidate is an uncommitted working tree on `codex/s2-cr-01-consolidated`, based
on `80eb0c990bd07bf58de9f442be066b4360ec0baa`. Because it is uncommitted,
identify the exact reviewed bytes using the hashes below; request a new review
if they change. Other unrelated dirty and untracked files exist and are outside
this candidate.

| Candidate file | SHA256 of local file bytes |
| --- | --- |
| `.github/workflows/claude-review-shadow.yml` | `596940b5758de86d15cf9c37e9ffa6280c480e18ad93f54cc8795255aac231d4` |
| `.github/workflows/shadow-review-guard.yml` | `2361acf9749600b28164fa042173c44d30aab69d7639343949890145422235eb` |
| `tools/run_claude_shadow.py` | `0084fc2a32f728a76a435a67833b0a9e9af795ad77b3a707a6c9e7c94e1ee07c` |
| `tools/claude_shadow_workflow.py` | `d50b6e42f953dcf37082606d96004dbc4a9fefbf63e0c848ef81826e7e39ce3d` |
| `tools/install_claude_shadow.py` | `01ec440fb8b247cbf4ae4ca6026c5d636dcc3ce7e6b488508a9906cb62db25ab` |
| `tests/test_claude_shadow_workflow.py` | `783ff4555a5d0fe4d566842061c882ae5ad8477b555c2417f5d7708ad76b9f08` |
| `tests/test_run_claude_shadow.py` | `253845086a587a264717d1bb19888d03ace65a20eaa6b0d881afe306fe8bdaa0` |
| `tests/test_install_claude_shadow.py` | `0bdbd35788bda0b5662fa1301bc161d30b6025f85c8ce04b04b5bb749eb7ad13` |
| `tests/direct_cli_local_probe.py` | `a9fb4ca9cd07086b5649c009aeca8df3935117686ca5d39e9d209878c4529669` |

Review the whole effective trust chain, including imported runtime validators,
the prompt, schema lock, CI workflow and pinned executable provenance. In
particular, investigate:

1. Whether the GitHub token can reach the provider or CLI through environment,
   Git config, inherited files/processes, CLI configuration, network, logs or
   error paths. Do not equate a clean environment with an OS security boundary.
2. Whether the provider token and untrusted diff can be disclosed or instructions
   in the diff can escape the intended boundary, including deferred tools, MCP,
   local settings, output files, and malformed result handling.
3. Installer archive and executable hash provenance; substitutions, redirect,
   archive traversal/duplicates, executable and temporary-directory races,
   dependency drift, and behavior before credentials are present.
4. Snapshot/diff binding, fresh result handling, duplicate/non-finite JSON,
   schema and finding-location checks, errors, timeouts, output size and resource
   exhaustion, and how the changed result-file interface fails closed.
5. Whether the PR-controlled guard can be bypassed or spoofed, and what trusted
   publisher, bootstrap/exception process, branch protection and owner decisions
   are necessary before any workflow enablement.
6. Whether real provider OAuth, GitHub-hosted execution, or behavior outside the
   synthetic loopback test remains unverified. The shadow result must remain
   advisory and the job must remain disabled during this review.

Local probe details and limits are in `S2_CR_01_Direct_CLI_Candidate_2026-11-11.md`;
the prior outer-action credential finding is in
`S2_CR_01_Outer_Action_Probe_2026-11-11.md`. Return a clear pass/fail recommendation,
blocking findings with exact locations and evidence, and any residual uncertainty.
The final required-check publisher and independent reviewer calibration are not
implemented merely because this candidate exists.
