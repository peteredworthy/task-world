# Step 3: Sender Rewiring

Switch all `WorkflowService` lifecycle methods to enqueue signals unconditionally,
removing the `has_active_workflow` routing branches. Wire the consumer into executor
startup so signals are processed. Change API responses from 200 to 202 Accepted.
This is the behavioral pivot — after this step, all lifecycle operations flow through
the single queue and the dual-path routing is gone.

## Intent Verification
**Original Intent**: [I-01], [I-09], [I-10], [I-11], [I-13], [I-17], [I-27], [I-28] from
`docs/single-queue-2/intent.md`

**Functionality to Produce**:
- `WorkflowService.start_run()` enqueues a `RUN_START` signal; no direct `engine.start_run()` call
- `WorkflowService.pause_run()` always enqueues `PAUSE` signal; no `has_active_workflow` branch
- `WorkflowService.resume_run()` always enqueues `RESUME` signal; no `has_active_workflow` branch
- `WorkflowService.cancel_run()` always enqueues `CANCEL` signal; `env_lifecycle` hooks moved to consumer
- `retry_fan_out_child()` always enqueues `PAUSE` when run is ACTIVE; no `has_active_workflow` check
- `RunWorkflow.handle_pause` no longer calls `unregister_active_run()` (consumer owns registry)
- `env_lifecycle.on_run_start()` moved from service to consumer's `_handle_run_start()`
- Start/pause/resume/cancel API endpoints return **202 Accepted**
- Consumer loop started in app lifespan before service methods are called

**Final Verification Criteria**:
- `grep -r "has_active_workflow" src/orchestrator/workflow/service.py` returns no hits
- `grep -r "engine.start_run" src/orchestrator/workflow/service.py` returns no hits
- `grep -r "unregister_active_run" src/orchestrator/workflow/signals/runtime.py` returns no hits for `handle_pause`
- Integration test confirms 202 from start/pause/resume/cancel endpoints
- Integration test confirms run transitions to ACTIVE within 2 seconds of `start` signal enqueue

---

## Task 1: Rewire `start_run()` to Enqueue `RUN_START` Signal

**Description**: Replace `engine.start_run()` direct call with signal enqueueing in
`WorkflowService.start_run()`. Remove the `env_lifecycle.on_run_start()` hook call
from this method (it moves to the consumer in Task 2). API endpoint stays as-is for
now (response code changes in Task 5).

**Implementation Plan (Do These Steps)**

The current `start_run()` at line 366 of `service.py`:
1. Fetches the run
2. Calls `engine.start_run(run_id)` to do DRAFT → ACTIVE
3. Persists via `_persist()`
4. Calls `env_lifecycle.on_run_start()`
5. Warns about managed agent spawning

Replace steps 2–4 with a single signal enqueue. Steps 1 and 5 remain (step 5
still logs a useful warning even in the new model).

- [ ] In `src/orchestrator/workflow/service.py`, rewrite `start_run()`:

```python
async def start_run(self, run_id: str) -> Run:
    """Start a run by enqueuing a RUN_START signal (DRAFT -> ACTIVE via consumer)."""
    import logging
    logger = logging.getLogger(__name__)

    run = await self._repo.get(run_id)
    logger.info(
        f"Starting run {run_id}: agent_type={run.agent_type}, "
        f"repo={run.repo_name}, routine={run.routine_id}"
    )

    from orchestrator.workflow.signals import (
        DbSignalTransport,
        SignalQueue,
        WorkflowSignal,
    )
    transport = DbSignalTransport(self._session)
    queue = SignalQueue(transport)
    await queue.enqueue(run_id, WorkflowSignal.RUN_START, None)

    # Warn if using a managed agent that requires spawning
    if run.agent_type in (
        AgentRunnerType.CLI_SUBPROCESS,
        AgentRunnerType.OPENHANDS_LOCAL,
        AgentRunnerType.OPENHANDS_DOCKER,
    ):
        agent_type_str = run.agent_type.value if run.agent_type else "unknown"
        logger.warning(
            f"Run {run_id} queued for start with managed agent {agent_type_str}. "
            f"Agent will be spawned after consumer processes RUN_START signal."
        )

    return run
```

