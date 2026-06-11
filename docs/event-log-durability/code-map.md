# Code Map: Event-log Durability

## Event Store Schema

- `src/orchestrator/db/orm/models.py` — `EventV2Model` lines 238-251: ORM mapping for the `events_v2` event log, including global position, aggregate ID, event type, JSON payload, timestamp, per-aggregate version, and uniqueness/index definitions.
- `src/orchestrator/db/migrations/versions/u1a2b3c4d5e6_add_events_v2_table.py` — `upgrade()` lines 25-38: Alembic migration creating `events_v2`, the `(aggregate_id, version)` uniqueness constraint, and stream/type indexes.
- `src/orchestrator/db/migrations/versions/u1a2b3c4d5e6_add_events_v2_table.py` — `downgrade()` lines 41-45: Drops the `events_v2` table and indexes.

## Event Store Access

- `src/orchestrator/db/access/event_store_v2.py` — `StoredEvent` lines 25-33: Stored event DTO returned by the event store and consumed by outbox/projector code.
- `src/orchestrator/db/access/event_store_v2.py` — `EventStore` lines 42-54: Protocol defining append, stream reads, full reads, and activity pagination.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore` lines 57-68: Runtime event store initialized with a SQLAlchemy session, concurrency strategy, outbox listeners, and projection listeners.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.add_listener()` lines 70-72: Registers post-commit secondary output observers such as the JSONL outbox.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.add_projection_listener()` lines 74-76: Registers synchronous projection listeners that run in the append transaction.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.append()` lines 78-143: Appends workflow events to `events_v2`, assigns per-aggregate versions, flushes rows, dispatches projectors, and queues secondary outbox writes.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.get_stream()` lines 145-152: Reads one aggregate stream ordered by position.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.get_all()` lines 154-161: Reads all events after a global position cursor.
- `src/orchestrator/db/access/event_store_v2.py` — `SqliteEventStore.get_events_paginated()` lines 163-187: Serves activity-feed rows from `events_v2`.
- `src/orchestrator/db/access/event_store_v2.py` — `create_wired_event_store_v2()` lines 194-221: Wires the SQLite event store to JSONL outbox and run/task/lifecycle projectors.

## Secondary Journal Sink

- `src/orchestrator/db/access/event_outbox.py` — `EventOutboxBatch` lines 19-25: Queued post-commit observer invocation for secondary event outputs.
- `src/orchestrator/db/access/event_outbox.py` — `queue_event_outbox()` lines 27-37: Adds secondary outbox work to the SQLAlchemy session.
- `src/orchestrator/db/access/event_outbox.py` — `commit_with_event_outbox()` lines 39-51: Commits the DB transaction, then flushes secondary event outputs.
- `src/orchestrator/db/access/event_outbox.py` — `flush_event_outbox()` lines 60-65: Runs queued secondary observers in FIFO order.
- `src/orchestrator/db/access/jsonl_outbox.py` — `resolve_default_journal_path()` lines 19-48: Resolves the JSONL path from environment or SQLite DB path.
- `src/orchestrator/db/access/jsonl_outbox.py` — `resolve_default_journal_path_from_session()` lines 51-56: Resolves the journal path from the current SQLAlchemy session bind.
- `src/orchestrator/db/access/jsonl_outbox.py` — `JsonlOutboxObserver` lines 59-93: Idempotently appends committed stored events to JSONL by `position`.

## Event Serialization

- `src/orchestrator/workflow/events/types.py` — `WorkflowEvent` lines 11-17: Base Pydantic event model carrying timestamp, run ID, and event type.
- `src/orchestrator/workflow/events/types.py` — `TaskStatusChanged` lines 19-28: Task status event used by task projections and lifecycle tests.
- `src/orchestrator/workflow/events/types.py` — `RunStatusChanged` lines 31-38: Run status event used by run projections and lifecycle tests.
- `src/orchestrator/workflow/events/__init__.py` — `_EVENT_TYPE_MAP` lines 67-129: Event type registry used for deserializing stored event payloads.
- `src/orchestrator/workflow/events/__init__.py` — `deserialize_event()` lines 132-140: Converts stored event rows back to typed workflow events for rebuild/bootstrap.
- `src/orchestrator/workflow/events/logger.py` — `PersistentEventEmitter` lines 11-51: Persists events through the configured store and notifies in-process listeners.

## Projection Rebuild

