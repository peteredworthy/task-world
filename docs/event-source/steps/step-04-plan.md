# Step 4: Signal System Migration

**Milestone:** M4 — Signal System Migration
**Plan:** [step-04-plan.md](../step-04-plan.md)
**Architecture:** [architecture.md](../architecture.md) §Signal System
**Intent:** [intent.md](../intent.md) — TD-03 (process-local `_active_run_ids` breaks on restart)

## Dry-Run Hardening Applied

- Rebuild `RunLifecycleProjector` from persisted events on startup before signal redelivery begins;
  an in-memory projector only fixes restart behavior when it is rebuilt.
- Define the active status set explicitly and test transitions to paused, failed, completed,
  cancelled, and stopping.
- Make signal drain idempotent under concurrent consumers by treating duplicate
  `SignalProcessed.enqueued_position` claims as already processed.
- Treat stale signals as no-ops during drain in addition to rejecting obviously inactive runs at
  enqueue time.
- Inject lifecycle/projector dependencies into `SignalConsumer`; do not reintroduce globals or
  `app.state` reads.
- Move all producers and consumers off `pending_signals` together and keep a grep/check for legacy
  writes.

## Tasks

### Task 4.1: Add SignalEnqueued and SignalProcessed event types

Add two new Pydantic event model subclasses alongside the existing event
definitions. `SignalEnqueued` carries `run_id`, `signal_type` (string), and
optional `payload` (dict). `SignalProcessed` carries `run_id` and
`enqueued_position` (the `events_v2.position` of the matched
`SignalEnqueued`), linking consumption back to origin.

**Files:** `src/orchestrator/workflow/events/types.py`
**LOC estimate:** ~40
**Verify:** Unit test round-trips both event types through
`.model_dump_json()` / `.model_validate_json()`. Fields are present and
typed correctly. Existing event type tests continue to pass.

### Task 4.2: Implement RunLifecycleProjector

Create `RunLifecycleProjector` (in `src/orchestrator/db/projections/`) that
handles `RunStatusChanged` events to maintain an in-memory set of active
`run_id`s. Expose `is_active(run_id: str) -> bool`. Register the projector in
`ProjectionRegistry` alongside the projectors from Step 02.

**Files:** `src/orchestrator/db/projections/run_lifecycle.py`,
`src/orchestrator/db/projections/__init__.py`
**LOC estimate:** ~80
**Verify:** Unit test feeds `RunStatusChanged(new_status=ACTIVE)` →
`is_active()` returns `True`; then `RunStatusChanged(new_status=PAUSED)` →
`False`. Rebuild via `rebuild(event_stream)` restores correct state.

### Task 4.3: Implement EventSignalTransport

Add `EventSignalTransport(SignalTransport)` to
`src/orchestrator/workflow/signals/signals.py`. `enqueue()` appends a
`SignalEnqueued` event to `SqliteEventStore`. `drain()` queries `events_v2`
for `SignalEnqueued` events that have no matching `SignalProcessed` (by
`enqueued_position`) for the given `run_id`, appends `SignalProcessed` events
to mark them consumed, and returns the corresponding `PendingSignal` list in
FIFO (position) order. The indexed query on `(aggregate_id, event_type)` is
equivalent in performance to the current `pending_signals` table scan.

**Files:** `src/orchestrator/workflow/signals/signals.py`
**LOC estimate:** ~110
**Verify:** Unit test: `enqueue()` then `drain()` returns one signal; second
`drain()` returns empty. `SignalProcessed` event with correct
`enqueued_position` exists in the store after drain. `enqueue()` for an
inactive run (detected via `RunLifecycleProjector`) raises a domain error.

### Task 4.4: Replace _active_run_ids with RunLifecycleProjector

Remove the module-level `_active_run_ids: set[str]`, `register_active_run()`,
`unregister_active_run()`, and `has_active_workflow()` from
`src/orchestrator/workflow/signals/consumer.py`. Replace all call sites inside
`SignalConsumer` with queries to `RunLifecycleProjector.is_active()`. Update
`_redeliver_on_startup` to use the projector instead of the in-memory set.
Remove `register_active_run` / `unregister_active_run` calls in
`_handle_run_start`, `_handle_resume`, `_safe_run_workflow`, and
`_handle_pause` / `_handle_cancel`.

