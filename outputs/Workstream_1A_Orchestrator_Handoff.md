# Workstream 1A — Orchestrator Handoff

**Workstream:** Thesis Architecture Contract Schemas  
**Schema package:** `architecture/schemas/v1.0`  
**Dialect:** JSON Schema Draft 2020-12  
**Current gate:** Batch 0 green and persisted  
**Execution state:** Batch 1 and Batch 2 ready; Batch 3 blocked  

## 1. Purpose of this handoff

This document records what has actually been authored, validated, and committed
for Workstream 1A. It also defines the current ticket state so that the
orchestrator can begin downstream schema implementation without treating draft
or unvalidated material as authoritative.

The authoritative starting point is the `v1.0` schema package. The pre-existing
`architecture/schemas/v0.1` directory is an unvalidated prototype and must not
be used as a contract source or merged into `v1.0` without a reviewed ticket.

## 2. Policy decisions resolved

The following policy questions are closed:

1. **JSON Schema dialect:** Draft 2020-12.
2. **Access-class representation:** every declared instance field carries a
   non-empty `x-access-class` array. A custom linter enforces membership,
   uniqueness, and presence.
3. **Invariant split:** schema-expressible invariants are enforced in JSON
   Schema. Runtime, temporal, semantic, authorization, and cross-artifact
   invariants are recorded in `deferred-invariants.md` and assigned to code
   validators.
4. **Outcome vector scope:** `outcome-vector.schema.json` is a first-class
   contract, not an anonymous inline definition.
5. **Contract inventory:** downstream scope contains thirteen contract schemas.
   `common.defs.schema.json` is shared infrastructure, bringing the complete
   schema-file inventory to fourteen.
6. **Additional contracts:** `tool-outcome.schema.json` and
   `event.schema.json` are explicit leaf contracts.

There are no open specification QUERYs blocking Batch 1 or Batch 2.

## 3. Batch 0 work completed

### 3.1 Shared definitions

`common.defs.schema.json` defines:

- stable identifiers;
- version identifiers;
- SHA-256 content hashes;
- normalized time with source timezone and uncertainty;
- provenance records;
- evidence references;
- access classes;
- provenance sources;
- epistemic statuses;
- validator statuses;
- criticality classes;
- enforceability classes;
- reversibility classes;
- supervisor decisions; and
- time-uncertainty kinds.

The approved enum values are byte-exact. Normalized-time conditionals currently
enforce, among other constraints:

- `EXACT` requires zero uncertainty bounds; and
- `UNKNOWN` requires a null instant.

IANA timezone validity is checked by the package checker because stock JSON
Schema cannot validate membership in the IANA timezone database.

### 3.2 Conventions

`conventions.md` establishes:

- naming and identifier conventions;
- normalized-time semantics;
- access-class annotation semantics;
- schema versus runtime invariant ownership;
- fixture and mutation requirements;
- reference and version rules; and
- worktree discipline.

The worktree rule now explicitly states:

> Session state is not storage. Work is not complete until artifacts are
> written to the repository, validated, reviewed, and committed.

### 3.3 Deferred invariant register

`deferred-invariants.md` contains fifteen structured records. Every record has:

- a unique invariant ID;
- the invariant statement;
- the reason it cannot be fully expressed in JSON Schema;
- an owner;
- a named validator;
- an enforcement phase;
- failure resolution;
- a positive test;
- a negative test; and
- status.

The register hands runtime enforcement work to Workstream 1C without silently
dropping non-schema-expressible requirements.

### 3.4 Validation tooling

`scripts/check_schemas.py` implements the Batch 0 gate:

1. JSON and JSON-compatible manifest parsing;
2. Draft 2020-12 meta-schema validation;
3. unique absolute schema-ID checking;
4. local reference-closure checking;
5. `x-access-class` linting;
6. enum-fidelity checking;
7. positive-fixture validation;
8. negative-fixture validation;
9. mutation detection; and
10. deferred-invariant register validation.

It also verifies the validator versions pinned in `ci-manifest.yaml`.

The primary validator is `jsonschema==4.25.1`. The secondary implementation is
`fastjsonschema==2.21.2`. Dependencies are reproducibly declared in
`architecture/schemas/requirements-schema.txt`; the local `.vendor` directory
used for validation is intentionally ignored by Git.

### 3.5 Fixtures and mutations

The Batch 0 corpus contains:

- one valid shared-definition fixture;
- six invalid fixtures covering conditional time semantics, RFC 3339 date-time
  format, IANA timezone validity, provenance enum fidelity, and version format;
