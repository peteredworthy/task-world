# Event-Driven Migration — Architecture

## Integration Strategy

### Module Placement

All new code respects the existing 9-module boundary:

| New Component | Module | Location |
|---------------|--------|----------|
| `EventStore` protocol + `SqliteEventStore` | `db` | `src/orchestrator/db/access/event_store_v2.py` |
| `ConcurrencyStrategy` (retry abstraction) | `db` | `src/orchestrator/db/access/concurrency.py` |
| `events_v2` table ORM model | `db` | `src/orchestrator/db/orm/models.py` (extend) |
| `Projector` protocol + `ProjectionRegistry` | `db` | `src/orchestrator/db/projections/` |
| `RunStateProjector`, `TaskStateProjector` | `db` | `src/orchestrator/db/projections/` |
| `RunLifecycleProjector` (active-run tracking) | `db` | `src/orchestrator/db/projections/` |
| `JsonlOutboxObserver` | `db` | `src/orchestrator/db/access/jsonl_outbox.py` |
| Command handlers | `workflow` | `src/orchestrator/workflow/commands/` |
| `OutputBatcher` | `runners` | `src/orchestrator/runners/execution/output_batcher.py` |
| Alembic migrations | `db` | `src/orchestrator/db/migrations/versions/` |
| CLI `rebuild-projections` command | `cli` | `src/orchestrator/cli/db.py` (extend) |

### Data Flow (Post-Migration)

```
API Request / Agent Callback
        ↓
WorkflowService (validates, dispatches command)
        ↓
Command Handler (emits events via BufferingEmitter or direct append)
        ↓
SqliteEventStore.append(events)         ← single write, single source of truth
  ├─ retry with backoff on version conflict (swappable strategy for future PostgreSQL)
        ↓
ProjectionRegistry.notify(events)       ← synchronous, same transaction
        ↓
[RunStateProjector, TaskStateProjector, RunLifecycleProjector, ...]
        ↓
Read-model tables updated (runs, tasks, attempts, etc.)
        ↓
JsonlOutboxObserver.write(events)       ← secondary, keyed by position, idempotent
        ↓
WebSocket broadcast (from events, not projections)
```

### Event Store Schema

```sql
CREATE TABLE events_v2 (
    position    INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id TEXT NOT NULL,          -- run_id (partition key)
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON-serialized event
    timestamp   TEXT NOT NULL,           -- ISO 8601
    version     INTEGER NOT NULL,        -- per-aggregate sequence number
    UNIQUE(aggregate_id, version)
);

CREATE INDEX idx_events_v2_aggregate ON events_v2(aggregate_id, position);
CREATE INDEX idx_events_v2_type ON events_v2(event_type, position);
```

### Projection Metadata

```sql
CREATE TABLE projection_checkpoints (
    projector_name TEXT PRIMARY KEY,
    last_position  INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
);
```

### Command Handler Pattern

```python
class CreateRunCommand(BaseModel):
    run_id: str
    routine_id: str
    project_path: str
    config: dict
    # ... full initial state

async def handle_create_run(
    cmd: CreateRunCommand,
    event_store: SqliteEventStore,
    session: AsyncSession,
) -> list[WorkflowEvent]:
    event = RunCreated(
        run_id=cmd.run_id,
        routine_id=cmd.routine_id,
        project_path=cmd.project_path,
        config=cmd.config,
        # ... full initial state captured for empty-DB rebuild
    )
    await event_store.append([event])
    return [event]

class UpdateRunStatusCommand(BaseModel):
    run_id: str
    new_status: RunStatus
    reason: str | None = None

async def handle_update_run_status(
    cmd: UpdateRunStatusCommand,
    event_store: SqliteEventStore,
    session: AsyncSession,
) -> list[WorkflowEvent]:
    # 1. Read current state from projection
    current = await RunRepository(session).get_run(cmd.run_id)
    # 2. Validate transition
    validate_status_transition(current.status, cmd.new_status)
    # 3. Emit event
    event = RunStatusChanged(
        run_id=cmd.run_id,
        old_status=current.status,
        new_status=cmd.new_status,
        pause_reason=cmd.reason,
    )
    await event_store.append([event])
    return [event]
```

### Projector Pattern

```python
class RunStateProjector:
    """Maintains the `runs` read-model table from lifecycle events."""

    handled_events = {RunCreated, RunStatusChanged, TaskCreated, TaskStatusChanged, StepCompleted}

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        match event:
            case RunCreated():
                session.add(RunModel(
                    id=event.run_id,
                    routine_id=event.routine_id,
                    status="queued",
                    # ... full initial state from event payload
                ))
            case RunStatusChanged():
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(status=event.new_status, ...)
                )
            case TaskCreated():
                session.add(TaskModel(
                    id=event.task_id,
                    run_id=event.run_id,
                    # ... full initial state from event payload
                ))
            case TaskStatusChanged():
                ...

    async def rebuild(self, events: AsyncIterator[WorkflowEvent], session: AsyncSession) -> None:
        """Rebuild requires server stop — no live-event coordination needed."""
        async for event in events:
            if type(event) in self.handled_events:
                await self.handle(event, session)
```

### Concurrency Strategy

