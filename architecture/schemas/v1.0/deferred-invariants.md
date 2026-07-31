# Deferred Runtime Invariants

Schema-expressible invariants remain in JSON Schema. The following invariants require code, state, time, or cross-artifact knowledge and are handed to Workstream 1C.

```yaml
invariant_id: INV-001
statement: A COMPENSATABLE action's compensation template was prevalidated before the original action was authorized.
reason_deferred: Prevalidation is a historical cross-artifact fact.
owner: Workstream 1C
validator: compensation_prevalidation_check
enforcement_phase: pre-execution
failure_resolution: REJECT
positive_test: INV-001-P
negative_test: INV-001-N
status: OPEN
```

```yaml
invariant_id: INV-002
statement: A compensation action remains authorized and valid against the current state when recovery begins.
reason_deferred: Authorization and state can change after proposal validation.
owner: Workstream 1C
validator: compensation_current_authority_check
enforcement_phase: reconciliation
failure_resolution: ESCALATE
positive_test: INV-002-P
negative_test: INV-002-N
status: OPEN
```

```yaml
invariant_id: INV-003
statement: Every artifact reference resolves to an existing artifact of the declared type.
reason_deferred: Referential integrity spans stored artifacts.
owner: Workstream 1C
validator: artifact_reference_check
enforcement_phase: ingest
failure_resolution: QUARANTINE
positive_test: INV-003-P
negative_test: INV-003-N
status: OPEN
```

```yaml
invariant_id: INV-004
statement: State and plan versions used for authorization equal the current executable versions.
reason_deferred: Current version is runtime state.
owner: Workstream 1C
validator: current_version_check
enforcement_phase: pre-execution
failure_resolution: REPAIR
positive_test: INV-004-P
negative_test: INV-004-N
status: OPEN
```

```yaml
invariant_id: INV-005
statement: Event IDs are unique within the event store.
reason_deferred: Uniqueness is global across records.
owner: Workstream 1C
validator: event_id_uniqueness_check
enforcement_phase: ingest
failure_resolution: QUARANTINE
positive_test: INV-005-P
negative_test: INV-005-N
status: OPEN
```

```yaml
invariant_id: INV-006
statement: Event logical clocks are strictly ordered under the declared concurrency policy.
reason_deferred: Ordering spans an event sequence.
owner: Workstream 1C
validator: logical_clock_order_check
enforcement_phase: replay
failure_resolution: QUARANTINE
positive_test: INV-006-P
negative_test: INV-006-N
status: OPEN
```

```yaml
invariant_id: INV-007
statement: Canonical state versions advance only through legal reducer transitions.
reason_deferred: Legality depends on prior state and event semantics.
owner: Workstream 1C
validator: state_version_transition_check
enforcement_phase: replay
failure_resolution: QUARANTINE
positive_test: INV-007-P
negative_test: INV-007-N
status: OPEN
```

```yaml
invariant_id: INV-008
statement: Replaying the ordered event log from the initial state reproduces the recorded canonical state.
reason_deferred: Requires executing the reducer across the event log.
owner: Workstream 1C
validator: deterministic_replay_check
enforcement_phase: replay
failure_resolution: QUARANTINE
positive_test: INV-008-P
negative_test: INV-008-N
status: OPEN
```

```yaml
invariant_id: INV-009
statement: Tool effects become canonical facts only after verification against tool or environment evidence.
reason_deferred: Verification depends on external evidence and reconciliation.
owner: Workstream 1C
validator: verified_effect_check
enforcement_phase: reconciliation
failure_resolution: REPAIR
positive_test: INV-009-P
negative_test: INV-009-N
status: OPEN
```

```yaml
invariant_id: INV-010
statement: Post-execution audit completes by audit_deadline; missing or unverifiable audit escalates.
reason_deferred: Deadline compliance requires clock and audit state.
owner: Workstream 1C
validator: audit_deadline_check
enforcement_phase: reconciliation
failure_resolution: ESCALATE
positive_test: INV-010-P
negative_test: INV-010-N
status: OPEN
```

```yaml
invariant_id: INV-011
statement: Clarification counters equal the classified QUERY and USER_RESPONSE events in the trace.
reason_deferred: Aggregates must be reconciled with an event sequence.
owner: Workstream 1C
validator: clarification_counter_reconciliation
enforcement_phase: promotion
failure_resolution: QUARANTINE
positive_test: INV-011-P
negative_test: INV-011-N
status: OPEN
```

```yaml
invariant_id: INV-012
statement: An adapter is compatible with the declared base model, target modules, and runtime.
reason_deferred: Compatibility spans model and adapter manifests plus runtime capabilities.
owner: Workstream 1C
validator: adapter_compatibility_check
enforcement_phase: pre-execution
failure_resolution: REJECT
positive_test: INV-012-P
negative_test: INV-012-N
status: OPEN
```

```yaml
invariant_id: INV-013
statement: Dataset splits do not share prohibited seeds, templates, graph structures, or disruption compositions.
reason_deferred: Leakage detection compares multiple instance manifests.
owner: Workstream 1C
validator: split_leakage_check
enforcement_phase: promotion
failure_resolution: QUARANTINE
positive_test: INV-013-P
negative_test: INV-013-N
status: OPEN
```

```yaml
invariant_id: INV-014
statement: Policy-training inputs contain no PRIVATE_ENVIRONMENT, EVALUATOR_ONLY, or VALIDATOR_VISIBLE fields.
reason_deferred: Enforcement requires traversing compiled training examples and projection lineage.
owner: Workstream 1C
validator: policy_input_leakage_check
enforcement_phase: ingest
failure_resolution: QUARANTINE
positive_test: INV-014-P
negative_test: INV-014-N
status: OPEN
```

```yaml
invariant_id: INV-015
statement: Stored content hashes and event-log integrity hashes match canonical serialized content.
reason_deferred: Hash verification requires canonical serialization and stored bytes.
owner: Workstream 1C
validator: artifact_integrity_check
enforcement_phase: ingest
failure_resolution: QUARANTINE
positive_test: INV-015-P
negative_test: INV-015-N
status: OPEN
```

```yaml
invariant_id: INV-016
statement: Episode trace steps belong to the declared episode and have unique contiguous step_index values in ascending order.
reason_deferred: Membership, uniqueness, contiguity, and ordering are cross-item sequence properties.
owner: Workstream 1C
validator: episode_trace_order_check
enforcement_phase: replay
failure_resolution: QUARANTINE
positive_test: INV-016-P
negative_test: INV-016-N
status: OPEN
```
