# Stage 1 runtime

`conditional_autonomy.storage` provides the append-only persistence boundary.

## Canonical bytes and hash domains

- Canonical JSON is UTF-8 with keys sorted lexicographically, compact `,` and
  `:` separators, Unicode preserved, and non-finite numbers rejected.
- A contract object's canonical content hash is SHA-256 over those bytes after
  removing only the object's top-level `content_hash` field. The returned form
  is `sha256:<64 lowercase hex characters>`.
- Artifact envelopes always record that canonical content hash. If the domain
  object declares its own top-level hash, it must match; contracts without that
  field remain unmodified.
- The event-log hash is SHA-256 over the exact canonical JSONL bytes, including
  one trailing newline per event. Verification rejects noncanonical bytes,
  partial lines, duplicate event IDs, or invalid event content hashes.

Artifact and event-log updates use a flushed temporary file in the destination
directory followed by atomic replacement. Failed staging or interruption before
replacement leaves the preceding complete version visible. A shared-root file
lock serializes the complete durable read/check/write transaction across store
instances and processes, and supported platforms flush the destination directory
after replacement so its new entry is durable.

Run the focused suite from the repository root:

```powershell
python -m unittest tests.test_storage -v
```
