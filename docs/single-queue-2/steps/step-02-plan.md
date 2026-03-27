# Step 2: Consumer

Build the consumer loop as new code that polls `pending_signals`, dispatches each
signal to the appropriate handler, and manages the active-run registry. The consumer
is the sole entity that creates and destroys `RunWorkflow` instances, owns the
active-run registry, and handles all run lifecycle transitions. Nothing in `WorkflowService`
writes signals via the new paths yet — that happens in Step 3 — so all existing tests
continue to pass.

## Intent Verification
**Original Intent**: [I-02], [I-05], [I-12], [I-25], [I-31], [I-36] — Consumer module,
signal handlers, delivery tracking, redelivery, per-run serial concurrency

**Functionality to Produce**:
- `src/orchestrator/workflow/signals/consumer.py` that polls `pending_signals` ordered
  by integer PK every 100ms
- Per-run concurrency: one `asyncio.Task` per `run_id`; signals for the same run
  processed serially; different runs processed concurrently
- `delivered_at` set before handler invocation; `handled_at` set after handler returns
  successfully; handler error leaves `handled_at` null (signal eligible for redelivery)
- Signal handlers: `RUN_START` (DRAFT→ACTIVE), `RESUME` (PAUSED→ACTIVE), `PAUSE`
  (STOPPING path if active, direct if not), `CANCEL` (STOPPING path if active, direct if not),
  `ACTIVITY_COMPLETED` and `ACTIVITY_VERIFIED` (deliver to RunWorkflow)
