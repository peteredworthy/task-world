# Step 03: Sender Rewiring

All lifecycle methods in `WorkflowService` currently branch on `has_active_workflow` to decide
whether to write signals or mutate the database directly. This step rewires every method to
unconditionally enqueue signals. The consumer (from Step 02) becomes the sole arbiter of
whether a RunWorkflow is active, removing the sender's need to know process-local state.

After this step, all lifecycle transitions—start, pause, resume, cancel—flow through the
signal queue. The consumer loop is wired into executor startup so that signals are processed
immediately upon enqueueing.

## Intent Verification

**Original Intent**: [I-01], [I-09], [I-10], [I-11], [I-13], [I-17], [I-27], [I-28] from `docs/single-queue/intent.md`

**Functionality to Produce**:
- `start_run()` enqueues `RUN_START` signal; no direct `executor.spawn_run()` call from service layer
- `pause_run()` enqueues `PAUSE` signal unconditionally; no `has_active_workflow` check
- `resume_run()` enqueues `RESUME` signal unconditionally; no `has_active_workflow` check
- `cancel_run()` enqueues `CANCEL` signal unconditionally; no `has_active_workflow` check
- `retry_fan_out_child()` enqueues `PAUSE` for active runs; no `has_active_workflow` check in service
- `RunWorkflow.handle_pause()` no longer calls `unregister_active_run()` (consumer owns this)
- Consumer loop starts as part of executor/app initialization; processes queued signals
- All lifecycle transitions observable via API (status changes propagate as signals are processed)

**Final Verification Criteria**:
- Grep confirms no `has_active_workflow()` calls in `service.py`, `routers/`, or API-initiated code paths
- Integration test: `start_run()` → signal enqueued → consumer processes → RunWorkflow created
- Integration test: `pause_run()` on active run → STOPPING state → PAUSED (consumer-driven)
- Integration test: `cancel_run()` on active run → STOPPING state → FAILED (consumer-driven)
- Full test suite passes; no regression in existing lifecycle tests
- Pre-commit guard (`check_signal_routing.py`) passes on modified code

---

## Task 1: Rewire `start_run()` to Enqueue RUN_START Signal

**Description**:
Replace the direct call to `executor.spawn_run()` with an enqueue of the `RUN_START` signal.
The service method will no longer perform the DRAFT→ACTIVE transition; the consumer will handle
this after dequeuing the signal.

**Implementation Plan (Do These Steps)**

The current implementation calls `executor.spawn_run()` synchronously, which creates a RunWorkflow
immediately. We will replace this with `enqueue_signal(...)` and remove the DB transition logic
from the service layer.

- [ ] Open `src/orchestrator/workflow/service.py` and locate the `start_run()` method
- [ ] Remove the line that calls `executor.spawn_run(run_id, ...)` directly
- [ ] Replace it with a call to `enqueue_signal()` with signal type `WorkflowSignal.RUN_START`
  ```python
  # Before:
  executor.spawn_run(run_id, ...)

  # After:
  enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.RUN_START, context={...})
  ```
- [ ] Verify that `start_run()` no longer performs the DRAFT→ACTIVE DB transition (the consumer will do this)
- [ ] Run unit tests for `WorkflowService` to confirm no immediate breakage
  ```bash
  uv run pytest tests/unit/test_workflow_service.py -v
  ```

**Dependencies**
- [ ] `src/orchestrator/workflow/signals/signals.py` must export `enqueue_signal()` function (created in S-02)
- [ ] `WorkflowSignal.RUN_START` enum value must exist (created in S-01)
- [ ] Consumer loop must be running to process the signal (Task 4 in this step)

