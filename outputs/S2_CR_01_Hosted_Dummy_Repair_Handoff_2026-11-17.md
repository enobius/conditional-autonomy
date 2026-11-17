# PR 43 focused repair handoff

Previous reviewed head: `159496e837f5d7b797160e9d6d1a1f64dd7aedac`.
Independent Claude prose review supplied by the owner on November 17 gave
PASS for merging the test increment, FAIL for production enablement, with two
nonblocking P2 oracle gaps and P3 improvements. This delta requires fresh review;
the old verdict does not cover the repairs.

## Repairs

- Collect Docker logs with a scrubbed subprocess environment, bounded deadline,
  return-code check, and explicit scans of **both stdout and stderr**. Neither
  stream nor the canary is printed. No production runtime helper was modified.
- Fake-Docker tests call the actual `probe()` and require rejection of config,
  stdout and stderr leaks, log collection failure, absent/writable secret mount,
  premature unlink and a surviving credential. The success case checks teardown
  before unlink, sanitized subprocess arguments/environment and canary-free output.
- Add main-push triggers and production workflow/policy paths to the hosted test
  workflow, retaining the original PR paths.
- Add workflow/job/step key allowlists and negative tests for step `shell`/`if`
  overrides. Permissions remain exact read-only, no secrets or cache action.
- Suppress the success message during mocked artifact verification tests so local
  unit output cannot be confused with an actual hosted artifact run.

The suggested privileged Docker daemon-state scan is not added. It requires a
separate scoped design for privileged filesystem reads and bounded handling of
potentially sensitive daemon data. No daemon-state or malicious-CLI isolation
claim is made by this increment.

## Re-review request

Review the changed harness, tests and workflow, and the new commit's remote run.
In particular, assess whether the leak injections exercise the checks rather than
merely reasserting the implementation. Give separate merge and enablement verdicts.
The former PASS remains historical at its exact head; this is not approval.

Production workflow/policy remain unchanged, hard-disabled and false/null-origin.
No real provider credential, live call, environment/settings change, check
publisher or experiment is authorized. Runtime-token/cache adversarial tests,
malicious CLI tests, protected environment, trusted publisher and real CLI/OAuth/TLS
compatibility remain open. Do not close S2-CR-01 or enable production.
