# Step 2 Dry-Run Analysis: Consumer

**Analyzed against codebase state:** 2026-03-26
**Step file:** `docs/single-queue-2/steps/step-02-plan.md`
**Prerequisite:** Step 1 complete (integer PK, `delivered_at`/`handled_at`, `STOPPING` state, `RUN_START` signal type).

---

## Overview

Step 2 builds the consumer as purely additive new code. Nothing rewires existing signal
paths (that is Step 3), so all existing tests should continue to pass after Task 8 wires
the consumer into app startup. The analysis below identifies concrete failure modes
against the actual codebase state.

---

## Pre-Step Baseline Verification

Before any task runs, confirm Step 1 postconditions are in place:

- `WorkflowSignal.RUN_START` exists in `signals.py` (consumer imports it in Task 2)
- `PendingSignalModel.id` is `INTEGER PRIMARY KEY` (consumer orders by `id`)
- `PendingSignalModel.delivered_at` column exists
- `PendingSignalModel.handled_at` column exists (renamed from `processed_at`)
- `RunStatus.STOPPING` exists in enum
- `WorkflowEngine` allows STOPPING→PAUSED and STOPPING→FAILED transitions

If any of these are absent the consumer module will fail to compile or runtime-error
on first use. Verify before starting Task 1.

---

## Task 1: Consumer Module Skeleton

### Assumptions

- `async_sessionmaker` and `AsyncSession` are available from `sqlalchemy.ext.asyncio`.
- The `PendingSignalModel` is importable from `orchestrator.db.orm.models` (actual path:
  `src/orchestrator/db/orm/models.py` — confirmed correct).
- Per-run task/queue dicts use `run_id: str` as key.
- Handler stubs raise `NotImplementedError` — meaning every signal processed before
  Task 2 will error and be left unhandled (eligible for retry on next poll cycle). This
  is intended behavior.

### Failure Modes

**FM-1A: `delivered_at` is set in the wrong loop scope**
The step design routes signals from the main poll loop into per-run `asyncio.Queue`
instances. `delivered_at` must be set BEFORE calling the handler, and inside the
per-run task (`_run_task`), not in the main poll loop. If `delivered_at` is
accidentally set in `_poll_loop` (at routing time rather than at dispatch time),
it would be set before the per-run task even pops the signal — this breaks the
semantic "delivered to handler" meaning and causes redelivery to re-dispatch
signals that were routed but not yet handled.

**Hardening:** Annotate clearly: `_poll_loop` only appends to per-run queues;
`_run_task` sets `delivered_at` when popping, before calling `_dispatch`.

**FM-1B: Per-run task never cleans itself up**
If a per-run `asyncio.Task` exits after draining its queue (queue empty), the
entry in `_run_tasks` and `_run_queues` becomes stale. On next signal for that
run, the code may find a `done()` task in the dict and fail to route correctly.

**Hardening:** In `_run_task`, after the queue is drained (e.g., with `queue.empty()`
check or a `QueueEmpty` catch), remove `run_id` from both `_run_tasks` and
`_run_queues` before returning. Document the cleanup contract.

**FM-1C: Signal routing loop creates duplicate per-run tasks**
The main poll loop may emit multiple signals for the same run in one batch. If
task creation is `if run_id not in _run_tasks` but checked before the task has
had a chance to register itself, concurrent signals for the same run in the same
poll batch may spawn multiple tasks.

**Hardening:** Insert into `_run_tasks` and `_run_queues` synchronously before
yielding to the event loop. Since `_poll_loop` is a single coroutine, a
`run_id in _run_tasks` guard evaluated synchronously is race-free.

**FM-1D: Long-lived DB session across the poll loop**
Opening a single session for the entire poll cycle and querying multiple rows can
leave an uncommitted transaction open for 100ms+. For SQLite this is fine, but
it becomes a problem if the session factory wraps a connection pool with short
timeouts.

**Hardening:** Follow the step's recommendation: open a new session per signal
inside `_dispatch`. For the poll query itself, use a short-lived session that
closes after the SELECT.

