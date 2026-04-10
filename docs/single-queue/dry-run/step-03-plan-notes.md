# Step 03: Sender Rewiring — Dry-Run Analysis

**Date:** 2026-03-26
**Status:** Simulation of Phase 3 (Sender Rewiring) — Implementation planning before execution

---

## Executive Summary

Step 03 depends on **completed S-01 and S-02**, but S-01 prerequisites are NOT yet in the codebase:
- `RUN_START` signal type missing from `WorkflowSignal` enum
- `STOPPING` run state missing from `RunStatus` enum
- Consumer module (`consumer.py`) does not exist
- Consumer NOT wired into app startup

**Key Finding:** Tasks 1 and 4 will FAIL without S-01/S-02 completion first. Tasks 2–3 are partially
blocked but the underlying mechanisms (`pause_run`, `resume_run`, `cancel_run` already use signals)
are in place. Task 5 requires Task 4 to complete.

**Recommendation:** Do NOT proceed with Task 1 until `RUN_START` is added in S-01. Verify S-02
consumer module is fully implemented before Task 4.

---

## Task 1: Rewire `start_run()` to Enqueue RUN_START Signal

### Assumptions

1. **`RUN_START` signal exists** — Step file assumes `WorkflowSignal.RUN_START` can be used. **ACTUAL:** Does not exist.
   - `WorkflowSignal` enum at `src/orchestrator/workflow/signals/signals.py:24-31` has only: `PAUSE`, `RESUME`, `CANCEL`, `ACTIVITY_COMPLETED`, `ACTIVITY_VERIFIED`.

2. **`enqueue_signal()` function exists** — Step file mentions `enqueue_signal(run_id, signal_type, context)`. **ACTUAL:** Not found.
   - Current code uses `SignalQueue(transport).enqueue(run_id, signal_type, payload)` (see `service.py:327, 444, 487`).
   - The pattern differs slightly: `SignalQueue` is instantiated first, then enqueue is called on the instance.

3. **`start_run()` currently calls `executor.spawn_run()`** — Step assumption. **ACTUAL:** False.
   - `start_run()` at `service.py:366-415` calls `engine.start_run(run_id)` (line 384), NOT `executor.spawn_run()`.
   - It then persists state with `self._persist(state, run_id, buffer)` (line 388).
   - There is NO direct executor spawning in the current `start_run()` implementation.

4. **Consumer will handle DRAFT→ACTIVE transition** — Step assumes consumer creates workflow. **ACTUAL:** Consumer does not exist yet.
   - S-02 must be complete and `consumer.py` must have a `RUN_START` handler that calls `engine.start_run()` or equivalent.

5. **Return value contract unchanged** — Step says run object is still returned. **ACTUAL:** Current code returns `result` from `self._persist()` (line 388, 415).
   - If transition to signal-based, must ensure DB reflects new run state before returning (or caller must poll for changes).

### Expected Outputs

- `start_run()` enqueues `RUN_START` signal instead of (or in addition to) `engine.start_run()` call.
- No DRAFT→ACTIVE DB transition in `start_run()`.
- Run object returned (current state from DB, not yet transitioned).

### Critical Blockers

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| `RUN_START` signal type missing | **CRITICAL** | Add `RUN_START = "run_start"` to `WorkflowSignal` enum in S-01. |
| `enqueue_signal()` vs `SignalQueue` API mismatch | High | Clarify: does `enqueue_signal()` exist as a module-level function, or must callers use `SignalQueue(transport).enqueue()`? Current code uses the latter. |
| Consumer module missing | **CRITICAL** | S-02 must be complete; `consumer.py` must exist and handle `RUN_START` signals. |
| Consumer NOT wired into startup | **CRITICAL** | Task 4 must be completed before consumer will process signals. Without it, `RUN_START` signals accumulate unprocessed. |
| Incorrect understanding of current code | High | `start_run()` does NOT call `executor.spawn_run()`. It calls `engine.start_run()`. The step file's assumption is wrong. |

### Failure Modes

1. **`WorkflowSignal.RUN_START` NameError** — If `RUN_START` is not added to the enum, the line will fail with `AttributeError: enum 'WorkflowSignal' has no member 'RUN_START'`.
   - **Hardening:** Add test `tests/unit/test_workflow_signal_enum.py` that verifies `RUN_START` exists and can be serialized.

