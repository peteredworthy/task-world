# Step 02: Consumer

**Phase:** 2
**Goal:** Build the consumer loop as new code. It reads from the queue but nothing writes to it yet via the new paths.

---

## Purpose and Functionality

Create the consumer module that polls `pending_signals`, dispatches each signal
to the appropriate handler, and manages the active-run registry. The consumer is
the sole owner of `RunWorkflow` lifecycle (create/destroy) and the
`register_active_run`/`unregister_active_run` functions.

---

## Prerequisites / Dependencies

- **S-01 complete:** `pending_signals` table has integer PK, `delivered_at`/`handled_at` columns, `STOPPING` state exists, `RUN_START` signal type defined.

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `pending_signals` rows | DB | Signals with integer PK, ordered by PK |
| Signal types | `WorkflowSignal` enum | RUN_START, RESUME, PAUSE, CANCEL, ACTIVITY_COMPLETED, ACTIVITY_VERIFIED |

### Outputs

| Output | Description |
|--------|-------------|
| `consumer.py` module | Core loop: poll → dispatch → track delivery |
| Signal handlers | RUN_START: DRAFT→ACTIVE, create RunWorkflow, register. RESUME: PAUSED→ACTIVE, create RunWorkflow, register. PAUSE (active): ACTIVE→STOPPING→PAUSED, unregister. PAUSE (inactive): →PAUSED directly. CANCEL (active): ACTIVE→STOPPING→FAILED, unregister. CANCEL (inactive): →FAILED directly. ACTIVITY_COMPLETED/VERIFIED: deliver to RunWorkflow. |
| Delivery tracking | `delivered_at` set before handler invocation, `handled_at` set after success |
| Startup redelivery | Signals with `delivered_at IS NOT NULL AND handled_at IS NULL` for inactive runs are re-dispatched on startup |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Handler error | Signal handler throws exception | Leave `handled_at` null — signal is eligible for redelivery |
| Stale signal | Signal for a run that no longer exists | Log warning, mark as handled |

---

## Verification Strategy

1. **Consumer dispatch tests** (`tests/unit/test_signal_consumer.py`):
   - FIFO ordering by integer PK.
   - `delivered_at` set before handler, `handled_at` after success.
   - Handler error leaves `handled_at` null.
   - Serial processing per `run_id`, concurrent across different `run_id`s.

2. **Signal handler tests** (`tests/unit/test_signal_consumer.py`):
   - Each signal type tested with active RunWorkflow present.
   - Each signal type tested with no active RunWorkflow.
   - STOPPING transitions verified for PAUSE/CANCEL with active workflow.

3. **Startup redelivery tests** (`tests/unit/test_signal_redelivery.py`):
   - Simulate crash: signal delivered but not handled.
   - Restart consumer, confirm redelivery occurs.
   - Signals for active runs are not redelivered (run is already being handled).

4. **Regression:** Existing tests pass — consumer is new code, no existing paths changed.

---

## Files Changed

- New: `src/orchestrator/workflow/signals/consumer.py`
- New: `tests/unit/test_signal_consumer.py`
- New: `tests/unit/test_signal_redelivery.py`

---

## Traces

[I-02], [I-05], [I-12], [I-25], [I-31]