- [ ] Remove the `engine.start_run()` call and all surrounding `_build_engine` /
  `_persist` usage that was only needed for the direct-DB path in this method.
- [ ] Keep the import of `AgentRunnerType` (already present at top of file).

**Constraints**
- Only modify `start_run()` in `service.py`. Do not touch the router yet.
- Do not remove `env_lifecycle` imports — they are used by other methods.

**Side Effects**
- The API endpoint in `runs.py` calls `executor.start_run_with_agent()` which in turn
  calls `service.start_run()`. After this task, the service no longer transitions the
  run to ACTIVE synchronously. The executor's `spawn_for_run` call may spawn before the
  consumer picks up the signal — that is acceptable; the executor manages agent lifecycle
  separately.

**Functionality (Expected Outcomes)**
- [ ] `start_run()` enqueues a `RUN_START` signal and returns the run in DRAFT status
- [ ] No call to `engine.start_run()` or `_build_engine` in `start_run()`
- [ ] No `env_lifecycle.on_run_start()` call in `start_run()`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "engine.start_run\|_build_engine\|env_lifecycle" src/orchestrator/workflow/service.py | grep -A2 -B2 "def start_run"` — no hits within the method body
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — unit tests pass

---

## Task 2: Move `env_lifecycle.on_run_start()` to Consumer `_handle_run_start()`

**Description**: The consumer's `_handle_run_start()` handler (from Step 2 / S-02)
must call `env_lifecycle.on_run_start()` inline after applying the DRAFT → ACTIVE
transition. The consumer runs this inline (blocking that run's signals only).

**Implementation Plan (Do These Steps)**

The consumer is in `src/orchestrator/workflow/signals/consumer.py` (created in S-02).
The `_handle_run_start` method currently: transitions run DRAFT → ACTIVE, creates
RunWorkflow, registers it. We need to add the env_lifecycle hook call after the
transition succeeds.

- [ ] Locate `_handle_run_start()` in `consumer.py`.
- [ ] After the DRAFT → ACTIVE DB transition and before `register_active_run()`, add
  the env_lifecycle call:

```python
# Call env_lifecycle hook if configured and worktree is available
if self._env_lifecycle is not None and run.worktree_path and run.env_file_specs:
    from pathlib import Path
    worktree_path = Path(run.worktree_path)
    source_dir = Path(run.env_source_dir) if run.env_source_dir else None
    await self._env_lifecycle.on_run_start(
        run_id=run_id,
        repo_name=run.repo_name,
        worktree_path=worktree_path,
        env_specs=run.env_file_specs,
        source_dir=source_dir,
    )
```

- [ ] Ensure the consumer's `__init__` accepts an optional `env_lifecycle:
  EnvFileLifecycle | None = None` parameter and stores it as `self._env_lifecycle`.
- [ ] Update wherever the consumer is instantiated (in `app.py` lifespan, Task 6) to
  pass `env_lifecycle` from `app.state` if available.

**Dependencies**
- [ ] Task 1 complete (env_lifecycle hook no longer called from `start_run()`)

**References**
- `src/orchestrator/envfiles/lifecycle.py` — `EnvFileLifecycle.on_run_start()` signature

**Constraints**
- Only modify `consumer.py` and wherever the consumer is instantiated.
- Do not change `service.py` further in this task.

**Functionality (Expected Outcomes)**
- [ ] Consumer's `_handle_run_start()` calls `env_lifecycle.on_run_start()` inline when
  lifecycle is configured and run has worktree + env specs
- [ ] Hook failure leaves `handled_at` null so signal is redelivered on restart
- [ ] Consumer still completes DRAFT → ACTIVE transition even when env_lifecycle is None

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "on_run_start" src/orchestrator/workflow/signals/consumer.py` — shows hook call in handler
- [ ] `uv run pytest tests/unit/test_signal_consumer.py -x -q 2>&1 | tail -5` — passes

---

## Task 2b: Rewrite `handle_pause()` and `handle_cancel()` in `runtime.py` to Not Re-Enqueue