- three active Batch 0 mutations; and
- three downstream mutations retained as blocked until their target schemas
  exist.

The three active mutations prove that the harness detects:

- a removed access annotation;
- a deliberately renamed contract field; and
- a deliberately divergent enum member.

## 4. Validation evidence

Run from the repository root:

```powershell
python architecture\schemas\v1.0\scripts\check_schemas.py
```

The post-commit run reported:

```text
PASS 1 JSON parsing
PASS 2 Meta-schema
PASS 3 Schema IDs
PASS 4 Reference closure
PASS 5 Access lint
PASS 6 Enum fidelity
PASS 7 Positive fixtures
PASS 8 Negative fixtures
PASS 9 Mutation harness
PASS 10 Deferred register
PASS Manifest validator pins
BATCH 0 TECHNICAL GATE: GREEN
```

This is cross-implementation schema and fixture validation. It does not replace
the independent specification-fidelity review required on every downstream
ticket.

## 5. Repository evidence

Two commits establish the current state:

| Commit | Meaning |
|---|---|
| `6fb0289` | `build(schema): complete Workstream 1A Batch 0 gate` |
| `feae593` | `chore(schema): unblock Batch 1 and Batch 2 tickets` |

Batch 0 is therefore both technically green and persisted. It is not dependent
on an interactive session or uncommitted workspace state.

## 6. Current ticket state

### Ready for assignment

| Ticket | Tier | Contract |
|---|---|---|
| B1-1 | Base | `validator-result.schema.json` |
| B1-2 | Base | `supervisor-decision.schema.json` |
| B1-3 | Base | `tool-outcome.schema.json` |
| B1-4 | Base | `outcome-vector.schema.json` |
| B1-5 | Base | `user-model.schema.json` |
| B1-6 | Base | `instance-manifest.schema.json` |
| B1-7 | Base | `adapter-manifest.schema.json` |
| B1-8 | Base | `event.schema.json` |
| B2-1 | Mid | `action-proposal.schema.json` |
| B2-2 | Mid | `canonical-state.schema.json` |
| B2-3 | Mid | `access-scoped-observation.schema.json` |

`READY` authorizes implementation, not automatic merge.

### Still blocked

| Ticket | Contract | Blocking dependency |
|---|---|---|
| B3-1 | `trace-step.schema.json` | B1-1 through B1-8 and B2-1 through B2-3 |
| B3-2 | `episode.schema.json` | B3-1 |

Batch 3 must remain blocked until its referenced contracts have merged and the
reference-closure check can resolve the complete composite graph.

## 7. Required downstream ticket contents

Every Batch 1 and Batch 2 ticket must carry:

1. the exact specification section;
2. a field inventory;
3. an access-class inventory;
4. required, type, enum, pattern, bounds, conditional, and composition
   constraints;
5. at least one valid fixture;
6. one invalid fixture per constraint or documented equivalence class;
7. results from both pinned validators;
8. an independent specification-fidelity review; and
9. any necessary updates to the deferred-invariant register.

Ambiguity between the formal specification and a proposed schema remains a
QUERY for the Lead. Workers must not invent policy.

## 8. Orchestrator execution instructions

1. Assign B1-1 through B1-8 to base-tier workers as independent leaf-schema
   tickets.
2. Assign B2-1 through B2-3 to mid-tier workers. These may run in parallel with
   Batch 1.
3. Give each worker a separate worktree and restrict the worker to its schema,
   fixtures, ticket evidence, and explicitly authorized register changes.
4. Require the package checker to remain green after each integration.
5. Do not allow ad hoc changes to `common.defs.schema.json`. Shared-definition
   changes require a Lead-approved ticket because they fan out across every
   contract.
6. Merge only after independent specification-fidelity review.
7. When all Batch 1 and Batch 2 tickets have merged and reference closure is
   green, change B3-1 to `READY`.
8. Unblock B3-2 only after B3-1 merges.

## 9. Immediate next action

The orchestrator may now start Batch 1 and Batch 2 in parallel. The first
integration checkpoint should confirm:

- every new schema compiles under Draft 2020-12;
- both pinned validators agree on all fixtures;
- every declared field has a valid access-class annotation;
- enum values remain byte-exact;
- all local references close;
- ticket-specific mutations are detected; and
- no worker changed shared definitions without Lead approval.

The authoritative live status is maintained in
`architecture/schemas/v1.0/tickets/README.md`.
