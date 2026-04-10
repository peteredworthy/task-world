# Single-Queue Signal Model — Implementation Plan

**Source:** `docs/single-queue-2/intent.md`
**Last updated:** 2026-03-27

---

## Build Philosophy

Each phase is independently shippable and testable. Tests must pass after every phase.
Order is chosen to minimize risk: schema changes first (lowest behavioral impact),
then the consumer (new code, no callers yet), then sender rewiring (swap behavior),
then registry isolation (lock in invariants), then guards and documentation.

Lessons from prior dry-run analysis are incorporated inline as caveats. Critical
execution notes are called out explicitly to prevent known failure modes.

---

## Phase 1: Schema and State Machine

**Goal:** Lay the data foundation without changing any runtime behavior.

**Traces to:** [I-07], [I-08], [I-09], [I-16], [I-22], [I-26], [I-35]

### 1.1 Alembic migration for `pending_signals`

- Replace UUID string PK with `INTEGER PRIMARY KEY AUTOINCREMENT`.
- Rename existing `processed_at` column to `handled_at`.
- Add `delivered_at TIMESTAMP NULL` column (new).
- Retain `created_at` as audit-only (no ordering use).
- Update all drain/query code to ORDER BY integer PK.

**Caveat — Migration path:** The migration file MUST be placed in
`src/orchestrator/db/migrations/versions/`, NOT `alembic/versions/`. The project uses
a custom migration directory structure.

**Decision — Migration assumes no in-progress runs:** The migration can assume the server
is stopped cleanly and there are no pending signals at migration time. No backfill of
in-flight rows is needed — the table can be recreated with the new schema.

**Caveat — Constraint handling:** Use Alembic's `batch_alter_table()` for table restructuring.
Do NOT hard-code SQLite auto-generated constraint names (e.g., `sqlite_autoindex_...`) as
these vary by SQLite version.

**Files:**
- New: `src/orchestrator/db/migrations/versions/xxxx_single_queue_signals.py`
- Modify: `src/orchestrator/db/models.py` (PendingSignal model)
- Modify: `src/orchestrator/workflow/signals/signals.py` (drain queries)

**Verification:** Migration applies cleanly. Existing signal tests pass. `created_at` is not used in ORDER BY anywhere.

### 1.2 Add `STOPPING` to `RunStatus`

- Add `STOPPING = "stopping"` to the `RunStatus` enum.
- Add state machine validation: STOPPING can only transition to PAUSED or FAILED.
- `start_task()` and `submit_for_verification()` reject STOPPING runs.
- API returns 409 for resume/restart/duplicate pause/cancel on STOPPING runs.

**Files:**
- Modify: `src/orchestrator/db/models.py` (RunStatus enum)
- Modify: `src/orchestrator/workflow/engine.py` (transition guards)
- Modify: `src/orchestrator/api/routers/runs.py` (API guards)
- New: `tests/unit/test_stopping_state.py`

**Verification:** Unit tests confirm all valid/invalid STOPPING transitions. API returns 409 for disallowed transitions on STOPPING runs.

### 1.3 Add `RUN_START` signal type

- Add `RUN_START` to `WorkflowSignal` enum.
- No handler wiring yet — just the type definition and serialization.

**Files:**
- Modify: `src/orchestrator/workflow/signals/signals.py`

**Verification:** Signal can be created and serialized. Existing tests pass.

---

## Phase 2: Consumer

**Goal:** Build the consumer loop as new code. It reads from the queue but nothing writes to it yet via the new paths.

**Traces to:** [I-02], [I-05], [I-12], [I-25], [I-31], [I-36]

### 2.1 Consumer module skeleton

- Create `src/orchestrator/workflow/signals/consumer.py`.
- Implement the core loop: poll `pending_signals` ordered by integer PK every 100ms, dispatch per signal type.
- Concurrency model: one `asyncio.Task` per `run_id`. Signals for the same run are processed serially (inline), so a slow operation (e.g., env_lifecycle hook creating a worktree) blocks subsequent signals for that run but not for other runs.
- Set `delivered_at` before handler invocation, `handled_at` (renamed from `processed_at`) after success.
- On handler error: leave `handled_at` null (eligible for redelivery).

**Files:**
- New: `src/orchestrator/workflow/signals/consumer.py`
- New: `tests/unit/test_signal_consumer.py`

**Verification:** Unit tests with mock signals confirm FIFO ordering, delivery tracking, and error-leaves-unhandled behavior.

### 2.2 Signal handlers in consumer

