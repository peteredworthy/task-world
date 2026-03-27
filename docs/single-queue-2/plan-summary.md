# Single-Queue Signal Model — Plan Summary

**Source documents:** `intent.md`, `plan.md`, `clarifications.md`, step files 01–06
**Verification status:** All critical gaps applied; step files validated
**Last updated:** 2026-03-27

---

## Executive Summary

This document describes the implementation plan for migrating the signal routing architecture
from dual-path (sender-side routing via `has_active_workflow` branch) to single-queue
(unconditional enqueue + consumer dispatch). The work is organized into **6 phases**,
**39 total tasks**, executed serially to maintain test safety.

**Key outcome:** All lifecycle signals (start, pause, resume, cancel) flow through the
`pending_signals` queue with no direct DB branching in `WorkflowService`. The consumer
is the sole entity managing `RunWorkflow` lifecycle and active-run registry.

---

## Intent Satisfaction

The plan satisfies all 36 intent items [I-01 through I-36]:

### Goals (6 items)
- **[I-01]** Eliminate sender-side routing via `has_active_workflow` branch → **S-03**: sender rewiring phase
- **[I-02]** Introduce single consumer managing `RunWorkflow` lifecycle → **S-02**: consumer phase
- **[I-03]** Add `STOPPING` run state → **S-01**: schema phase
- **[I-04]** Move registry functions to consumer only → **S-04**: registry isolation phase
- **[I-05]** Add delivery tracking (`delivered_at`, `handled_at`) → **S-01**, **S-02**: schema + consumer phases
- **[I-06]** Lay groundwork for future multi-worker separation → **S-02**, **S-03**: consumer concurrency model

### Scope — In Scope (13 items)
- **[I-07]** Restructure `pending_signals` table (int PK, delivered_at, handled_at) → **S-01**
- **[I-08]** Add `STOPPING` to `RunStatus` with state machine guards → **S-01**
- **[I-09]** Add `RUN_START` signal type; make `RESUME` functional → **S-01**, **S-02**
- **[I-10]** Rewrite `start_run()`, `pause_run()`, `resume_run()`, `cancel_run()` to enqueue; return 202 → **S-03**
- **[I-11]** Remove `has_active_workflow` from `WorkflowService`, routers → **S-03**
- **[I-12]** Build consumer: per-run FIFO, concurrent runs, 100ms polling, redelivery → **S-02**
- **[I-13]** Remove `unregister_active_run()` from `RunWorkflow.handle_pause` → **S-03**
- **[I-14]** Add `scripts/check_signal_routing.py` pre-commit guard → **S-05**
- **[I-15]** Add AGENTS.md rules for signal queue and runner isolation → **S-05**
- **[I-16]** Alembic migration for schema + `STOPPING` status → **S-01**
- **[I-17]** Update `retry_fan_out_child()` to enqueue instead of branching → **S-03**
- **[I-32]** Verify pre-commit guard catches violations → **S-05**
- **[I-35]** Alembic migration exists → **S-01**

### Scope — Out of Scope (3 items)
- **[I-18]** Separate runner processes → deferred (future work)
- **[I-19]** Event broadcast decoupling → deferred (future work)
- **[I-20]** Performance optimization of queue → deferred (future work)

### Constraints (6 items)
- **[I-21]** All existing tests pass after each phase → **S-06**: validation phase
- **[I-22]** `STOPPING` state machine rules enforced in API/engine → **S-01**, **S-03**
- **[I-23]** No `app.state` access from `RunWorkflow`/executor → existing constraint, verified **S-06**
- **[I-24]** No process-local state crossing API/executor boundary → **S-03**, **S-04**
- **[I-25]** Consumer crash recovery via `delivered_at/handled_at` → **S-02**
- **[I-26]** `created_at` retained for audit, not used in ordering → **S-01**

### Definition of Complete (8 items)
- **[I-27]** All signals via `pending_signals`, no direct-DB branching → **S-03**
- **[I-28]** `has_active_workflow()` not called from service/routers → **S-03**
- **[I-29]** Registry functions only in consumer module → **S-04**
- **[I-30]** `STOPPING` state exists with enforced transitions → **S-01**
- **[I-31]** Consumer FIFO ordering, delivery tracking, redelivery → **S-02**
- **[I-33]** AGENTS.md has four signal-queue rules → **S-05**
- **[I-34]** Tests pass after each phase → **S-06**
- **[I-36]** `RUN_START` and `RESUME` signals functional → **S-02**

**Coverage:** 100% of 36 intent items mapped to phases.