The `SqliteEventStore.append()` uses optimistic concurrency control via the `UNIQUE(aggregate_id, version)` constraint. When a conflict occurs (two writers appending the same version for the same aggregate), the store raises a retriable error. A `ConcurrencyStrategy` abstraction encapsulates the retry logic:

```python
class ConcurrencyStrategy(Protocol):
    async def execute_with_retry(self, operation: Callable) -> T: ...

class RetryWithBackoff(ConcurrencyStrategy):
    """SQLite strategy: retry up to 3 times with exponential backoff."""
    max_attempts: int = 3
    base_delay_ms: float = 10.0
```

This is factored as a swappable strategy so that a future PostgreSQL migration can replace it with advisory locks or serializable transactions without changing the event store interface.

### JSONL Outbox Observer

The `JsonlOutboxObserver` subscribes to the `SqliteEventStore` post-append notification and writes events to the JSONL file. It is keyed by event position (sequence number) and idempotent: if the same position is already written (e.g., on retry after a partial failure), the write is skipped.

```python
class JsonlOutboxObserver:
    async def on_events_appended(self, events: list[StoredEvent]) -> None:
        for event in events:
            if not self._already_written(event.position):
                self._append_to_jsonl(event)
                self._mark_written(event.position)
```

On startup with an empty DB, the bootstrap script reads JSONL to seed `events_v2` and rebuild all projections.

### Output Batching

The `OutputBatcher` accumulates `AgentOutputEvent` lines and flushes to the event store when either threshold is reached:
- **Line count:** 50 lines (default, configurable)
- **Time interval:** 100ms (default, configurable)

Immediate flush is triggered on phase transitions (task completion, run pause, etc.) to ensure no output is lost.

## Testing Strategy

### Unit Tests

| What | How | Location |
|------|-----|----------|
| Pydantic event serialization | Construct, serialize, deserialize all event types | `tests/unit/test_pydantic_events.py` |
| Event store append/read | Real in-memory SQLite, `SqliteEventStore` | `tests/unit/test_event_store_v2.py` |
| Concurrency retry strategy | Simulate version conflicts, assert retry behavior | `tests/unit/test_concurrency_strategy.py` |
| JSONL outbox observer | Assert idempotent writes keyed by position | `tests/unit/test_jsonl_outbox.py` |
| Projector logic | Feed events directly, assert read-model state | `tests/unit/test_projectors.py` |
| Command handler validation | Inject fake state, assert events emitted | `tests/unit/test_command_handlers.py` |
| Output batcher flush | Inject clock, assert batch boundaries | `tests/unit/test_output_batcher.py` |
| Projection rebuild | Emit sequence, rebuild, compare | `tests/unit/test_projection_rebuild.py` |

### Integration Tests

| What | How | Location |
|------|-----|----------|
| Full write path | API call → command → event → projection → read-back | `tests/integration/test_event_sourced_workflow.py` |
| Signal migration | Emit signal event, assert runner receives it | `tests/integration/test_signal_events.py` |
| Recovery from event log | Clear read-model, rebuild, assert API returns correct state | `tests/integration/test_projection_recovery.py` |
| Output batching end-to-end | Run agent, assert batched events arrive via WebSocket | `tests/integration/test_output_batching.py` |
| Migration script | Import legacy JSONL, verify events_v2 populated | `tests/integration/test_event_migration.py` |
| Bootstrap from JSONL | Start with empty DB, read JSONL, verify projections | `tests/integration/test_jsonl_bootstrap.py` |

### Parity Testing (Transition Period)

During milestones 2-3, both old and new write paths exist. Parity tests assert that the projection-derived state matches the directly-written state for the same operation sequence. These tests are removed once the old path is deleted in M5.

### Performance Tests

- Event append latency: <5ms for a batch of 10 events (integration test with timing assertions).
- Projection rebuild: process 10,000 events in <10 seconds (benchmarked in CI).
- API response time regression: existing API integration tests with timing thresholds.

## Migration Safety

### Rollback Strategy

Each milestone is independently deployable. Rollback per milestone:

| Milestone | Rollback |
|-----------|----------|
| M0 | Revert Pydantic event models back to dataclasses |
| M1 | Revert migration, restore dual-write in `PersistentEventEmitter` |
| M2 | Remove projectors from listener chain; read-model tables unaffected |
| M3 | Restore `RunRepository` write methods; repoint `WorkflowService` |
| M4 | Restore `DbSignalTransport` and `_active_run_ids` |
| M5 | Restore `EventBroadcaster` per-line writes; restore recovery code |

### Data Migration

- A simple one-time script imports existing JSONL journal entries into `events_v2`.
- Existing `events` table data is also imported (deduplicated by timestamp + run_id + event_type).
- The script is idempotent (skips already-imported positions).
- This is a single-instance deployment; if migration fails, the DB can be blown away and rebuilt from JSONL. No need for bulletproof migration logic.
- On startup with an empty DB, the bootstrap path reads JSONL to seed `events_v2` and rebuild projections automatically.

### Backwards Compatibility

- All REST API response schemas remain unchanged.
- WebSocket event shapes remain unchanged.
- CLI commands retain existing behavior; new commands are additive.
- JSONL export preserves the same format for external consumers.
