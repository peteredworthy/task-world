# Single-Queue Signal Model — Execution Summary

**Date:** 2026-03-26
**Status:** Ready for implementation (post-verification remediation)
**Source:** `docs/single-queue/intent.md`, `docs/single-queue/plan.md`

---

## Intent Satisfaction Summary

The implementation eliminates the dual-path signal routing in `WorkflowService` and replaces it with a single, uniform queue (`pending_signals` table) through which all lifecycle signals pass unconditionally. This removes sender-side branching logic (`has_active_workflow` checks), centralizes consumer responsibility (a new signal consumer loop), and adds observable state management via a `STOPPING` run state and delivery tracking (`delivered_at`, `handled_at`).

### Coverage
All 36 intent items [I-01] through [I-36] are addressed by the implementation plan:
- **Routing elimination:** [I-01], [I-10], [I-11], [I-27], [I-28] — all service methods enqueue unconditionally
- **Consumer introduction:** [I-02], [I-12], [I-25], [I-31] — consumer loop with FIFO, delivery tracking, redelivery
- **State machine:** [I-03], [I-08], [I-22], [I-30] — STOPPING state with enforced transitions
- **Registry isolation:** [I-04], [I-13], [I-29] — registry functions moved to consumer only
- **Signal delivery:** [I-05], [I-26] — delivered_at, handled_at columns; ordering by PK not created_at
- **New signals:** [I-09], [I-36] — RUN_START and RESUME signals defined and functional
- **Guards and documentation:** [I-14], [I-15], [I-32], [I-33] — pre-commit script and AGENTS.md rules
- **Testing and validation:** [I-21], [I-34] — all tests pass after each phase
- **Out-of-scope items:** [I-06], [I-18], [I-19], [I-20] — explicitly deferred or emergent properties

---

## Implementation Phases (6 steps, 26 tasks total)

Phases are ordered to minimize behavioral risk: schema changes first (low impact), consumer
next (new code, no callers), then sender rewiring (swap behavior), then isolation (lock in
invariants), then guards and documentation, finally validation.

### Phase 1: Schema and State Machine (4 tasks in step-01-plan.md)
**Goal:** Lay the data and enum foundation without changing runtime behavior.

- **Task 1.1:** Alembic migration for `pending_signals` table restructuring
  - Migrate UUID PK to `INTEGER PRIMARY KEY AUTOINCREMENT`
  - Add `delivered_at` and `handled_at` TIMESTAMP columns (nullable)
  - Preserve `created_at` for audit only (not used for ordering)
  - Backfill existing rows: assign sequential integer PKs based on `created_at` order (with ROWID tie-breaker)

- **Task 1.2:** Update `PendingSignal` ORM model
  - New integer `id` as PK
  - New `delivered_at` and `handled_at` timestamp fields
  - Drain queries order by integer PK, not `created_at`

- **Task 1.3:** Add `STOPPING` to `RunStatus` enum and state machine
  - Enum value `STOPPING = "stopping"`
  - State transitions: ACTIVE → STOPPING → {PAUSED, FAILED}
  - Guards in `engine.start_task()` and `submit_for_verification()` reject STOPPING
  - API returns 409 for resume/restart/duplicate pause/cancel on STOPPING runs

- **Task 1.4:** Add `RUN_START` signal type
  - New enum value in `WorkflowSignal`
  - No handler wiring yet; serialization only

### Phase 2: Consumer (8 tasks in step-02-consumer.md)
**Goal:** Build the consumer loop as new code. Queue remains read-only by consumers; senders don't use it yet.

- **Task 2.1:** Create consumer module skeleton (`src/orchestrator/workflow/signals/consumer.py`)
  - Poll `pending_signals` ordered by integer PK
  - Serial FIFO processing per `run_id`, concurrent across different `run_id`s
  - Set `delivered_at` before handler invocation, `handled_at` after success
  - Leave `handled_at` null on error (eligible for redelivery)

- **Task 2.2–2.7:** Implement signal handlers
  - `RUN_START`: DRAFT → ACTIVE, create RunWorkflow, register active run
  - `RESUME`: PAUSED → ACTIVE, create RunWorkflow, register active run
  - `PAUSE` (active or inactive): transition to STOPPING (if active) or PAUSED (if inactive), unregister on completion
  - `CANCEL` (active or inactive): transition to STOPPING (if active) or FAILED (if inactive), unregister on completion
  - `ACTIVITY_COMPLETED` / `ACTIVITY_VERIFIED`: pass through to RunWorkflow

