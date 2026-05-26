# Event-Driven Migration — Plan

## Overview

This plan migrates the Orchestrator to event sourcing in six phases: one preparatory milestone (M0) followed by five iterative milestones. Each milestone delivers a working system with all tests passing. The approach is strangler-fig: new event-sourced paths are introduced alongside existing code, validated for parity, then the old paths are removed.

## Milestone 0: Pydantic Event Conversion (Preparatory)

**Deliverable:** All existing event dataclasses (~20 `WorkflowEvent` subclasses such as `RunStatusChanged`, `TaskStatusChanged`, `AgentOutputEvent`, etc.) are converted from Python dataclasses to Pydantic `BaseModel` subclasses. This is a prerequisite for [I-22] and simplifies serialization/validation in later milestones.

**Implementation order:**
1. Convert `WorkflowEvent` base class and all subclasses from `@dataclass` to Pydantic `BaseModel`.
2. Update all event construction sites to use Pydantic model instantiation (keyword args, no positional).
3. Ensure JSON serialization (`.model_dump_json()`) and deserialization (`.model_validate_json()`) work for all event types.
4. Update any existing tests that construct events directly.
5. Validate: all existing tests pass; no behavior changes.

**Dependencies:** None (preparatory).

**Risks:**
- Large surface area (~20 event types, many construction sites). Mitigated by mechanical conversion with automated tests validating each type.
- Pydantic's stricter validation may surface latent type mismatches in existing event data. Fix on encounter.

## Milestone 1: Event Store Foundation

**Deliverable:** A unified event store abstraction that replaces the current dual-write (`EventStore` + `JsonlEventJournal`) with a single append interface backed by SQLite, retaining JSONL as an optional export format.

**Implementation order:**
1. Define `EventStore` protocol with `append(events)`, `get_stream(aggregate_id)`, `get_all(after_position)` in `db/access/`. Factor the concurrency interface (append with version check) behind an abstraction so the retry/conflict strategy can be swapped when migrating to PostgreSQL later.
2. Create a new `events_v2` SQLite table with: `position` (auto-increment), `aggregate_id` (run_id), `event_type`, `payload` (JSON), `timestamp`, `version`. The `UNIQUE(aggregate_id, version)` constraint provides optimistic concurrency control.
3. Implement `SqliteEventStore` satisfying the protocol, with batch append support. On version conflict (UNIQUE constraint violation), retry with exponential backoff (max 3 attempts). The retry logic is encapsulated in a swappable strategy layer.
4. Move JSONL write out of `_persist` (where it was inline, causing the atomicity bug). Implement a `JsonlOutboxObserver` that subscribes to appended events and writes them to JSONL keyed by event sequence number (position). The observer is idempotent: re-appending the same position is a no-op.
5. Add Alembic migration for the new table.
6. Wire `PersistentEventEmitter` to write to `SqliteEventStore` instead of the legacy dual-write path. Register the `JsonlOutboxObserver` as a post-append listener.
7. Validate: all existing tests pass; event append latency measured via integration test.

**Dependencies:** Milestone 0 (events must be Pydantic models for serialization).

**Risks:**
- Migration of existing event data: mitigated by a simple import script that loads legacy JSONL into the new table. This is a one-time operation for the single production instance; if migration fails, the DB can be blown away and rebuilt from JSONL.
- Performance: batch append and single-table design keep write amplification low.
- Concurrent writes: retry with backoff handles rare conflicts; the strategy layer allows switching to PostgreSQL advisory locks or serializable transactions later.

## Milestone 2: Projection Infrastructure

**Deliverable:** A projection framework that subscribes to events and maintains read-model tables, with a CLI command to rebuild projections from scratch.

**Implementation order:**
1. Define `Projector` protocol: `handle(event) -> None`, `rebuild(event_stream) -> None`, with metadata tracking last-processed position.
2. Create `ProjectionRegistry` in `db/` that registers projectors and coordinates rebuilds.
3. Implement `RunStateProjector` — maintains the existing `runs` table state by handling `RunStatusChanged`, `TaskStatusChanged`, `StepCompleted`, etc.
4. Implement `TaskStateProjector` — maintains task/attempt state from task-lifecycle events.
5. Add `orchestrator db rebuild-projections` CLI command that replays all events through all registered projectors.
6. Add integration test: emit a sequence of events, rebuild, assert read-model state matches.
7. Wire projectors into `PersistentEventEmitter` listener chain (called after append).

**Dependencies:** Milestone 1 (event store must exist).

**Risks:**
- Projection rebuild speed: for large event logs, batched processing with progress tracking.
- Schema drift between events and projections: Pydantic models for both, validated on load.
- Rebuild requires a server stop (brief downtime acceptable). No need for live-rebuild coordination logic — stop server, run rebuild, restart.

## Milestone 3: Command-Event Refactor of RunRepository

**Deliverable:** `RunRepository` state mutations are replaced by command handlers that emit events; projectors handle the state updates. The repository becomes a read-only query layer.

**Implementation order:**
1. Identify all `RunRepository` write methods (approximately: `create_run`, `create_task`, `update_run_status`, `update_task_status`, `update_parent_oversight_facts`, `update_checklist`, `set_grade`, etc.). This includes entity creation methods — `RunCreated` and `TaskCreated` events must capture the full initial state for empty-DB rebuild [I-24].
2. For each write method, create a corresponding command handler in `workflow/` that:
   - Validates the command against current state (read from projection).
   - Emits the appropriate event(s).
   - Returns the emitted events.