- `src/orchestrator/db/projections/registry.py` — `_expand_events_for_projection()` lines 23-29: Expands `RunCreated` snapshots into projection events before dispatch/rebuild.
- `src/orchestrator/db/projections/registry.py` — `Projector` lines 32-44: Protocol for event-backed read-model projectors.
- `src/orchestrator/db/projections/registry.py` — `ProjectionRegistry` lines 47-63: Holds registered projectors.
- `src/orchestrator/db/projections/registry.py` — `ProjectionRegistry.__call__()` lines 65-105: Dispatches appended events to projectors inside the event-store transaction and updates checkpoints.
- `src/orchestrator/db/projections/registry.py` — `ProjectionRegistry.rebuild_all()` lines 107-122: Replays a full event stream through registered projectors.
- `src/orchestrator/db/projections/run_state.py` — `RunStateProjector` lines 135-163: Declares run/step event types handled by the run-state read model.
- `src/orchestrator/db/projections/run_state.py` — `RunStateProjector.handle()` lines 165-462: Applies run and step events to `runs` and `steps`.
- `src/orchestrator/db/projections/run_state.py` — `RunStateProjector._insert_run_from_snapshot()` lines 464-544: Rebuilds a run row from a `RunCreated` snapshot.
- `src/orchestrator/db/projections/run_state.py` — `RunStateProjector.rebuild()` lines 546-549: Replays handled run-state events.
- `src/orchestrator/db/projections/task_state.py` — `TaskStateProjector` lines 108-135: Declares task/attempt event types handled by the task-state read model.
- `src/orchestrator/db/projections/task_state.py` — `TaskStateProjector.handle()` lines 137-594: Applies task, checklist, clarification, approval, fan-out, and attempt events to task read models.
- `src/orchestrator/db/projections/task_state.py` — `TaskStateProjector.rebuild()` lines 596-599: Replays handled task-state events.
- `src/orchestrator/db/projections/run_lifecycle.py` — `RunLifecycleProjector` lines 16-36: Tracks active and terminal run IDs from status events.
- `src/orchestrator/db/projections/run_lifecycle.py` — `RunLifecycleProjector.handle()` lines 38-55: Applies a `RunStatusChanged` event to in-memory lifecycle state.
- `src/orchestrator/db/projections/run_lifecycle.py` — `RunLifecycleProjector.rebuild()` lines 57-62: Rebuilds lifecycle state from status events.

## Journal Bootstrap And Restore

- `src/orchestrator/db/bootstrap.py` — `_parse_jsonl_record()` lines 31-76: Parses current outbox records and legacy journal records into event-store fields.
- `src/orchestrator/db/bootstrap.py` — `_read_jsonl_records()` lines 79-100: Reads valid JSONL records from a journal file.
- `src/orchestrator/db/bootstrap.py` — `bootstrap_from_jsonl()` lines 103-237: Seeds empty `events_v2` from JSONL and rebuilds projections.
- `scripts/restore_from_journal.py` — `build_projection_registry()` lines 33-39: Builds the standard registry for restore/bootstrap.
- `scripts/restore_from_journal.py` — `restore_from_journal()` lines 42-56: Initializes a DB, bootstraps from JSONL, rebuilds projections, and commits.
- `scripts/restore_from_journal.py` — `parse_args()` lines 59-75: CLI arguments for DB and journal paths.
- `scripts/restore_from_journal.py` — `main()` lines 78-81: CLI entry point for restore.

## Workflow Write Paths

- `src/orchestrator/workflow/service.py` — `WorkflowService.__init__()` lines 338-377: Creates or accepts the wired event store and persistent event emitter for service methods.
- `src/orchestrator/workflow/service.py` — `WorkflowService.create_run()` lines 3615-3623: Persists run creation through `handle_create_run()` and commits with event outbox flushing.
- `src/orchestrator/workflow/service.py` — `WorkflowService.update_checklist_item()` lines 3820-3838: Persists checklist updates through the event store and reloads the projected task item.
- `src/orchestrator/workflow/service.py` — `WorkflowService.request_clarification()` lines 4031-4053: Persists clarification-request events and notifies listeners after store append.
- `src/orchestrator/workflow/commands/run_lifecycle.py` — `CreateRunCommand` lines 104-154: Pydantic command model carrying run, step, task, attempt, and snapshot inputs for event creation.
- `src/orchestrator/workflow/commands/run_lifecycle.py` — `handle_create_run()` lines 511-691: Converts create-run command data into `RunCreated`, `StepCreated`, `TaskCreated`, and attempt events, then appends them.
- `src/orchestrator/workflow/commands/run_lifecycle.py` — `handle_delete_run()` lines 694-705: Appends `RunDeleted` for run deletion.
- `src/orchestrator/workflow/commands/checklist.py` — `handle_update_checklist_item()` lines 27-40: Appends checklist status/note updates.
- `src/orchestrator/workflow/commands/checklist.py` — `handle_set_checklist_grade()` lines 51-64: Appends checklist grading events.

## Existing Verification Surfaces

- `tests/unit/test_projection_rebuild.py` — `test_rebuild_all_restores_run_status()` lines 59-83: Unit coverage for projection rebuild from workflow events.
- `tests/unit/test_projection_rebuild.py` — `test_registry_dispatch_updates_checkpoint()` lines 139-161: Unit coverage for event-store projection listener checkpoint updates.
- `tests/integration/test_projection_recovery.py` — `_store_and_project()` lines 63-83: Integration helper appending to `events_v2` with projectors wired.
- `tests/integration/test_projection_recovery.py` — `test_full_lifecycle_rebuild()` lines 85-131: Integration coverage for corrupting then rebuilding run state from `events_v2`.
- `tests/integration/test_projection_recovery.py` — `test_step_skipped_rebuild_restores_completed_and_current_step_index()` lines 134-204: Integration coverage for rebuilding step skip state.