**References**
- [Single-Queue Plan: Phase 3.1](../plan.md#31-rewire-start_run)
- [S-02: Consumer Module](../steps/step-02-plan.md)

**Constraints**
- Only modify `start_run()` method; do not change other WorkflowService methods in this task
- Do not remove the method signature or its return value (still returns run object)
- Do not alter the API contract (router still receives 202 or equivalent)

**Functionality (Expected Outcomes)**
- [ ] `start_run()` calls `enqueue_signal(RUN_START)` instead of `executor.spawn_run()`
- [ ] No DRAFT→ACTIVE transition happens in `start_run()` (deferred to consumer)
- [ ] Existing run object is returned to caller (for API response)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Grep confirms `executor.spawn_run()` is not called in `start_run()`
  ```bash
  grep -n "executor.spawn_run" src/orchestrator/workflow/service.py | grep -v "^#" || echo "No direct spawn calls found"
  ```
- [ ] Run integration test: signal is enqueued and consumer processes it
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_start_run_via_signal -v
  ```
- [ ] No regression in other service tests:
  ```bash
  uv run pytest tests/unit/test_workflow_service.py -v
  ```

---

## Task 2: Rewire `pause_run()`, `resume_run()`, `cancel_run()` to Enqueue Signals

**Description**:
These three methods currently branch on `has_active_workflow` and either call handlers directly or
write to the database. Rewire each to unconditionally enqueue its respective signal (`PAUSE`,
`RESUME`, `CANCEL`) and remove all branching logic.

**Implementation Plan (Do These Steps)**

Each method follows the same pattern: remove the `has_active_workflow` check and replace the
entire if/else tree with a single `enqueue_signal()` call.

- [ ] Open `src/orchestrator/workflow/service.py` and locate `pause_run()` method
- [ ] Remove the entire `if has_active_workflow(run_id):` branch
- [ ] Replace with:
  ```python
  enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.PAUSE, context={"reason": reason})
  return None  # or return run object, matching existing API contract
  ```
- [ ] Locate `resume_run()` method and apply the same pattern
  ```python
  enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.RESUME, context={})
  ```
- [ ] Locate `cancel_run()` method and apply the same pattern
  ```python
  enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.CANCEL, context={})
  ```
- [ ] Verify no `has_active_workflow()` calls remain in any of these three methods
- [ ] Run unit tests for `WorkflowService`
  ```bash
  uv run pytest tests/unit/test_workflow_service.py -v
  ```

**Dependencies**
- [ ] `enqueue_signal()` function available in signals module
- [ ] `WorkflowSignal.PAUSE`, `WorkflowSignal.RESUME`, `WorkflowSignal.CANCEL` enum values exist
- [ ] Consumer handlers for these signals implemented (S-02)

**References**
- [Single-Queue Plan: Phase 3.2](../plan.md#32-rewire-pause_run-resume_run-cancel_run)
- [Consumer Handlers (S-02)](../steps/step-02-plan.md)

**Constraints**
- Remove all `has_active_workflow()` calls from these three methods
- Do not change the API contract (methods still return 202 or equivalent)
- Do not alter error handling for invalid state transitions (guards in `engine.py` handle this)

**Side Effects**
- Tests that assumed synchronous ACTIVE→PAUSED transition will now see ACTIVE→STOPPING→PAUSED
- Existing integration tests must be updated (Task 5)

**Functionality (Expected Outcomes)**
- [ ] `pause_run()` unconditionally enqueues `PAUSE` signal with reason
- [ ] `resume_run()` unconditionally enqueues `RESUME` signal
- [ ] `cancel_run()` unconditionally enqueues `CANCEL` signal
- [ ] No `has_active_workflow` checks remain in service layer for lifecycle methods

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Grep confirms no `has_active_workflow()` calls in these three methods
  ```bash
  grep -A 20 "def pause_run\|def resume_run\|def cancel_run" src/orchestrator/workflow/service.py | grep "has_active_workflow" && echo "FAIL: has_active_workflow found" || echo "PASS: No has_active_workflow calls"
  ```
- [ ] Integration test: pause active run → STOPPING state observable
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_pause_run_via_signal -v
  ```
