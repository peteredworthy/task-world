# GraphProjection Map Inventory

**Status:** Refreshed after the W5 strict payload cutover

`GraphProjection` remains a `TypedDict` because its outer keys are named graph
indexes and most nested maps are dynamic `id -> value` lookups. W5 did not try
to eliminate dictionaries that represent indexes, public JSON, patch values,
or intentionally opaque provider metadata. It eliminated raw event/command
payload boundaries, legacy payload parsing, payload-shaped untyped projection
records, and partial-read field mirrors.

## Projection Value Classes

| Classification | Current examples | Decision |
|---|---|---|
| Primitive dynamic indexes | node/task states, kinds, roles, positions, task regions, attempts, candidates, planner successor/session indexes, active requirement versions, retry times | Keep typed maps such as `dict[str, str]`, `dict[str, int]`, and nested primitive maps. Checkpoint restore validates their shape. |
| Concrete projection records | `LeaseProjection`, `EdgeProjection`, `InputBindingProjection`, `CandidateProjection`, `VerifierVerdictProjection`, `VerificationResultProjection`, `CheckResultProjection`, `InvalidTestBlockProjection`, `EnvironmentFailureProjection`, `RequirementRevisionProjection`, `SupportEvidenceProjection`, `CleanupRequestedProjection` | Store concrete validated values rather than payload dictionaries. |
| Strict business records | `OutputRecordPayload`, `FileStateRecord`, `NodeCreationProjection`, `ApprovalDecisionProjection`, `AuthorityDecisionProjection`, `OversightDecisionProjection`, `PendingGateDecisionProjection`, `CallbackIdempotencyEvent` | Preserve the owning typed record through projection and checkpoint paths. |
| Typed index helpers | `ResourceClaimProjection`, `AcceptedOutputRecord`, `RecoveryNodeIndexEntry`, `LatestRoutineSnapshotRecord`, planner map wrappers | Retain explicit models/wrappers where leaf shape or restore semantics are richer than primitives. |
| Public view records | `GraphRecordSummary`, `FinalInvariantBlocker`, topology/scheduler/decision views | Keep closed `TypedDict` or Pydantic response shapes where JSON output is the contract. |

The outer indexes remain maps because node IDs, record IDs, lease IDs, regions,
ports, and requirements are runtime data. This is not raw payload dispatch.

## Intentionally Flexible Nested Values

These values remain dictionary-shaped by design and must not be described as
untyped event envelopes:

- command definitions and provider-specific command metadata;
- patch operations, macro inputs, diagnostics, and read-set differences;
- edge metadata, contracts, selectors, and policy objects;
- decision actor/scope metadata;
- check command/environment metadata;
- callback-submitted heterogeneous record lists before per-record validation;
- public topology and presentation JSON.

Where the value is JSON, current closed models use `JsonValue` rather than a
catch-all top-level payload field. Flexible nested business values are named
fields owned by a specific model or validation layer. W5's strict payload rule
does not claim every nested dictionary was removed.

## Event And Read Boundaries

The pre-W5 `EventEnvelope.payload` raw-dispatch description is superseded.
Current persistence uses `StoredEventEnvelope` only at the JSON boundary and
returns `HydratedEvent` with one concrete `StrictPayload`. The injected catalog
validates generation 2 and hydrates once before typed reducer dispatch. There
are no legacy output-record models/helpers in the current path and no
`reduce_legacy_event` fallback.

`GraphEventStore.read_run()` is the complete hydrated baseline.
`read_run_light()`, `read_run_summary_rebuild()`, `read_run_projection()`, and
`read_run_node_detail()` delegate to the complete read. Projection/checkpoint
serialization preserves typed projection records, and API presentation
summaries are applied only after hydration. No path mirrors payload fields into
a hand-maintained allowlist.

Task 11 verified payload parity for all five readers:

| Workload | Rows | Payload bytes per reader | Median allocated peak range |
|---|---:|---:|---:|
| Fixture scale, 64 KiB heavy payload every second row | 300 | 19,731,738 | 60,304,850-60,309,546 bytes |
| Generated, 128 KiB heavy payload every second row | 1,000 | 131,308,839 | 397,651,584-397,744,576 bytes |

Payload parity was true for every semantic reader. Physical optimization based
on these measurements remains deferred to
`post-w5-event-column-promotion.md`; it must not reintroduce mirrored field
lists.