- `env_lifecycle.on_run_start()` called inside `_handle_run_start()` (inline, blocking
  that run's signals but not other runs)
- `env_lifecycle.on_cancel()` called inside `_handle_cancel()` (inline, same rule)
- Startup redelivery: on consumer start, re-dispatch signals where
  `delivered_at IS NOT NULL AND handled_at IS NULL` for inactive runs
- Registry functions (`register_active_run`, `unregister_active_run`, `has_active_workflow`)
  accessible to consumer and its tests only (Step 4 removes public exports; consumer
  is the sole caller from Step 3 onward)
- Unit tests: `tests/unit/test_signal_consumer.py` and `tests/unit/test_signal_redelivery.py`

**Final Verification Criteria**:
- Consumer dispatch tests pass (FIFO ordering, delivery tracking, error-leaves-unhandled)
- Signal handler tests pass for every signal type, both active and inactive RunWorkflow paths
- Redelivery tests pass (crash recovery, re-dispatch on startup)
- All existing backend tests pass: `uv run pytest tests/ -x -q --tb=short`

---

## Task 1: Consumer Module Skeleton with Polling Loop and Per-Run Task Management

**Description**:
Create the foundation of the consumer module: the core polling loop that fetches
unhandled signals ordered by integer PK, and the per-run task management that ensures
signals for the same run are processed serially while different runs run concurrently.
All handlers are stubs that immediately raise `NotImplementedError` — this task only
establishes the scaffolding.

**Implementation Plan (Do These Steps)**

The consumer uses a "worker per run" concurrency model:
1. Main loop polls `pending_signals` every 100ms for signals where `handled_at IS NULL`
   and `delivered_at IS NULL`, ordered by `id` (integer PK).
2. For each run_id appearing in the batch, route signals to a per-run `asyncio.Queue`.
3. A per-run `asyncio.Task` drains its queue serially (one signal at a time).
4. Tasks are created on first signal for a run and cleaned up when the queue empties.

**Key design notes:**
- Query only `delivered_at IS NULL` in the main poll — redelivery (delivered but not handled)
  is a separate startup path (Task 5).
- Set `delivered_at` when popping from the per-run queue, immediately before calling the handler.
- Set `handled_at` immediately after the handler returns without exception.
- On handler exception: log the error, leave `handled_at` null, let the signal be retried
  on the next poll cycle (after a brief backoff to avoid tight error loops).
- Use `async_sessionmaker` for DB access; open a new session per signal to avoid long-lived transactions.

- [ ] Create `src/orchestrator/workflow/signals/consumer.py` with:
  - `SignalConsumer` class with `__init__(self, session_factory, run_workflow_factory, env_lifecycle)`
  - `async def start(self) -> None` — starts the main polling loop as a background task
  - `async def stop(self) -> None` — cancels all per-run tasks and the main loop
  - `async def _poll_loop(self) -> None` — polls every 100ms, routes signals to per-run queues
  - `async def _run_task(self, run_id: str, queue: asyncio.Queue) -> None` — drains queue serially
  - `async def _dispatch(self, session, signal) -> None` — calls appropriate handler stub
  - Handler stubs: `_handle_run_start`, `_handle_resume`, `_handle_pause`, `_handle_cancel`,
    `_handle_activity_completed`, `_handle_activity_verified` — all raise `NotImplementedError`
  - Per-run task registry: `_run_tasks: dict[str, asyncio.Task]`
  - Per-run queue registry: `_run_queues: dict[str, asyncio.Queue]`

```python
class SignalConsumer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        run_workflow_factory: Callable[[str], RunWorkflow],
        env_lifecycle: Any,
        engine: WorkflowEngine,
        service_factory: Callable,  # FM-3C: needed for handler calls
    ) -> None:
        self._session_factory = session_factory
        self._run_workflow_factory = run_workflow_factory
        self._env_lifecycle = env_lifecycle
        self._engine = engine
        self._service_factory = service_factory  # FM-3C: Callable[[AsyncSession], Awaitable[WorkflowService]]
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._run_queues: dict[str, asyncio.Queue] = {}
        self._run_workflows: dict[str, RunWorkflow] = {}
        self._main_task: asyncio.Task | None = None
        self._poll_interval = 0.1  # 100ms

    async def start(self) -> None:
        # run startup redelivery, then launch _poll_loop as a background task
        ...

    async def stop(self) -> None:
        # cancel _main_task, cancel all _run_tasks, await cleanup
        ...
```

- [ ] Verify syntax: `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py`

**Functionality (Expected Outcomes)**
- [ ] `consumer.py` exists and is syntactically valid
- [ ] `SignalConsumer` can be instantiated with mock arguments
- [ ] `start()` launches the poll loop as a background task; `stop()` cancels it cleanly
- [ ] `_dispatch()` routing calls the correct stub for each `WorkflowSignal` type

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Syntax check passes: `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py`
- [ ] Module imports: `uv run python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('OK')"`

---

## Task 2: Implement RUN_START and RESUME Handlers

**Description**:
Implement `_handle_run_start()` and `_handle_resume()`. Both handlers transition the
run to ACTIVE, create a `RunWorkflow` instance via the factory, register it, and call
the appropriate env_lifecycle hook. Both handlers are idempotent: if the run is already
ACTIVE, treat it as a no-op and mark handled.

**Implementation Plan (Do These Steps)**

`_handle_run_start()` logic:
1. Load run from DB; if status is not DRAFT, log and return (idempotent no-op).
2. Call `engine.start_run(run_id)` to transition DRAFT → ACTIVE.
3. **FM-2A: `on_run_start` requires 4+ params — load from run object before calling:**
   ```python
   if self._env_lifecycle is not None and run.worktree_path and run.env_file_specs:
       from pathlib import Path
       source_dir = Path(run.env_source_dir) if run.env_source_dir else None
       await self._env_lifecycle.on_run_start(
           run_id=run_id,
           repo_name=run.repo_name,
           worktree_path=Path(run.worktree_path),
           env_specs=run.env_file_specs,
           source_dir=source_dir,
       )
   ```
   Do NOT call `on_run_start(run_id)` with just one argument — that raises TypeError.
4. Create `RunWorkflow` via `self._run_workflow_factory(run_id)`.
5. Store in `self._run_workflows[run_id]`; call `register_active_run(run_id)`.
6. Launch `RunWorkflow.run()` as a background task (do NOT await it — it runs the agent loop).

`_handle_resume()` logic:
1. Load run from DB; if status is not PAUSED, log and return (idempotent no-op).
2. Call `engine.resume_run(run_id)` to transition PAUSED → ACTIVE.
3. Create `RunWorkflow` via `self._run_workflow_factory(run_id)`.
4. Call `register_active_run(run_id)`.
5. Launch `RunWorkflow.run()` as a background task.

**Note on registry functions**: Import directly from `orchestrator.workflow.signals.signals`
(not via `__init__`), as Step 4 will remove the public exports. This import form is correct
from Day 1 of the consumer.

```python
from orchestrator.workflow.signals.signals import (
    has_active_workflow,
    register_active_run,
    unregister_active_run,
)
```

- [ ] Replace the `_handle_run_start` stub with the implementation above
- [ ] Replace the `_handle_resume` stub with the implementation above
- [ ] Import `register_active_run` from `orchestrator.workflow.signals.signals` directly
- [ ] Import `WorkflowEngine` and ensure the consumer has access to an engine instance
  (add `engine: WorkflowEngine` to `SignalConsumer.__init__`)

**Constraints**
- Only `src/orchestrator/workflow/signals/consumer.py` is modified.
- Registry functions imported from `.signals` directly, not via package `__init__`.

**Functionality (Expected Outcomes)**
- [ ] `_handle_run_start()` transitions run DRAFT → ACTIVE, calls `on_run_start`, registers workflow
- [ ] `_handle_resume()` transitions run PAUSED → ACTIVE, registers workflow
- [ ] Both handlers are idempotent (wrong-state run is a no-op, not an exception)
- [ ] `RunWorkflow.run()` is launched as a background task (not awaited inline)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Module imports: `uv run python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('OK')"`
- [ ] `grep "from orchestrator.workflow.signals.signals import" src/orchestrator/workflow/signals/consumer.py` shows the direct import form

---

## Task 3: Implement PAUSE and CANCEL Handlers

**Description**:
Implement `_handle_pause()` and `_handle_cancel()`. Each handler has two paths: if a
`RunWorkflow` is active for the run, use the STOPPING intermediate state; if not (run
is already PAUSED or ACTIVE without an active workflow), transition directly.

**Implementation Plan (Do These Steps)**

`_handle_pause()` logic:
1. If `has_active_workflow(run_id)`:
   a. Transition ACTIVE → STOPPING via `engine.set_run_stopping(run_id)` (public method — FM-3D).
   b. Get service: `service = await self._service_factory(session)` (FM-3C).
   c. Deliver PAUSE signal to the RunWorkflow: `await workflow.handle_pause(session, service, payload)`.
   d. On ack: transition STOPPING → PAUSED via `engine.pause_run(run_id)`.
      **Note (FM-3B):** `handle_pause()` internally calls `service.pause_run()` which will enqueue
      a new PAUSE signal after Step 3 rewiring. This double-transition is resolved in Step 3
      when `handle_pause` is rewritten to just `return True` — in Step 2, leave as-is.
   e. Call `unregister_active_run(run_id)`.
2. If no active workflow:
   a. Transition directly to PAUSED via `engine.pause_run(run_id)`.
3. Idempotency: if run already PAUSED, return no-op.

`_handle_cancel()` logic:
1. If `has_active_workflow(run_id)`:
   a. Transition ACTIVE → STOPPING via `engine.set_run_stopping(run_id)` (public method).
   b. Get service: `service = await self._service_factory(session)` (FM-3C).
   c. Deliver CANCEL signal to the RunWorkflow: `await workflow.handle_cancel(session, service, payload)`.
   d. On ack: transition STOPPING → FAILED via `engine.cancel_run(run_id)`.
   e. **FM-3A: `env_lifecycle.on_cancel` does NOT exist on EnvFileLifecycle. Use `on_run_end` instead:**
      ```python
      if self._env_lifecycle is not None and run.worktree_path and run.env_file_specs:
          from pathlib import Path
          await self._env_lifecycle.on_run_end(
              run_id=run_id, repo_name=run.repo_name,
              worktree_path=Path(run.worktree_path), success=False,
          )
      ```
   f. Call `unregister_active_run(run_id)`.
2. If no active workflow:
   a. Transition directly to FAILED via `engine.cancel_run(run_id)`.
   b. Call `on_run_end` hook as in step 1e above.
3. Idempotency: if run already FAILED, return no-op.

**Note on STOPPING transitions (FM-3D)**: Step 1 added `transition_to_stopping(run_id)` to
`WorkflowEngine`. Use this public method — NOT an underscore-prefixed `_set_stopping`. If Step 1
used a different name, confirm the actual method name before using it in the consumer.

- [ ] Replace the `_handle_pause` stub with the implementation above
- [ ] Replace the `_handle_cancel` stub with the implementation above
- [ ] If `WorkflowEngine` lacks a direct ACTIVE→STOPPING method, add `set_run_stopping(run_id)`
  to `src/orchestrator/workflow/engine.py`

**Side Effects**
- If `WorkflowEngine.set_run_stopping()` is added, it touches `engine.py`. This is the
  only permitted additional file.

**Constraints**
- Only `consumer.py` and optionally `engine.py` (for the STOPPING helper) are modified.

**Functionality (Expected Outcomes)**
- [ ] PAUSE with active workflow: ACTIVE → STOPPING → PAUSED, unregister
- [ ] PAUSE with no active workflow: direct → PAUSED
- [ ] CANCEL with active workflow: ACTIVE → STOPPING → FAILED, on_cancel hook, unregister
- [ ] CANCEL with no active workflow: on_cancel hook, direct → FAILED
- [ ] Both handlers are idempotent for already-terminal runs

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Module imports: `uv run python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('OK')"`
- [ ] Syntax check on any modified files passes

---

## Task 4: Implement ACTIVITY Handlers

**Description**:
Implement `_handle_activity_completed()` and `_handle_activity_verified()`. Both
handlers deliver signals to an active RunWorkflow. If no active workflow exists, log
a warning and return (not an error — the run may have been cancelled between signal
enqueue and delivery).

**Implementation Plan (Do These Steps)**

`_handle_activity_completed()` logic:
1. Check `has_active_workflow(run_id)`. If not: log warning, return (handled as no-op).
2. Get the workflow: retrieve via `get_active_workflow(run_id)` (add this helper alongside
   the existing registry functions in `signals.py` if it does not exist, or use
   `_run_workflows` dict in consumer).
3. Call `await workflow.handle_activity_completed(session, service, payload)`.

`_handle_activity_verified()` logic:
Same pattern, calling `workflow.handle_activity_verified(session, service, payload)`.

**Note on workflow retrieval**: The consumer needs a way to retrieve an active `RunWorkflow`
by `run_id` to call its handler methods. Options:
- Add `get_active_workflow(run_id) -> RunWorkflow | None` as a module-level helper in
  `signals.py` alongside `has_active_workflow()` (keeps registry encapsulated).
- OR maintain a `_run_workflows: dict[str, RunWorkflow]` dict inside `SignalConsumer` itself
  (simpler, consumer owns both tasks and workflow references).

Prefer the consumer-owned dict approach for simplicity: when `_handle_run_start` or
`_handle_resume` creates a workflow, store it in `self._run_workflows[run_id]`. Remove
it in `_handle_pause`/`_handle_cancel` after unregistering.

- [ ] Add `_run_workflows: dict[str, RunWorkflow]` to `SignalConsumer.__init__`
- [ ] Update `_handle_run_start` and `_handle_resume` to store workflow in `_run_workflows`
- [ ] Update `_handle_pause` and `_handle_cancel` to remove from `_run_workflows` after unregistering
- [ ] Replace `_handle_activity_completed` stub with the implementation above
- [ ] Replace `_handle_activity_verified` stub with the implementation above

**Constraints**
- Only `consumer.py` is modified.
- Do NOT modify `signals.py` just to add a retrieval helper — the consumer dict is sufficient.

**Functionality (Expected Outcomes)**
- [ ] ACTIVITY_COMPLETED delivers to active RunWorkflow
- [ ] ACTIVITY_VERIFIED delivers to active RunWorkflow
- [ ] Missing active workflow logs a warning and marks the signal handled (no exception)
- [ ] Workflow dict stays in sync with registry across all handler paths

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Module imports: `uv run python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('OK')"`

---

## Task 5: Implement Startup Redelivery Logic

**Description**:
Add startup redelivery that re-dispatches signals where `delivered_at IS NOT NULL AND
handled_at IS NULL`. These are signals that were picked up by a previous consumer
instance (delivered_at was set) but the server crashed before the handler completed
(handled_at never set). On restart, the consumer re-dispatches them through the normal
handler path.

**Implementation Plan (Do These Steps)**

`startup_redelivery()` logic:
1. Query `pending_signals` WHERE `delivered_at IS NOT NULL AND handled_at IS NULL`,
   ordered by `id` ASC.
2. For each signal: check if `has_active_workflow(run_id)`. If the run already has an
   active workflow from a prior recovery path, skip (the workflow owns that run).
3. For inactive runs: dispatch the signal directly through `_dispatch()`.
4. If dispatch raises: log error and continue to next signal (do not abort the whole redelivery).
5. Call `await startup_redelivery()` at the beginning of `start()`, before launching `_poll_loop`.

```python
async def _startup_redelivery(self) -> None:
    async with self._session_factory() as session:
        result = await session.execute(
            select(PendingSignalModel)
            .where(
                PendingSignalModel.delivered_at.is_not(None),
                PendingSignalModel.handled_at.is_(None),
            )
            .order_by(PendingSignalModel.id)
        )
        signals = result.scalars().all()
    for signal in signals:
        if has_active_workflow(signal.run_id):
            continue
        try:
            async with self._session_factory() as session:
                await self._dispatch(session, signal)
        except Exception:
            logger.exception("Redelivery failed for signal %s", signal.id)
```

- [ ] Add `_startup_redelivery()` async method to `SignalConsumer`
- [ ] Call `await self._startup_redelivery()` at the start of `start()` before launching `_poll_loop`
- [ ] Import `PendingSignalModel` from `orchestrator.db.orm.models` (or wherever the ORM model lives)

**Constraints**
- Only `consumer.py` is modified.

**Functionality (Expected Outcomes)**
- [ ] `_startup_redelivery()` queries signals with `delivered_at IS NOT NULL AND handled_at IS NULL`
- [ ] Signals are re-dispatched in PK order (FIFO)
- [ ] Fully handled signals (`handled_at IS NOT NULL`) are not redelivered
- [ ] Not-yet-delivered signals (`delivered_at IS NULL`) are not touched by redelivery
- [ ] Individual dispatch failures do not abort the full redelivery sweep
- [ ] Redelivery completes before the main poll loop starts

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Module imports: `uv run python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('OK')"`

---

## Task 6: Unit Tests for Consumer Dispatch and Signal Handlers

**Description**:
Write unit tests that verify the core consumer behaviors: FIFO ordering, two-phase
delivery tracking, error-leaves-unhandled, and each signal handler's behavior with
both an active and inactive RunWorkflow.

**Implementation Plan (Do These Steps)**

Use an in-memory SQLite DB (already used by other tests) and mock `RunWorkflow`,
`WorkflowEngine`, and `env_lifecycle`. The goal is behavioral coverage, not just
presence coverage: each test must fail if the feature under test is broken.

Key test cases:
- **FIFO ordering**: Insert signals with ids 10, 20, 5. Confirm they are dispatched
  in order 5, 10, 20 (ascending PK).
- **delivered_at set before handler**: Mock handler records when `delivered_at` was set
  vs when it ran; assert delivery precedes handler call.
- **handled_at set after handler**: Assert `handled_at IS NOT NULL` after successful handler.
- **handler error leaves handled_at null**: Mock handler raises; assert `handled_at IS NULL`
  after dispatch.
- **RUN_START**: Run in DRAFT → assert ACTIVE, RunWorkflow created, `on_run_start` called.
- **RUN_START idempotent**: Run in ACTIVE → assert no exception, no new RunWorkflow.
- **RESUME**: Run in PAUSED → assert ACTIVE, RunWorkflow created.
- **PAUSE active**: Run in ACTIVE with active workflow → STOPPING → PAUSED, unregistered.
- **PAUSE inactive**: Run in ACTIVE with no workflow → directly PAUSED.
- **CANCEL active**: Run in ACTIVE with active workflow → STOPPING → FAILED, `on_cancel` called.
- **CANCEL inactive**: Run in ACTIVE with no workflow → FAILED, `on_cancel` called.
- **ACTIVITY_COMPLETED with active workflow**: workflow.handle_activity_completed called.
- **ACTIVITY_COMPLETED with no active workflow**: warning logged, signal marked handled.
- **ACTIVITY_VERIFIED with active workflow**: workflow.handle_activity_verified called.

For test isolation, inject a `run_workflow_factory` that returns a mock `RunWorkflow`.
The mock should have `run()`, `handle_pause()`, `handle_cancel()`, `handle_activity_completed()`,
`handle_activity_verified()` as `AsyncMock` attributes.

- [ ] Create `tests/unit/test_signal_consumer.py` with the test cases above
- [ ] Use `pytest-asyncio` with `asyncio_mode = "auto"` (check existing tests for configuration)
- [ ] Use `unittest.mock.AsyncMock` for RunWorkflow methods
- [ ] Each test must be independently runnable (no shared mutable state between tests)

**Constraints**
- Only `tests/unit/test_signal_consumer.py` is created. No production code changes.

**Functionality (Expected Outcomes)**
- [ ] FIFO ordering test passes (signals dispatched in PK order, not insertion order)
- [ ] Delivery tracking tests pass (delivered_at before handler, handled_at after success)
- [ ] Error handling test passes (handler error leaves handled_at null)
- [ ] All handler tests pass for both active and inactive RunWorkflow paths

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] All consumer tests pass: `uv run pytest tests/unit/test_signal_consumer.py -v`
- [ ] Test count ≥ 14 (one per key test case above): `uv run pytest tests/unit/test_signal_consumer.py --collect-only -q | tail -3`

