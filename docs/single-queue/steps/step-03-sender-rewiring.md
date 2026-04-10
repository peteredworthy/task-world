# Step 03: Sender Rewiring

All `WorkflowService` lifecycle methods currently branch on `has_active_workflow()` to decide between direct DB mutation or enqueueing a signal. This step eliminates that branching by making every method unconditionally enqueue signals. The consumer (from Step 02) becomes the sole owner of registry state and RunWorkflow lifecycle. The consumer loop is wired into application startup so that signals are processed automatically.

After this step, every lifecycle transition—start, pause, resume, cancel—flows through the signal queue. The API returns 202 Accepted immediately after enqueueing, and the consumer processes the signal asynchronously.

## Intent Verification

**Original Intent**:
- [I-01] Enqueue RUN_START unconditionally in start_run()
- [I-09] Enqueue PAUSE unconditionally in pause_run()
- [I-10] Enqueue RESUME unconditionally in resume_run()
- [I-11] Enqueue CANCEL unconditionally in cancel_run()
- [I-13] Remove registry calls from service layer
- [I-17] Rewire retry_fan_out_child() to enqueue PAUSE
- [I-27] & [I-28] Wire consumer into executor/app startup

**Functionality to Produce**:
- `WorkflowService.start_run()` enqueues `RUN_START` signal; no direct `executor.spawn_run()` call; no DRAFT→ACTIVE transition in service
- `pause_run()`, `resume_run()`, `cancel_run()` all enqueue their respective signals unconditionally, with no `has_active_workflow()` check
- `RunWorkflow.handle_pause()` no longer calls `unregister_active_run()` (consumer owns registry)
- `retry_fan_out_child()` enqueues PAUSE signal for active runs, without checking `has_active_workflow()`
- Consumer loop starts automatically on app initialization
- All lifecycle transitions flow through the signal queue

**Final Verification Criteria**:
- Grep confirms `has_active_workflow()` not called from `service.py`, `routers/`, or any API-initiated code path
- Integration tests verify each signal is enqueued and consumer processes it (not just presence of enqueue call)
- End-to-end test: create run → start via API → consumer picks up RUN_START → run transitions to ACTIVE
- Full test suite passes (all 565+ backend tests, 221+ frontend tests)
- Type check and linter pass with no errors

---

## Task 1: Rewire start_run() to enqueue RUN_START signal

**Description**:
Replace the direct `executor.spawn_run()` call in `WorkflowService.start_run()` with signal enqueueing. Remove the DRAFT→ACTIVE transition from the service layer—the consumer will own this. Update integration tests to verify the signal is enqueued and the consumer processes it, not just that the method returns.

**Implementation Plan (Do These Steps)**

The goal is to stop calling `executor.spawn_run()` directly and instead insert a signal record. The service method should return immediately after enqueueing (202 Accepted pattern).

- [ ] Open `src/orchestrator/workflow/service.py` and locate `start_run()` (around line 366).
  The method currently calls `engine.start_run(run_id)` (NOT `executor.spawn_run()` — that call
  does not exist in this method). It also calls `self._env_lifecycle.on_run_start()`.
- [ ] Remove the `engine.start_run(run_id)` call from the service method (consumer will own this transition).
- [ ] Remove any DRAFT→ACTIVE transition in the service method (consumer now owns this).
- [ ] Preserve the `self._env_lifecycle.on_run_start()` call — move it to the consumer's
  `_handle_run_start()` handler so it is still invoked after the run transitions to ACTIVE.
- [ ] Add a call to enqueue `RUN_START` signal using the existing `SignalQueue` pattern
  (no `enqueue_signal()` top-level function exists; replicate the pattern from `pause_run()` at line 327):
  ```python
  # Existing code
  run = session.query(Run).get(run_id)
  # REMOVE: engine.start_run(run_id) call
  # REMOVE: Direct DB mutations like run.status = RunStatus.ACTIVE

  # ADD: Enqueue signal (same pattern as pause_run() / cancel_run() in this file)
  from orchestrator.workflow.signals import DbSignalTransport, SignalQueue, WorkflowSignal
  queue = SignalQueue(DbSignalTransport(session))
  queue.enqueue(run_id, WorkflowSignal.RUN_START, payload=None)
  session.commit()
  ```
