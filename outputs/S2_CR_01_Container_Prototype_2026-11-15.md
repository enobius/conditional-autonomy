# No-egress container prototype — 2026-11-15

Status: local implementation only; workflow remains disabled and unchanged in
topology. This is not a production provider sandbox or an enablement approval.

Verification: full local regression 280/280 in 132.122 seconds; schema gate
green; final container unit suite 5/5 after adding invalid-input assertions.
Docker smoke/boundary and timeout-removal checks passed. No remote CI or new
Stage 1 exit-gate run is claimed for this change.

## New implementation

`tools/shadow_container.py` builds a fixed, pinned-image Docker configuration:
network none, non-root UID/GID 65534, read-only root, no-new-privileges, all
capabilities dropped, 64-process limit, 2 GB memory, two CPUs, 64 MB temporary
filesystem, and a 1 MB regular-file size limit. It mounts only the executable
file and trusted tools directory read-only, never the repository root, Git,
Docker socket or runner command files. The container entrypoint accepts a
bounded prompt on standard input and invokes the checksum-verifying CLI runner.

The Linux host secret helper refuses non-Linux/non-tmpfs delivery, validates
credential encoding, creates a private directory and mode-0600 env file under
`/dev/shm`, and removes the file/directory on exit. The Docker client environment
does not inherit GitHub, artifact/cache, provider or Docker-context variables.
The credential value is not put in command-line arguments. Privileged host
inspection and provider-token exposure inside the container remain residual.

The lifecycle confirms Docker creation before attach/start, avoiding a
run/startup cleanup race. It bounds stdout and stderr while draining them,
force-removes the exact generated container on timeout or overflow, and fails
if removal is not confirmed. Creation timeouts/daemon failures are errors, not
claims that an ambiguous operation was certainly cancelled. No arbitrary
caller-supplied container or image name is exposed through the high-level API.

## Local tests and observed output

Unit tests exercise command policy, environment allowlisting, prompt/deadline
checks, real local-process output overflow and timeouts, cleanup failure,
confirmed creation-before-start, and invalid secret encodings.

The Docker smoke test used the generated configuration, not a real provider.
Observed output:

```json
{"status":"PASS","uid":65534,"network":["lo"],"capabilities":0,"no_new_privileges":true,"readonly_root":true,"github_env_absent":true,"tmpfs_secret_mode":"0600","secret_cleaned":true,"file_limit":1048576}
{"timeout_cleanup":"PASS","container_and_descendants_removed":true}
```

The smoke test separately verified the real Linux tmpfs secret helper inside
the container, and force-removal of a container running a child process. Its
host was Windows: the outer env file held **only a dummy value** in a disposable
ordinary directory, and the timeout test adapted the Docker-client transport
for Windows. Production host secret delivery was not bypassed or claimed tested
end-to-end against a Linux-host Docker socket. An initial smoke failure exposed
an invalid `Path.open(opener=...)` call in the helper; this was corrected to
built-in `open` and the smoke test rerun successfully.

SHA256 of implemented inputs:

- Launcher: `ddfed5f20d08a3f9472755fff0eaa6f80d81b3451e9e18f2d37615b78ddaccfd`
- Entrypoint: `96ffd7f8c86f1fde6e61ce204dae7fda7f037e01a3874931fab401dbfe55501c`
- Docker probe: `dff8edf14c23b7ec3d79b2d52434c5713cd8f4e5a89d844d48a9fdac07d54f78`
- Unit tests: `097358dd0c8128ca3987be04a0b6958c196cff567bed6d7b2a2034f41996049f`

## Remaining work

There is deliberately no provider egress. Do not replace network none with a
normal bridge as a shortcut. The hostname-allowlisting proxy/internal-network
boundary, metadata/host denial and bypass tests must be implemented before a
real model can be reached. The three jobs, artifact ID/digest transport through
trusted fetch outputs, cache/artifact adversarial tests, and trusted publisher
remain outstanding. The existing single-job disabled workflow does not yet
invoke this container launcher. The artifact-binding helper also remains local.

No real provider credential, model call, settings change, commit, push or
workflow activation occurred. Independent review is still required.