- `RUN_START`: Apply DRAFT -> ACTIVE transition, create `RunWorkflow`, call `register_active_run()`.
- `RESUME`: Apply PAUSED -> ACTIVE transition, create `RunWorkflow`, call `register_active_run()`.
- `PAUSE` (with active RunWorkflow): Set run to STOPPING, deliver to RunWorkflow. On ack: transition to PAUSED, call `unregister_active_run()`.
- `PAUSE` (no active RunWorkflow): Apply PAUSED directly.
- `CANCEL` (with active RunWorkflow): Set run to STOPPING, deliver to RunWorkflow. On ack: transition to FAILED, call `unregister_active_run()`.
- `CANCEL` (no active RunWorkflow): Apply FAILED directly.
- `ACTIVITY_COMPLETED` / `ACTIVITY_VERIFIED`: Deliver to RunWorkflow (as today).

**Files:**
- Modify: `src/orchestrator/workflow/signals/consumer.py`
- Modify: `tests/unit/test_signal_consumer.py`

**Verification:** Each handler tested with unit tests covering both "active RunWorkflow" and "no active RunWorkflow" paths.

### 2.3 Startup redelivery

- On consumer startup, query signals where `delivered_at IS NOT NULL AND handled_at IS NULL` for runs not currently active.
- Re-dispatch these signals through the normal handler path.

**Files:**
- Modify: `src/orchestrator/workflow/signals/consumer.py`
- New: `tests/unit/test_signal_redelivery.py`

**Verification:** Test simulates crash (signal delivered but not handled), restarts consumer, confirms redelivery.

---

## Phase 3: Sender Rewiring

**Goal:** Switch all `WorkflowService` methods to enqueue signals unconditionally. Remove the `has_active_workflow` branching.

**Traces to:** [I-01], [I-09], [I-10], [I-11], [I-13], [I-17], [I-27], [I-28]

### 3.1 Rewire `start_run()`

- `WorkflowService.start_run()` enqueues a `RUN_START` signal instead of calling `engine.start_run()` directly.
- Remove the direct DRAFT -> ACTIVE DB transition from the service method.
- Preserve `self._env_lifecycle.on_run_start()` hook — move it to the consumer's `_handle_run_start()` handler (runs inline, blocking that run's signal processing but not other runs).
- API endpoint changes from 200 to **202 Accepted** (breaking change — decided in clarifications).

**Caveat — Signal enqueueing API:** Use the `SignalQueue` pattern, NOT a standalone `enqueue_signal()` function:
```python
queue = SignalQueue(DbSignalTransport(session))
queue.enqueue(run_id, WorkflowSignal.RUN_START, payload=None)
session.commit()
```
Use existing `pause_run()` at line ~327 of `service.py` as reference for the pattern.

**Caveat — start_run() internals:** The method currently calls `engine.start_run(run_id)`, NOT `executor.spawn_run()`. Remove the `engine.start_run()` call.

**Files:**
- Modify: `src/orchestrator/workflow/service.py`
- Modify: `tests/integration/test_api_full_lifecycle.py` (update expectations)

**Verification:** Integration test confirms run starts via signal queue. No direct engine.start_run call in service method.

### 3.2 Rewire `pause_run()`, `resume_run()`, `cancel_run()`

- Each method enqueues its respective signal unconditionally.
- Remove `has_active_workflow` check and direct-DB branch from each.
- Remove `unregister_active_run()` call from `RunWorkflow.handle_pause`.
- For `cancel_run()`: env_lifecycle hooks and worktree cleanup must be moved to consumer's `_handle_cancel()` (runs inline per-run), not removed entirely.
- All three API endpoints change from 200 to **202 Accepted**.

**Files:**
- Modify: `src/orchestrator/workflow/service.py`
- Modify: `src/orchestrator/workflow/run_workflow.py` (remove registry call from handle_pause)
- Modify: integration tests

**Verification:** Tests confirm signals are always enqueued. No `has_active_workflow` calls in service layer.

### 3.3 Rewire `retry_fan_out_child()`

- Remove `has_active_workflow` check.
- If run is ACTIVE, enqueue PAUSE signal; consumer handles the transition.

**Files:**
- Modify: `src/orchestrator/workflow/service.py`

**Verification:** Unit test confirms fan-out enqueues PAUSE signal for active runs.

### 3.4 Wire consumer into executor startup

- Start the consumer loop as part of `AgentRunnerExecutor` initialization or `app.py` startup.
- Consumer replaces the current direct-spawn paths.
- Consumer must start BEFORE any service methods are called to avoid dead-lettered signals.

**Files:**
- Modify: `src/orchestrator/executor.py` or `src/orchestrator/app.py`

**Verification:** End-to-end integration test: create run, start via API, confirm consumer picks up signal and creates RunWorkflow within 1-2 seconds.

---

## Phase 4: Registry Isolation

**Goal:** Restrict `register_active_run` / `unregister_active_run` / `has_active_workflow` to the consumer module only.

**Traces to:** [I-04], [I-29], [I-30]

### 4.1 Audit and move registry functions

