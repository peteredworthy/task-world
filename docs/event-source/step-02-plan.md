# Step 02 — Projection Infrastructure

## Purpose

Build the projection framework: a `Projector` protocol, a
`ProjectionRegistry` that coordinates event dispatch, and concrete projectors
(`RunStateProjector`, `TaskStateProjector`) that maintain the existing
read-model tables from events. Add a CLI command to rebuild all projections
from the event log (requires server stop).

## Prerequisites / Dependencies

- **Step 01** must be complete — the `SqliteEventStore` must exist so
  projectors can subscribe to appended events and the rebuild command can
  replay the full event stream.

## Functional Contract

### Inputs

| Input | Description |
|-------|-------------|
| `Projector` protocol | `handle(event, session)`, `rebuild(event_stream, session)` |
| `ProjectionRegistry` | Registers projectors; dispatches events; coordinates rebuilds |
| `projection_checkpoints` table | `projector_name` (PK), `last_position`, `updated_at` |
| Event stream from `SqliteEventStore.get_all()` | Full ordered event log for rebuild |

### Outputs

- `RunStateProjector` — handles `RunCreated`, `RunStatusChanged`,
  `TaskCreated`, `TaskStatusChanged`, `StepCompleted`, etc. to maintain the
  `runs` and related read-model tables.
- `TaskStateProjector` — maintains task/attempt state from task-lifecycle
  events.
- `ProjectionRegistry` wired into `PersistentEventEmitter` listener chain
  (called synchronously after `SqliteEventStore.append`).
- `projection_checkpoints` table (Alembic migration).
- `orchestrator db rebuild-projections` CLI command.

### Errors

| Error | Handling |
|-------|----------|
| Unknown event type during projection | Logged and skipped — projectors only handle their declared event set |
| Rebuild on a running server | CLI command should refuse (or warn) if the server lock file exists; rebuild requires server stop |
| Projection checkpoint desync | Rebuild resets the checkpoint to 0 and replays from the beginning |

## Verification Strategy

1. **Unit tests** (`tests/unit/test_projectors.py`):
   - Feed a sequence of events directly to `RunStateProjector`; assert
     read-model table state matches expected values.
   - Same for `TaskStateProjector`.
2. **Unit tests** (`tests/unit/test_projection_rebuild.py`):
   - Emit a sequence of events to the event store, clear read-model tables,
     run rebuild, assert state matches.
3. **Integration test** (`tests/integration/test_projection_recovery.py`):
   - Full lifecycle: create run → update status → clear projections → rebuild
     → verify API returns correct state.
4. **CLI test**: Run `orchestrator db rebuild-projections` against a test DB
   with known events; assert tables populated correctly.
5. **Existing test suite**: `uv run pytest` — full suite passes.

## Deliverables

| Artifact | Location |
|----------|----------|
| `Projector` protocol + `ProjectionRegistry` | `src/orchestrator/db/projections/` |
| `RunStateProjector` | `src/orchestrator/db/projections/` |
| `TaskStateProjector` | `src/orchestrator/db/projections/` |
| `projection_checkpoints` migration | `src/orchestrator/db/migrations/versions/` |
| `rebuild-projections` CLI command | `src/orchestrator/cli/db.py` (extend) |
| Unit tests | `tests/unit/test_projectors.py`, `tests/unit/test_projection_rebuild.py` |
| Integration test | `tests/integration/test_projection_recovery.py` |
