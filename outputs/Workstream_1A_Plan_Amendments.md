# Plan Approval Gate - Workstream 1A: JSON Schemas

## Amendment and Decision Record

**Status:** Approved with amendments
**Specification baseline:** Thesis Architecture Formalization v1.1.2
**Schema dialect:** JSON Schema 2020-12
**Workstream objective:** Produce the machine-readable contracts required by the Stage 1 environment, trace, evaluation, and adapter planes without silently weakening or extending the specification.

---

## 1. Approval decisions

### Decision A: JSON Schema dialect

**Approved:** JSON Schema 2020-12.

The workstream will pin a primary validator implementation and version in CI. A second implementation will be used for portability checks before closure.

The CI manifest must declare:

```yaml
schema_draft: "2020-12"
primary_validator: "<implementation and version>"
secondary_validator: "<implementation and version>"
format_assertion: true
```

`format_assertion: true` means values using `format: date-time` must be validated rather than treated only as annotations.

### Decision B: access-class annotations

**Approved with clarified semantics:** Every schema property must carry a machine-readable `x-access-class` annotation.

The allowed classes are byte-exact:

```text
POLICY_VISIBLE
SUPERVISOR_VISIBLE
VALIDATOR_VISIBLE
EVALUATOR_ONLY
PRIVATE_ENVIRONMENT
```

An annotation may contain one or more authorized classes:

```json
{
  "x-access-class": [
    "SUPERVISOR_VISIBLE",
    "VALIDATOR_VISIBLE"
  ]
}
```

Rules:

1. Missing `x-access-class` annotations fail schema lint.
2. Nested properties do not silently inherit access. Every property is annotated explicitly.
3. A nested field may be more restricted than its containing object.
4. A nested field may not become less restricted without an explicit projection or declassification rule.
5. Static schema annotations and runtime `access_class` values serve different purposes:
   - `x-access-class` defines which component types may consume the field.
   - `access_class` labels a particular runtime artifact or reference.
6. The following flows are forbidden unless an explicit, tested projection exists:

```text
PRIVATE_ENVIRONMENT  -/-> POLICY_VISIBLE
EVALUATOR_ONLY       -/-> POLICY_VISIBLE
VALIDATOR_VISIBLE    -/-> POLICY_VISIBLE
SUPERVISOR_VISIBLE   -/-> POLICY_VISIBLE
```

7. `POLICY_VISIBLE` information may flow to authorized downstream components.
8. The data compiler must reject policy-training inputs containing fields restricted to `PRIVATE_ENVIRONMENT`, `EVALUATOR_ONLY`, or `VALIDATOR_VISIBLE`.

### Decision C: invariant split

**Approved:** Schemas enforce every invariant expressible in JSON Schema. Non-local, temporal, operational, or cross-artifact invariants are assigned to code validators through `deferred-invariants.md`.

No invariant may disappear because it is not schema-expressible.

---

## 2. Corrected scope

The original plan contained a counting defect. It added `outcome_vector` but omitted a ticket for `tool_outcome`, even though `trace_step` composes it.

The event-sourced architecture also requires an owned event contract. The `event` schema is therefore included in Workstream 1A rather than left implicit.

### Contract schemas

Workstream 1A will deliver thirteen contract schemas:

1. `canonical_state.schema.json`
2. `access_scoped_observation.schema.json`
3. `event.schema.json`
4. `action_proposal.schema.json`
5. `validator_result.schema.json`
6. `supervisor_decision.schema.json`
7. `tool_outcome.schema.json`
8. `outcome_vector.schema.json`
9. `trace_step.schema.json`
10. `episode.schema.json`
11. `user_model.schema.json`
12. `instance_manifest.schema.json`
13. `adapter_manifest.schema.json`

### Shared support schema

The workstream will also deliver:

14. `common.defs.schema.json`

`common.defs.schema.json` is shared infrastructure and is not counted as a domain contract.

### Supporting artifacts

- `conventions.md`
- `deferred-invariants.md`
- `check_schemas.py`
- Access-class lint rules
- Positive and negative fixtures
- Mutation-test fixtures
- CI configuration

---

## 3. Batch 0 - conventions and shared definitions

**Owner:** Lead
**Blocking:** All downstream schema work

### Deliverables

- `common.defs.schema.json`
- `conventions.md`
- `deferred-invariants.md`
- Portable schema checker
- Reference-closure checker
- Access-class linter
- Fixture runner
- Mutation-test harness

### Shared definitions

Batch 0 must define:

- Stable identifier syntax
- Version identifier syntax
- Content-hash syntax
- Normalized time objects
- Provenance objects
- Evidence references
- Epistemic status
- Access classes
- Every specification enum
- Nullability conventions
- `$id` and `$ref` conventions
- Extension policy
- Compatibility/versioning policy

### Normalized time

Time is represented as a structured object rather than three unrelated fields:

```json
{
  "instant": "2026-11-26T14:00:00Z",
  "source_timezone": "America/New_York",
  "uncertainty": {
    "kind": "EXACT",
    "minus_seconds": 0,
    "plus_seconds": 0
  }
}
```