---

## Task 2: RUN_START and RESUME Handlers

### Assumptions

- `WorkflowEngine.start_run(run_id)` exists and transitions DRAFT→ACTIVE.
  **Confirmed** (`engine.py` line ~135).
- `WorkflowEngine.resume_run(run_id)` exists and transitions PAUSED→ACTIVE.
  **Confirmed** (`engine.py` line ~189).
- `env_lifecycle.on_run_start(run_id, ...)` is callable from within the consumer.

### Failure Modes

**FM-2A: `env_lifecycle.on_run_start` requires 4 required parameters beyond `run_id`**
This is a **critical blocker**. The actual signature is:
```python
async def on_run_start(
    self,
    run_id: str,
    repo_name: str,           # required
    worktree_path: Path,      # required
    env_specs: list[EnvFileSpec],  # required
    source_dir: Path | None = None,
) -> None:
```
The step says "Call `await self._env_lifecycle.on_run_start(run_id)`" — this will
raise `TypeError: on_run_start() missing 3 required positional arguments`.

The consumer must load the run from the DB first to retrieve `repo_name`,
`worktree_path`, and `env_specs` before calling `on_run_start`. If the run has no
`env_specs` the method is a no-op, so the quick path is to check for env specs first.

**Hardening:** In `_handle_run_start`, after transitioning DRAFT→ACTIVE:
1. Load the run object from DB.
2. Check if `run.env_file_specs` is non-empty (or equivalent field).
3. If non-empty: load worktree path and repo name from run metadata, then call
   `on_run_start` with all required args.
4. If empty: skip `on_run_start` call entirely (the method returns early anyway).

**FM-2B: `RunWorkflow.run()` already calls `register_active_run(run_id)` internally**
`RunWorkflow.run()` at line 176 of `runtime.py` calls `register_active_run(run_id)`
as the first action before starting `_run_loop()`. The step plan also says the
consumer should call `register_active_run(run_id)` before launching `run()`.

Result: `register_active_run` is called twice. Since `_active_run_ids` is a Python
`set`, the add is idempotent — no crash. But the invariant "consumer is sole
registrar" is violated: RunWorkflow self-registers.

This double-registration does not break tests in Step 2 because Step 2 is additive.
However, it becomes a correctness issue in Step 3 when both paths coexist. The
resolution belongs to Step 3 (remove `register_active_run` from `RunWorkflow.run()`),
but the architectural conflict should be noted now.

**Hardening for Step 2:** Document in consumer code that `RunWorkflow.run()` also
registers; note that Step 3 must remove registration from `RunWorkflow.run()` before
the consumer becomes the sole registrar. Do NOT remove it in Step 2.

**FM-2C: `WorkflowEngine` instance needed in consumer but not in constructor spec**
The step adds `engine: WorkflowEngine` to `SignalConsumer.__init__`. The spec is
clear. Confirm that `WorkflowEngine` is importable from `orchestrator.workflow.engine`
or `orchestrator.workflow.engine.engine`.

**Hardening:** Use `from orchestrator.workflow.engine.engine import WorkflowEngine`
(direct import form, not via `__init__`). Verify the import path before implementation.

**FM-2D: Component wiring gap — RUN_START handler not reachable yet**
In Step 2, nothing calls `WorkflowService.start_run()` via the new path. The
consumer's `_handle_run_start` is implemented and tested in isolation, but no
production code path enqueues a `RUN_START` signal to trigger it. This is
intentional per the step design ("additive only"). However, integration tests
(Task 8) should confirm the handler is reachable if a RUN_START signal is manually
inserted into `pending_signals`.

---

## Task 3: PAUSE and CANCEL Handlers

### Assumptions

- `WorkflowEngine.set_run_stopping(run_id)` will be added in this task if it doesn't exist.
  **Confirmed absent** — it must be added.
- `RunWorkflow.handle_pause(session, service, payload)` is callable as a method on the
  consumer's managed workflow instance.
