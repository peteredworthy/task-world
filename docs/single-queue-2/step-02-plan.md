# Step Plan: Consumer

## Purpose

Build the consumer loop as new code that reads from the `pending_signals` queue
and dispatches signal handlers. The consumer is the sole entity that creates/destroys
`RunWorkflow` instances and manages the active-run registry. Nothing writes to the
queue via the new paths yet — that happens in Step 3.

## Prerequisites

- **S-01 complete**: Integer PK on `pending_signals`, `delivered_at`/`handled_at`
  columns, `STOPPING` state, `RUN_START` signal type all in place.

## Functional Contract

### Inputs

- `pending_signals` table with integer PK ordering, `delivered_at`, `handled_at`.
- Signal types: `RUN_START`, `RESUME`, `PAUSE`, `CANCEL`, `ACTIVITY_COMPLETED`,
  `ACTIVITY_VERIFIED`.
- `RunWorkflow` factory (injected — DB session, config, broadcaster).

### Outputs

- **`src/orchestrator/workflow/signals/consumer.py`** with:
  - Core loop polling `pending_signals` every 100ms, ordered by integer PK.
  - One `asyncio.Task` per `run_id` — signals for same run processed serially;
    different runs processed concurrently.
  - Sets `delivered_at` before handler invocation, `handled_at` after success.
  - On handler error: leaves `handled_at` null (eligible for redelivery).
- **Signal handlers**:
  - `RUN_START`: DRAFT → ACTIVE, create RunWorkflow, `register_active_run()`.
  - `RESUME`: PAUSED → ACTIVE, create RunWorkflow, `register_active_run()`.
  - `PAUSE` (active RunWorkflow): ACTIVE → STOPPING → PAUSED, `unregister_active_run()`.
  - `PAUSE` (no active RunWorkflow): → PAUSED directly.
  - `CANCEL` (active RunWorkflow): ACTIVE → STOPPING → FAILED, `unregister_active_run()`.
  - `CANCEL` (no active RunWorkflow): → FAILED directly.
  - `ACTIVITY_COMPLETED` / `ACTIVITY_VERIFIED`: deliver to RunWorkflow.
- **Startup redelivery**: On consumer startup, re-dispatch signals where
  `delivered_at IS NOT NULL AND handled_at IS NULL` for inactive runs.
- **Test files**:
  - `tests/unit/test_signal_consumer.py`
  - `tests/unit/test_signal_redelivery.py`

### Error Cases

- Handler raises exception → `handled_at` stays null, signal eligible for redelivery.
- Run already in target state (idempotency) → handler is a no-op, marks handled.
- RunWorkflow factory fails → error logged, signal unhandled for retry.
- Consumer starts with stale `delivered_at` rows → redelivery path picks them up.

## Tasks

1. Create `consumer.py` with core polling loop and per-run task management.
2. Implement `_handle_run_start()` handler (DRAFT → ACTIVE, create RunWorkflow, register).
3. Implement `_handle_resume()` handler (PAUSED → ACTIVE, create RunWorkflow, register).
4. Implement `_handle_pause()` handler (STOPPING path if active, direct if not).
5. Implement `_handle_cancel()` handler (STOPPING path if active, direct if not).
6. Implement `_handle_activity_completed()` and `_handle_activity_verified()` (deliver to RunWorkflow).
7. Implement startup redelivery logic.
8. Write unit tests for FIFO ordering, delivery tracking, error-leaves-unhandled.
9. Write unit tests for each handler with/without active RunWorkflow.
10. Write unit tests for crash recovery redelivery.

## Verification Approach

### Auto-Verify

- Unit tests confirm FIFO ordering: signals with lower PK processed first.
- Unit tests confirm `delivered_at` set before handler, `handled_at` after.
- Unit tests confirm handler error leaves `handled_at` null.
- Each handler tested with both "active RunWorkflow" and "no active RunWorkflow" paths.
- Redelivery test: simulate crash (delivered but not handled), restart consumer,
  confirm signal re-dispatched.
- All existing tests still pass (consumer is additive, not replacing anything yet).

### Manual Verification

- Consumer can be instantiated and started in isolation with mock signals.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 2 (§2.1, §2.2, §2.3)
- Architecture: `docs/single-queue-2/architecture.md` — Consumer Configuration,
  Signal Flow diagrams, Crash Recovery Flow
- Decision: inline runner per run (slow hook blocks that run, not others)
- Decision: 100ms polling interval
- Decision: two-phase delivery tracking (delivered_at before, handled_at after)