---

## Task 7: Unit Tests for Crash Recovery Redelivery

**Description**:
Write unit tests for the startup redelivery path. Tests must verify that signals in
the correct state (delivered but not handled) are re-dispatched, and signals in all
other states are ignored.

**Implementation Plan (Do These Steps)**

Key test cases:
- **Redelivery re-dispatches unhandled signals**: Insert a signal with `delivered_at` set
  and `handled_at` null. Create a fresh `SignalConsumer` (simulating a restart). Call
  `_startup_redelivery()`. Assert the signal is dispatched.
- **Redelivery ignores fully handled signals**: Signal with both `delivered_at` and
  `handled_at` set. Assert it is NOT re-dispatched.
- **Redelivery ignores not-yet-delivered signals**: Signal with `delivered_at IS NULL`
  and `handled_at IS NULL`. Assert it is NOT re-dispatched.
- **Redelivery preserves FIFO order**: Insert unhandled signals with ids 30, 10, 20.
  Assert they are re-dispatched in order 10, 20, 30.
- **Redelivery skips runs with active workflow**: Insert unhandled signal for a run that
  already has an active workflow. Assert it is NOT re-dispatched.
- **Redelivery continues past errors**: Two unhandled signals. Handler for first raises.
  Assert second is still dispatched.
- **start() calls _startup_redelivery before poll loop**: Patch `_startup_redelivery` as
  an AsyncMock; call `start()`; assert it was called before poll loop began.

