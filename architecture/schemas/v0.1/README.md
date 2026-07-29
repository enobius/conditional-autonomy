# Thesis Architecture JSON Schemas v0.1

> **Historical prototype — non-authoritative.** This package predates the
> validated Workstream 1A contracts. Do not use it as an implementation
> contract or copy its fields into `v1.0` without a reviewed ticket. The
> authoritative package is `architecture/schemas/v1.0`.

JSON Schema 2020-12 contracts for the Stage 1 environment and evidence plane.

## Guarantees encoded

- `COMPENSATABLE` proposals require a non-null compensation action and audit deadline.
- `HARD + UNKNOWN` validator results can resolve only to `QUERY` or `ESCALATE`.
- Policy observations are `POLICY_VISIBLE`; canonical trace state is `EVALUATOR_ONLY`; user private state is `PRIVATE_ENVIRONMENT`.
- Clarification categories required by H3 are present in the outcome vector.
- Generator, user model, policy, tool, validator, and adapter versions are explicit.

## Validation

Run `python validate_examples.py` from this directory. The zero-dependency validator checks JSON integrity, unique schema IDs, local reference targets, access rules, and representative positive/negative semantic cases. The schemas target JSON Schema 2020-12 and should additionally be checked with a full implementation such as Python `jsonschema` or Ajv in the project environment.

## Versioning

This package is `v0.1`. Breaking field or semantic changes require a new versioned directory. Additive optional fields may increment the patch version after compatibility tests.