- `WorkflowService` is creatable from within the consumer with just session.

### Failure Modes

**FM-3A: `env_lifecycle.on_cancel` does not exist**
This is a **critical blocker**. The `EnvFileLifecycle` class has these methods:
`on_run_start`, `on_task_start`, `on_task_end`, `on_run_end`. There is NO `on_cancel`
method. The step says `_handle_cancel()` should call
`await self._env_lifecycle.on_cancel(run_id)`. This will raise `AttributeError`.

The cancel cleanup that happens in the existing codebase occurs via worktree cleanup
in `app.py`'s lifespan (runs are cancelled by the executor, which cancels the
asyncio task, which triggers the `CancelledError` handler that calls `service.pause_run`
with `server_shutdown`, not cancel). There is no `EnvFileLifecycle` hook for cancel.

**Hardening:** Remove the `env_lifecycle.on_cancel(run_id)` call from the cancel
handler. If cancel-specific cleanup is needed (worktree deletion, etc.), it should be
called directly from the consumer via the worktree utilities, not via EnvFileLifecycle.
The step plan references must be updated to reflect this.

**FM-3B: `RunWorkflow.handle_pause()` internally calls `service.pause_run()`**
When the consumer calls `await workflow.handle_pause(session, service, payload)`, the
method does:
1. `unregister_active_run(self.run_id)`
2. `await service.pause_run(run_id, reason=reason)` — which transitions to PAUSED

Then the consumer (per the plan) also transitions STOPPING→PAUSED via
`engine.pause_run(run_id)`. This is a **double-transition**: the run is already PAUSED
from step 2, so the consumer's transition is a redundant no-op IF `engine.pause_run()`
handles already-PAUSED runs idempotently (it does, per existing code). But the
sequence means the consumer's post-handle STOPPING→PAUSED call arrives after the run
is already PAUSED.

The deeper issue is that `RunWorkflow.handle_pause()` was designed as the full handler
(it does the unregister + service call). The consumer re-wraps it with additional
pre/post steps that duplicate what the method already does. This creates logical
redundancy that may cause confusion.

**Hardening:** The consumer's `_handle_pause` should either:
a) Call `workflow.handle_pause()` and trust it to complete the full transition
   (unregister + PAUSED state), OR
b) Not call `workflow.handle_pause()` but instead directly signal the workflow to
   stop (cancel its `_run_loop`) and handle all state transitions itself.

Option (a) is simpler for Step 2. The STOPPING intermediate state transition
(ACTIVE→STOPPING) must still happen before calling `handle_pause`, but the
STOPPING→PAUSED transition can be left to `service.pause_run()` inside `handle_pause`.
Document this clearly.

**FM-3C: Consumer needs `WorkflowService` to call `workflow.handle_pause(session, service, payload)`**
`RunWorkflow.handle_pause()` signature requires a `service: WorkflowService` argument.
The consumer only has `session_factory` and `engine`. Creating a `WorkflowService`
requires `session, repo, engine, emitter, lock_manager`. The consumer doesn't have
a `repo` (RunRepository), `emitter`, or `lock_manager` readily available.

The consumer would need either:
- A service factory callable injected at construction: `create_service: Callable[[AsyncSession], WorkflowService]`
- Or access to all `WorkflowService` dependencies injected separately

**Hardening:** Add `service_factory: Callable[[AsyncSession], Awaitable[WorkflowService]]`
to `SignalConsumer.__init__`. This matches the existing `ExecutorCallbacks.create_service`
pattern used in `RunWorkflow._run_loop` (see `runtime.py` line 186:
`service = await self._callbacks.create_service(session)`). The consumer can reuse
this same pattern.

**FM-3D: `engine._set_stopping(run_id)` is not a public API**
The step uses `engine._set_stopping(run_id)` (underscore-prefixed). This implies a
private/internal method. The step also says "add `set_run_stopping(run_id)` to
`engine.py` as part of this task (max 1 additional file touch)." The correct form is to
add `engine.set_run_stopping(run_id)` as a public method alongside other engine
transition methods.