**Description**: **CRITICAL (FM-5, FM-6)**: After Task 1 rewires `pause_run()` and
`cancel_run()` to always enqueue signals, `RunWorkflow.handle_pause()` internally calls
`service.pause_run()` and `handle_cancel()` calls `service.cancel_run()`. This creates
an infinite signal loop: consumer delivers PAUSE → RunWorkflow.handle_pause() → service.pause_run()
enqueues new PAUSE → consumer delivers again → infinite loop.

**This task MUST be done before Task 3 rewires the service methods.**

**Implementation Plan (Do These Steps)**

- [ ] In `src/orchestrator/workflow/signals/runtime.py`, find `handle_pause()` and
  rewrite it to stop the run loop WITHOUT calling `service.pause_run()`. The consumer
  is now responsible for the PAUSED DB transition after the workflow acknowledges:
  ```python
  @signal_handler(WorkflowSignal.PAUSE)
  async def handle_pause(self, session, service, payload):
      """Signal the run loop to stop. Consumer applies PAUSED transition after ack."""
      reason = (payload or {}).get("reason", "manual_pause")
      self._pause_reason = reason
      self._stop_requested = True  # or however the run loop checks for stop
      return True  # acknowledge to consumer
  ```
  Do NOT call `service.pause_run()` here. Do NOT call `unregister_active_run()` here
  (that is also the consumer's responsibility — removed in Task 5).

- [ ] Similarly rewrite `handle_cancel()` to NOT call `service.cancel_run()`:
  ```python
  @signal_handler(WorkflowSignal.CANCEL)
  async def handle_cancel(self, session, service, payload):
      """Signal the run loop to stop. Consumer applies FAILED transition after ack."""
      self._cancel_requested = True  # or however the run loop checks for cancel
      return True  # acknowledge to consumer
  ```

- [ ] Read the current `RunWorkflow._run_loop()` implementation to understand how it
  currently checks for pause/cancel signals (via `self.on_signal()`). The new design
  has the consumer deliver the signal BEFORE the loop runs; the loop must check for the
  stop flag and exit gracefully without calling any service methods itself.

- [ ] Run tests: `uv run pytest tests/unit/ -x -q --tb=short`

**Constraints**
- Only modify `handle_pause` and `handle_cancel` in `runtime.py`.
- Do NOT modify the run loop's internal pause calls (those are addressed in the
  "internal calls" scoping decision below).