3. Update `WorkflowService` to call command handlers instead of repository write methods.
4. Verify that projectors correctly update read-model state from the emitted events.
5. Remove write methods from `RunRepository` (it becomes purely a read-model query layer).
6. Validate: all existing tests pass; add command-handler unit tests for each refactored path.

**Dependencies:** Milestone 2 (projectors must handle the events correctly).

**Risks:**
- Large surface area: ~15 write methods to refactor. Mitigated by doing one method at a time with per-method validation.
- Locked JSON merge mechanics in `update_parent_oversight_facts`: complex logic must be preserved in the projector.
- Concurrent access: projectors run synchronously after event append within the same transaction, maintaining current consistency guarantees.

## Milestone 4: Signal System Migration

**Deliverable:** The signal system is event-driven. `_active_run_ids` is eliminated (TD-03 resolved). Signal dispatch is derived from event state.

**Implementation order:**
1. Replace `_active_run_ids` module-level set with a `RunLifecycleProjector` that tracks which runs are active based on `RunStatusChanged` events.
2. Replace `DbSignalTransport` pending_signals table with an event-based approach: signals are events (`SignalEnqueued`, `SignalProcessed`) stored in the event store.
3. Update `RunWorkflow` signal drain to query unprocessed signal events for its run_id.
4. Update `WorkflowService.pause_run()` / `resume_run()` / `cancel_run()` to emit signal events instead of writing to `pending_signals`.
5. Remove `pending_signals` table (new migration marks it deprecated; data migrated to events).
6. Remove `_active_run_ids` set and its registration/unregistration calls.
7. Validate: signal delivery integration tests pass; startup recovery works without the process-local set.

**Dependencies:** Milestone 1 (signals stored as events), Milestone 3 (WorkflowService uses command handlers).

**Risks:**
- Signal delivery latency: polling the event store for unprocessed signals must be as fast as the current table scan. Mitigated by indexed query on `(aggregate_id, event_type, processed)`.
- Race conditions: signal processing marks events as consumed within the same transaction as the handler.

## Milestone 5: Output Batching and Cleanup

**Deliverable:** `AgentOutputEvent` batching resolves TD-09. Legacy dual-write code removed. System fully event-sourced.

**Implementation order:**
1. Implement `OutputBatcher` in `runners/execution/` that accumulates `AgentOutputEvent` lines and flushes to the event store on configurable thresholds. Defaults: 100ms flush interval, 50 lines batch size (both configurable).
2. Replace per-line `EventBroadcaster.emit_log_event()` calls with `OutputBatcher.add_lines()`.
3. Update WebSocket broadcast to work from batched events (maintain `line_offset` ordering).
4. Remove legacy `EventStore` (the old events table), legacy `JsonlEventJournal` inline write path, and `db/recovery/event_journal.py`. The `JsonlOutboxObserver` (introduced in M1) remains as the live JSONL writer.
5. Remove `db/recovery/journal_replay.py` (replaced by `rebuild-projections` command).
6. Remove `db/recovery/recovery.py` startup recovery (replaced by projection-based recovery).
7. Add bootstrap capability: on startup with an empty DB, the bootstrap script reads JSONL to seed `events_v2` and rebuild projections.
8. Final cleanup: remove deprecated `pending_signals` table migration, update `docs/ARCHITECTURE.md`.
9. Performance validation: measure end-to-end API latency, confirm <10% regression target.

**Dependencies:** All previous milestones.

**Risks:**
- Batching introduces small latency for real-time WebSocket updates. Mitigated by configurable flush interval (default 100ms) and immediate flush on phase transitions.
- Removing recovery code: only after projection rebuild is proven reliable in integration tests.

## Implementation Order Summary

```
M0 (Pydantic Event Conversion)
 └─► M1 (Event Store Foundation)
      └─► M2 (Projection Infrastructure)
           └─► M3 (Command-Event Refactor)
                ├─► M4 (Signal System Migration)
                └─► M5 (Output Batching + Cleanup)
```

M0 is a preparatory step that must complete before the main migration begins. M4 and M5 can proceed in parallel after M3, but M5 should be completed last as it removes legacy code that M4 may reference during development.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Pydantic event conversion as separate M0 | Large cross-cutting change (~20 event types); doing it first avoids mixing serialization changes with event-sourcing logic |
| SQLite-backed event store (not pure JSONL) | Indexed queries for projection rebuild and signal lookup; JSONL retained as live secondary write via outbox observer |
| JSONL via outbox observer (not inline in `_persist`) | Fixes atomicity bug; idempotent by sequence number; decouples JSONL from the critical write path |
| Full event sourcing including entity creation | `RunCreated`/`TaskCreated` events enable empty-DB rebuild without baseline snapshots [I-24] |
| Strangler-fig migration (not big-bang) | Each milestone is deployable; rollback is possible per-milestone |
| Projectors run synchronously post-append | Maintains current consistency guarantees; async projectors are future optimization |
| Projection rebuild requires server stop | Simpler implementation; brief downtime is acceptable for this single-instance deployment |
| Retry with backoff for concurrent writes | Handles optimistic concurrency conflicts; strategy layer is swappable for future PostgreSQL migration |
| Simple migration script (not bulletproof) | Single production instance; DB can be blown away and rebuilt from JSONL if migration fails |
| Signals become events | Unifies the two persistence mechanisms; signals gain replay/audit properties |
| Output batching defaults: 100ms / 50 lines | Balances DB write reduction against WebSocket latency; configurable for tuning |
| Output batching is last | Least risky; can be tuned independently after core migration is stable |
| Bootstrap from JSONL on empty DB | Startup reads JSONL when DB is empty to seed events_v2 and rebuild projections |