**Hardening:** Add `set_run_stopping(run_id) -> Run` as a public method to
`WorkflowEngine` (no leading underscore). Pattern it after `pause_run()`.

---

## Task 4: ACTIVITY Handlers

### Assumptions

- `RunWorkflow.handle_activity_completed(session, service, payload)` exists.
  **Confirmed** (runtime.py line 314).
- `RunWorkflow.handle_activity_verified(session, service, payload)` exists.
  **Confirmed** (runtime.py line 351).
- The consumer's `_run_workflows` dict is the authoritative source for active
  RunWorkflow references.

### Failure Modes

**FM-4A: Signal competition between consumer and `RunWorkflow.on_signal()`**
This is the most subtle structural issue in the step. In the target architecture the
consumer processes ALL signals from `pending_signals`. But `RunWorkflow._run_loop()`
calls `self.on_signal()` at the top of every iteration, which drains pending signals
via `SignalQueue.drain(run_id)`.

After Task 8 wires the consumer into app startup, both the consumer AND
`RunWorkflow.on_signal()` will poll `pending_signals` for ACTIVITY signals. A signal
could be consumed by `RunWorkflow.on_signal()` before the consumer picks it up (it
would then have `handled_at` set and the consumer won't see it), OR the consumer picks
it up first (sets `delivered_at`, calls handler) and `RunWorkflow.on_signal()` misses it.

**The resolution is that `RunWorkflow.on_signal()` queries for `processed_at IS NULL`
(or `handled_at IS NULL` after Step 1 renaming).** If the consumer sets `handled_at`
after completing the handler, `RunWorkflow.on_signal()` won't re-process it. But if
the consumer sets `delivered_at` and then calls `_handle_activity_completed()` (which
is `workflow.handle_activity_completed(session, service, payload)`), this IS the same
processing that `RunWorkflow.on_signal()` would do. They'd be doing the same work in
parallel.

**In Step 2, this race doesn't manifest in tests** because:
1. Existing tests use `InMemorySignalTransport` (no DB involvement).
2. Integration tests use old paths where WorkflowService delivers signals directly
   to RunWorkflow (not via pending_signals for active runs).

But it IS a latent race that will surface in Step 3 when senders are rewired. The
step should explicitly note that `RunWorkflow.on_signal()` must be disabled or made
a no-op once the consumer is the primary signal processor (likely in Step 3 or 4).

**Hardening for Step 2:** Add a TODO/comment in `_handle_activity_completed` and
`_handle_activity_verified` noting that `RunWorkflow.on_signal()` is the current
processor of these signals; the consumer calling these handlers directly is only safe
once `RunWorkflow.on_signal()` is disabled (Step 3+).

**FM-4B: `service_factory` needed for activity handlers too**
Same issue as FM-3C: `handle_activity_completed(session, service, payload)` requires
a `WorkflowService`. The consumer must construct it. Apply the same `service_factory`
injection fix from FM-3C.

---

## Task 5: Startup Redelivery

### Assumptions

- `PendingSignalModel.delivered_at` and `PendingSignalModel.handled_at` are both
  importable from the ORM model (confirmed, after Step 1 migration).
- `select(PendingSignalModel)` works with the updated schema.

### Failure Modes

**FM-5A: Redelivery calls `_dispatch()` which opens a session internally, but redelivery also opens its own session**
The redelivery pseudocode in the step opens one session to fetch signals, closes it,
then opens a new session per `_dispatch()` call. This is correct — sessions don't
live across the signal fetch and handler invocation. But `_dispatch()` itself would
need to open the session (or receive one). The step's example passes `session` to
`_dispatch()`, so the redelivery code must open a per-signal session before calling
`_dispatch()`.

**Hardening:** Keep the session management as shown in the step's pseudocode: one
session for the SELECT query (closed after fetch), one session per dispatched signal.

**FM-5B: Redelivery may deliver ACTIVITY signals to workflows that have resumed on the same startup**
During startup redelivery, if a run has been auto-resumed (e.g., server_shutdown
auto-resume in `app.py`), it may already have an active RunWorkflow. The step says
"if `has_active_workflow(run_id)`: skip." This is correct — skip if already active.
But auto-resume happens in `app.py`'s startup, which may run before or after the
consumer's redelivery. The ordering must be explicit.

**Hardening:** In Task 8, ensure consumer.start() (which calls `_startup_redelivery`)
runs AFTER the existing auto-resume logic in `app.py`. This prevents redelivery from
double-processing signals for already-resumed runs.

---

## Task 6: Unit Tests for Consumer Dispatch

### Assumptions

- Tests use `asyncio_mode = "auto"` (confirmed from existing test files).
- `InMemorySignalTransport` is used for signal injection (not DB).
- `RunWorkflow` is mocked — its `run()` is an `AsyncMock`.

### Failure Modes

**FM-6A: Mock `RunWorkflow` does not call `register_active_run` in `run()`**
The real `RunWorkflow.run()` calls `register_active_run(run_id)`. A mock won't.
This means tests for the `_handle_run_start` handler that check "workflow is
registered after handler" will pass even if the consumer's own `register_active_run`
call is removed — they won't catch the double-registration bug noted in FM-2B.

**Hardening:** In tests that verify registration, explicitly check that
`has_active_workflow(run_id)` is True AFTER the mock `run()` is launched, and track
whether registration came from the consumer or the mock (by inspecting the mock call
order). Note that the mock won't self-register; only the consumer's explicit call
registers.

**FM-6B: FIFO ordering test must use integer PKs**
If Step 1 migration is not complete and `id` is still a UUID string, the FIFO test
ordering will be wrong (string comparison of UUIDs doesn't match insertion order).
The test MUST insert signals with specific integer PK values (e.g., 5, 10, 20) and
assert they are processed in ascending numeric order.

**Hardening:** Use an in-memory SQLite DB with the Step 1 schema (integer PK). Assert
that signals are dispatched in PK-ascending order by capturing dispatch call order.

**FM-6C: Per-run task async interactions**
Tests that test "FIFO ordering within a single run" need to await the per-run task
completion before asserting order. If the main poll loop routes signals to a per-run
queue but the test asserts before the per-run task drains the queue, assertions
will be premature.

**Hardening:** After injecting signals and advancing the poll loop, explicitly
`await asyncio.sleep(0)` or `await consumer._run_tasks[run_id]` (with a cancel
guard) to ensure per-run tasks have fully drained.

---

## Task 7: Unit Tests for Crash Recovery Redelivery

### Assumptions

- Tests directly insert rows into DB with `delivered_at` set and `handled_at` null
  to simulate crash state.
- `_startup_redelivery()` can be called independently (not just via `start()`).

### Failure Modes

**FM-7A: Test "start() calls _startup_redelivery before poll loop" depends on ordering**
The test patches `_startup_redelivery` as `AsyncMock` and calls `start()`. But `start()`
launches `_poll_loop` as a background task. The assertion "redelivery was called before
poll loop" requires observing ordering of async calls. The background task may not have
started yet when `start()` returns.

**Hardening:** Implement `start()` with an explicit `await self._startup_redelivery()`
BEFORE `asyncio.create_task(self._poll_loop())`. This is synchronously ordered, so
patching `_startup_redelivery` and checking it was awaited before `create_task` is
reliably testable.

---

## Task 8: Wire Consumer into App Startup

### Assumptions

- Consumer is wired as part of the lifespan startup.
- `build_executor_callbacks(app_state)` provides a complete `ExecutorCallbacks`.

### Failure Modes

**FM-8A: `build_executor_callbacks(app_state)` does not exist**
This is a **critical blocker**. The task pseudocode references
`build_executor_callbacks(app_state)` which is not defined anywhere in the codebase.
The actual pattern in `app.py` and `executor.py` constructs `ExecutorCallbacks(...)`
directly with all required fields. Callers like `app.py` lines 607–620 show the
pattern: instantiate `WorkflowService` with all dependencies explicitly.

**Hardening:** Replace `build_executor_callbacks(app_state)` with the inline
`ExecutorCallbacks(...)` construction pattern already used in the executor. All
required fields:
- `session_factory`: `app.state.session_factory`
- `create_service`: same factory callable used by executor
- `monitor_agent_health`: from executor or a no-op
- `heartbeat`, `find_next_task`, `execute_task`, `attempt_store`, `broadcaster`: all
  from `app.state.runner_executor`

**FM-8B: `RunWorkflow` created by consumer needs a `transport` for `on_signal()`**
`RunWorkflow.__init__` accepts `transport: SignalTransport | None`. The consumer's
`_run_workflow_factory` must provide a `DbSignalTransport(session)` or the RunWorkflow
will use a null transport and `on_signal()` will fail silently.

Since the factory is a lambda, the session is not available at factory-creation time.
The factory must be a callable that opens a session per-call, or `RunWorkflow.__init__`
must accept the `session_factory` and create transport lazily.

**Hardening:** The factory lambda should construct the transport at call time:
```python
run_workflow_factory=lambda run_id: RunWorkflow(
    run_id=run_id,
    transport=DbSignalTransport(session_for_this_call),  # needs session
    callbacks=callbacks,
)
```
This requires the factory to be a proper function (not a lambda) with access to
`session_factory` so it can open a session. Alternatively, pass `session_factory`
directly to `RunWorkflow` and have it manage transport internally (deferred design).

**FM-8C: Consumer startup ordering relative to auto-resume logic in `app.py`**
`app.py`'s lifespan already auto-resumes runs paused with `server_shutdown` reason.
This creates `RunWorkflow` instances (via the existing executor path) and registers
them. If the consumer starts BEFORE this auto-resume, the consumer's redelivery may
try to re-dispatch the same runs' signals — but `has_active_workflow` guard would
prevent it. If the consumer starts AFTER, there's no conflict.

**Hardening:** Start the consumer AFTER the existing auto-resume block in `app.py`.
Add a comment explaining this ordering dependency.

**FM-8D: Consumer competes with `RunWorkflow.on_signal()` for ACTIVITY signals**
See FM-4A. In Step 2, this does not break existing tests because:
1. In-memory transport tests don't involve the DB.
2. Integration tests use old WorkflowService paths where signals are delivered
   directly (no pending_signals for active runs).
But this race is a time bomb for Step 3 integration tests.

**Hardening:** Add an explicit test after Task 8 wiring that confirms an ACTIVITY
signal is processed EXACTLY ONCE (not twice) under the combined consumer + RunWorkflow
system. This will either pass (race doesn't manifest in tests) or expose the bug early.

**FM-8E: Consumer polling adds 100ms latency to all operations**
Existing integration tests likely assert state transitions without any delay (synchronous
signal delivery via `drain_signals` helper). After wiring the consumer, tests that
trigger signals through the NEW consumer path will need to wait up to 100ms for the
consumer to pick up the signal.

In Step 2, existing tests still use old paths, so this doesn't break them. But it's
a heads-up for Step 3 test updates.

---

## Component Wiring Verification

The step is explicitly additive: no existing call sites are replaced. The consumer is
a new class, started by `app.py`, that runs in the background. In Step 2:

- Consumer IS wired: `app.py` starts it in lifespan.
- Consumer has NOTHING to do: no new-path signals are enqueued.
- All existing tests use old paths: they pass unchanged.

The wiring is complete but inert until Step 3. This is the correct design. The only
risk is FM-8D (signal competition), which is latent in Step 2 but surfaces in Step 3.

---

## Summary of Failure Modes by Severity

### Critical (will break implementation)

| ID | Task | Issue |
|----|------|-------|
| FM-2A | Task 2 | `env_lifecycle.on_run_start` requires 4+ parameters; step calls it with 1 |
| FM-3A | Task 3 | `env_lifecycle.on_cancel` does not exist on `EnvFileLifecycle` |
| FM-3C | Task 3 | Consumer needs `WorkflowService` (service factory) for handler calls; not in constructor |
| FM-8A | Task 8 | `build_executor_callbacks(app_state)` function does not exist in codebase |
| FM-8B | Task 8 | `RunWorkflow` factory needs a `transport`; lambda can't provide it without session |

### Moderate (will cause subtle bugs or test failures)

| ID | Task | Issue |
|----|------|-------|
| FM-2B | Task 2 | `RunWorkflow.run()` already calls `register_active_run` — double-registration |
| FM-3B | Task 3 | `RunWorkflow.handle_pause()` internally calls `service.pause_run()` — double-transition |
| FM-3D | Task 3 | `engine._set_stopping()` underscore form — should be public `set_run_stopping()` |
| FM-4A | Task 4 | Consumer + `RunWorkflow.on_signal()` both poll `pending_signals` — latent race for Step 3 |
| FM-4B | Task 4 | `handle_activity_completed/verified` also needs `WorkflowService` (same as FM-3C) |
| FM-6A | Task 6 | Mock `RunWorkflow` won't self-register — false confidence on registration invariants |
| FM-8C | Task 8 | Consumer must start AFTER auto-resume block to avoid redelivery conflict |

### Minor (design clarity / robustness)

| ID | Task | Issue |
|----|------|-------|
| FM-1A | Task 1 | `delivered_at` set in wrong loop scope if implemented carelessly |
| FM-1B | Task 1 | Per-run task never cleans up stale entries in `_run_tasks`/`_run_queues` |
| FM-1C | Task 1 | Race creating duplicate per-run tasks in same poll batch (synchronous check avoids it) |
| FM-1D | Task 1 | Long-lived DB session across poll loop |
| FM-5A | Task 5 | Session management in redelivery — one session per dispatched signal |
| FM-5B | Task 5 | Redelivery ordering relative to auto-resume |
| FM-6B | Task 6 | FIFO test must use integer PKs (Step 1 postcondition) |
| FM-6C | Task 6 | Per-run async task draining must complete before test assertions |
| FM-7A | Task 7 | `start()` ordering test requires explicit `await` before `create_task` |
| FM-8D | Task 8 | Latent signal competition — add explicit "processed exactly once" test |
| FM-8E | Task 8 | 100ms latency for consumer-path signals (only matters in Step 3+ tests) |

---

## Hardening Summary

1. **Inject `service_factory`** into `SignalConsumer.__init__` (mirrors `ExecutorCallbacks.create_service` pattern). Resolves FM-3C and FM-4B.
2. **Load run from DB** in `_handle_run_start` before calling `env_lifecycle.on_run_start(run_id, repo_name, worktree_path, env_specs)`. Resolves FM-2A.
3. **Remove `env_lifecycle.on_cancel` call** from `_handle_cancel` — use worktree cleanup directly if needed, since `EnvFileLifecycle` has no such method. Resolves FM-3A.
4. **Replace `build_executor_callbacks`** with inline `ExecutorCallbacks(...)` construction. Resolves FM-8A.
5. **Provide `transport` via factory function** (not lambda) that opens a session for `DbSignalTransport`. Resolves FM-8B.
6. **Add public `WorkflowEngine.set_run_stopping(run_id)`** (no underscore). Resolves FM-3D.
7. **Add TODO in Step 2** noting that `RunWorkflow.run()` self-registers (must be removed in Step 3). Resolves FM-2B.
8. **Document `on_signal()` conflict** in activity handlers — will be resolved in Step 3. Resolves FM-4A.
9. **Ensure consumer.start() after auto-resume block** in app.py lifespan. Resolves FM-8C.
10. **Per-run task cleanup**: remove from `_run_tasks`/`_run_queues` on queue empty. Resolves FM-1B.