- [ ] Create `tests/unit/test_signal_redelivery.py` with the test cases above

**Constraints**
- Only `tests/unit/test_signal_redelivery.py` is created. No production code changes.

**Functionality (Expected Outcomes)**
- [ ] Crash recovery test passes: a signal with delivered_at set and handled_at null is re-dispatched
- [ ] Fully handled signals are not re-dispatched
- [ ] Not-yet-delivered signals are not touched by redelivery
- [ ] FIFO ordering preserved during redelivery
- [ ] Redelivery skips runs already active in the consumer
- [ ] Individual dispatch errors do not abort redelivery sweep

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] All redelivery tests pass: `uv run pytest tests/unit/test_signal_redelivery.py -v`
- [ ] Test count ≥ 7: `uv run pytest tests/unit/test_signal_redelivery.py --collect-only -q | tail -3`

---

## Task 8: Wire Consumer into App Startup and Verify Full Test Suite

**Description**:
Integrate `SignalConsumer` into the application startup lifecycle. The consumer must
start before any API requests are handled and shut down cleanly on app termination.
Then verify that all existing tests continue to pass (consumer is purely additive —
no existing signal paths have been rewired yet).

**Implementation Plan (Do These Steps)**

The consumer needs a `run_workflow_factory`. In the current codebase, `RunWorkflow`
is created inside `executor.py`. Wire the consumer so it uses the same factory
pattern: inject `session_factory`, `engine`, `env_lifecycle`, and the callbacks
bundle that `RunWorkflow.__init__` expects.