2. **Signal not enqueued correctly** — Step says `enqueue_signal(run_id=run_id, signal_type=WorkflowSignal.RUN_START, context={...})` but the actual API might be different.
   - **Hardening:** Check current `pause_run()` implementation (which works) and replicate its `SignalQueue` pattern exactly in `start_run()`.

3. **Transition happens in wrong place** — If the service layer no longer calls `engine.start_run()`, WHO transitions DRAFT→ACTIVE?
   - **Current:** `engine.start_run()` in service layer (line 384).
   - **Future:** Consumer must call equivalent in its `handle_run_start()` handler (part of S-02).
   - **Risk:** If consumer is not running or crashes, signal sits in queue unprocessed, run stays DRAFT.
   - **Hardening:** Integration test must verify: API call → signal enqueued → consumer picks up → run transitions to ACTIVE within timeout.

4. **Return value stale** — `start_run()` returns the run object from DB immediately after enqueueing signal. But the consumer hasn't processed it yet, so the returned run is still DRAFT.
   - **Hardening:** API documentation must clarify that `POST /api/runs/{id}/start` returns 202 Accepted with the run in DRAFT state; client must poll for ACTIVE transition.

5. **No executor spawning for managed agents** — The current `start_run()` logs a warning if the agent is `CLI_SUBPROCESS`, `OPENHANDS_LOCAL`, or `OPENHANDS_DOCKER` (lines 403–413), noting that the agent "must be spawned separately". If we switch to signal-based, the consumer must ensure this warning and any spawning logic is preserved.
   - **Hardening:** Consumer's `handle_run_start()` handler must replicate the agent warning and any spawning setup from current `start_run()`.

6. **Env lifecycle hook not called** — Current `start_run()` calls `self._env_lifecycle.on_run_start()` at lines 391–400. If we remove the direct `engine.start_run()` call, this hook might not be called, or it might be called at the wrong time.
   - **Hardening:** Consumer handler must also invoke `env_lifecycle.on_run_start()` after run transitions to ACTIVE, or the hook must be deferred to the consumer.

### Component Wiring: Is New Code Actually Used?

**Current path:** `POST /api/runs/{id}/start` → `router.start_run()` → `service.start_run()` → `engine.start_run()` → run DRAFT→ACTIVE.

**Proposed path:** `POST /api/runs/{id}/start` → `router.start_run()` → `service.start_run()` → `enqueue_signal(RUN_START)` → [consumer running in background] → consumer calls `handle_run_start()` → `engine.start_run()` → run DRAFT→ACTIVE.

**Wiring Risk:** The consumer is a NEW background task. If it is not started in Task 4 (app startup), or if it crashes, the path breaks and runs never transition.

**Verification Required:**
- [ ] Consumer is actually instantiated and started in `app.py` or `executor.py` (Task 4).
- [ ] Consumer loop is running and polling `pending_signals` table.
- [ ] Consumer's `handle_run_start()` handler exists and calls `engine.start_run()` or equivalent (S-02).
- [ ] Integration test: create run, call `POST /api/runs/{id}/start`, poll `GET /api/runs/{id}` until status is ACTIVE, verify within timeout.

---

## Task 2: Rewire `pause_run()`, `resume_run()`, `cancel_run()`

### Assumptions

1. **These methods branch on `has_active_workflow()`** — Step says they do. **ACTUAL:** Confirmed.
   - `pause_run()`: Lines 438–446 (if active) vs. 449–452 (direct DB).
   - `resume_run()`: Lines 484–488 (if active) vs. 490–510 (direct DB).
   - `cancel_run()`: Lines 321–328 (if active) vs. 330–364 (direct DB).

2. **Rewrite to ALWAYS enqueue signals** — Step says remove branching. **ACTUAL:** Currently they branch.
   - **Goal:** Eliminate `has_active_workflow()` check, always enqueue.

3. **No `has_active_workflow` call in service layer** — Step says remove it. **ACTUAL:** Current code uses it extensively.
   - Grep confirms: `has_active_workflow()` appears in `pause_run`, `resume_run`, `cancel_run`, and `retry_fan_out_child`.