**Note on `_run_loop()` internal service.pause_run() calls (FM-7 / issue #7)**:
`_run_loop()` calls `service.pause_run()` at ~13 call sites for error conditions
(gate_blocked, agent_cancelled, etc.). After rewiring, these enqueue PAUSE signals.
The RunWorkflow then calls `unregister_active_run()` (violating registry isolation)
and exits. The consumer picks up the PAUSE and transitions to PAUSED. **This is
semantically correct but violates registry isolation invariant until Step 4.**
Accept this as a known invariant violation documented for Step 4 cleanup.

**Functionality (Expected Outcomes)**
- [ ] `handle_pause()` returns True without calling `service.pause_run()`
- [ ] `handle_cancel()` returns True without calling `service.cancel_run()`
- [ ] No infinite PAUSE/CANCEL signal loop when consumer delivers to RunWorkflow

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "service.pause_run\|service.cancel_run" src/orchestrator/workflow/signals/runtime.py | grep "handle_pause\|handle_cancel"` — no hits in these two methods
- [ ] `uv run pytest tests/unit/ -x -q --tb=short` — passes

---

## Task 3: Rewire `pause_run()` and `resume_run()` to Always Enqueue

**Description**: Remove the `has_active_workflow` branch from both `pause_run()` and
`resume_run()` in `WorkflowService`. Both methods should always enqueue their respective
signal, never mutating the DB directly.

**Implementation Plan (Do These Steps)**

Current `pause_run()` (line 417): checks `has_active_workflow`, enqueues if true, else
direct DB mutation. Current `resume_run()` (line 454): same pattern.

- [ ] Rewrite `pause_run()` in `service.py`:

```python
async def pause_run(
    self,
    run_id: str,
    reason: str = "manual_pause",
    error_detail: str | None = None,
) -> Run:
    """Pause a run by enqueuing a PAUSE signal (processed by consumer)."""
    from orchestrator.workflow.signals import (
        DbSignalTransport,
        SignalQueue,
        WorkflowSignal,
    )
    transport = DbSignalTransport(self._session)
    queue = SignalQueue(transport)
    payload: dict[str, object] = {"reason": reason}
    if error_detail is not None:
        payload["error_detail"] = error_detail
    await queue.enqueue(run_id, WorkflowSignal.PAUSE, payload)
    return await self._repo.get(run_id)
```

- [ ] Rewrite `resume_run()` in `service.py`. Keep the agent-change and revert-strategy
  logic (it applies before the signal), but replace the final `engine.resume_run()` +
  `_persist()` call with a signal enqueue:

```python
# At end of resume_run(), replace engine.resume_run(run_id) + _persist():
from orchestrator.workflow.signals import (
    DbSignalTransport,
    SignalQueue,
    WorkflowSignal,
)
transport = DbSignalTransport(self._session)
queue = SignalQueue(transport)
await queue.enqueue(run_id, WorkflowSignal.RESUME, None)
return run
```

- [ ] Remove the `has_active_workflow` imports from both methods.

**Constraints**
- Keep the revert-strategy (`resume_strategy == "revert"`) and agent-change logic in
  `resume_run()` — only the final transition and signal emission change.
- Only modify `pause_run()` and `resume_run()` in `service.py`.

**Side Effects**
- Internal callers of `pause_run()` (e.g., error handling in the executor) now enqueue
  rather than mutate directly. The consumer will process the signal shortly after.
  This is acceptable; internal callers don't require synchronous state changes.

**Functionality (Expected Outcomes)**
- [ ] `pause_run()` always enqueues `PAUSE` signal; no `has_active_workflow` check
- [ ] `resume_run()` always enqueues `RESUME` signal; no `has_active_workflow` check
- [ ] No `engine.pause_run()` or `engine.resume_run()` calls in these methods

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "has_active_workflow" src/orchestrator/workflow/service.py` — no hits in
  `pause_run` or `resume_run`
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 4: Rewire `cancel_run()` and `retry_fan_out_child()`

**Description**: Remove `has_active_workflow` from `cancel_run()` (always enqueue CANCEL)
and from `retry_fan_out_child()` (always enqueue PAUSE when run is ACTIVE). Move
`env_lifecycle` and worktree cleanup from `cancel_run()` to the consumer's
`_handle_cancel()`.

**Implementation Plan (Do These Steps)**

- [ ] Rewrite `cancel_run()` in `service.py` to always enqueue:

```python
async def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
    """Cancel a run by enqueuing a CANCEL signal (processed by consumer)."""
    run = await self._repo.get(run_id)
    # Idempotency: if already terminal, return as-is
    if run.status in (RunStatus.FAILED, RunStatus.COMPLETED):
        return run
    from orchestrator.workflow.signals import (
        DbSignalTransport,
        SignalQueue,
        WorkflowSignal,
    )
    transport = DbSignalTransport(self._session)
    queue = SignalQueue(transport)
    payload: dict[str, object] = {}
    if reason is not None:
        payload["reason"] = reason
    await queue.enqueue(run_id, WorkflowSignal.CANCEL, payload or None)
    return run
```

- [ ] Remove the direct-DB branch (the `engine.cancel_run()` call, `_persist()`, and
  `env_lifecycle.on_run_end()` / `handle_run_completion()` calls from `cancel_run()`).
- [ ] Move the `env_lifecycle.on_run_end()` and `handle_run_completion()` calls to the
  consumer's `_handle_cancel()` handler (consumer already handles the ACTIVE → FAILED
  transition; add the hook calls after that transition):

```python
# In consumer._handle_cancel(), after transitioning to FAILED:
if self._env_lifecycle is not None and run.worktree_path and run.env_file_specs:
    from pathlib import Path
    await self._env_lifecycle.on_run_end(
        run_id=run_id,
        repo_name=run.repo_name,
        worktree_path=Path(run.worktree_path),
        success=False,
    )
worktree_manager = self._create_worktree_manager(run)
if worktree_manager is not None:
    handle_run_completion(run, worktree_manager)
```

  Note: consumer will need access to `_create_worktree_manager` logic or equivalent.
  Use a helper that replicates `WorkflowService._create_worktree_manager()`.