- [ ] Open `src/orchestrator/app.py`
- [ ] In the lifespan startup section (or `@app.on_event("startup")`), create and start
  a `SignalConsumer`. **FM-8A: `build_executor_callbacks(app_state)` does not exist —
  use the inline `ExecutorCallbacks(...)` construction pattern from the executor.
  FM-8B: `RunWorkflow` needs a transport — the factory must open a session per call.**

  Read `src/orchestrator/executor.py` to understand the `ExecutorCallbacks` construction
  pattern used there, then replicate it. The factory function (not a lambda) should be:
  ```python
  def make_run_workflow(run_id: str) -> RunWorkflow:
      # Transport is created per-call; RunWorkflow manages its own session for on_signal()
      return RunWorkflow(
          run_id=run_id,
          transport=None,  # consumer manages signal delivery; RunWorkflow.on_signal() disabled
          callbacks=ExecutorCallbacks(
              session_factory=session_factory,
              create_service=lambda s: WorkflowService(s, repo, engine, emitter, lock_manager),
              # ... other callbacks from executor pattern
          ),
      )

  consumer = SignalConsumer(
      session_factory=session_factory,
      run_workflow_factory=make_run_workflow,
      env_lifecycle=getattr(app.state, "env_lifecycle", None),
      engine=app.state.engine,
      service_factory=lambda s: WorkflowService(s, repo, engine, emitter, lock_manager),
  )
  app.state.signal_consumer = consumer
  await consumer.start()
  ```
  **Use the exact `ExecutorCallbacks` and `WorkflowService` construction from `app.py`'s
  existing executor wiring — do not invent new patterns.**
