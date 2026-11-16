# Strict tool-matrix rerun

All 13 representative cases completed with exit code zero under the tightened
test oracle. Each case now requires `failed-closed`, no destination file, no
marker, only the two expected advertised tools, and an explicit tool-error
response naming the attempted tool. A successful/accepted invocation now fails
the probe. Unit tests also reject missing/error-free evidence and a rejection
of a different tool.

The names were Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch,
NotebookEdit, Task, Agent, DeferredToolPlaceholder, and
`mcp__github__get_file_contents`. One generic argument payload per name was used;
these are not an exhaustive inventory or attack-space test.

The run used the same pinned CLI and Python image as the earlier matrix:
`python@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39`.
Docker network was `none`, root filesystem read-only, user `65534:65534`, all
capabilities dropped, no-new-privileges, 2 GB memory, two CPUs, and a temporary
512 MB filesystem. Mounts were only the tools directory, pinned CLI directory
and probe, all read-only. The local stub used dummy provider credentials; no
real provider or GitHub API request was made. A 300-second container-level
timeout surrounded the test. This test isolation is not yet the production
workflow boundary.

Input SHA256 values:

- Probe: `3e2e5fec4d59b7d1c901c3b8927d7d626d306b8d537d142f987dbce5042278d8`
- Evidence checker: `8a68f7f804f34730321169ba0283553890e00af3383eeef6177ea74326284724`
- Evidence-checker tests: `f1e2489cddb64e11010e0d4791d8518be351d377ed55d000f3a129eaa3a2af07`

The previous matrix evidence describes the older probe; it is not silently
replaced by this result. These new changes require independent review. The
workflow remains disabled and no commit, PR, settings or secrets were changed.