---

## Implementation Plan: 6 Phases, 39 Tasks

| Phase | Goal | Tasks | Est. Impact | Go/No-Go |
|-------|------|-------|-------------|----------|
| **S-01** | Schema and state machine | 6 | Low (no behavior change) | ✓ Safe |
| **S-02** | Consumer (new code, no callers) | 8 | Medium (new paths exist in parallel) | ✓ Safe |
| **S-03** | Sender rewiring (behavior swap) | 9 | **High** (routes all signals) | ⚠ Incremental |
| **S-04** | Registry isolation (enforcement) | 5 | Low (gating existing behavior) | ✓ Safe |
| **S-05** | Guards and documentation | 5 | Low (guards only, no behavior) | ✓ Safe |
| **S-06** | Validation and cleanup | 6 | Low (cleanup only) | ✓ Safe |
| **Total** | — | **39 tasks** | — | **Executable** |

### Phase 1: Schema and State Machine (6 tasks)
**Duration:** ~4-6 hours (migration + testing)

1. **Task 1:** Alembic migration — restructure `pending_signals` table (int PK, delivered_at, handled_at)
2. **Task 2:** Update `PendingSignalModel` ORM and `PendingSignal` dataclass; fix drain queries (ORDER BY id)
3. **Task 3:** Add `RunStatus.STOPPING` to enum; update state machine (ACTIVE → STOPPING → PAUSED/FAILED)
4. **Task 4:** Engine guards — reject start_task/submit_for_verification on STOPPING runs
5. **Task 5:** API guards — return 409 for resume/cancel/pause/start on STOPPING runs
6. **Task 6:** Unit tests for all valid/invalid STOPPING transitions

**Go-No-Go:** Migration applies cleanly; all tests pass. Existing tests pass (no behavioral change yet).

---

### Phase 2: Consumer (8 tasks)
**Duration:** ~6-8 hours (new code + comprehensive tests)

1. **Task 1:** Consumer skeleton — async polling loop, per-run task concurrency, delivery tracking
2. **Task 2:** Handler wiring — `RUN_START`, `RESUME`, `PAUSE` (active/inactive), `CANCEL` (active/inactive), `ACTIVITY_*` signals
3. **Task 3:** Hooks integration — call `env_lifecycle.on_run_start()` and `on_run_end()` from consumer handlers
4. **Task 4:** Registry calls — `register_active_run()` / `unregister_active_run()` from consumer handlers
5. **Task 5:** Startup redelivery — on startup, re-dispatch signals with `delivered_at NOT NULL AND handled_at IS NULL`
6. **Task 6:** Unit tests — FIFO ordering, delivery tracking, handler errors, error-leaves-unhandled behavior
7. **Task 7:** Redelivery tests — 7 test cases covering signal state permutations and redelivery logic
8. **Task 8:** Wire consumer into executor startup (before any service methods are called)

**Go-No-Go:** All consumer tests pass; no changes to sender yet (parallel paths). Existing tests pass.

---

### Phase 3: Sender Rewiring (9 tasks)
**Duration:** ~6-8 hours (high-impact behavior changes, incremental)

1. **Task 1:** Rewire `start_run()` — enqueue `RUN_START` signal; return 202 Accepted
2. **Task 2:** Rewire `pause_run()` — enqueue `PAUSE` signal unconditionally; return 202 Accepted
3. **Task 3:** Rewire `resume_run()` — enqueue `RESUME` signal unconditionally; return 202 Accepted
4. **Task 4:** Rewire `cancel_run()` — enqueue `CANCEL` signal unconditionally; return 202 Accepted
5. **Task 5:** Rewire `retry_fan_out_child()` — enqueue `PAUSE` instead of branching
6. **Task 2b:** Fix circular loops — rewrite `RunWorkflow.handle_pause()` and `handle_cancel()` to NOT call service (return True instead)
7. **Task 7:** Test infrastructure — injectable transport for service tests (handle DB vs InMemory mismatch)
8. **Task 7a:** Integration test updates — assert 202 instead of 200; add polling helper for async verification
9. **Task 9:** Verify no `has_active_workflow()` calls remain in service, routers, or API code

**Go-No-Go:** All tests pass; `has_active_workflow` removed from sender paths; signals flow via queue only.

---

### Phase 4: Registry Isolation (5 tasks)
**Duration:** ~2-3 hours (straightforward mechanical changes)