- [ ] Rewrite `retry_fan_out_child()` to remove `has_active_workflow` check. Replace:

```python
# OLD:
if run.status == RunStatus.ACTIVE:
    if has_active_workflow(run_id):
        # ... enqueue PAUSE
    else:
        await self._repo.update_run_status(
            run_id, RunStatus.PAUSED, pause_reason="fan_out_child_retry"
        )
```

with:

```python
# NEW:
if run.status == RunStatus.ACTIVE:
    from orchestrator.workflow.signals import (
        DbSignalTransport,
        SignalQueue,
        WorkflowSignal,
    )
    transport = DbSignalTransport(self._session)
    queue = SignalQueue(transport)
    await queue.enqueue(
        run_id,
        WorkflowSignal.PAUSE,
        {"reason": "fan_out_child_retry"},
    )
```

**Constraints**
- Only modify `cancel_run()`, `retry_fan_out_child()` in `service.py` and
  `_handle_cancel()` in `consumer.py`.
- Do not change `recover_run()` or other service methods.

**Functionality (Expected Outcomes)**
- [ ] `cancel_run()` always enqueues `CANCEL`; no `has_active_workflow`, no direct engine call
- [ ] `retry_fan_out_child()` always enqueues `PAUSE` for ACTIVE runs; no `has_active_workflow`
- [ ] Consumer's `_handle_cancel()` calls `env_lifecycle.on_run_end()` and `handle_run_completion()`
  for runs with worktrees

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "has_active_workflow" src/orchestrator/workflow/service.py` — zero hits
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 5: Remove `unregister_active_run()` from `RunWorkflow.handle_pause` and Change API to 202

**Description**: Two changes batched together because they're small and related:
(a) remove the `unregister_active_run()` call from `RunWorkflow.handle_pause` in
`runtime.py` (consumer owns the registry now), and (b) change start/pause/resume/cancel
API endpoints from 200 to 202 Accepted.

**Implementation Plan (Do These Steps)**

**Part A — Remove registry call from RunWorkflow**

- [ ] In `src/orchestrator/workflow/signals/runtime.py`, find `handle_pause()` (line ~276):

```python
@signal_handler(WorkflowSignal.PAUSE)
async def handle_pause(self, session, service, payload):
    ...
    unregister_active_run(self.run_id)   # ← REMOVE this line
    await service.pause_run(self.run_id, reason=reason)
    return True
```

Remove the `unregister_active_run(self.run_id)` call. The consumer's
`_handle_pause()` handler now owns this call.

- [ ] Similarly remove `unregister_active_run(self.run_id)` from `handle_cancel()`
  in `runtime.py` (line ~310) for the same reason.

**Part B — Change API endpoints to return 202**

- [ ] In `src/orchestrator/api/routers/runs.py`, change the four route decorators
  and response signatures:

```python
# start_run endpoint (~line 412):
@router.post("/{run_id}/start", status_code=202)
async def start_run(...) -> Response:
    run = await executor.start_run_with_agent(run_id, service)
    return Response(status_code=202)

# cancel_run endpoint (~line 434):
@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(...) -> Response:
    await executor.cancel_run(run_id)
    await service.cancel_run(run_id)
    return Response(status_code=202)

# pause_run endpoint (~line 447):
@router.post("/{run_id}/pause", status_code=202)
async def pause_run(...) -> Response:
    await executor.cancel_run(run_id)
    await service.pause_run(run_id)
    return Response(status_code=202)

# resume_run endpoint (~line 460):
@router.post("/{run_id}/resume", status_code=202)
async def resume_run(...) -> Response:
    # keep all existing logic, change final return:
    ...
    return Response(status_code=202)