Allowed uncertainty kinds:

```text
EXACT
BOUNDED
ESTIMATED
UNKNOWN
```

Requirements:

- `instant` uses RFC 3339.
- `source_timezone` uses an IANA timezone identifier.
- `minus_seconds` and `plus_seconds` are nonnegative.
- `EXACT` requires both uncertainty bounds to equal zero.
- `UNKNOWN` must not be silently converted into an exact time.

### Provenance sources

Byte-exact provenance values:

```text
USER
TOOL
ENVIRONMENT
DERIVED_RULE
MODEL_CLAIM
EVALUATOR
```

### Epistemic status

Byte-exact values:

```text
OBSERVED
ASSERTED
INFERRED
UNKNOWN
CONTRADICTED
SUPERSEDED
```

### Other required enums

```text
PASS | FAIL | UNKNOWN
HARD | SOFT
PREVENTABLE | PREDICTIVE | DETECTABLE
REVERSIBLE | COMPENSATABLE | IRREVERSIBLE
APPROVE | REPAIR | QUERY | REJECT | ESCALATE
POLICY_VISIBLE | SUPERVISOR_VISIBLE | VALIDATOR_VISIBLE |
EVALUATOR_ONLY | PRIVATE_ENVIRONMENT
```

Enum spelling and case are contract data. Paraphrases are not allowed.

---

## 4. Batch 1 - leaf schemas

**Execution:** Parallel after Batch 0
**Dependencies:** `common.defs.schema.json` only

Tickets:

1. `validator_result`
2. `supervisor_decision`
3. `tool_outcome`
4. `outcome_vector`
5. `user_model`
6. `instance_manifest`
7. `adapter_manifest`
8. `event`

### Required semantic checks

Examples include:

- `HARD + UNKNOWN` may resolve only to `QUERY` or `ESCALATE`.
- A successful validator result must use the permitted execution resolution defined by the contract.
- Clarification counters required by H3 are present in `outcome_vector`.
- User private state is marked `PRIVATE_ENVIRONMENT`.
- Generator, user-model, validator, evaluator, tool, policy, and adapter versions are explicit.
- Events include stable identity, episode identity, logical order, source, access classification, payload, and integrity metadata.

---

## 5. Batch 2 - structural schemas

**Execution:** May overlap Batch 1 after Batch 0
**Tier:** Mid-tier

Tickets:

1. `action_proposal`
2. `canonical_state`
3. `access_scoped_observation`

### Action proposal requirements

The schema must enforce:

```text
reversibility = COMPENSATABLE
    => compensation_action is non-null
    AND audit_deadline is non-null
```

It must also enforce:

```text
reversibility = IRREVERSIBLE
    => compensation_action is null
```

Schema validity does not prove that compensation was prevalidated or remains executable. Those are deferred runtime invariants.

### Canonical state and observation relationship

`access_scoped_observation` is not a schema child of `canonical_state`.

Both depend on shared definitions:

```text
common.defs
   +-- canonical_state
   +-- access_scoped_observation
```

The runtime projector may derive an observation from canonical state, but the observation schema exposes a deliberately smaller representation and must never inline canonical state.

Required leakage fixtures:

- A valid policy-visible observation.
- An observation containing `PRIVATE_ENVIRONMENT` data that must fail.
- An observation containing an evaluator-only field that must fail.
- A trace with a canonical-state reference that remains `EVALUATOR_ONLY`.

---

## 6. Batch 3 - composite schemas

**Execution:** After required Batch 1 and Batch 2 contracts merge
**Tier:** Mid-tier

Tickets:

1. `trace_step`
2. `episode`

### Trace-step composition

`trace_step` composes:

- Policy-visible observation
- Action proposal
- Supervisor decision
- Validator results
- Tool outcome
- Outcome vector
- Evidence and provenance references
- Transition difference
- Policy and adapter versions

Canonical state is referenced, not embedded:

```json
{
  "canonical_state_ref": {
    "ref_id": "state:episode-1:version-4",
    "access_class": "EVALUATOR_ONLY"
  }
}
```

The acting policy must not receive `canonical_state_ref`.

### Episode composition

`episode` contains:

- Stable episode ID
- Environment/schema versions
- Generator-manifest reference
- User-model reference
- Policy versions
- Ordered trace steps
- Final outcome vector
- Split assignment
- Event-log integrity hash
- Terminal status

Trace ordering, referential integrity, replay equality, and event-log hash correctness are runtime checks unless the chosen representation makes a subset schema-expressible.

---

## 7. Deferred runtime invariants

`deferred-invariants.md` must use this record format:

```yaml
invariant_id: INV-001
statement: "<formal or testable requirement>"
reason_deferred: "<why JSON Schema cannot enforce it>"
owner: "Workstream 1C"
validator: "<checker or function name>"
enforcement_phase: "ingest | pre-execution | reconciliation | replay | promotion"
failure_resolution: "REPAIR | QUERY | REJECT | ESCALATE | QUARANTINE"
positive_test: "<fixture/test ID>"
negative_test: "<fixture/test ID>"
status: "OPEN | IMPLEMENTED | VERIFIED"
```