1. **Task 1:** Audit — grep all files for `register_active_run`, `unregister_active_run`, `has_active_workflow` calls
2. **Task 2:** Move/restrict registry functions to consumer; remove from signals.py public surface
3. **Task 3:** Update `__init__.py` exports — remove these functions from `workflow/signals/__init__.py` and `workflow/__init__.py`
4. **Task 4:** Verify imports fail — confirm no imports from outside consumer module
5. **Task 5:** Update consumer-focused tests — ensure test imports still work

**Go-No-Go:** Grep confirms no registry imports outside consumer; import errors caught at module load time.

---

### Phase 5: Guards and Documentation (5 tasks)
**Duration:** ~2-3 hours (tooling + docs)

1. **Task 1:** Create `scripts/check_signal_routing.py` — AST-based guard that fails if registry functions imported/called outside consumer.py
2. **Task 2:** Add pre-commit hook — integrate guard into `.pre-commit-config.yaml` or equivalent
3. **Task 3:** Test guard — verify it passes on clean codebase; fails on artificial violation; supports `# noqa: signal-routing`
4. **Task 4:** Add AGENTS.md section — "Signal Queue and Runner Isolation" with four rules
5. **Task 5:** Verify documentation — section exists and matches specification

**Go-No-Go:** Guard passes on clean code; catches violations on intentional bad imports.

---

### Phase 6: Validation and Cleanup (6 tasks)
**Duration:** ~3-4 hours (final verification + cleanup)

1. **Task 1:** Full test suite — `uv run pytest tests/ -q --tb=short` (backend) + frontend tests
2. **Task 2:** Type check and linting — `uv run mypy src/` and ESLint/ruff clean
2. **Task 3:** Dead code removal — remove unused branching logic from old dual-path routing
4. **Task 4:** Traceability check — verify every [I-XX] item in intent.md is covered by at least one phase
5. **Task 5:** Commit and documentation — ensure all changes are committed
6. **Task 6:** Final verification — confirm intent is satisfied, all requirements addressed

**Go-No-Go:** All tests pass; no dead code; traceability complete.

---

## Key Decisions (from Clarifications)

All design decisions were made during the clarification phase and are documented in
`docs/single-queue-2/clarifications.md`. Here are the critical ones:

| # | Decision | Rationale | Impact |
|---|----------|-----------|--------|
| 1 | **API response: 202 Accepted** instead of 200 | Cleaner async semantics; signals are fire-and-forget | Breaking change for clients |
| 2 | **Consumer polling: 100ms baseline** | 10 queries/second when idle is acceptable; balances latency vs load | May add up to 100ms latency to run start |
| 3 | **Delivery tracking: delivered_at + handled_at** (repurpose processed_at) | Two-phase tracking enables crash recovery without state inspection | Requires migration to rename column |
| 4 | **STOPPING state: expose in API/frontend** | Full transparency; frontend shows "Stopping..." even though transient | Client-visible transient state |
| 5 | **Migration assumes clean stop** (no in-flight signals) | Simplifies migration logic; drop-and-recreate is safe | Requires operator discipline |
| 6 | **Env lifecycle hooks: inline in consumer** per-run | Simple, deterministic ordering; blocks that run's signals but not others | May briefly block signal processing for one run |
| 7 | **Pre-commit guard: AST-based enforcement** | Catches violations at commit time; prevents future regressions | Tight coupling to Python AST; requires maintenance |
| 8 | **Test isolation: factory interface for RunWorkflow** | Decouples consumer tests from real RunWorkflow construction | Requires abstract factory pattern in tests |

---

## Risk Register and Mitigations

| Risk | Likelihood | Impact | Severity | Mitigation |
|------|-----------|--------|----------|-----------|
| **Existing tests break during S-03 sender rewiring** | Medium | High | **Critical** | Phase 3 is incremental (one method at a time). Run tests after each sub-step. Task 7a introduces test transport injection to isolate service from DB. |
| **Consumer polling adds latency to run start** | Low | Medium | Medium | 100ms poll interval is baseline; tunable if latency becomes issue. Note: current system has ~0ms latency; any polling adds some. This is accepted tradeoff. |
| **Alembic migration fails on existing DBs with pending signals** | Low | Medium | Medium | Migration assumes clean server stop with no pending signals. If signals exist, table can be recreated (signals are ephemeral). Requires operator communication. |
| **Registry isolation breaks executor tests** | Medium | Medium | Medium | Phase 4 updates tests to use consumer-aware test helpers. Registry functions are moved to consumer, but tests can import from consumer module. |
| **env_lifecycle hooks not called after moving to consumer** | Medium | Medium | Medium | Explicitly preserve hook calls in consumer handlers (S-02 Task 3). Add integration test (S-06) confirming hooks fire. |
| **Circular signal loops after S-03 rewiring** | **High** | **High** | **Critical** | S-03 Task 2b adds new subtask: rewrite `RunWorkflow.handle_pause()` and `handle_cancel()` to return True WITHOUT calling service. Without this, PAUSE/CANCEL signals re-enqueue infinitely. |
| **Test transport mismatch: service uses DB, tests use InMemory** | Medium | Medium | Medium | S-03 Task 7a introduces injectable transport solution to allow tests to control which transport the service uses. |
| **Consumer factory for RunWorkflow provides wrong dependencies** | Medium | Medium | Medium | S-02 Task 8 defines factory function (not lambda) with closure over session/app_state. Factory signature must match RunWorkflow's __init__. |

