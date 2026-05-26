# Event Source Dry-Run Notes

## Summary

This file consolidates the per-step dry-run notes in `docs/event-source/dry-run/`. The dry run
found the expected high-risk areas for an event-sourcing migration: serialization compatibility,
transactional projection behavior, command/event atomicity, signal idempotency, output batching, and
JSONL bootstrap. The significant findings have been applied to the step files as compact
`Dry-Run Hardening Applied` sections.

## Per-Step Simulation Results

| Step | Result | Key Risks Found | Applied to step files |
|------|--------|-----------------|-----------------------|
| Step 00 - Pydantic Event Conversion | Viable with serialization safeguards | Timestamp defaults, mutable defaults, event type preservation, enum/datetime JSON shape | Applied to step files: YES |
| Step 01 - Event Store Foundation | Viable with interface and JSONL compatibility fixes | Alembic chain, retry semantics, emitter/store interface mismatch, outbox write errors, JSONL key compatibility | Applied to step files: YES |
| Step 02 - Projection Infrastructure | Viable if projection failure remains transactional | Swallowed projector errors, checkpoint over-advance, rebuild/live deserialization drift, stale rows on rebuild | Applied to step files: YES |
| Step 03 - Command-Event Refactor | Highest-risk step; needs strict atomicity | Incomplete creation events, double emission, output delta replacement, fan-out retry consistency, repository write shims | Applied to step files: YES |
| Step 04 - Signal System Migration | Viable with startup rebuild and idempotent drain | Lifecycle projector rebuild, duplicate signal processing, stale signals, dependency injection | Applied to step files: YES |
| Step 05 - Output Batching and Cleanup | Viable if cleanup waits for bootstrap proof | Lost tail output, mixed stream buffers, JSONL bootstrap format drift, premature recovery deletion | Applied to step files: YES |

## Persistence Mapping Audit

| State / Event Surface | Event Source | Projection / Consumer | Required Persistence Detail | Status |
|-----------------------|--------------|-----------------------|-----------------------------|--------|
| Workflow event history | `events_v2` | `SqliteEventStore.get_stream()` / `get_all()` | `position`, `aggregate_id`, `event_type`, `payload`, `timestamp`, per-aggregate `version` | Applied to Step 01 |
| JSONL journal continuity | `JsonlOutboxObserver` | Existing JSONL tooling and bootstrap | Legacy-compatible `run_id` and `sequence_number`, or reader support for both legacy/new shapes | Applied to Steps 01 and 05 |
| Run read model | `RunCreated`, `RunStatusChanged`, step/checklist events | `RunStateProjector` | Every non-nullable run column has an event field or deterministic default | Applied to Steps 02 and 03 |
| Task read model | `TaskCreated`, `TaskStatusChanged`, attempt/fan-out events | `TaskStateProjector` | Task/checklist/attempt rows rebuild from events with ordered deltas | Applied to Steps 02 and 03 |
| Projection progress | Appended stored events | `projection_checkpoints` | Per-projector progress advances after successful handling or full rebuild | Applied to Step 02 |
| Signals | `SignalEnqueued`, `SignalProcessed` | `EventSignalTransport`, `RunLifecycleProjector` | Unprocessed signals found by run aggregate and consumed idempotently | Applied to Step 04 |
| Agent output | Batched `AgentOutputEvent` | Activity/WebSocket consumers | Batched rows preserve line order and monotonic offsets | Applied to Step 05 |
| Legacy queue cleanup | Existing `pending_signals` rows | Migration to signal events or empty assertion | No queued work is silently dropped before table removal | Applied to Step 05 |

No MISSING cells remain in the persistence mapping audit.

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Hardening Action | Applied to step files |
|------|--------------|------------|------------------|-----------------------|
| 00 | `timestamp` bound at import time during Pydantic conversion | Medium | Require timestamp `Field(default_factory=...)` and add verification | Applied to step files: YES |
| 00 | Event type or enum/datetime JSON shape changes | High | Preserve `event_type`; standardize `model_dump(mode="json")` / `model_dump_json()` | Applied to step files: YES |
| 01 | Alembic migration forks or has wrong `down_revision` | Medium | Require exact down revision and single-head verification | Applied to step files: YES |
| 01 | Non-conflict exceptions are retried/wrapped as concurrency conflicts | Medium | Re-raise non-conflict exceptions unchanged | Applied to step files: YES |
| 01 | `PersistentEventEmitter` calls old append interface | High | Update emit paths and add `append_batch` transition alias | Applied to step files: YES |
| 01 | JSONL outbox writes records existing tooling cannot read | High | Require legacy-compatible keys or reader compatibility tests | Applied to step files: YES |
| 02 | Projector exception commits partial projection state | High | Let projector exceptions abort append transaction | Applied to step files: YES |
| 02 | Checkpoints advance for projectors that handled no events | Medium | Advance per projector only after successful handling or rebuild | Applied to step files: YES |
| 02 | Rebuild leaves stale projection rows | Medium | Clear projection-owned tables or use deterministic upsert/removal behavior | Applied to step files: YES |
| 03 | Creation events cannot rebuild empty DB | High | Map every non-nullable projection column to event payload/default | Applied to step files: YES |
| 03 | Old repository write and new command handler both emit events | High | Assert exact event counts for converted transitions | Applied to step files: YES |
| 03 | Fan-out retry updates child/parent/step non-atomically | High | Batch fan-out retry events in one append/transaction | Applied to step files: YES |
| 04 | Lifecycle projector loses active state after restart | High | Rebuild projector before redelivery on startup | Applied to step files: YES |
| 04 | Concurrent drains process one signal twice | Medium | Make `SignalProcessed.enqueued_position` idempotent/unique | Applied to step files: YES |
| 05 | Output batcher loses tail lines on exception or pause | High | Flush in `finally`/boundary paths | Applied to step files: YES |
| 05 | Bootstrap skips current JSONL outbox records | High | Support both legacy and outbox JSONL shapes or write compatible outbox records | Applied to step files: YES |
| 05 | Recovery modules deleted before replacement is proven | Medium | Make cleanup depend on passing bootstrap/rebuild tests | Applied to step files: YES |

## Cross-Step Risk Synthesis

- Step 00 is a hard prerequisite for Step 01 because Step 01 serializes events through Pydantic
  methods. Step 01 now includes an explicit prerequisite check for `model_dump_json()`.
- Step 01's listener interface must carry enough context for Step 02 projectors: stored events,
  original workflow events, and the active session. Step 02 now calls this out as a required
  transaction boundary.
- Step 03 must preserve JSONL compatibility established in Step 01, because removing old repository
  writes makes the outbox the live journal path.
- Step 04's event-backed signal queue depends on Step 02 projector rebuild behavior; the lifecycle
  projector must be rebuilt before startup redelivery.
- Step 05 cleanup depends on Step 02 rebuild and Step 05 bootstrap tests passing. Legacy recovery
  modules should be deleted only after the replacement path is verified.

## Plan Changes Recommended

| Change | Confirmation |
|--------|--------------|
| Add dry-run hardening sections to each step file | Applied |
| Preserve legacy-readable JSONL keys or prove reader compatibility | Applied to Steps 01 and 05 |
| Require projection failure to abort append transactions | Applied to Step 02 |
| Require exact event-count tests during command-event refactor | Applied to Step 03 |
| Require lifecycle projector startup rebuild before redelivery | Applied to Step 04 |
| Require output flush on exception/pause/cancel paths | Applied to Step 05 |

