# Step 02: Consumer

Build the consumer loop as new code that polls `pending_signals`, dispatches each signal to the appropriate handler, and manages the active-run registry. The consumer is the sole owner of `RunWorkflow` lifecycle and the registry functions. Nothing writes signals to the queue yet via the new paths (that comes in Step 03), so all existing tests continue to pass.

## Intent Verification

**Original Intent**: [I-02], [I-05], [I-12], [I-25], [I-31] — Consumer module, signal handlers, delivery tracking, redelivery

**Functionality to Produce**:
- Consumer module `src/orchestrator/workflow/signals/consumer.py` that polls `pending_signals` ordered by integer PK
- FIFO signal dispatch: `RUN_START`, `RESUME`, `PAUSE`, `CANCEL`, `ACTIVITY_COMPLETED`, `ACTIVITY_VERIFIED`
- `delivered_at` timestamp set before handler execution, `handled_at` set after success
- Serial per-run processing, concurrent across different run IDs
- Handler error behavior: leave `handled_at` null (signal is eligible for redelivery)
- Signal handlers for RUN_START (DRAFT→ACTIVE), RESUME (PAUSED→ACTIVE), PAUSE/CANCEL (with active/inactive branching), ACTIVITY (deliver to RunWorkflow)
- Startup redelivery: re-dispatch signals where `delivered_at IS NOT NULL AND handled_at IS NULL`
- Registry functions (`register_active_run`, `unregister_active_run`) accessible to consumer and its tests only

**Final Verification Criteria**:
- Consumer dispatch unit tests pass (FIFO ordering, delivery tracking, error handling)
- Signal handler unit tests pass (each signal type with active/inactive RunWorkflow)
- Redelivery unit tests pass (crash recovery, signal re-dispatch on startup)
- Existing integration tests continue to pass (consumer is new code, no rewiring yet)
- All backend tests pass: `uv run pytest tests/ -x --tb=short`

---

## Task 1: Consumer Module Skeleton with Polling Loop

**Description**: Create the foundation of the consumer module with the core polling loop, delivery tracking framework, and handler dispatch structure. This task establishes the basic skeleton that subsequent tasks will fill in with specific handler logic.

**Implementation Plan (Do These Steps)**

The consumer is a long-running loop that polls `pending_signals` ordered by integer PK, sets `delivered_at` before calling handlers, and tracks `handled_at` after success. Signals are processed serially per run_id but concurrently across different run_ids.

- [ ] Create `src/orchestrator/workflow/signals/consumer.py` with polling loop and handler stubs
- [ ] Verify syntax: `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py`

**Functionality (Expected Outcomes)**:
- Consumer module exists at `src/orchestrator/workflow/signals/consumer.py`
- Core polling loop queries unhandled signals in FIFO order
- Handler dispatch routing is in place
- `delivered_at` and `handled_at` tracking framework is in place
- All handler stubs defined but empty

**Final Verification (Proof of Completion)**

- [ ] Syntax check passes: `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py`
- [ ] Module imports: `uv run python -c "from src.orchestrator.workflow.signals.consumer import consume_signals; print('OK')"`

---

## Task 2: Implement RUN_START and RESUME Signal Handlers

**Description**: Implement state machine logic for RUN_START and RESUME handlers, create registry functions, and transition runs from DRAFT→ACTIVE or PAUSED→ACTIVE.

**Implementation Plan (Do These Steps)**

- [ ] Add active-run registry functions: `register_active_run()`, `unregister_active_run()`, `has_active_workflow()`, `get_active_workflow()`
- [ ] Implement `_handle_run_start()`: DRAFT → ACTIVE, create RunWorkflow, register it
- [ ] Implement `_handle_resume()`: PAUSED → ACTIVE, create RunWorkflow, register it
- [ ] Add placeholder `_create_run_workflow()` factory (will be properly injected in task 8)

