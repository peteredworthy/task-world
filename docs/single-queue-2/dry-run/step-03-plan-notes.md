# Step 3 Dry-Run Analysis: Sender Rewiring

**Date:** 2026-03-26
**Step file:** `docs/single-queue-2/steps/step-03-plan.md`
**Plan file:** `docs/single-queue-2/steps/step-03-plan.md` (step plan at bottom)

---

## Executive Summary

Step 3 is the behavioral pivot of the entire single-queue migration. It carries
the highest risk of any phase because it rewires all lifecycle call sites at once
and the test infrastructure (InMemorySignalTransport drain) is fundamentally
incompatible with the DB-based signal enqueue the service methods will use after
rewiring. There are also two circular-signal-loop bugs in signal handlers, and
13+ internal `service.pause_run()` calls in `_run_loop()` that are not addressed
by any task in this step.

---

## Pre-condition Check

The step assumes S-01 (schema + STOPPING) and S-02 (consumer loop) are complete.
All analysis below assumes both are done.

---

## Task-by-Task Simulation

### Task 1: Rewire `start_run()` to enqueue `RUN_START`

**Assumptions:**
- `RUN_START` exists in `WorkflowSignal` enum (added by S-01).
- `DbSignalTransport` and `SignalQueue` are importable from `orchestrator.workflow.signals`.
- `_build_engine` and `_persist` are NOT called in the current `start_run()` body
  (the method calls `self._engine.start_run()` using an already-built engine attribute,
  not a `_build_engine()` helper). The step's mention of removing `_build_engine /
  _persist` usage is somewhat misleading — these are patterns used in other methods
  but may not appear in `start_run()` itself. **Verify** before removing them.

**Expected output:**
`service.start_run()` inserts one `pending_signals` row and returns the run in DRAFT.

**Blockers:**
- None significant if S-01/S-02 are complete.

**Failure modes:**

1. **`executor.start_run_with_agent()` race condition** (HIGH)
   The router calls `executor.start_run_with_agent(run_id, service)` which calls
   `service.start_run()` internally. After rewiring, the service returns the run in
   DRAFT state (no ACTIVE transition). `start_run_with_agent()` then tries to create
   a worktree and spawn an agent. Worktree creation checks `run.source_branch` (not
   `run.status`), so this may be OK. But the agent subprocess launched while the run
   is still in DRAFT may behave unexpectedly when it calls back via `/tasks/{id}/start`.
   The consumer will transition to ACTIVE within 100ms, but there is a window.
   **Hardening:** Add an explicit note in the step that `start_run_with_agent()` must
   NOT check `run.status == ACTIVE` as a guard for its own logic. Read the executor
   code and confirm before implementing.

2. **`_build_engine` / `_persist` references** (LOW)
   The step says to remove these from `start_run()`. Verify that the current
   `start_run()` actually uses `_build_engine` / `_persist` — a search in service.py
   shows `_persist()` is used in many methods but `start_run()` might use
   `self._engine` (already-built) directly. Blindly removing code that isn't there
   could introduce bugs or leave actual calls intact.

---

### Task 2: Move `env_lifecycle.on_run_start()` to consumer `_handle_run_start()`

**Assumptions:**
- `EnvFileLifecycle.on_run_start()` signature:
  `async def on_run_start(self, run_id, repo_name, worktree_path, env_specs, source_dir=None)`
- `Run` model has `env_source_dir: str | None` and `env_file_specs: list[dict]` fields.
  Both confirmed in `src/orchestrator/db/orm/models.py` lines 65-66. OK.
- Consumer already has access to a DB session to load the Run object.

**Expected output:**
Consumer calls `env_lifecycle.on_run_start()` inline after DRAFT → ACTIVE transition.

**Failure modes:**

3. **`env_lifecycle` not injected into consumer** (HIGH)
   Task 6 wires the consumer with `env_lifecycle=getattr(app.state, "env_lifecycle", None)`.
   But `app.state.env_lifecycle` may not be set if the app was created without env file
   support. The `None` guard is correct. However, if `env_lifecycle` IS configured,
   the consumer must call it correctly. The step shows pseudocode but doesn't confirm
   the exact call signature matches `EnvFileLifecycle.on_run_start()`. The step's
   proposed code passes `env_specs=run.env_file_specs` but the signature parameter
   is `env_specs: list[EnvFileSpec]`. Verify whether raw `list[dict]` is accepted or
   needs deserialization to `EnvFileSpec` objects.

4. **Error from `on_run_start()` leaves run stuck in ACTIVE with no task** (MEDIUM)
   If the hook raises, the step says `handled_at` stays null so the signal is
   redelivered. But the run was already transitioned to ACTIVE before the hook call.
   On redelivery, the transition guard for DRAFT → ACTIVE will fail (run is already
   ACTIVE). Consumer needs to handle re-delivery idempotently when run is already ACTIVE.
   **Hardening:** Add explicit guidance that the DRAFT → ACTIVE guard in the consumer
   must be idempotent (skip if already ACTIVE) for redelivery safety.

---

### Task 3: Rewire `pause_run()` and `resume_run()`

**Assumptions:**
- Consumer handles PAUSE and RESUME signals (from S-02).
- `resume_run()` revert-strategy logic (lines 493–547) stays in the service method
  and runs before enqueueing RESUME.

**Expected output:**
Both methods enqueue signals without calling `engine.pause_run()` / `engine.resume_run()`.

**Failure modes:**

5. **CRITICAL: Circular signal loop — `handle_pause()` calls `service.pause_run()`**
   `RunWorkflow.handle_pause()` in `runtime.py` line 287 calls
   `await service.pause_run(self.run_id, reason=reason)`. After Step 3, `pause_run()`
   enqueues another PAUSE signal. The consumer then picks up the new PAUSE signal and
   delivers it to the (still-running) RunWorkflow's `handle_pause()` which calls
   `service.pause_run()` again — infinite loop.

   The step only says to remove `unregister_active_run()` from `handle_pause()` (Task 5).
   It does NOT say to remove or replace the `service.pause_run()` call. This is a missing
   task.

   **Root cause:** `handle_pause()` currently uses `service.pause_run()` to apply the
   PAUSED DB transition. In the new model, the consumer applies this transition AFTER
   RunWorkflow acknowledges. `handle_pause()` should just `return True` (stop the loop)
   and NOT call the service.

   **Hardening:** Add an explicit task: "Rewrite `RunWorkflow.handle_pause()` to return
   `True` without calling `service.pause_run()`. The DB transition is now the consumer's
   responsibility."

6. **CRITICAL: Circular signal loop — `handle_cancel()` calls `service.cancel_run()`**
   Same problem as #5. `handle_cancel()` in `runtime.py` line 311 calls
   `await service.cancel_run(self.run_id)`. After rewiring, this enqueues another CANCEL
   signal → infinite loop.

   Task 5 only removes `unregister_active_run()` from `handle_cancel()`, NOT the
   `service.cancel_run()` call.

   **Hardening:** Same fix: `handle_cancel()` should `return True` without calling the
   service. Consumer applies the FAILED transition.

7. **CRITICAL: 13 internal `service.pause_run()` calls in `_run_loop()` not addressed**
   `_run_loop()` in `runtime.py` calls `service.pause_run()` (with `unregister_active_run()`
   before each call) at lines 487, 519, 543, 549, 561, 575, 587 — and `run()` calls
   it at lines 187, 199, 230. These are for internal error-handling paths
   (gate_blocked, agent_cancelled, agent_not_available, agent_execution_error, etc.).

   After rewiring, each of these enqueues a PAUSE signal. The RunWorkflow then calls
   `unregister_active_run()` (removing itself from the registry) and exits. The consumer
   later picks up the PAUSE signal, finds no active RunWorkflow, and transitions directly
   to PAUSED. This sequence is semantically correct.

   However:
   - `unregister_active_run()` is called from `_run_loop()` violating the registry
     isolation invariant planned for Phase 4.
   - The step does NOT address these 13 call sites. Tasks 3, 4, and 5 do not mention
     `_run_loop()`.
   - Step 5 verification: `grep "unregister_active_run" src/orchestrator/workflow/signals/runtime.py`
     — allows "executor-level finally blocks" but the `_run_loop()` calls are NOT in
     finally blocks. The grep will show many hits in `_run_loop()` that the step
     didn't intend to allow.

   **Hardening:** Explicitly scope what happens to `_run_loop()` internal calls. Either:
   (a) Accept the registry invariant violation in Step 3 and address in Step 4
   (document this explicitly), OR (b) add a task to rewrite all `service.pause_run()`
   calls in `_run_loop()` to use a direct engine/DB path (bypassing the signal queue
   for internal transitions).

8. **`handle_activity_completed()` also calls `service.pause_run()`** (HIGH)
   `handle_activity_completed()` at line 343 calls `service.pause_run()` when a gate
   is blocked. After rewiring, this enqueues a PAUSE signal while the RunWorkflow is
   still processing a signal (inside `on_signal()`). The consumer will then deliver
   a second PAUSE signal to the RunWorkflow. This may cause RunWorkflow to process two
   PAUSE signals in sequence.
   **Hardening:** Include this call site in the same scoping decision as #7.

9. **`resume_run()` revert strategy not propagated to consumer** (MEDIUM)
   The revert strategy (reverting the first BUILDING/VERIFYING task to QUEUED) and
   agent-change logic run in `resume_run()` BEFORE enqueueing the RESUME signal. The
   consumer's `_handle_resume()` handler then transitions PAUSED → ACTIVE and creates
   RunWorkflow. This ordering is correct — the DB is mutated first, then the signal
   is enqueued. No loop.

   However: if `resume_run()` applies the revert strategy and then enqueueing fails,
   the DB is left in a partially reverted state. This is a pre-existing risk (not new
   to this step). Acceptable, but worth noting.

---

### Task 4: Rewire `cancel_run()` and `retry_fan_out_child()`

**Assumptions:**
- `handle_run_completion()` is in `src/orchestrator/workflow/completion.py` (confirmed).
- Consumer needs access to `_create_worktree_manager()` logic.
- `env_lifecycle.on_run_end()` and `handle_run_completion()` are correctly imported
  in consumer.

**Expected output:**
`cancel_run()` enqueues CANCEL; consumer's `_handle_cancel()` runs cleanup hooks.

**Failure modes:**

10. **`_create_worktree_manager()` dependency in consumer** (HIGH)
    `service._create_worktree_manager()` uses `self._global_config` to create a
    `WorktreeManager`. The consumer must replicate this logic or import it. The step says
    "Use a helper that replicates `WorkflowService._create_worktree_manager()`" without
    specifying what that helper looks like or where it lives. If the consumer doesn't
    get `global_config`, worktree cleanup silently does nothing.
    **Hardening:** Specify the exact helper function location and signature. Confirm
    the consumer's `__init__` receives `global_config` and that `global_config` is
    wired in Task 6.

11. **`cancel_run()` idempotency guard uses stale run status** (MEDIUM)
    The proposed `cancel_run()` fetches the run and returns early if `status in
    (FAILED, COMPLETED)`. But after Step 3, STOPPING is also a valid terminal-bound
    state — a duplicate cancel for a STOPPING run should also be a no-op. The S-01
    API guard may cover this, but the service-level guard should also include STOPPING.
    **Hardening:** Add `RunStatus.STOPPING` to the early-return guard in `cancel_run()`.

12. **`retry_fan_out_child()` pause reason** (LOW)
    The new code enqueues PAUSE with `{"reason": "fan_out_child_retry"}`. In the old
    code when not active, it called `_repo.update_run_status()` with
    `pause_reason="fan_out_child_retry"` directly. Confirm that the consumer's
    `_handle_pause()` correctly propagates the `reason` payload to the DB transition.

---

### Task 5: Remove `unregister_active_run()` from handlers; change to 202

**Part A — Registry removal:**

13. **Step only targets `handle_pause` and `handle_cancel`; misses `_run_loop()`** (HIGH)
    Already covered in #7. The grep verification in Task 5 checks for "no hits in
    `handle_pause` or `handle_cancel`" — but `_run_loop()` has 7+ hits that will remain.
    The step's verification is too narrow and will give a false sense of completeness.

14. **`handle_pause()` still calls `service.pause_run()` after removing `unregister_active_run()`**
    Already covered in #5. The handler will have a circular loop even after the registry
    call is removed.

**Part B — 202 change:**

15. **`Response` import needed in `runs.py`** (LOW)
    The step correctly notes this. Confirm `from fastapi import Response` is not already
    imported. If the router uses `Response` elsewhere (e.g., for 409 returns), it may
    already be imported.

16. **Returning `Response(status_code=202)` changes response schema** (MEDIUM)
    Currently, start/pause/resume/cancel return `RunResponse` with full run data. After
    the change, they return empty 202 bodies. Frontend and any external API consumers
    expecting JSON body will break. The step acknowledges this but doesn't track a
    frontend update task. If there's no matching frontend PR, the UI will break
    (buttons that show spinner based on response JSON will fail silently).
    **Hardening:** Confirm frontend handling of 202 is in scope for this step or
    tracked in a follow-up task.

17. **`cancel_run` and `pause_run` router handlers call `executor.cancel_run()` first**
    The router calls `executor.cancel_run(run_id)` (which cancels the asyncio task)
    AND `service.cancel_run(run_id)` (which now enqueues). The executor call is still
    needed (terminates agent subprocess). This is correct behavior. No issue.

---

### Task 6: Wire Consumer Startup into App Lifespan

**Assumptions:**
- `SignalConsumer` exists with a `run()` coroutine (S-02 complete).
- Consumer `__init__` accepts `session_factory`, `global_config`, `env_lifecycle`.
- Consumer can be cancelled cleanly via `asyncio.CancelledError`.

**Expected output:**
`app.state.signal_consumer` holds a running consumer; cancelled on shutdown.

**Failure modes:**

18. **Consumer must start BEFORE `recover_active_runs_on_startup()`** (HIGH)
    The step says this explicitly, but `app.py` currently does:
    - Line 65: `recover_active_runs_on_startup()` (checks agent liveness)
    - Lines 76-100: Spawns executor loops for ACTIVE runs
    - Lines 102-207: Auto-resumes PAUSED runs via `service.resume_run()`

    If `service.resume_run()` (line 193) now enqueues RESUME signals, and the consumer
    is not yet started, those signals sit in the queue unprocessed until the consumer
    starts. If the consumer starts AFTER line 207, there is a window where resume signals
    are dead-lettered.

    Additionally, lines 76-100 spawn executor loops for ACTIVE runs via a direct path
    that bypasses the consumer. After Step 3, this direct spawning may conflict with
    the consumer processing RUN_START signals for the same runs.
    **Hardening:** Specify exactly where in `app.py` the consumer start is inserted.
    Remove or gate the direct-spawn code at lines 76-100 (or confirm it's still needed
    alongside the consumer).

19. **Consumer startup before `global_config` is available** (LOW)
    Verify that `global_config` is accessible in `app.state` at the point the consumer
    is created in the lifespan. If config is loaded later, the consumer won't have it.

---

### Task 7: Update Integration Tests for 202 and Async Transitions

**This task has the most significant gap in the entire step.**

20. **CRITICAL: Test infrastructure transport mismatch**
    All integration tests use `InMemorySignalTransport` for `drain()`:
    ```python
    transport_obj = InMemorySignalTransport()
    drain = make_drain_fn(app, transport_obj)
    ```
    `make_drain_fn()` creates a `RunWorkflow(run_id, transport=InMemorySignalTransport)`
    and calls `rw.on_signal()`. This drains signals from the InMemory transport.

    After Step 3, `service.start_run()` / `pause_run()` / `resume_run()` / `cancel_run()`
    all enqueue signals via `DbSignalTransport(self._session)`. Signals go into the
    SQLite DB, NOT into `InMemorySignalTransport`.

    `drain()` will drain from InMemorySignalTransport and find ZERO signals from
    lifecycle operations. The consumer is NOT running in tests (app lifespan not started
    by `ASGITransport(app=app)`). Tests that call `_start_run()` and then check
    `run["status"] == "active"` will fail forever.

    The step's proposed `wait_for_status()` polling helper will never succeed because
    there is no consumer processing the DB-backed signals.

    **Root cause:** The step treats tests as if they run a real consumer, but they use
    a synchronous-drain model with InMemorySignalTransport that bypasses the real signal
    flow after rewiring.

    **Required fix (not in the step):**
    Option A — Make the service injectable: `WorkflowService` accepts an optional
    `signal_transport: SignalTransport | None = None`. When set, uses it instead of
    creating `DbSignalTransport(session)`. Tests inject InMemorySignalTransport; production
    uses the default DbSignalTransport. `deps.py` reads `app.state.signal_transport`
    and passes it through.

    Option B — Update drain to use DbSignalTransport: Rewrite `make_drain_fn()` and
    `drain_signals()` to use `DbSignalTransport` AND route through consumer handlers
    (not `RunWorkflow.on_signal()`). This makes drain equivalent to "run the consumer
    once for this run_id".

    Option C — Start app lifespan in tests: Switch test client to one that starts
    lifespan (e.g., Starlette's `TestClient` in async mode). More invasive.

    **Hardening:** The step must explicitly choose one of these options and add it as
    a task. Without this, all integration tests will fail after Task 1 is complete.

21. **`drain()` routes through `RunWorkflow.on_signal()`, not consumer handlers** (HIGH)
    Even if the transport mismatch is fixed, `drain()` currently routes through
    `RunWorkflow.on_signal()` → `build_registry()` → `handle_activity_completed`, etc.
    The RUN_START, RESUME (lifecycle), PAUSE (from service), CANCEL signals are NOT
    handled by RunWorkflow signal handlers. So even with the correct transport, the
    consumer's `_handle_run_start()`, `_handle_resume()`, etc. would never be called.
    The drain infrastructure needs to call the consumer's dispatch loop, not RunWorkflow's
    on_signal().

22. **`_start_run()` test helper asserts 200 and gets response body** (HIGH)
    `_start_run()` does `assert resp.status_code == 200` and `return resp.json()`. After
    Task 5 changes the endpoint to 202 with empty body, `resp.json()` will return `{}`
    or fail. Tests that use `run_data = await _start_run(...)` and then access
    `run_data["status"]` will fail immediately.
    **Hardening:** Update `_start_run()` to `assert resp.status_code == 202` and return
    `{}` or perform a separate GET for the run state.

23. **`test_full_lifecycle_cancel_active_run` checks `resp.json()["status"] == "failed"`**
    After Task 5, cancel returns 202 with no body. The test cannot extract status from
    the 202 response body. A separate GET is needed after calling cancel.

24. **`test_full_lifecycle_pause_resume` checks `resp.json()["status"] == "paused"` and `"active"`**
    Same problem as #23.

---

## Component Wiring Analysis

### New code introduced vs. actual call sites

| Component | Introduced in | Called from | Wiring verified? |
|-----------|--------------|-------------|-----------------|
| Consumer `_handle_run_start()` | S-02 | Consumer loop (S-02) | Yes, via consumer dispatch |
| Consumer `_handle_pause()` (with STOPPING) | S-02 | Consumer loop | Yes |
| Consumer `_handle_cancel()` (with env_lifecycle) | Task 4 | Consumer loop | Yes |
| Consumer loop startup | Task 6 | `app.py` lifespan | Needs explicit placement |
| `service.start_run()` enqueue | Task 1 | `executor.start_run_with_agent()` | Yes (router unchanged) |
| `service.pause_run()` enqueue | Task 3 | Router `pause_run`, `_run_loop()` internal calls | Partial (internal calls still call service directly) |

### Critical gap: RunWorkflow handlers after rewiring

After this step, `RunWorkflow.handle_pause()` calls `service.pause_run()` → re-enqueues.
`RunWorkflow.handle_cancel()` calls `service.cancel_run()` → re-enqueues. The consumer
delivers the signal to RunWorkflow, which creates a new signal, which the consumer
will pick up again. Neither handler is updated by any task in this step except to
remove `unregister_active_run()`.

**The step must add tasks to rewrite `handle_pause()` and `handle_cancel()` to stop
calling service methods and instead simply return `True` (acknowledge to consumer).**

---

## Summary of Hardening Actions

| # | Severity | Issue | Action Required |
|---|---------|-------|----------------|
| 5 | CRITICAL | `handle_pause()` → `service.pause_run()` loop after rewiring | Add task: rewrite `handle_pause()` to return True without calling service |
| 6 | CRITICAL | `handle_cancel()` → `service.cancel_run()` loop after rewiring | Add task: rewrite `handle_cancel()` to return True without calling service |
| 20 | CRITICAL | Test transport mismatch: service uses DB, drain uses InMemory | Add task: make service transport injectable OR update drain to use DB+consumer handlers |
| 7 | HIGH | `_run_loop()` has 13+ `service.pause_run()` + `unregister_active_run()` calls not addressed | Scope explicitly: accept invariant violation until Step 4, OR rewrite all to direct engine calls |
| 1 | HIGH | `start_run_with_agent()` spawns agent while run is still DRAFT | Read executor code; confirm no ACTIVE guard; add note |
| 3 | HIGH | `env_lifecycle` injection signature mismatch (`list[dict]` vs `list[EnvFileSpec]`) | Verify type accepted by `on_run_start()` or add deserialization |
| 4 | HIGH | Re-delivery of RUN_START when run already ACTIVE → transition guard fails | Add idempotency: skip DRAFT→ACTIVE if run already ACTIVE |
| 8 | HIGH | `handle_activity_completed()` calls `service.pause_run()` for gate-blocked | Include in scoping decision with `_run_loop()` calls |
| 10 | HIGH | `_create_worktree_manager` helper not specified for consumer | Specify helper location and signature; confirm global_config flows to consumer |
| 18 | HIGH | Consumer startup placement in `app.py` may conflict with existing ACTIVE-run spawning | Specify exact insertion point; address/remove lines 76-100 direct-spawn path |
| 21 | HIGH | `drain()` routes through `RunWorkflow.on_signal()`, not consumer handlers | Update drain to call consumer dispatch for lifecycle signals |
| 22 | HIGH | `_start_run()` helper asserts 200 and returns body | Update helper to assert 202 and GET for status |
| 9 | MEDIUM | Revert strategy runs in service then signal enqueued; partial-state risk if enqueue fails | Acceptable but document |
| 11 | MEDIUM | `cancel_run()` idempotency guard misses STOPPING status | Add STOPPING to early-return guard |
| 16 | MEDIUM | 202 empty body breaks frontend — no tracking task | Add follow-up tracking or frontend task |
| 2 | LOW | `_build_engine` / `_persist` references may not exist in `start_run()` | Verify before removing |
| 15 | LOW | `Response` import may already exist in `runs.py` | Check before adding duplicate import |
| 19 | LOW | `global_config` availability at consumer startup time | Verify config is in `app.state` when lifespan runs |

---

## Recommended Step Structure Changes

1. **Add Task 2b: Rewrite `handle_pause()` and `handle_cancel()` in `runtime.py`**
   - `handle_pause()` → remove `service.pause_run()` call, just `return True`
   - `handle_cancel()` → remove `service.cancel_run()` call, just `return True`
   - These are the consumer's responsibility now

2. **Expand Task 3/5: Explicitly scope `_run_loop()` internal pause calls**
   - Either keep them as-is (accept registry violation until Phase 4, document it)
   - OR add a helper like `_pause_run_direct(run_id, reason)` that calls engine directly

3. **Add Task 7a: Fix test infrastructure transport mismatch**
   - Before updating individual test assertions, address the drain/transport gap
   - Recommended: make `WorkflowService` accept injectable `signal_transport`
   - Update `deps.py` to pass `app.state.signal_transport` if set
   - This fixes tests without rewriting the drain infrastructure

4. **Refine Task 7: Replace `wait_for_status()` with updated `drain()`**
   - After transport is injectable, tests inject InMemorySignalTransport as today
   - `drain()` is updated to also handle lifecycle signals via consumer handlers
   - Tests call `drain(run_id)` after start/pause/resume/cancel (not poll)