- [ ] In the lifespan shutdown section, call `await app.state.signal_consumer.stop()`
- [ ] Consumer must start AFTER the DB is initialised (after `await init_db()`) and
  AFTER the existing auto-resume logic (`recover_active_runs_on_startup` block) but
  BEFORE any API routes handle requests. **FM-8C: Starting consumer BEFORE auto-resume
  could cause redelivery to conflict with runs being resumed by the existing executor
  path. Place consumer.start() AFTER the auto-resume block in app.py.**
- [ ] Verify app starts without error
- [ ] Run full unit test suite: `uv run pytest tests/unit/ -x -q --tb=short`
- [ ] Run full integration test suite: `uv run pytest tests/integration/ -x -q --tb=short`

**References**
- `src/orchestrator/app.py` — existing lifespan pattern and `app.state` usage
- `src/orchestrator/executor.py` — existing `ExecutorCallbacks` construction pattern

**Constraints**
- Only `src/orchestrator/app.py` is modified (plus any necessary import additions).
- Do NOT change any existing signal routing in `WorkflowService` — that is Step 3.
- The consumer must not break any currently-passing test.

**Side Effects**
- After this task, the consumer is running in the app process but has no signals to
  process (because WorkflowService still uses the old direct paths). All existing
  tests pass unchanged.

**Functionality (Expected Outcomes)**
- [ ] `SignalConsumer` is created and started as part of app lifespan
- [ ] Consumer is stopped cleanly on app shutdown
- [ ] No existing tests break (consumer is new code, not replacing existing paths yet)
- [ ] App starts cleanly: `uv run python -c "from orchestrator.app import app; print('OK')"`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] App imports: `uv run python -c "from orchestrator.app import app; print('OK')"`
- [ ] All unit tests pass: `uv run pytest tests/unit/ -x -q --tb=line`
- [ ] All integration tests pass: `uv run pytest tests/integration/ -x -q --tb=line`
- [ ] Full backend test suite passes: `uv run pytest tests/ -x -q --tb=short`
