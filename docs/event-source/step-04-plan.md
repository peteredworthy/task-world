# Step 04 — Signal System Migration

## Purpose

Migrate the signal system to be event-driven. Replace the `_active_run_ids`
process-local set with a `RunLifecycleProjector` that derives active-run state
from events. Replace the `pending_signals` table with signal events
(`SignalEnqueued`, `SignalProcessed`) stored in the event store. This resolves
TD-03 (process-local state that breaks on restart).

## Prerequisites / Dependencies

- **Step 01** — event store must be available for signal events.
- **Step 03** — `WorkflowService` must use command handlers so that
  `pause_run()`, `resume_run()`, and `cancel_run()` can be updated to emit
  signal events.

## Functional Contract

### Inputs

| Input | Description |
|-------|-------------|
| `RunLifecycleProjector` | Tracks which runs are active based on `RunStatusChanged` events |
| `SignalEnqueued` event | Replaces `pending_signals` table row insertion |
| `SignalProcessed` event | Marks a signal as consumed |
| `RunWorkflow` signal drain | Reads unprocessed signal events for its `run_id` |

### Outputs

- `RunLifecycleProjector` registered in `ProjectionRegistry`.
- `_active_run_ids` set and all `register_active_run` /
  `unregister_active_run` calls removed.
- `SignalEnqueued` / `SignalProcessed` event types added.
- `WorkflowService.pause_run()`, `resume_run()`, `cancel_run()` emit signal
  events.
- `RunWorkflow` signal drain queries unprocessed signal events instead of
  `pending_signals` table.
- `pending_signals` table marked deprecated (migration adds deprecation;
  table removed in Step 05).

### Errors

| Error | Handling |
|-------|----------|
| Signal delivery to an inactive run | `RunLifecycleProjector` query returns inactive; signal is rejected with a domain error |
| Race condition: signal enqueued during run completion | Signal processing checks run status from projection before executing; stale signals are no-ops |
| Query performance for unprocessed signals | Indexed query on `(aggregate_id, event_type)` in `events_v2`; equivalent to current `pending_signals` table scan |

## Verification Strategy

1. **Unit tests**:
   - `RunLifecycleProjector`: feed `RunStatusChanged` events, assert correct
     active/inactive state.
   - Signal event handlers: enqueue signal, assert `SignalEnqueued` event
     emitted; process signal, assert `SignalProcessed` event emitted.
2. **Integration test** (`tests/integration/test_signal_events.py`):
   - Emit `SignalEnqueued` event, assert runner receives the signal.
   - Test signal delivery after run completion (stale signal is no-op).
3. **Startup recovery test**:
   - Restart with unprocessed signal events in the event store; assert they
     are delivered to the resumed run.
4. **Existing test suite**: `uv run pytest` — full suite passes.
   - Signal delivery integration tests pass.
   - No references to `_active_run_ids` remain in the codebase.

## Deliverables

| Artifact | Location |
|----------|----------|
| `RunLifecycleProjector` | `src/orchestrator/db/projections/` |
| `SignalEnqueued`, `SignalProcessed` events | `src/orchestrator/` (with existing event definitions) |
| Updated `WorkflowService` signal methods | `src/orchestrator/workflow/` |
| Updated `RunWorkflow` signal drain | `src/orchestrator/workflow/` |
| Deprecation migration for `pending_signals` | `src/orchestrator/db/migrations/versions/` |
| Integration test | `tests/integration/test_signal_events.py` |