### Expected Outputs

- `pause_run()` enqueues `PAUSE` signal, no direct DB transition in service.
- `resume_run()` enqueues `RESUME` signal, no direct DB transition in service.
- `cancel_run()` enqueues `CANCEL` signal, no direct DB transition in service.
- All three methods return run object immediately (signal is processed asynchronously).

### Critical Blockers

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Consumer NOT handling all signal types | High | S-02 must implement handlers for `PAUSE`, `RESUME`, `CANCEL`. Verify handlers exist. |
| Consumer NOT wired into startup | **CRITICAL** | Task 4 must complete. Without it, signals are enqueued but never processed. |
| Tests assume synchronous transitions | High | Task 5 must update integration tests to poll for state changes. |

### Failure Modes

1. **Direct DB branch left in place** — If the step only removes `if has_active_workflow:` block but leaves the `else:` block, the method still mutates the DB directly for PAUSED runs.
   - **Current behavior:** Pause PAUSED run → works via direct DB path.
   - **Proposed behavior:** Pause PAUSED run → enqueue signal → consumer processes → transition to PAUSED (idempotent).
   - **Risk:** If consumer is slow, or run is in a weird state, behavior might change.
   - **Hardening:** Explicitly remove the `else:` branch in `pause_run()` / `resume_run()` / `cancel_run()`. Enqueue unconditionally.

2. **`pause_run()` calls `service.pause_run()` from within RunWorkflow handler** — At `runtime.py:287`, `handle_pause()` calls `service.pause_run()`.
   - **Risk:** If `service.pause_run()` now always enqueues, we have an infinite recursion: signal → handler → `service.pause_run()` → enqueue signal → loop.
   - **Hardening:** Remove `service.pause_run()` call from `handle_pause()`. Instead, call the DB mutation directly (or split into two methods: `_pause_run_internal()` for DB, `pause_run()` for API).

3. **`cancel_run()` has side effects** — Lines 344–362 show env_lifecycle hooks and worktree cleanup on cancellation.
   - **Risk:** If these happen in service layer (not signal consumer), they might run twice or at the wrong time.
   - **Hardening:** Consumer handler must also invoke env_lifecycle and worktree cleanup, or these must be deferred to consumer.

4. **`resume_run()` with agent/config changes** — Lines 490–510 handle agent_type, agent_config, resume_strategy parameter changes.
   - **Risk:** These are service-layer logic. If we enqueue signal, the consumer handler must accept and apply these parameters.
   - **Hardening:** Verify consumer's `handle_resume()` accepts and applies agent config updates from signal payload.

5. **Tests fail because run doesn't transition immediately** — Existing tests might assert `pause_run()` returns PAUSED run, but with signals it returns ACTIVE (still waiting for consumer).
   - **Hardening:** Task 5 updates tests to poll until desired state.

### Component Wiring: Signal Feedback Loop Risk

**Current:**
```
service.pause_run()
  ├─ if has_active_workflow:
  │   └─ enqueue signal → PAUSE handled by RunWorkflow.handle_pause()
  │     └─ calls unregister_active_run()
  │     └─ calls service.pause_run() again [RECURSION RISK]
  └─ else:
    └─ direct DB mutation
```

**After Task 2:**
```
service.pause_run()
  └─ always enqueue signal → PAUSE handled by consumer
    └─ consumer must apply transition without calling service.pause_run() again
```

**Wiring Verification Required:**
- [ ] `RunWorkflow.handle_pause()` does NOT call `service.pause_run()` (or it calls a separate internal method).
- [ ] Consumer's `handle_pause()` applies the DB transition directly (via engine or repository).
- [ ] Integration test: `pause_run()` on ACTIVE run → signal enqueued → consumer processes → run transitioned to PAUSED.

---

## Task 3: Rewire `retry_fan_out_child()` and Remove Registry Call from `RunWorkflow.handle_pause()`

### Assumptions

1. **`retry_fan_out_child()` checks `has_active_workflow()`** — Lines 1112–1129 confirm this.

2. **`RunWorkflow.handle_pause()` calls `unregister_active_run()`** — Line 286 confirms this.

3. **After rewiring, registry calls are only in consumer** — Step says remove from workflow, move to consumer. **ACTUAL:** Consumer does not exist yet.