- [ ] Integration test: cancel active run → STOPPING state observable
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_cancel_run_via_signal -v
  ```
- [ ] No regression in service unit tests:
  ```bash
  uv run pytest tests/unit/test_workflow_service.py -v
  ```

---

## Task 3: Rewire `retry_fan_out_child()` and Remove Registry Call from `RunWorkflow.handle_pause()`

**Description**:
`retry_fan_out_child()` in the service currently checks `has_active_workflow` and calls handlers
directly. Rewire it to enqueue a `PAUSE` signal. Separately, remove the `unregister_active_run()`
call from `RunWorkflow.handle_pause()` because the consumer (not the workflow) owns the registry.

**Implementation Plan (Do These Steps)**

This task touches two files and removes process-local state coupling.

- [ ] Open `src/orchestrator/workflow/service.py` and locate `retry_fan_out_child()` method
- [ ] Remove the `has_active_workflow` check
- [ ] If the run is active (we're enqueueing a signal that may reach an active workflow), enqueue `PAUSE`:
  ```python
  enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.PAUSE, context={"reason": "fan_out_failed"})
  ```
- [ ] Open `src/orchestrator/workflow/run_workflow.py` and locate the `handle_pause()` method
- [ ] Remove the line that calls `unregister_active_run(run_id)` (the consumer will do this)
- [ ] Verify `handle_pause()` still returns an ack or status but does not touch the registry
- [ ] Run unit tests:
  ```bash
  uv run pytest tests/unit/test_workflow_service.py tests/unit/test_run_workflow.py -v
  ```

**Dependencies**
- [ ] `enqueue_signal()` function available
- [ ] `WorkflowSignal.PAUSE` enum value exists
- [ ] Consumer `handle_pause()` handler will call `unregister_active_run()` when ack'd

**References**
- [Single-Queue Plan: Phase 3.3](../plan.md#33-rewire-retry_fan_out_child)
- [Consumer PAUSE Handler (S-02)](../steps/step-02-plan.md#22-signal-handlers-in-consumer)

**Constraints**
- Only modify `retry_fan_out_child()` and `RunWorkflow.handle_pause()` in this task
- Do not change the method signatures or return values
- The registry removal is critical: `unregister_active_run()` must NOT be called from the workflow

**Side Effects**
- `RunWorkflow.handle_pause()` will no longer directly unregister itself
- Consumer becomes the sole caller of `unregister_active_run()`

**Functionality (Expected Outcomes)**
- [ ] `retry_fan_out_child()` enqueues `PAUSE` signal for active runs
- [ ] `RunWorkflow.handle_pause()` does not call `unregister_active_run()`
- [ ] Registry functions called only from consumer module (enforced in Phase 5)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Grep confirms no `has_active_workflow()` in `retry_fan_out_child()`
  ```bash
  grep -A 15 "def retry_fan_out_child" src/orchestrator/workflow/service.py | grep "has_active_workflow" && echo "FAIL" || echo "PASS"
  ```
- [ ] Grep confirms no `unregister_active_run()` call in `RunWorkflow.handle_pause()`
  ```bash
  grep -A 20 "def handle_pause" src/orchestrator/workflow/run_workflow.py | grep "unregister_active_run" && echo "FAIL: unregister found" || echo "PASS"
  ```
- [ ] Unit tests pass:
  ```bash
  uv run pytest tests/unit/test_workflow_service.py tests/unit/test_run_workflow.py -v
  ```

---

## Task 4: Wire Consumer into Executor/App Startup

**Description**:
The consumer loop must be running for signals to be processed. Start the consumer as part of
executor or app initialization. This is the point where the new architecture becomes active.

**Implementation Plan (Do These Steps)**

The consumer loop is a background task that polls the signal queue. We will start it in the
executor (or in `app.py` if the executor does not have a startup hook).

- [ ] Open `src/orchestrator/executor.py` and locate the `__init__` or startup method
- [ ] Add code to start the consumer loop as an asyncio Task or background thread:
  ```python
  # In __init__ or startup:
  self.consumer_task = asyncio.create_task(self.consumer.run())
  ```
  (or equivalent, depending on executor architecture)
- [ ] Alternatively, if executor does not have startup hooks, add to `src/orchestrator/app.py` in
  the `lifespan` context manager or `@app.on_event("startup")` hook:
  ```python
  @app.on_event("startup")
  async def start_consumer():
      consumer = SignalConsumer(db_session_factory, ...)
      asyncio.create_task(consumer.run())
  ```
- [ ] Ensure the consumer has access to a DB session factory and any other dependencies it needs
  (pass via constructor or app.state)
- [ ] Add a shutdown hook to gracefully stop the consumer on app shutdown
- [ ] Verify the consumer imports are correct (from `src/orchestrator/workflow/signals/consumer.py`)
- [ ] Run the app and confirm no startup errors:
  ```bash
  uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8001 &
  sleep 2 && curl http://localhost:8001/health && pkill -f "uvicorn.*8001"
  ```

**Dependencies**
- [ ] `SignalConsumer` class exists and is importable from `signals.consumer` (S-02)
- [ ] Consumer `run()` method is implemented and async
- [ ] DB session factory available in executor or app context

**References**
- [Single-Queue Plan: Phase 3.4](../plan.md#34-wire-consumer-into-executor-startup)
- [Consumer Implementation (S-02)](../steps/step-02-plan.md)

**Constraints**
- Consumer must be started after DB initialization (migrations run)
- Must be stopped gracefully on app shutdown (prevent orphaned tasks)
- Do not block startup; use `asyncio.create_task()` or equivalent non-blocking call

**Side Effects**
- App startup now includes consumer initialization
- Background task will begin polling the signal queue immediately

**Functionality (Expected Outcomes)**
- [ ] Consumer loop starts on app startup
- [ ] Consumer has access to DB and can poll `pending_signals` table
- [ ] Consumer loop stops gracefully on app shutdown
- [ ] Signals enqueued during startup are processed within a few polling cycles

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] App starts without errors:
  ```bash
  uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8001 &
  sleep 3 && curl http://localhost:8001/health && echo "Health check passed" || echo "Health check failed"
  pkill -f "uvicorn.*8001"
  ```
- [ ] Consumer task is created and running (check logs or add print statement):
  ```bash
  # Look for log message "Consumer loop started" or similar
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_start_run_via_signal -v -s
  ```
- [ ] Integration test: signal enqueued, consumer processes it within a few seconds:
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_consumer_processes_signals -v
  ```