```

Import `Response` from `fastapi` at the top if not already imported.

**Constraints**
- Only modify `handle_pause` and `handle_cancel` in `runtime.py`.
- Only modify the four route handlers in `runs.py`.
- Do not change `response_model` annotations on other routes.

**Side Effects**
- Frontend code that checks for 200 on these endpoints will break. Frontend
  update is handled in Task 7 (integration tests) and tracked separately.

**Functionality (Expected Outcomes)**
- [ ] `handle_pause` in `runtime.py` does not call `unregister_active_run()`
- [ ] `handle_cancel` in `runtime.py` does not call `unregister_active_run()`
- [ ] Start/pause/resume/cancel endpoints return 202 with empty body

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "unregister_active_run" src/orchestrator/workflow/signals/runtime.py` — no
  hits in `handle_pause` or `handle_cancel` (only in executor-level finally blocks is OK)
- [ ] `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/runs/nonexistent/start` — returns 404 not 405 (route exists)
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 6: Wire Consumer Startup into App Lifespan

**Description**: Start the consumer loop as part of `app.py` lifespan, before any
service methods are called. The consumer must be running before signals are enqueued.

**Implementation Plan (Do These Steps)**

- [ ] In `src/orchestrator/api/app.py`, in the `_lifespan()` function, add consumer
  startup near the top (before `recover_active_runs_on_startup`):

```python
# Start signal consumer loop
from orchestrator.workflow.signals.consumer import SignalConsumer

env_lifecycle = getattr(app.state, "env_lifecycle", None)
signal_consumer = SignalConsumer(
    session_factory=session_factory,
    global_config=global_config,
    env_lifecycle=env_lifecycle,
)
consumer_task = asyncio.create_task(signal_consumer.run())
app.state.signal_consumer = signal_consumer
```

- [ ] On lifespan shutdown (in the `finally` block or after the `yield`), cancel the
  consumer task:

```python
consumer_task.cancel()
try:
    await consumer_task
except asyncio.CancelledError:
    pass
```

- [ ] Verify that `SignalConsumer` accepts `session_factory`, `global_config`, and
  `env_lifecycle` in its `__init__` (update consumer if needed to match this signature).
- [ ] Confirm the consumer's `run()` method is a coroutine that polls indefinitely
  (100ms interval) and can be cancelled cleanly.

**Dependencies**
- [ ] `SignalConsumer` class exists in `consumer.py` with a `run()` coroutine (S-02 complete)

**References**
- `docs/single-queue-2/architecture.md` — Consumer Configuration section
- `docs/single-queue-2/plan.md` — Phase 3, §3.4

**Constraints**
- Only modify `app.py` lifespan function.
- Consumer must start before `recover_active_runs_on_startup()` so that any signals
  written during recovery are immediately consumed.