### Expected Outputs

- `retry_fan_out_child()` no longer checks `has_active_workflow()`.
- Enqueues `PAUSE` signal for all active runs.
- `RunWorkflow.handle_pause()` and `handle_cancel()` no longer call `unregister_active_run()`.
- Consumer's handlers call `unregister_active_run()` after ack.

### Critical Blockers

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| `unregister_active_run()` only in consumer | **CRITICAL** | Phase 4 (Registry Isolation) must happen after Phase 3. For now, can remain in both places (workflow + consumer). |
| Consumer must call `unregister_active_run()` | High | S-02 must implement this in consumer handlers for PAUSE/CANCEL. |

### Failure Modes

1. **Registry leak if workflow removes but consumer doesn't** — If `RunWorkflow.handle_pause()` removes the unregister call but the consumer doesn't add it, the registry leaks and the run can be paused but won't unregister.
   - **Hardening:** Ensure consumer's `handle_pause()` handler calls `unregister_active_run()` BEFORE modifying the service method.

2. **Race condition: workflow unregisters, then consumer tries to unregister again** — If both workflow and consumer call `unregister_active_run()`, the second call might fail (depends on implementation of `unregister_active_run()`).
   - **Hardening:** Check `unregister_active_run()` implementation — is it idempotent? Can it be called multiple times safely?

3. **`retry_fan_out_child()` unconditionally enqueues PAUSE** — After removing the `has_active_workflow()` check, the method enqueues a PAUSE signal even if the run is not active. If the run is already PAUSED, this might cause an error or be a no-op.
   - **Hardening:** Ensure consumer handles PAUSE signals for non-active runs gracefully (idempotent transition).

4. **Signal payload might be lost** — `retry_fan_out_child()` currently passes `{"reason": "fan_out_child_retry"}` to the queue. The consumer must preserve this reason through to the final DB state.
   - **Hardening:** Verify consumer's `handle_pause()` accepts and uses the reason from signal payload.

### Component Wiring: Registry Owner Transition

**Before:** Registry called from:
- `service.pause_run()` (via signal handler in RunWorkflow)
- `RunWorkflow.handle_pause()`
- `RunWorkflow.handle_cancel()`
- (other internal places in `runtime.py`)

**After:** Registry called from:
- Consumer's `handle_pause()` handler
- Consumer's `handle_cancel()` handler
- (nowhere else)

**Risk:** If consumer is not running, registry is never cleaned up. Signals accumulate, workflows are never unregistered.

**Verification Required:**
- [ ] `unregister_active_run()` implementation is idempotent (can be called multiple times safely).
- [ ] Consumer's `handle_pause()` and `handle_cancel()` call `unregister_active_run()`.
- [ ] Test: pause active run → PAUSE signal enqueued → consumer processes → run PAUSED and unregistered.

---

## Task 4: Wire Consumer into Executor/App Startup

### Assumptions

1. **Consumer loop is async and can be started with `asyncio.create_task()`** — Step assumes this. **ACTUAL:** Consumer does not exist yet; assume S-02 provides an async `run()` method.

2. **Executor or app.py has startup hooks** — Step says add to either. **ACTUAL:**
   - `app.py` exists (checked with grep).
   - Need to verify if it has lifespan context or `@app.on_event("startup")`.

3. **DB session factory is available** — Consumer needs to poll `pending_signals`. **ACTUAL:** Unknown if available in startup context.

### Expected Outputs

- Consumer loop starts on app startup.
- Consumer has DB session factory and can poll signals.
- Consumer stops gracefully on shutdown.
- Signals enqueued during startup are processed within polling interval.

### Critical Blockers

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Consumer module does not exist | **CRITICAL** | S-02 must be complete first. |
| Consumer.run() signature/requirements unknown | High | S-02 must specify constructor parameters and run() method signature. |
| DB session factory availability unknown | High | Check `app.py` startup context — can we access a session factory there? |
| Async context at startup time | Medium | Verify startup hook is async-compatible. |

### Failure Modes

1. **Consumer started before DB migrations** — If the consumer starts before Alembic migrations run, it might fail to read `pending_signals` table.
   - **Hardening:** Ensure app startup order: migrations → DB init → consumer start.