- Grep all Python files for calls to registry functions.
- Move or restrict `register_active_run()` and `unregister_active_run()` to the consumer module.
- Remove exports from `workflow/signals/signals.py` public surface.
- Update `src/orchestrator/workflow/signals/__init__.py` and `src/orchestrator/workflow/__init__.py` `__all__` lists to remove these functions.
- `has_active_workflow()` remains available only to consumer and consumer-focused tests.
- Verify import fails from outside consumer module after removal.

**Files:**
- Modify: `src/orchestrator/workflow/signals/signals.py`
- Modify: `src/orchestrator/workflow/signals/__init__.py`
- Modify: `src/orchestrator/workflow/__init__.py`
- Modify: `src/orchestrator/workflow/signals/consumer.py`
- Modify: any files that currently import these functions (update to remove)

**Verification:** Grep confirms no imports of these functions outside consumer module and its tests. Both `__init__.py` files updated.

---

## Phase 5: Guards and Documentation

**Goal:** Lock in the new invariants with automated checks and documentation.

**Traces to:** [I-14], [I-15], [I-32], [I-33]

### 5.1 Pre-commit guard script

- Create `scripts/check_signal_routing.py`.
- Uses `ast` module to parse all Python files.
- Fails if `has_active_workflow`, `register_active_run`, or `unregister_active_run` are imported or called outside `consumer.py` (and its test file).
- Same structure as existing `scripts/check_module_imports.py`.
- Add to pre-commit hook list.
- Support `# noqa: signal-routing` suppression for edge cases.

**Files:**
- New: `scripts/check_signal_routing.py`
- Modify: `.pre-commit-config.yaml` or equivalent hook config

**Verification:** Script passes on clean codebase. Fails when a test violation is introduced.

### 5.2 AGENTS.md rules

- Add section "Signal Queue and Runner Isolation" with four rules:
  1. No registry function calls outside consumer.
  2. No process-local state crossing API/executor boundary.
  3. No `app.state` access from RunWorkflow/executor.
  4. All lifecycle transitions via signal queue.

**Files:**
- Modify: `AGENTS.md`

**Verification:** Section exists and matches specification.

---

## Phase 6: Validation and Cleanup

**Goal:** Final verification that all intent items are satisfied.

**Traces to:** [I-21], [I-34], [I-36]

### 6.1 Full test suite pass

- Run all backend tests (unit + integration).
- Run all frontend tests.
- Run type checker and linter.

### 6.2 Remove dead code

- Remove any now-unused branching logic, helper functions, or imports that were part of the old dual-path routing.
- Remove the no-op `handle_resume` log message from `RunWorkflow`.

### 6.3 Traceability check

- Verify every [I-XX] item from intent.md is addressed by at least one phase.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Existing tests break during Phase 3 sender rewiring | Medium | High | Phase 3 is incremental (one method at a time). Run tests after each sub-step. |
| Consumer polling adds latency to run start | Low | Medium | 100ms poll interval baseline; tunable. Not a performance goal. |
| Alembic migration fails on existing DBs with signals | Low | Medium | Migration assumes clean server stop with no pending signals. Table can be recreated with new schema. |
| Registry isolation breaks executor tests | Medium | Medium | Update tests in Phase 4 to use consumer-aware test helpers. |
| env_lifecycle hooks not called after moving to consumer | Medium | Medium | Explicitly preserve hooks in consumer handlers. Add integration test confirming hooks fire. |
| Backfill assigns duplicate PKs if ROWID assumptions fail | N/A | N/A | Resolved: migration assumes no pending signals, no backfill needed. |

---

## Resolved Design Decisions

*(From clarifications with human — see `docs/single-queue-2/clarifications.md`)*

1. **API response codes**: start/pause/resume/cancel endpoints change from 200 to **202 Accepted** (breaking change, cleaner async semantics).
2. **Consumer polling interval**: **100ms** baseline. 10 queries/second when idle is acceptable.
3. **Delivery tracking**: Repurpose existing `processed_at` column as `handled_at`, add only `delivered_at` as new column. Two-phase tracking enables crash recovery.
4. **STOPPING state visibility**: Exposed in REST API and frontend (full transparency). Frontend shows "Stopping..." indicator even though the state is transient.
5. **Migration strategy**: Alembic migration assumes clean server stop with no in-progress runs. No backfill of in-flight signals needed.
6. **Consumer concurrency model**: One `asyncio.Task` per `run_id`. Env_lifecycle hooks run inline within the per-run task, so a slow hook blocks that run's signals but not other runs.
7. **Pre-commit guard**: Proceed as planned — AST-based `scripts/check_signal_routing.py` with `# noqa: signal-routing` suppression.
8. **Test isolation**: Consumer tests need a way to inject mock RunWorkflow creation. Define a factory interface the consumer uses.