---

## Task 5: Update Integration Tests for Async Signal-Based Lifecycle

**Description**:
Existing integration tests assumed synchronous lifecycle: `start_run()` immediately creates
RunWorkflow, `pause_run()` immediately transitions to PAUSED. With signals, these are now async:
the API call enqueues, and the consumer processes. Update tests to poll for state changes instead
of asserting immediately.

**Implementation Plan (Do These Steps)**

Tests must now wait for the consumer to process signals. We will add a helper function to poll
the API until a desired state is reached.

- [ ] Open `tests/integration/test_api_full_lifecycle.py`
- [ ] Add a helper function to poll run status until a target state:
  ```python
  async def poll_until_status(client, run_id, target_status, timeout_sec=5):
      start = time.time()
      while time.time() - start < timeout_sec:
          response = await client.get(f"/api/runs/{run_id}")
          if response.json()["status"] == target_status:
              return response.json()
          await asyncio.sleep(0.1)
      raise TimeoutError(f"Run did not reach {target_status} within {timeout_sec}s")
  ```
- [ ] Update `test_start_run` to poll until ACTIVE (or BUILDING):
  ```python
  # Before:
  response = await client.post(f"/api/runs/{run_id}/start")
  assert response.status_code == 202
  run = await client.get(f"/api/runs/{run_id}").json()
  assert run["status"] == "ACTIVE"  # This now races with consumer

  # After:
  response = await client.post(f"/api/runs/{run_id}/start")
  assert response.status_code == 202
  run = await poll_until_status(client, run_id, "ACTIVE", timeout_sec=2)
  assert run["status"] == "ACTIVE"
  ```
- [ ] Update `test_pause_run` to poll until PAUSED (including STOPPING intermediate state):
  ```python
  response = await client.post(f"/api/runs/{run_id}/pause")
  assert response.status_code == 202
  run = await poll_until_status(client, run_id, "PAUSED", timeout_sec=2)
  ```
- [ ] Update `test_cancel_run` similarly
- [ ] Update `test_resume_run` to poll until ACTIVE
- [ ] Run the updated tests to confirm they pass:
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py -v
  ```
- [ ] Check for any other integration tests that assume synchronous start/pause/resume and update them

**Dependencies**
- [ ] Consumer running (Task 4)
- [ ] Signal enqueueing working (Tasks 1–3)

**References**
- [Full Lifecycle Test (existing)](../../../tests/integration/test_api_full_lifecycle.py)

**Constraints**
- Do not change the API contract (routes still return 202, etc.)
- Use reasonable timeouts (2–5 seconds) to avoid slow tests
- Preserve all existing assertions; only add polling between API call and assertion

**Side Effects**
- Tests now take slightly longer (polling overhead) but are more robust
- Tests will fail if consumer is not running (good: forces consumer wiring)

**Functionality (Expected Outcomes)**
- [ ] Integration tests poll for state changes instead of asserting immediately
- [ ] Tests pass with async signal processing
- [ ] STOPPING state (intermediate) is handled in pause/cancel tests

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] All integration tests pass:
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py -v
  ```
- [ ] Specific lifecycle tests work:
  ```bash
  uv run pytest tests/integration/test_api_full_lifecycle.py::test_start_run tests/integration/test_api_full_lifecycle.py::test_pause_run tests/integration/test_api_full_lifecycle.py::test_cancel_run -v
  ```
- [ ] No regression in other integration tests:
  ```bash
  uv run pytest tests/integration/ -v --tb=short
  ```
- [ ] Full backend test suite passes:
  ```bash
  uv run pytest tests/ -v --tb=short
  ```