2. **Consumer task not awaited, script exits immediately** — If the consumer task is created but not properly awaited or managed, the script might exit before consumer runs.
   - **Hardening:** Use proper async task management: create task in startup hook, store reference in app.state, clean up in shutdown hook.

3. **Session factory not available at startup** — Consumer needs to poll DB. If session factory is not available in startup context, the consumer will fail.
   - **Hardening:** Verify session factory is available in `app.state` or via dependency injection. If not, create one in startup hook.

4. **Graceful shutdown not implemented** — If app shuts down without stopping the consumer task, the task might orphan or crash.
   - **Hardening:** Add shutdown hook that cancels the consumer task and awaits it for clean termination.

5. **Polling interval too aggressive or too slow** — The step doesn't specify polling interval. Too fast = wasted DB queries. Too slow = delayed signal processing.
   - **Hardening:** Start with 100ms polling interval (as suggested in plan.md), make configurable via env var or config.

6. **Consumer crashes and is not restarted** — If the consumer task crashes, signals accumulate forever.
   - **Hardening:** Wrap consumer loop in try/except with logging. Optionally implement restart logic (out of scope for Phase 3, but worth noting).

### Component Wiring: Startup Order

**Required startup order:**
1. FastAPI app created.
2. DB engine initialized.
3. Alembic migrations run.
4. App state initialized (session factory, lock manager, etc.).
5. Consumer started as background task.

**Risk:** If this order is wrong, the consumer fails at startup and the app crashes or starts without it.

**Verification Required:**
- [ ] Startup hook is async and runs after migrations.
- [ ] Consumer is created with required dependencies (session factory, etc.).
- [ ] Consumer task is stored in app.state (for access in shutdown hook).
- [ ] Shutdown hook cancels and awaits the consumer task.
- [ ] Integration test: start app, verify consumer is running, enqueue signal, verify it's processed.

---

## Task 5: Update Integration Tests for Async Signal-Based Lifecycle

### Assumptions

1. **Existing tests assume synchronous start/pause/resume** — Step says update to poll. **ACTUAL:** Need to verify existing test structure.

2. **Polling helper can be reused** — Step provides template for `poll_until_status()`. **ACTUAL:** Helper must be idempotent and timeout-safe.

3. **Consumer processes signals within 2–5 seconds** — Step suggests this timeout. **ACTUAL:** Depends on polling interval (Task 4) and consumer speed.

### Expected Outputs

- Integration tests poll run status until desired state (not assert immediately).
- Tests account for STOPPING intermediate state.
- No regression in existing test assertions.
- Full test suite passes after update.

### Critical Blockers

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Consumer not running (Task 4 incomplete) | **CRITICAL** | Tests will hang waiting for state transitions that never happen. |
| STOPPING state not added to API schema | High | Frontend type must include STOPPING; tests might fail on type checks. |
| Existing test framework incompatible with polling | Medium | Verify test framework supports async polling (pytest-asyncio, etc.). |

### Failure Modes

1. **Tests timeout waiting for state transition** — If the consumer is not running, or is very slow, tests hit the 2–5 second timeout and fail.
   - **Hardening:** Ensure consumer is running before tests start. Verify signal is enqueued and consumer picks it up (via log or DB query).

2. **Polling helper is not idempotent** — If the helper makes side effects (e.g., API call increments a counter), repeated polling might fail.
   - **Hardening:** Implement helper to use GET only (no mutations). Verify GET is idempotent.

3. **Race condition: assertion reads old state** — If the assertion reads the database before the consumer has committed the transaction, the state is stale.
   - **Hardening:** Use `await asyncio.sleep(0.1)` between polls to avoid tight loop. Use DB read consistency guarantees (likely eventual consistency with in-memory DB).

4. **STOPPING state breaks existing assertions** — Tests might assert run is PAUSED immediately after pause, but now it might be STOPPING first.
   - **Hardening:** Update tests to expect PAUSED (final state), not STOPPING (intermediate). Or update to accept either.

5. **Timeout value too tight for CI environment** — Local tests run fast, but CI might have higher latency.
   - **Hardening:** Use longer timeout on CI (e.g., 10 seconds) via environment variable. Log polling attempts for debugging.