**Files:** `src/orchestrator/workflow/signals/consumer.py`
**LOC estimate:** ~80
**Verify:** `grep -r "active_run_ids" src/` returns no matches.
`grep -r "register_active_run\|unregister_active_run" src/` returns no
matches. Existing `SignalConsumer` unit tests pass (update any that imported
the removed functions).

### Task 4.5: Wire EventSignalTransport into WorkflowService and RunWorkflow

Update `SignalConsumer._find_pending_run_ids()` to query `events_v2` for
distinct `aggregate_id`s that have unprocessed `SignalEnqueued` events (using
`EventSignalTransport` or a direct store query) instead of polling
`pending_signals`. Update the default transport injected into `RunWorkflow` to
`EventSignalTransport`. Update `WorkflowService.pause_run()`, `resume_run()`,
and `cancel_run()` to enqueue signals via `EventSignalTransport` rather than
directly inserting into `pending_signals`.

**Files:** `src/orchestrator/workflow/signals/consumer.py`,
`src/orchestrator/workflow/signals/runtime.py`,
`src/orchestrator/workflow/service.py`
**LOC estimate:** ~130
**Verify:** Integration test: `pause_run()` call results in a
`SignalEnqueued` event in `events_v2`; the runner's `on_signal()` drain
returns the signal and appends `SignalProcessed`. No rows written to
`pending_signals`. `uv run pytest` full suite passes.

### Task 4.6: Alembic migration to mark pending_signals deprecated

Add an Alembic migration that records the deprecation of `pending_signals`.
The migration adds a `_deprecated` column (or a table-level comment in the
migration script) to signal that the table is no longer written by production
code paths. The table is not dropped here — that is deferred to Step 05.

**Files:** `src/orchestrator/db/migrations/versions/<hash>_deprecate_pending_signals.py`
**LOC estimate:** ~30
**Verify:** `uv run alembic upgrade head` completes without error.
`pending_signals` table still exists (verified via schema inspection test).
Migration is reversible (`downgrade` removes the added column).

### Task 4.7: Unit tests for RunLifecycleProjector and EventSignalTransport

Write focused unit tests for the two new components:

- `tests/unit/test_run_lifecycle_projector.py`: active/inactive transitions,
  rebuild from event stream, stale signal rejected when run is inactive.
- `tests/unit/test_event_signal_transport.py`: enqueue/drain round-trip,
  drain idempotency (second drain returns empty), `SignalProcessed`
  `enqueued_position` correctness, concurrent enqueue for same run_id,
  signal for completed run is a no-op (via projector check).

**Files:** `tests/unit/test_run_lifecycle_projector.py`,
`tests/unit/test_event_signal_transport.py`
**LOC estimate:** ~160
**Verify:** `uv run pytest tests/unit/test_run_lifecycle_projector.py
tests/unit/test_event_signal_transport.py` passes. No use of
`pending_signals` in any test assertion.

### Task 4.8: Integration test for signal event delivery and startup recovery

Write `tests/integration/test_signal_events.py` covering three scenarios:

1. **Normal delivery**: enqueue a `SignalEnqueued` event via
   `WorkflowService.pause_run()`; assert the runner's next `on_signal()` call
   returns the signal and a `SignalProcessed` event is appended.
2. **Stale signal**: enqueue a signal after the run transitions to COMPLETED;
   assert the signal is consumed as a no-op (no state change, no error).
3. **Startup recovery**: populate `events_v2` with an unprocessed
   `SignalEnqueued` event, restart `SignalConsumer`, assert the signal is
   redelivered to the resumed run.

**Files:** `tests/integration/test_signal_events.py`
**LOC estimate:** ~160
**Verify:** `uv run pytest tests/integration/test_signal_events.py` passes
for all three scenarios. `uv run pytest` full suite passes with no
regressions.
