# Workstream 1A Schema Conventions

## Authority and scope

These conventions implement Thesis Architecture Formalization v1.1.2 and the approved Workstream 1A amendment.

`common.defs.schema.json` is shared infrastructure. It is not one of the thirteen domain contract schemas.

The earlier `architecture/schemas/v0.1` directory is an unvalidated prototype and is not an authoritative contract source.

## JSON Schema dialect

- Dialect: JSON Schema 2020-12.
- Every schema declares `$schema`.
- Every schema declares a unique absolute `$id`.
- Relative `$ref` values resolve from the referring schema file.
- Format assertions are enabled in the primary validator.

## Names and files

- Schema filenames use kebab-case: `validator-result.schema.json`.
- JSON property names use snake_case: `validator_version`.
- Stable IDs are opaque identifiers and must not be parsed for business meaning.
- Version identifiers are bounded opaque strings. They may contain letters, digits, `.`, `_`, `:`, `+`, and `-`.
- Enum spelling and case are contract data and must match the specification byte-for-byte.

## Closed objects

Contract objects use `additionalProperties: false` unless a specification section explicitly requires an open extension map.

Open maps must:

1. State why arbitrary keys are required.
2. Constrain their values.
3. Carry an access-class annotation on the map property.

## Nullability

Optional and nullable are different:

- An optional property may be absent.
- A nullable property is present and may contain `null`.

Conditional contracts must not depend on accidental absence when the specification requires an explicit state.

## Normalized time

Time uses `$defs.normalizedTime`:

- `instant` is RFC 3339 or `null` only when uncertainty is `UNKNOWN`.
- `source_timezone` is an IANA timezone identifier.
- `uncertainty.kind` is `EXACT`, `BOUNDED`, `ESTIMATED`, or `UNKNOWN`.
- Uncertainty bounds are nonnegative seconds.
- `EXACT` requires zero bounds and a non-null instant.
- `UNKNOWN` requires a null instant.

IANA timezone membership is checked by the portable checker because JSON Schema has no standard timezone format.

## Access annotations

Every entry under a JSON Schema `properties` object must declare `x-access-class` as a non-empty array of allowed access classes.

Static schema annotations define authorized consumers. Runtime `access_class` fields label particular artifacts.

No restricted field becomes policy-visible merely because its parent is policy-visible. Projection is explicit and tested.

Forbidden flows without an approved projector:

```text
PRIVATE_ENVIRONMENT  -/-> POLICY_VISIBLE
EVALUATOR_ONLY       -/-> POLICY_VISIBLE
VALIDATOR_VISIBLE    -/-> POLICY_VISIBLE
SUPERVISOR_VISIBLE   -/-> POLICY_VISIBLE
```

## Invariants

Schemas enforce local structural invariants. Cross-artifact, temporal, environmental, and authorization invariants are recorded in `deferred-invariants.md`.

Deferral is not deletion. Every deferred invariant has an owner, enforcement phase, failure resolution, and positive/negative test IDs.

## Fixtures

- Valid fixtures live under `fixtures/valid`.
- Invalid fixtures live under `fixtures/invalid`.
- Each invalid fixture declares the constraint it is expected to violate in `fixture-manifest.json`.
- A fixture must fail for its intended reason, not merely for an unrelated missing field.

## Change control and persistence

1. Workers modify only their assigned schema, fixtures, and ticket notes.
2. Changes to `common.defs.schema.json` after Batch 0 require a Lead-approved ticket.
3. Ambiguity is a `QUERY`; workers do not invent policy.
4. Session state is not storage. Work is not complete until artifacts are written to the repository, validated, reviewed, and committed.
5. A schema field rename is a breaking change unless a migration is approved.
6. Generated or temporary mutation files must never be committed as production schemas.

## Canonical check

Run:

```powershell
python scripts/check_schemas.py --batch all
```

`make check` or another task runner may wrap this command, but the Python entrypoint is canonical.