- [ ] Run existing tests to identify which ones assume synchronous start behavior
- [ ] Update `tests/integration/test_api_full_lifecycle.py` where it calls `start_run()`:
  - After calling `start_run()`, add a poll loop that waits for `pending_signals` to be processed
  - Assert the signal was enqueued: `assert session.query(PendingSignal).filter(...).first()` exists
  - Assert consumer processed it: wait for run status to become ACTIVE (with timeout)
  - Do NOT assert the method returns ACTIVE—it should return DRAFT with a queued signal
- [ ] Run the updated test to confirm it passes
- [ ] Verify `start_run()` does not call `executor` or any registry functions

**Dependencies**
- [ ] Step 01 complete (schema, STOPPING state)
- [ ] Step 02 complete (consumer module exists)
- [ ] `enqueue_signal()` function exists in signals module

**References**
- `src/orchestrator/workflow/service.py` - WorkflowService class
- `src/orchestrator/workflow/signals/signals.py` - enqueue_signal() and WorkflowSignal enum
- `tests/integration/test_api_full_lifecycle.py` - existing start_run tests

**Constraints**
- Only modify `start_run()` in this task; do not change other methods
- Do not remove the parameter validation or error handling for run_id
- Do not modify the return type or API contract—it still returns a Run object (unchanged behavior from API caller's perspective)

**Side Effects**
- `executor.spawn_run()` is no longer called from the service layer
- Runs created via `start_run()` will now have a pending signal in the queue
- Tests that expected synchronous start behavior will need updating

**Functionality (Expected Outcomes)**
- [ ] `start_run()` enqueues a `RUN_START` signal in `pending_signals`
- [ ] `start_run()` does not call `executor.spawn_run()` directly
- [ ] `start_run()` does not transition run status in the service method
- [ ] Consumer processes the `RUN_START` signal asynchronously
- [ ] Run transitions to ACTIVE only after consumer handles the signal

**Final Verification (Proof of Completion)**

DO NOT CHECK THESE UNTIL ALL IMPLEMENTATION STEPS ARE COMPLETE.

- [ ] Integration test: Call `/api/runs/{id}/start`. Verify:
  - A `PendingSignal` row exists with `signal_type='RUN_START'` and `handled_at IS NULL`
  - Run status is still DRAFT (service did not transition it)
  - Within a few seconds, `handled_at` becomes non-null and run status becomes ACTIVE
  - (Test must wait for consumer, not just assert immediately)
- [ ] Grep confirms `engine.start_run()` is not called directly from `start_run()` in `service.py`
- [ ] Grep confirms `start_run()` does not set `run.status = ...`
- [ ] Run full integration test suite: `uv run pytest tests/integration/test_api_full_lifecycle.py -v` — all tests pass

---

## Task 2: Rewire pause_run(), resume_run(), cancel_run() to enqueue signals unconditionally

**Description**:
Remove the `has_active_workflow()` check from all three methods. Each should unconditionally enqueue its respective signal (PAUSE, RESUME, CANCEL). Delete the "active" and "inactive" code branches—one path only.

**Implementation Plan (Do These Steps)**

Currently, each method has a conditional:
```python
if has_active_workflow(run_id):
    # Branch A: direct DB mutation + deliver to RunWorkflow
else:
    # Branch B: write to pending_signals
```

Remove the conditional and always enqueue.

- [ ] Open `src/orchestrator/workflow/service.py` and locate `pause_run(run_id, reason=...)`
- [ ] Remove the `if has_active_workflow(run_id):` check and both branches
- [ ] Replace with unconditional enqueue using the `SignalQueue` pattern already used in this file:
  ```python
  queue = SignalQueue(DbSignalTransport(session))
  queue.enqueue(run_id, WorkflowSignal.PAUSE, payload={'reason': reason})
  session.commit()
  ```
- [ ] Repeat for `resume_run()`:
  ```python
  queue = SignalQueue(DbSignalTransport(session))
  queue.enqueue(run_id, WorkflowSignal.RESUME, payload=None)
  session.commit()
  ```
- [ ] Repeat for `cancel_run()`. **Important:** `cancel_run()` currently has side effects at
  lines 344–362 (env_lifecycle hooks, worktree cleanup). These must be moved to the consumer's
  `_handle_cancel()` handler — do NOT remove them from the codebase entirely:
  ```python
  queue = SignalQueue(DbSignalTransport(session))
  queue.enqueue(run_id, WorkflowSignal.CANCEL, payload={'reason': reason})
  session.commit()
  # NOTE: env_lifecycle.on_run_cancel() and worktree cleanup have been moved to consumer._handle_cancel()
  ```
- [ ] Remove any direct calls to `unregister_active_run()` from these methods (consumer now owns registry)
- [ ] Run tests to identify failures
- [ ] Update `tests/integration/test_api_full_lifecycle.py` test cases for pause/resume/cancel:
  - After API call, wait for signal to be processed (poll for `handled_at IS NOT NULL`)
  - Assert the run transitions to the expected state (PAUSED, ACTIVE, FAILED)
  - Do not assume immediate state change; add polling with timeout
- [ ] Verify no `has_active_workflow()` calls remain in these three methods

**Dependencies**
- [ ] Task 1 complete
- [ ] `enqueue_signal()` supports payload parameter (check signals.py)

**References**
- `src/orchestrator/workflow/service.py` - pause_run, resume_run, cancel_run methods
- `tests/integration/test_api_full_lifecycle.py` - pause/resume/cancel test cases

**Constraints**
- Remove the entire `if has_active_workflow()` conditional; do not refactor it into a separate method
- Preserve the pause_reason parameter in pause_run() (pass it in the payload)
- Preserve error handling for invalid run IDs

**Side Effects**
- Pause/resume/cancel are now asynchronous (queued, not immediate)
- Tests that expected immediate state changes will fail and must be updated
- `has_active_workflow()` function is no longer called from service methods

**Functionality (Expected Outcomes)**
- [ ] `pause_run()` unconditionally enqueues PAUSE signal
- [ ] `resume_run()` unconditionally enqueues RESUME signal
- [ ] `cancel_run()` unconditionally enqueues CANCEL signal
- [ ] No `has_active_workflow()` calls in any of the three methods
- [ ] No direct `unregister_active_run()` calls in service.py
- [ ] Consumer handles the signals asynchronously

**Final Verification (Proof of Completion)**

DO NOT CHECK THESE UNTIL ALL IMPLEMENTATION STEPS ARE COMPLETE.

- [ ] Integration test: Start a run, then call `/api/runs/{id}/pause`. Verify:
  - A PAUSE signal is enqueued in `pending_signals`
  - Run stays ACTIVE initially (pause is not immediate)
  - Within a few seconds, run becomes PAUSED (consumer processed the signal)
- [ ] Integration test: Resume a paused run. Verify:
  - A RESUME signal is enqueued
  - Run transitions PAUSED → ACTIVE (consumer processes)
- [ ] Integration test: Cancel a run. Verify:
  - A CANCEL signal is enqueued
  - Run transitions ACTIVE → STOPPING → FAILED (or PAUSED → FAILED if not active)
- [ ] Grep confirms no `has_active_workflow()` in `pause_run()`, `resume_run()`, `cancel_run()`
- [ ] Run full integration test suite: `uv run pytest tests/integration/test_api_full_lifecycle.py -v` — all tests pass

---

## Task 3: Remove unregister_active_run() call from RunWorkflow.handle_pause()

**Description**:
The consumer is now the sole owner of the active-run registry. Remove the `unregister_active_run()` call from `RunWorkflow.handle_pause()`. The consumer will call it after receiving the pause acknowledgment.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/run_workflow.py` and locate `handle_pause()` method
- [ ] Find the call to `unregister_active_run(self.run_id)` (or similar)
- [ ] Delete that line
- [ ] If the method has any logging that references "unregistering", update it to remove that reference (optional)
- [ ] Verify the method still acknowledges the pause and completes current work (all other logic unchanged)
- [ ] Run tests for RunWorkflow to confirm they still pass (pause/stop behavior unchanged)
- [ ] Run integration tests to confirm pause operations work end-to-end

**Dependencies**
- [ ] Task 1 and 2 complete (pause signals are now enqueued)
- [ ] Step 02 complete (consumer handles registry on ack)

**References**
- `src/orchestrator/workflow/run_workflow.py` - handle_pause method
- `src/orchestrator/workflow/signals/consumer.py` - consumer calls unregister_active_run on ack

**Constraints**
- Only remove the `unregister_active_run()` call; do not change any other pause logic
- The method must still properly acknowledge and gracefully stop work

**Side Effects**
- Registry lifecycle is now exclusively in the consumer module
- No process-local state is mutated from within RunWorkflow

**Functionality (Expected Outcomes)**
- [ ] `handle_pause()` no longer calls `unregister_active_run()`
- [ ] Pause acknowledgment still works
- [ ] Consumer (not RunWorkflow) owns registry cleanup

**Final Verification (Proof of Completion)**

DO NOT CHECK THESE UNTIL ALL IMPLEMENTATION STEPS ARE COMPLETE.

- [ ] Grep confirms `unregister_active_run` is not called from `run_workflow.py`
- [ ] Integration test: Start a run, pause it while active. Verify:
  - Run transitions ACTIVE → STOPPING (consumer sets this)
  - RunWorkflow.handle_pause() is invoked
  - After pause ack, run becomes PAUSED
  - (Consumer called unregister, not RunWorkflow)
- [ ] Run unit tests for RunWorkflow: `uv run pytest tests/unit -k 'run_workflow' -v` — all pass

---

## Task 4: Rewire retry_fan_out_child() to enqueue PAUSE signal

**Description**:
The `retry_fan_out_child()` method currently checks `has_active_workflow()` to decide between pausing a run directly or enqueueing a signal. Remove the check and always enqueue PAUSE for active runs.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/service.py` and locate `retry_fan_out_child()` method
- [ ] Find the `if has_active_workflow(run_id):` check (around lines 1112–1129)
- [ ] Remove the conditional and replace with the `SignalQueue` pattern:
  ```python
  # Always enqueue PAUSE for the fan-out child run (consumer handles both active/inactive cases)
  queue = SignalQueue(DbSignalTransport(session))
  queue.enqueue(run_id, WorkflowSignal.PAUSE, payload={'reason': 'fan_out_child_retry'})
  session.commit()
  ```
- [ ] If there is separate logic for non-active runs (e.g., direct DB pause), remove it—the consumer handles both cases
- [ ] Run tests to identify any failures (update if needed)
- [ ] Verify no `has_active_workflow()` call remains

**Dependencies**
- [ ] Tasks 1–3 complete (pause signal queueing is working)

**References**
- `src/orchestrator/workflow/service.py` - retry_fan_out_child method
- `src/orchestrator/workflow/signals/consumer.py` - handles PAUSE for both active and non-active runs

**Constraints**
- Only modify the retry_fan_out_child logic; do not change other fan-out behavior
- Preserve the reason parameter (e.g., 'fan_out_retry')

**Side Effects**
- Fan-out retries now go through the signal queue (asynchronous)
- Any test expecting synchronous pause must be updated

**Functionality (Expected Outcomes)**
- [ ] `retry_fan_out_child()` enqueues PAUSE signal for the child run
- [ ] No `has_active_workflow()` check
- [ ] Consumer handles the signal (pause active run or pause non-active run)

**Final Verification (Proof of Completion)**

DO NOT CHECK THESE UNTIL ALL IMPLEMENTATION STEPS ARE COMPLETE.

- [ ] Grep confirms `has_active_workflow()` is not called in `retry_fan_out_child()`
- [ ] Integration test: Create a run with fan-out child, trigger retry. Verify:
  - PAUSE signal is enqueued for the child run
  - Consumer processes it and pauses the child
- [ ] Run full integration test suite: `uv run pytest tests/integration/ -v` — all tests pass

---

## Task 5: Wire consumer loop into app startup and verify end-to-end

**Description**:
The consumer loop (from Step 02) must start automatically when the application initializes. Wire it into `app.py` or `executor.py` startup. Verify end-to-end that signals are enqueued and processed in the correct order.

**Implementation Plan (Do These Steps)**

The consumer loop is a background task that polls `pending_signals` continuously. It must be started on app init, not on-demand.

- [ ] Open `src/orchestrator/app.py` (or `executor.py` if using executor-based startup)
- [ ] Import the consumer module: `from orchestrator.workflow.signals.consumer import SignalConsumer`
- [ ] In the app startup (lifespan event or app initialization):
  ```python
  # On app startup
  consumer = SignalConsumer(
      session_factory=session_factory,
      run_workflow_factory=run_workflow_factory,
      poll_interval=0.1  # seconds
  )
  asyncio.create_task(consumer.run())
  ```
  (Adjust parameters based on actual consumer signature from Step 02)
- [ ] Ensure the consumer runs in a background task, not blocking startup
- [ ] Store consumer instance in `app.state` if needed for testing/shutdown
- [ ] Run the application and verify it starts without errors
- [ ] Run existing full integration test suite to ensure nothing broke

**Dependencies**
- [ ] Step 02 complete (consumer module and SignalConsumer class exist)
- [ ] Tasks 1–4 complete (all methods enqueue signals)

**References**
- `src/orchestrator/app.py` - app initialization, lifespan
- `src/orchestrator/executor.py` - if using executor-based startup
- `src/orchestrator/workflow/signals/consumer.py` - SignalConsumer class and run() method

**Constraints**
- Consumer must start on every app initialization
- Do not block app startup; consumer runs in a background task
- Do not remove the existing app startup logic

**Side Effects**
- App startup now includes consumer initialization
- Signals are automatically processed (no manual trigger needed)
- If consumer crashes, it should be restarted (add error handling if needed)

**Functionality (Expected Outcomes)**
- [ ] Consumer loop starts on app initialization
- [ ] Pending signals are polled continuously
- [ ] Signals are dispatched to handlers
- [ ] `delivered_at` and `handled_at` are set correctly
- [ ] Run status transitions are owned by consumer

**Final Verification (Proof of Completion)**

DO NOT CHECK THESE UNTIL ALL IMPLEMENTATION STEPS ARE COMPLETE.

- [ ] Start the application: `uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000 --host 0.0.0.0`
  - Confirm it starts without errors
  - Confirm no "consumer" or "signal" errors in logs
- [ ] End-to-end test: Create run → start via API → verify consumer processes RUN_START → run becomes ACTIVE
  ```bash
  # Create run
  curl -X POST http://localhost:8000/api/runs \
    -H "Content-Type: application/json" \
    -d '{"routine_id": "demo-task", "agent_config": {...}}'

  # Start run
  curl -X POST http://localhost:8000/api/runs/{id}/start

  # Poll for ACTIVE status (consumer processes the signal)
  # Confirm run.status == "ACTIVE" within a few seconds
  ```
- [ ] Integration test: `uv run pytest tests/integration/test_api_full_lifecycle.py::test_full_lifecycle -v`
  - Verify the full flow: create → start → build → verify → complete
  - All transitions go through signal queue
- [ ] Run full backend test suite: `uv run pytest tests/ -v` (all 565+ tests pass)
- [ ] Type check: `uv run pyright src/` — no errors
- [ ] Lint: `uv run ruff check src/` — no errors (or apply auto-fix as needed)

---

## Summary of Phase 3 Completion

After all five tasks are complete:

1. ✅ All lifecycle methods in `WorkflowService` enqueue signals unconditionally
2. ✅ `has_active_workflow()` is no longer called from service or API layer
3. ✅ `RunWorkflow` does not call registry functions (consumer owns them)
4. ✅ Consumer loop runs automatically on app init
5. ✅ All signals are processed asynchronously through the queue
6. ✅ Full test suite passes
7. ✅ Traces to intent items [I-01], [I-09], [I-10], [I-11], [I-13], [I-17], [I-27], [I-28]

The next phase (Step 04) will enforce registry isolation with pre-commit guards.