**Critical blockers:** Task 2b (circular loop fix) and Task 7a (transport injection) must be completed before S-03 tests will pass.

---

## Caveats and Known Constraints for Execution

### Schema Caveats

1. **Migration directory structure** (S-01 Task 1)
   The project uses a custom migration directory: `src/orchestrator/db/migrations/versions/`.
   Do NOT place the migration in `alembic/versions/`. The Alembic config is configured to use
   the custom path.

2. **Constraint handling in SQLite** (S-01 Task 1)
   Use Alembic's `batch_alter_table()` for restructuring. Do NOT hard-code SQLite auto-generated
   constraint names (e.g., `sqlite_autoindex_*`) as these vary by SQLite version.

3. **Backfill is not needed** (S-01 Task 1)
   The migration assumes a clean server stop with no pending signals. Drop-and-recreate is safe
   and simpler than backfill logic. If the migration runs with pending signals in the table,
   they will be lost — but this is acceptable because signals are ephemeral state (replayable
   via startup redelivery for handled signals, disposable for unhandled).

### Consumer Caveats

4. **on_run_start() signature** (S-02 Task 2)
   `env_lifecycle.on_run_start()` requires 4+ parameters: `run_id`, `agent_id`, `env_path`,
   and optional context. The consumer must load the run from the DB and pass the required args.
   Do NOT call with just `run_id`.

5. **on_cancel() does not exist** (S-02 Task 3)
   The `EnvFileLifecycle` class does NOT have `on_cancel()`. Use `on_run_end()` instead to
   clean up resources (works for both pause and cancel).

6. **Consumer needs service_factory** (S-02 Task 8)
   The consumer's signal handlers often need to call service methods (e.g., to update run state).
   The consumer must accept a `service_factory` in its constructor to create service instances
   with the right dependencies. Do NOT try to import service as a module-level singleton.

7. **RunWorkflow factory complexity** (S-02 Task 2b)
   The consumer creates `RunWorkflow` instances for active runs. The factory cannot be a simple
   lambda because it needs access to the session (for signal transport) and app state (for executors).
   Use a factory function with closure over these dependencies, not a lambda.

8. **Signal ordering: ORDER BY id** (S-01 Task 2, S-02 Task 1)
   All queries must use `ORDER BY id` (the integer PK), NOT `ORDER BY created_at`. The integer
   PK ensures FIFO ordering and is required for crash recovery (unhandled signals are replayed
   in order).

### Sender Rewiring Caveats

9. **Circular loops: handle_pause and handle_cancel** (S-03 Task 2b) **[CRITICAL]**
   When the consumer sends a PAUSE or CANCEL signal to a RunWorkflow via its `on_signal()` method,
   the `handle_pause()` and `handle_cancel()` methods MUST NOT call back to `service.pause_run()`
   or `service.cancel_run()` — that would enqueue another signal and loop infinitely.
   Instead, these methods should return `True` (ack to consumer) without calling service.
   The consumer itself handles the DB state transition after the ack.

10. **Test transport injection** (S-03 Task 7a) **[CRITICAL]**
    Service tests use an in-memory transport to verify signal enqueueing, but the running service
    uses a DB transport. This mismatch causes tests to enqueue signals that don't persist.
    S-03 Task 7a introduces injectable transport: tests pass a custom transport to the service,
    capturing enqueued signals in memory for assertion.

11. **API response code: 202 Accepted** (S-03 Tasks 1–5)
    All four lifecycle endpoints (`start_run`, `pause_run`, `resume_run`, `cancel_run`) return
    202 Accepted instead of 200. This is a breaking change. The response body should be minimal
    (or empty) because the signal has been queued, not yet processed. The run state will not
    reflect the signal yet when the response is sent.