**Functionality (Expected Outcomes)**:
- RUN_START handler transitions DRAFT→ACTIVE and registers RunWorkflow
- RESUME handler transitions PAUSED→ACTIVE and registers RunWorkflow
- Active-run registry tracks all active workflows by run_id
- No exceptions for valid state transitions

**Final Verification (Proof of Completion)**

- [ ] Module imports: `uv run python -c "from src.orchestrator.workflow.signals.consumer import register_active_run; print('OK')"`

---

## Task 3: Implement PAUSE and CANCEL Signal Handlers

**Description**: Implement PAUSE and CANCEL handlers with logic for both active RunWorkflow (ACTIVE→STOPPING→PAUSED/FAILED) and inactive (direct state transition) cases.

**Implementation Plan (Do These Steps)**

- [ ] Implement `_handle_pause()`: Check if active workflow exists. If yes: ACTIVE→STOPPING, deliver to workflow, then STOPPING→PAUSED, unregister. If no: directly ACTIVE→PAUSED
- [ ] Implement `_handle_cancel()`: Check if active workflow exists. If yes: ACTIVE→STOPPING, deliver to workflow, then STOPPING→FAILED, unregister. If no: directly ACTIVE→FAILED

**Functionality (Expected Outcomes)**:
- PAUSE handler transitions correctly for both active and inactive cases
- CANCEL handler transitions correctly for both active and inactive cases
- STOPPING state used as intermediate for graceful workflow coordination
- RunWorkflow is unregistered after handler completes

**Final Verification (Proof of Completion)**

- [ ] Module imports: `uv run python -c "from src.orchestrator.workflow.signals.consumer import _handle_pause, _handle_cancel; print('OK')"`

---

## Task 4: Implement ACTIVITY Signal Handlers

**Description**: Implement ACTIVITY_COMPLETED and ACTIVITY_VERIFIED handlers that deliver events to the active RunWorkflow.

**Implementation Plan (Do These Steps)**

- [ ] Implement `_handle_activity_completed()`: Get active workflow, extract activity_id and outcome from metadata, deliver to workflow
- [ ] Implement `_handle_activity_verified()`: Get active workflow, extract activity_id and verdict from metadata, deliver to workflow
- [ ] Both should log warning and return (not error) if no active workflow

**Functionality (Expected Outcomes)**:
- ACTIVITY_COMPLETED handler delivers events to RunWorkflow
- ACTIVITY_VERIFIED handler delivers events to RunWorkflow
- Missing RunWorkflow is logged but doesn't cause handler failure

**Final Verification (Proof of Completion)**

- [ ] Module imports: `uv run python -c "from src.orchestrator.workflow.signals.consumer import _handle_activity_completed; print('OK')"`

---

## Task 5: Implement Startup Redelivery Logic

**Description**: Add startup logic that detects and re-dispatches signals which were delivered but not handled (crash recovery).

**Implementation Plan (Do These Steps)**

- [ ] Add `startup_redelivery()` function: Query signals where `delivered_at IS NOT NULL AND handled_at IS NULL`, ordered by PK
- [ ] Re-dispatch each signal through normal handler path
- [ ] Continue redelivery even if individual signals fail
- [ ] Call `startup_redelivery()` at the beginning of `consume_signals()`

**Functionality (Expected Outcomes)**:
- Startup redelivery function exists
- Signals with both delivered_at and null handled_at are queried in FIFO order
- Unhandled signals are re-dispatched
- Consumer startup completes regardless of redelivery errors

**Final Verification (Proof of Completion)**

- [ ] Module imports: `uv run python -c "from src.orchestrator.workflow.signals.consumer import startup_redelivery; print('OK')"`

---

## Task 6: Create Comprehensive Unit Tests