6. **Tests don't verify consumer is actually running** — The test might poll indefinitely if consumer crashed at startup.
   - **Hardening:** Add a pre-test check: verify consumer is running (e.g., health check endpoint, or check task is in app.state).

### Component Wiring: Test → Consumer Dependency

**Current:** Tests call API → service updates DB synchronously → tests assert new state.

**After:** Tests call API → service enqueues signal → consumer processes asynchronously → tests poll for new state.

**Risk:** If consumer is not running, tests break in non-obvious ways (hang rather than fail fast).

**Verification Required:**
- [ ] Test setup includes a fixture that starts the app with a running consumer.
- [ ] Fixture optionally injects a mock/in-memory consumer for unit tests (optional).
- [ ] Integration tests verify consumer is running before polling (optional but recommended).
- [ ] Test timeout values are reasonable for the target environment.
- [ ] Tests pass with current (slow) polling interval; can be tuned later.

---

## Cross-Cutting Concerns

### 1. Recursion Risk: Service Methods Calling Each Other

**Current code:**
- `service.pause_run()` enqueues signal → `RunWorkflow.handle_pause()` → calls `service.pause_run()` again.

**Risk:** Infinite recursion if the signal path is not carefully separated from the direct-call path.

**Mitigation:**
- Split `pause_run()` into two: `pause_run_api()` (enqueues) and `pause_run_internal()` (DB mutation).
- Or: Ensure `RunWorkflow.handle_pause()` calls the internal DB method, not the API method.

### 2. Async Context Propagation

**Current:** Some methods are async, some are sync. Adding consumer (async) might require changes.

**Risk:** If consumer runs in a different async context, database session handling might be fragile.

**Mitigation:**
- Verify all service methods use the same session management (likely dependency-injected).
- Ensure consumer uses compatible session factory.

### 3. Integration Test Flakiness

**Risk:** Polling-based tests are inherently flaky if timeouts are not generous or if environment is slow.

**Mitigation:**
- Use generous timeouts (5–10 seconds).
- Log polling attempts and consumer state for debugging.
- Optionally add metrics to consumer to measure signal processing latency.

### 4. Missing STOPPING State Guards

**Currently:** RunWorkflow handlers assume run is ACTIVE. After adding STOPPING, handlers must be updated to handle it.

**Risk:** Handlers might be called on STOPPING runs and cause unexpected behavior.

**Mitigation:**
- Verify engine guards (lines 66–73 in service.py) reject mutations on STOPPING runs.
- Test: try to start_task on STOPPING run → should reject with same error as PAUSED.

---

## Unresolved Dependencies (Must Be Done Before Phase 3)

### From S-01: Schema and State Machine
- [ ] Add `RUN_START = "run_start"` to `WorkflowSignal` enum.
- [ ] Add `STOPPING = "stopping"` to `RunStatus` enum.
- [ ] Add Alembic migration for `STOPPING` state (if stored as string column).
- [ ] State machine guards: STOPPING can only transition to PAUSED/FAILED, not to ACTIVE.

### From S-02: Consumer
- [ ] Implement `SignalConsumer` class at `src/orchestrator/workflow/signals/consumer.py`.
- [ ] Implement async `run()` method for polling loop.
- [ ] Implement handlers: `handle_run_start()`, `handle_pause()`, `handle_resume()`, `handle_cancel()`.
- [ ] Handlers must call `register_active_run()` / `unregister_active_run()` appropriately.
- [ ] Startup redelivery of unhandled signals.

---

## Phase 3 Execution Checklist

### Pre-Flight Checks (Must Pass Before Starting)
- [ ] S-01 complete: `RUN_START` signal and `STOPPING` state exist.
- [ ] S-02 complete: Consumer module exists and handlers implemented.
- [ ] Consumer can be imported without errors: `from orchestrator.workflow.signals.consumer import SignalConsumer`.
- [ ] No existing tests are failing (baseline).

### Per-Task Checks

#### Task 1: Rewire `start_run()`
- [ ] Determine current behavior: does `start_run()` call `engine.start_run()` or `executor.spawn_run()`? (Current answer: `engine.start_run()`).
- [ ] Modify to enqueue `RUN_START` signal instead.
- [ ] Verify `engine.start_run()` call is removed from service layer.
- [ ] Test: integration test `test_start_run_via_signal` passes.