- **Task 2.8:** Startup redelivery
  - Query signals: `delivered_at IS NOT NULL AND handled_at IS NULL` for inactive runs
  - Re-dispatch through normal handlers on consumer startup

### Phase 3: Sender Rewiring (5 tasks in step-03-sender-rewiring.md)
**Goal:** Switch all `WorkflowService` methods to unconditional signal enqueueing. Swap from direct-spawn/DB-mutation to queue-based approach.

- **Task 3.1:** Rewire `start_run()`
  - Remove `engine.start_run(run_id)` call
  - Enqueue `RUN_START` signal unconditionally
  - Preserve `self._env_lifecycle.on_run_start()` hook; move to consumer's `_handle_run_start()`

- **Task 3.2:** Rewire `pause_run()`, `resume_run()`, `cancel_run()`
  - Remove `has_active_workflow()` check and direct-DB branching
  - Enqueue respective signals unconditionally
  - Remove `unregister_active_run()` from `RunWorkflow.handle_pause()` (now consumer's responsibility)
  - Preserve env_lifecycle hooks in cancel_run; move to consumer's `_handle_cancel()`

- **Task 3.3:** Rewire `retry_fan_out_child()`
  - Remove `has_active_workflow()` check
  - Enqueue PAUSE signal for active runs; consumer handles transition

- **Task 3.4:** Wire consumer into startup
  - Consumer loop starts as part of `AgentRunnerExecutor` initialization or `app.py` startup
  - Consumer replaces current direct-spawn paths

- **Task 3.5:** Final verification
  - `PendingSignal` rows created for all lifecycle operations
  - `has_active_workflow()` not called from `WorkflowService`
  - Consumer processes signals and transitions runs

### Phase 4: Registry Isolation (4 tasks in step-04-plan.md)
**Goal:** Restrict `register_active_run()` / `unregister_active_run()` / `has_active_workflow()` to consumer module only.

- **Task 4.1:** Audit current usage
  - Grep all Python files for calls to registry functions
  - Document all current import paths

- **Task 4.2:** Move or restrict functions
  - Remove exports from `signals.py` public API
  - Update `src/orchestrator/workflow/signals/__init__.py` and `src/orchestrator/workflow/__init__.py` `__all__` lists
  - Verify import fails outside consumer module

- **Task 4.3:** Update all non-consumer imports
  - Remove imports from any files outside `consumer.py` and its test file

- **Task 4.4:** Final verification
  - Grep confirms no usage outside consumer module
  - Both `__init__.py` files updated

### Phase 5: Guards and Documentation (4 tasks in step-05-plan.md)
**Goal:** Lock in new invariants with automated checks and documentation.

- **Task 5.1:** Create `scripts/check_signal_routing.py`
  - Pre-commit guard using Python AST
  - Flags if `has_active_workflow`, `register_active_run`, or `unregister_active_run` are imported or called outside `consumer.py`
  - Matches pattern in existing `scripts/check_module_imports.py`

- **Task 5.2:** Integrate into pre-commit hooks
  - Add script to `.pre-commit-config.yaml` or equivalent hook config

- **Task 5.3:** Add signal-queue rules to AGENTS.md
  - Section: "Signal Queue and Runner Isolation"
  - Rule 1: No registry function calls outside consumer
  - Rule 2: No process-local state crossing API/executor boundary
  - Rule 3: No `app.state` access from RunWorkflow/executor
  - Rule 4: All lifecycle transitions via signal queue

- **Task 5.4:** Validation
  - Script runs without error on clean codebase
  - Script fails when a test violation is introduced

### Phase 6: Validation and Cleanup (5 tasks in step-06-plan.md)
**Goal:** Final verification that all intent items are satisfied.

- **Task 6.1:** Full test suite pass
  - Run all backend unit tests (330+)
  - Run all integration tests (235+)
  - Run all frontend tests (221+)
  - No regressions

- **Task 6.2:** Type checking and linting
  - `mypy` clean
  - `eslint` clean
  - `ruff` format check clean

- **Task 6.3:** Remove dead code
  - No-op branching from old dual-path logic
  - Unused helper functions or imports

- **Task 6.4:** Traceability audit
  - Every [I-XX] item satisfied by at least one phase

- **Task 6.5:** Final integration test
  - Full lifecycle: create run → start via RUN_START → verify → complete
  - Pause/resume cycles
  - Cancellation with STOPPING state
  - Redelivery after consumer restart

---

## Key Architectural Decisions

1. **Single queue as source of truth:** All lifecycle state transitions are initiated by signals in `pending_signals`, not by direct DB mutations or `RunWorkflow` introspection. This removes the two-path routing problem entirely.

2. **Integer PK with delivery tracking:** Migration to integer PKs enables FIFO ordering independent of timestamp precision. `delivered_at` and `handled_at` enable crash recovery: if a signal is delivered but not handled, it's redelivered on restart.

3. **STOPPING state for safe pause/cancel:** Introducing STOPPING between ACTIVE and {PAUSED, FAILED} makes the pause/cancel operation observable and race-free. Active runs explicitly acknowledge the pause/cancel signal by transitioning through STOPPING.

4. **Consumer loop isolation:** The consumer is the *sole creator and destroyer* of `RunWorkflow` instances. This removes registry introspection from the sender side and centralizes lifecycle management in one place.

5. **Backfill strategy using ROWID:** For existing `pending_signals` rows, sequential integer PKs are assigned using SQLite's implicit ROWID as a tie-breaker (for signals with identical `created_at`). This preserves insertion order without relying on timestamp uniqueness.

6. **Per-run serial, cross-run concurrent:** The consumer processes signals for a given `run_id` serially (FIFO), but different runs are processed concurrently. This prevents signal reordering within a run while allowing parallel progress across multiple runs.

7. **Registry functions consumer-only:** `register_active_run()`, `unregister_active_run()`, and `has_active_workflow()` are no longer exported from `signals.py`. They are accessible only to the consumer module. A pre-commit guard enforces this restriction.

---

## Risk Register and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Existing tests break during Phase 3 (sender rewiring) | **Medium** | High | Phase 3 is incremental: rewire one method at a time. Run tests after each sub-step. Verify full suite passes after Phase 3 complete before moving to Phase 4. |
| Consumer polling latency affects run start responsiveness | **Low** | Medium | Consumer polls frequently (100ms baseline, tunable). Not a performance goal of this change. If latency becomes noticeable, interval can be tightened. |
| Alembic migration fails on existing DBs with pending signals | **Low** | High | Migration handles existing rows gracefully: backfill integer PK using ROWID as tie-breaker, set `delivered_at`/`handled_at` to NULL. Tested against schema with multiple rows. |
| Registry isolation breaks executor tests | **Medium** | Medium | Update tests in Phase 4 to use consumer-aware test helpers. Tests can still access registry functions via the consumer test file (sibling imports allowed). |
| env_lifecycle hooks not called after moving to consumer | **Medium** | Medium | Explicitly preserve hooks in consumer handlers. Add integration test confirming hooks fire on start/cancel/pause. |
| Backfill logic assigns duplicate PKs if ROWID assumptions fail | **Low** | High | Use SQLite's native `batch_alter_table()` for table reorganization. This removes manual PK assignment and delegates to Alembic. If row reordering still needed, backfill uses `ROW_NUMBER() OVER (ORDER BY created_at, ROWID)` which is deterministic. |

---

## Critical Execution Caveats

### 1. **Migration Path (Step 01)**
   - **Caveat:** The migration must be placed in `src/orchestrator/db/migrations/versions/`, NOT `alembic/versions/`.
   - **Why:** The project uses a custom migration directory structure; the standard Alembic path will not be discovered.
   - **Action:** Verify migration file exists in correct directory and is discoverable via `alembic upgrade head` before proceeding to Phase 2.

### 2. **Backfill SQL Tie-Breaker (Step 01)**
   - **Caveat:** Two or more signals may have identical `created_at` timestamps. Direct UUID comparison is not insertion-order-preserving.
   - **Why:** SQLite timestamps have millisecond precision; high-throughput runs can batch multiple signals with identical timestamps.
   - **Action:** Use SQLite's implicit `ROWID` as tie-breaker: `ORDER BY created_at, ROWID`. This ensures deterministic ordering.

### 3. **Signal Enqueueing API (Step 03)**
   - **Caveat:** The API is `SignalQueue(DbSignalTransport(session)).enqueue(run_id, signal_type, payload)`, NOT a standalone `enqueue_signal()` function.
   - **Why:** `SignalQueue` is an abstraction that decouples the API from the transport layer. It is instantiated per operation.
   - **Action:** Use the pattern from existing `pause_run()` method (line 327 of `service.py`) as a reference for all three enqueue calls in Phase 3.

### 4. **env_lifecycle Hook Preservation (Step 03)**
   - **Caveat:** `start_run()` currently calls `self._env_lifecycle.on_run_start()` (lines 391–400). Removing `engine.start_run()` does NOT remove this hook call.
   - **Why:** The hook has side effects (e.g., worktree setup). It must still be called after the signal is enqueued.
   - **Action:** Move the hook call to the consumer's `_handle_run_start()` handler. Preserve the call in the service method until the consumer is wired (Phase 3.4).

### 5. **__init__.py Re-exports (Step 04)**
   - **Caveat:** Removing registry functions from `signals.py` does NOT automatically remove them from `__all__` in `signals/__init__.py` or `workflow/__init__.py`.
   - **Why:** Re-exports are listed separately; removing a definition does not cascade to `__all__` lists.
   - **Action:** Explicitly remove from both `__init__.py` files using the provided grep commands. Verify import fails after removal.

### 6. **Consumer Startup Timing (Step 03–04)**
   - **Caveat:** The consumer loop must start before any signals are enqueued (Phase 3 onwards). If signals are enqueued before the consumer is ready, they will be left unhandled until redelivery.
   - **Why:** The system expects a consumer to be polling; without it, signals are dead-lettered.
   - **Action:** Ensure consumer loop is initialized in `app.py` startup or `AgentRunnerExecutor.__init__()` *before* any service methods are called. Verify via integration test that consumer picks up a signal within 1–2 seconds.

### 7. **Testing After Each Phase (All Phases)**
   - **Caveat:** Do NOT skip test runs after any phase. Regressions can accumulate silently.
   - **Why:** Each phase introduces new code paths. Broken tests must be fixed immediately to avoid cascading failures in later phases.
   - **Action:** Run the full test suite (backend + frontend + type check + lint) after each phase complete. Commit passing tests before moving to the next phase.

### 8. **Redelivery Logic (Step 02)**
   - **Caveat:** Signals with `delivered_at IS NOT NULL AND handled_at IS NULL` for runs that are not currently active are redelivered on startup.
   - **Why:** If a consumer crashes after setting `delivered_at` but before setting `handled_at`, the signal is orphaned. Redelivery on startup prevents signal loss.
   - **Action:** Verify redelivery by running integration test: enqueue signal, kill consumer mid-handling (before `handled_at` is set), restart consumer, confirm signal is redelivered and run completes normally.

### 9. **STOPPING State Validation (Step 01)**
   - **Caveat:** API must reject resume/restart/duplicate pause/cancel for runs in STOPPING state. STOPPING is a transient state; no user action should target it.
   - **Why:** STOPPING is internal to pause/cancel coordination. Exposing it to the API adds confusion and potential race conditions.
   - **Action:** Add guards in `routers/runs.py` for each operation. Add unit test confirming 409 response for each disallowed transition.

---

## Execution Checklist

- [ ] Phase 1 complete: Schema migration applied, STOPPING enum added, all Phase 1 tests pass
- [ ] Phase 2 complete: Consumer loop created, all handlers implemented, redelivery tested
- [ ] Phase 3 complete: All service methods rewired to unconditional enqueueing, `has_active_workflow()` removed
- [ ] Phase 4 complete: Registry functions isolated to consumer module only
- [ ] Phase 5 complete: Pre-commit guard and AGENTS.md rules in place
- [ ] Phase 6 complete: Full test suite passes, dead code removed, traceability verified

---

## Verification Criteria (Definition of Done)

The implementation is complete when:

1. **All 36 intent items [I-01] through [I-36] are satisfied** (verified by mapping each to a phase outcome).
2. **No `has_active_workflow()` calls exist outside comments or unit tests** (grep clean).
3. **Registry functions only exported from `consumer.py`** (import validation).
4. **All lifecycle signals (RUN_START, RESUME, PAUSE, CANCEL) enqueued unconditionally** (service method audit).
5. **Consumer processes signals with FIFO ordering, delivery tracking, and redelivery** (integration test).
6. **STOPPING state exists and enforces defined transitions** (state machine test).
7. **Pre-commit guard prevents registry function usage outside consumer** (hook test).
8. **AGENTS.md documents four signal-queue rules** (documentation audit).
9. **Full test suite passes: 330+ unit, 235+ integration, 221+ frontend, clean type check/lint** (CI pass).
10. **Alembic migration applies cleanly and backfills existing signals correctly** (migration test).

---

## Post-Implementation Roadmap (Not Included)

This implementation makes possible but does NOT include:

- **Multi-worker separation:** With signals in a persistent queue and consumer isolated, a second worker process can be added without modifying the core signal routing. The queue becomes the coordination point.
- **Async event delivery:** EventBroadcaster can be decoupled from the consumer loop, allowing WebSocket/SSE broadcast without blocking signal processing.
- **Queue performance optimization:** Indexing strategies, batching, and tuning can be applied to the consumer polling loop once throughput becomes a concern.

These are explicitly deferred to future work.