**Functionality (Expected Outcomes)**
- [ ] Consumer asyncio task is created and running during application lifespan
- [ ] Consumer task is cancelled cleanly on shutdown
- [ ] `app.state.signal_consumer` holds the running consumer instance

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "signal_consumer\|SignalConsumer" src/orchestrator/api/app.py` — shows startup wiring
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 7a: Fix Test Infrastructure Transport Mismatch

**Description**: **CRITICAL (FM-20, FM-21)**: After Tasks 1–4 rewire service methods
to use `DbSignalTransport`, signals are written to the SQLite DB. But integration tests
use `InMemorySignalTransport` via `make_drain_fn()` / `drain_signals()`. The drain
helper calls `RunWorkflow.on_signal()` which reads from `InMemorySignalTransport` — it
will find ZERO signals from lifecycle operations. No consumer is running in tests.
`wait_for_status()` polling will never succeed.

**This task MUST be done before Task 7 updates individual test assertions.**

**Implementation Plan (Do These Steps)**

The recommended fix (Option A from dry-run analysis): make `WorkflowService` accept
an injectable transport that tests can override.

- [ ] In `src/orchestrator/workflow/service.py`, add optional transport injection to
  `WorkflowService.__init__`:
  ```python
  def __init__(
      self,
      session: AsyncSession,
      repo: RunRepository,
      engine: WorkflowEngine,
      emitter: EventEmitter,
      lock_manager: LockManager | None = None,
      signal_transport: SignalTransport | None = None,  # ADD THIS
  ) -> None:
      self._signal_transport = signal_transport  # None = use DbSignalTransport(session)
  ```

- [ ] In each of `start_run()`, `pause_run()`, `resume_run()`, `cancel_run()`, use the
  injected transport if set, otherwise create `DbSignalTransport(session)`:
  ```python
  transport = self._signal_transport or DbSignalTransport(self._session)
  queue = SignalQueue(transport)
  ```

- [ ] In `src/orchestrator/api/deps.py`, read `app.state.signal_transport` if set, and
  pass it to `WorkflowService`:
  ```python
  signal_transport = getattr(request.app.state, "signal_transport", None)
  # ... include signal_transport in WorkflowService construction
  ```

- [ ] In `tests/integration/conftest.py` (or wherever the test app is set up), set
  `app.state.signal_transport = InMemorySignalTransport()` so that service methods
  in tests use the in-memory transport that `drain_signals()` reads from.

- [ ] Update `drain_signals()` / `make_drain_fn()` in test helpers to also handle the
  new lifecycle signals (RUN_START, RESUME) by routing them through consumer handlers,
  not just through `RunWorkflow.on_signal()`. For Step 3 tests, the minimal fix is:
  when draining, also call the consumer's `_handle_run_start()`, `_handle_resume()`,
  etc. for lifecycle signals, while keeping `RunWorkflow.on_signal()` for ACTIVITY signals.

**Constraints**
- Only modify `service.py`, `deps.py`, and test infrastructure files in this task.
- Production behavior unchanged when `signal_transport` is None.

**Functionality (Expected Outcomes)**
- [ ] Tests can inject `InMemorySignalTransport` so `drain_signals()` picks up lifecycle signals
- [ ] Production uses `DbSignalTransport(session)` by default (no change to prod behavior)
- [ ] Integration tests can verify state transitions after start/pause/resume/cancel

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "signal_transport" src/orchestrator/workflow/service.py` — shows optional injection
- [ ] `uv run pytest tests/unit/ -x -q --tb=short` — passes (no regressions)

---

## Task 7: Update Integration Tests for 202 and Async State Transitions

**Description**: Integration tests that POST to start/pause/resume/cancel currently
assert 200 status codes and immediate state transitions. Update them to expect 202
and poll for the expected state change.

**Implementation Plan (Do These Steps)**

- [ ] In `tests/integration/test_api_full_lifecycle.py`, find all assertions on
  start/pause/resume/cancel response codes. Replace `assert response.status_code == 200`
  with `assert response.status_code == 202` for these endpoints.
- [ ] Where tests immediately check `run["status"]` after start/pause/resume/cancel,
  add a polling helper that waits up to 2 seconds:

```python
async def wait_for_status(client, run_id, expected_status, timeout=2.0, interval=0.1):
    """Poll run status until it matches expected or timeout."""
    import asyncio
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/runs/{run_id}")
        if resp.json()["status"] == expected_status:
            return resp.json()
        await asyncio.sleep(interval)
    raise AssertionError(
        f"Run {run_id} did not reach status {expected_status!r} within {timeout}s. "
        f"Last status: {resp.json()['status']!r}"
    )
```

- [ ] Apply `wait_for_status()` after each start/pause/resume/cancel call where the
  test relies on the state change having happened.
- [ ] In `tests/integration/test_api_tasks.py`, update any start/pause/resume/cancel
  assertions similarly.
- [ ] Run the full integration test suite to identify any remaining failures and fix them.

**Dependencies**
- [ ] Tasks 1–6 complete (service and endpoints rewired)

**Constraints**
- Update only test files. Do not change production code in this task.
- Do not skip or delete existing tests — update them to work with async behavior.

**Functionality (Expected Outcomes)**
- [ ] All integration tests pass with 202 responses from lifecycle endpoints
- [ ] Tests that check run status after lifecycle calls wait for consumer processing
- [ ] No test asserts 200 from start/pause/resume/cancel endpoints

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "status_code == 200" tests/integration/test_api_full_lifecycle.py` — no hits
  for start/pause/resume/cancel endpoints (200 still OK for other endpoints like GET)
- [ ] `uv run pytest tests/integration/test_api_full_lifecycle.py -x -q 2>&1 | tail -10` — all pass
- [ ] `uv run pytest tests/integration/ -x -q 2>&1 | tail -10` — all pass (or known-failing openhands skipped)
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — all pass