#### Task 2: Rewire `pause_run()`, `resume_run()`, `cancel_run()`
- [ ] Remove `has_active_workflow()` check from each method.
- [ ] Remove direct DB mutation branches (else clause).
- [ ] Ensure all three unconditionally enqueue signals.
- [ ] Test: integration tests for pause, resume, cancel pass.

#### Task 3: Rewire `retry_fan_out_child()` and Registry Calls
- [ ] Remove `has_active_workflow()` check from `retry_fan_out_child()`.
- [ ] Always enqueue `PAUSE` signal.
- [ ] Remove `unregister_active_run()` calls from `RunWorkflow.handle_pause()` and `handle_cancel()`.
- [ ] Verify consumer handlers call `unregister_active_run()`.
- [ ] Test: integration test for fan-out retry passes.

#### Task 4: Wire Consumer into Startup
- [ ] Verify startup hook exists (or create one) in `app.py`.
- [ ] Instantiate consumer with required dependencies.
- [ ] Start consumer as async task.
- [ ] Add shutdown hook to stop consumer gracefully.
- [ ] Test: app starts without errors; consumer is running.

#### Task 5: Update Integration Tests
- [ ] Implement polling helper `poll_until_status()`.
- [ ] Update existing tests to use polling helper.
- [ ] Account for STOPPING intermediate state.
- [ ] Verify no regressions in other tests.
- [ ] Test: full integration test suite passes.

### Post-Completion Verification
- [ ] Grep confirms no `has_active_workflow()` calls in service, routers, or API-initiated paths.
- [ ] Grep confirms no `executor.spawn_run()` calls in service layer.
- [ ] Full test suite passes (unit + integration + type check + lint).
- [ ] STOPPING state is used and transitions correctly in tests.
- [ ] Consumer is running and processing signals within acceptable latency.

---

## Recommended Execution Order

1. **Verify S-01 and S-02 are complete.** (Pre-requisite)
2. **Task 4: Wire Consumer into Startup.** (Must be done first; other tasks depend on it.)
3. **Task 1: Rewire `start_run()`.** (Simplest; no branching logic to remove.)
4. **Task 2: Rewire `pause_run()`, `resume_run()`, `cancel_run()`.** (Similar pattern; reuse Task 1 approach.)
5. **Task 3: Rewire `retry_fan_out_child()` and Registry Calls.** (Depends on Tasks 1–2 patterns; must remove registry calls from workflow.)
6. **Task 5: Update Integration Tests.** (Last; depends on all other tasks completing.)

---

## Summary of Key Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| S-01/S-02 incomplete | Medium | Critical | Verify dependencies before starting. |
| Recursion: service calls itself via signal | Medium | High | Split into internal/API methods; document call chain. |
| Consumer not running at startup | Medium | High | Add startup checks; verify in test fixtures. |
| Tests timeout waiting for state | Low | Medium | Generous timeouts; log consumer state for debugging. |
| STOPPING state breaks existing code | Low | Medium | Add guards in handlers; update tests. |
| Registry not cleaned up properly | Low | Medium | Ensure consumer calls `unregister_active_run()`; make idempotent. |
| Session factory not available at startup | Low | High | Verify in `app.py`; create if needed in startup hook. |

---

## Lessons Learned (For Future Phases)

1. **Component interdependencies are tight.** — Phase 3 depends on Phase 1 (signal types) and Phase 2 (consumer). Ensure upstream phases are truly complete before starting downstream.

2. **Async/background tasks add operational complexity.** — Once the consumer is a background task, startup/shutdown order, error handling, and crash recovery become critical. Plan these carefully.

3. **Recursion risks in refactoring.** — When splitting code paths (direct DB vs. signal queue), watch for cycles. Document call chains explicitly.

4. **Testing async behavior requires discipline.** — Polling-based tests are inherently flaky. Use generous timeouts, log intermediate states, and verify pre-conditions (e.g., consumer running).

5. **Backward compatibility is fragile with state machine changes.** — Adding `STOPPING` state requires careful guard logic. Test extensively on existing runs in all states.