12. **start_run() no longer calls engine.start_run()** (S-03 Task 1)
    The service currently calls `engine.start_run(run_id)` to transition DRAFT → ACTIVE.
    After rewiring, the service enqueues a `RUN_START` signal only. The consumer's handler
    performs the transition.

### Registry Isolation Caveats

13. **Registry functions are private to consumer** (S-04)
    After Phase 4, `register_active_run()` and `unregister_active_run()` are no longer exported
    from `workflow/signals/signals.py`. They become internal functions within `consumer.py`.
    `has_active_workflow()` is also private to the consumer (used only by consumer handlers).
    Any code needing to check if a run is active must query the consumer's state via a public
    API (not yet defined; for now, internal only).

14. **Consumer tests can import from consumer module** (S-04)
    Test files for the consumer CAN import registry functions from `consumer.py` (e.g., for mocking
    or verification). The guard in Phase 5 allows imports from `consumer.py` and tests
    matching `*consumer*.py` or `*redelivery*.py`.

### Guards and Documentation Caveats

15. **Pre-commit guard: AST parsing** (S-05 Task 1)
    The guard script uses Python's `ast` module to parse all `.py` files and check for disallowed
    imports. It's similar to existing `scripts/check_module_imports.py`. The guard must handle:
    - `from X import func` statements
    - `import X; X.func()` attribute access
    - `# noqa: signal-routing` suppression comments
    Failures cause the commit to be rejected.

16. **Exemptions in the guard** (S-05 Task 1)
    The guard allows imports in:
    - `src/orchestrator/workflow/signals/consumer.py` (implementation)
    - Test files matching `*consumer*.py` or `*redelivery*.py` (testing)
    - Files with `# noqa: signal-routing` comment (explicit override)

### Validation and Cleanup Caveats

17. **Traceability check** (S-06 Task 4)
    Verify every intent item [I-01] through [I-36] is addressed by at least one task in the plan.
    Out-of-scope items [I-18], [I-19], [I-20] should be marked as `NO-REQ: deferred`.

18. **Dead code removal** (S-06 Task 3)
    Remove any unused branching logic from the old dual-path routing (e.g., dead code paths in
    `service.py` that are no longer reachable after Phase 3 rewiring).

---

## Execution Checklist

Before starting implementation:

- [ ] Read intent.md, plan.md, all step files (01–06)
- [ ] Review clarifications.md and understand all 8 design decisions
- [ ] Review this plan-summary.md and all caveats
- [ ] Ensure database is in clean state (no pending signals)
- [ ] Confirm pre-commit hooks are configured (will add one in Phase 5)
- [ ] Verify no other work is in progress (worktrees are clean)
- [ ] Plan for 22–30 hours of focused implementation time across 1–2 days

### Phase-by-Phase Go/No-Go Gates

- **S-01 complete:** Migration applies cleanly; all tests pass; `ORDER BY id` used everywhere
- **S-02 complete:** Consumer tests pass; no sender changes yet; existing tests still pass
- **S-03 complete:** All service methods enqueue signals; `has_active_workflow` gone from sender; circular loops fixed
- **S-04 complete:** Registry functions not importable from outside consumer; grep confirms isolation
- **S-05 complete:** Guard script written and passes on clean code; fails on intentional violation
- **S-06 complete:** All tests pass; type check and linting clean; dead code removed; intent fully satisfied

---

## Summary: What Will Be True When Complete

1. **All signals go through the queue.** No direct DB mutations in `WorkflowService` for lifecycle state changes.
2. **Consumer is the sole manager of RunWorkflow lifecycle.** Only the consumer creates/destroys RunWorkflow instances.
3. **STOPPING state is observable.** Pause/cancel transitions are visible as ACTIVE → STOPPING → PAUSED/FAILED.
4. **Registry is private to consumer.** `register_active_run()` / `unregister_active_run()` are consumer-internal.
5. **Signals are redeliverable.** `delivered_at` and `handled_at` columns enable crash recovery.
6. **API is async.** Lifecycle endpoints return 202 Accepted (signal queued, not yet processed).
7. **Invariants are enforced.** Pre-commit guard prevents future regressions in registry isolation.
8. **Work is documented.** AGENTS.md has the four signal-queue and runner-isolation rules.
9. **All tests pass.** Unit, integration, and frontend tests confirm the new model works.
10. **Intent is satisfied.** Every [I-XX] goal, scope item, constraint, and completion criterion is met.