The initial register must include:

- Compensation action was prevalidated.
- Compensation remains authorized in current state.
- Referenced IDs exist and resolve to the correct artifact type.
- State and plan versions are current.
- Event IDs are unique.
- Event logical clocks are ordered.
- State versions advance legally.
- Event replay reproduces canonical state.
- Tool effects are verified before becoming canonical facts.
- Audit completes by `audit_deadline`.
- Clarification counters agree with query and response events.
- Adapter is compatible with the declared base model.
- Generator split assignment does not leak templates, graph structures, or seeds.
- Policy-training inputs contain no prohibited access classes.

---

## 8. Definition of done

Each schema ticket is complete only when all applicable requirements pass.

### Schema correctness

- Valid JSON
- Valid JSON Schema 2020-12
- Unique `$id`
- Closed and portable `$ref` graph
- Required fields declared
- `additionalProperties` or `unevaluatedProperties` policy explicit
- All properties carry `x-access-class`
- Enums match the specification byte-for-byte
- Conditional constraints encoded where expressible

### Constraint inventory

Every ticket identifies its:

- Required-field constraints
- Type constraints
- Enum constraints
- Pattern constraints
- Numeric bounds
- Conditional constraints
- Access constraints
- Composition constraints

### Fixtures

- At least one valid fixture
- At least one invalid fixture for every declared constraint or justified equivalence class
- Boundary fixtures for numeric and temporal constraints
- Leakage-negative fixtures for observation and trace contracts
- Reference-resolution fixtures for composite schemas

### Review

- Primary validator passes.
- Secondary validator passes.
- Independent reviewer verifies fidelity to the cited specification section.
- Reviewer checks field names, requiredness, enums, access annotations, and conditional semantics rather than only compilation.

### Mutation testing

Seeded defects are introduced only into temporary mutation-test copies.

Required mutations include:

- Rename a required field.
- Change an enum value.
- Remove an access annotation.
- Permit `COMPENSATABLE` with a null compensation action.
- Permit `HARD + UNKNOWN` to execute.
- Inline canonical state into a policy-visible observation.

The test harness passes only when each mutation is detected.

---

## 9. Portable CI entrypoint

The canonical command is:

```text
python scripts/check_schemas.py
```

Optional wrappers may expose it through:

```text
make check
npm run check
tox
nox
CI workflow
```

GNU Make is not a required runtime dependency.

`check_schemas.py` must run:

1. JSON parsing
2. Meta-schema validation
3. `$id` uniqueness
4. `$ref` closure
5. Access-annotation lint
6. Enum-fidelity checks
7. Positive fixtures
8. Negative fixtures
9. Mutation tests
10. Deferred-invariant register completeness

---

## 10. Worktree and change-control rules

1. Each worker modifies only its assigned schema, fixtures, and ticket notes.
2. Workers do not modify `common.defs.schema.json` after Batch 0.
3. A required shared-definition change becomes a Lead-approved ticket.
4. Ambiguous specification language results in `QUERY`; workers do not invent policy.
5. Schema field renames are breaking changes unless an explicit migration is approved.
6. Every merge includes its specification section, constraint inventory, fixtures, and reviewer result.
7. Shared changes are merged before dependent tickets rebase or regenerate fixtures.

---

## 11. Revised sequencing

### Day 1

- Batch 0
- Validator/tooling selection
- Conventions approval
- Deferred-invariant register initialized

### Days 2-3

- Batch 1 leaf schemas in parallel
- Batch 2 structural schemas in parallel
- Lead resolves specification queries

### Day 4

- Batch 3 composite schemas
- Reference-closure testing
- Access-flow lint
- Cross-validator portability run
- Independent specification review
- Mutation-test closure

The estimate assumes specification questions are resolved promptly and validator dependencies are already available.

---

## 12. Exit criteria

Workstream 1A closes when:

- Thirteen contract schemas are merged.
- One shared definitions schema is merged.
- All schemas compile under JSON Schema 2020-12.
- Primary and secondary validators agree on the fixture corpus.
- Every property has a valid access annotation.
- The reference graph is closed.
- Constraint-specific positive and negative fixtures pass.
- Mutation tests demonstrate detection of deliberate drift.
- Independent review confirms fidelity to v1.1.2.
- `deferred-invariants.md` is accepted by Workstream 1C.
- CI is green through the portable Python entrypoint.

---

## Approval statement

Workstream 1A is approved subject to this amendment.

The approved implementation scope is **thirteen contract schemas plus one shared definitions schema**. `tool_outcome` and `event` have explicit ownership. `outcome_vector` remains a standalone contract. Access-scoped observation is a projection sibling of canonical state, not its schema child. Schema-expressible invariants are enforced in JSON Schema; all others are tracked with owners, tests, enforcement phases, and failure resolutions.