**Description**: Create unit tests for consumer dispatch, delivery tracking, and all signal handlers with mock RunWorkflow instances.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_signal_consumer.py` with ~500 LOC of tests
- [ ] Tests for delivery tracking: `delivered_at` set before handler, `handled_at` after success, null on error
- [ ] Tests for RUN_START handler: DRAFT→ACTIVE transition, RunWorkflow created and registered
- [ ] Tests for RESUME handler: PAUSED→ACTIVE transition, RunWorkflow created and registered
- [ ] Tests for PAUSE handler: both active workflow (ACTIVE→STOPPING→PAUSED) and inactive (direct PAUSED) paths
- [ ] Tests for CANCEL handler: both active workflow (ACTIVE→STOPPING→FAILED) and inactive (direct FAILED) paths
- [ ] Tests for ACTIVITY handlers: delivery to active workflow, logging when no active workflow

**Functionality (Expected Outcomes)**:
- All consumer dispatch tests pass
- All handler behavior tests pass
- Error handling verified (handled_at remains null on handler error)
- Registry operations verified

**Final Verification (Proof of Completion)**

- [ ] All consumer tests pass: `uv run pytest tests/unit/test_signal_consumer.py -v`

---

## Task 7: Create Redelivery Unit Tests

**Description**: Create unit tests for startup redelivery logic that verify signals are correctly re-dispatched on consumer startup.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_signal_redelivery.py` with ~250 LOC of tests
- [ ] Test redelivery queries unhandled signals: `delivered_at IS NOT NULL AND handled_at IS NULL`
- [ ] Test signals are redelivered in PK order (FIFO)
- [ ] Test fully handled signals are ignored
- [ ] Test not-yet-delivered signals are ignored
- [ ] Test redelivery continues even if individual dispatch fails
- [ ] Test consume_signals calls startup_redelivery on startup

**Functionality (Expected Outcomes)**:
- All redelivery tests pass
- Startup redelivery verified to be called on consumer startup
- Idempotency verified (same signal can be redelivered multiple times)

**Final Verification (Proof of Completion)**

- [ ] All redelivery tests pass: `uv run pytest tests/unit/test_signal_redelivery.py -v`

---

## Task 8: Wire Consumer into Executor Startup and Verify All Tests Pass

**Description**: Integrate consumer into application startup as a background task and verify all existing tests continue to pass.

**Implementation Plan (Do These Steps)**

- [ ] Add consumer startup to `src/orchestrator/app.py` using `@app.on_event("startup")`
- [ ] Create consumer task: `asyncio.create_task(consume_signals(SessionLocal))`
- [ ] Add consumer shutdown: cancel task on `@app.on_event("shutdown")`
- [ ] Verify app imports without error
- [ ] Run all integration tests: `uv run pytest tests/integration/ --tb=short -q`
- [ ] Run all unit tests: `uv run pytest tests/unit/ --tb=short -q`
- [ ] Verify full test suite passes

**Functionality (Expected Outcomes)**:
- Consumer task created on app startup
- Consumer continuously polls `pending_signals`
- Consumer gracefully shut down on app shutdown
- All existing integration tests pass (no signal enqueueing yet, so no new work)
- All unit tests pass
- No type errors or linting issues

**Final Verification (Proof of Completion)**

- [ ] App imports: `uv run python -c "from src.orchestrator.app import app; print('OK')"`
- [ ] All integration tests pass: `uv run pytest tests/integration/ -q --tb=line`
- [ ] All unit tests pass: `uv run pytest tests/unit/ -q --tb=line`

---

## Summary

Once all 8 tasks are complete, the Step 02 consumer is ready:

✓ Consumer module exists and polls `pending_signals` in FIFO order
✓ All signal handlers implemented (RUN_START, RESUME, PAUSE, CANCEL, ACTIVITY)
✓ Delivery tracking (delivered_at, handled_at) in place
✓ Startup redelivery enables crash recovery
✓ Registry functions confined to consumer module
✓ Comprehensive unit tests verify all behavior
✓ Consumer wired into app startup
✓ All existing tests pass (no rewiring to existing paths yet)

Next step (Step 03: Sender Rewiring) will enqueue signals from `WorkflowService` methods, making the consumer the central orchestration point for all lifecycle transitions.
