# Slice 2.8 — Graph startup & crash recovery wiring

Size: M. Completes Phase 2 runtime durability. The recovery primitives already
exist and are integration-tested (`recover()`, `reconcile_runtime()`, the 2.1
outbox crash-point suite, the 2.5 snapshot_cleanup recovery tests). This slice
**wires them into the server lifespan** for graph-mode runs and re-arms the
`GraphRunDriver` (2.7) so a graph run survives a server restart / reload — the
graph analog of the legacy `_run_startup_recovery` in `api/app.py`.

The slice-2.5 crash-safety re-audit (docs/graph-approach/slice-audits/
reaudit-2.5-final.md) found NO gaps, so this slice is purely recovery wiring;
there is no 2.5 remediation folded in.

## Ground truth

- execution-graph-prd-plus.md §13 Runtime Recovery Policy — the rebuilt-state /
  runtime-check / recovery table this slice realises in the server:
  active lease + missing process → `agent_died` + reschedule; outbox dispatch
  pending → retry idempotently; callback received-but-not-accepted → re-validate.
- §12.3 (side effects start only after accepted intent), §14 (task projection).
- execution-graph-evaluation.md §6.1 (run-completion invariant; the re-armed
  driver must honour it on resume).
- Existing primitives (do NOT rebuild): `graph_runtime/recovery.py`
  `recover()` (returns `RecoveryReport` with `redispatched`, `pending_cleanups`,
  `awaiting_start_ack`, `awaiting_callback`); `graph_runtime/dispatch.py`
  `reconcile_runtime(controller, dispatcher, report)` (dead lease → `agent_died`);
  `OutboxDispatcher.dispatch_pending` / `pending_items`.
- 2.7 driver: `workflow/graph_driver.py` `GraphRunDriver.run()` is already
  re-enterable (seeds only when `current_position == 0`; dispatch idempotent
  via the outbox). `api/deps.py` `make_graph_runner(...)`; SignalConsumer
  `graph_runner` injection + `_safe_run_graph_driver`.
- Legacy pattern to mirror: `api/app.py` `_run_startup_recovery()` +
  `_is_startup_recoverable_pause_reason()`; lifespan wiring (~line 478).

## Scope — what to build

### 1. Graph startup-recovery routine

Add `_run_graph_startup_recovery(app)` (in `api/app.py`, sibling to
`_run_startup_recovery`, OR a small `workflow/graph_recovery.py` helper it
delegates to — keep the heavy logic out of `app.py`). On startup, after the
HTTP server is up:

1. **Select graph runs needing recovery** (`execution_mode == "graph"`):
   - `RunStatus.ACTIVE` graph runs — orphaned when reload cancelled the driver
     task even though the agent subprocess / outbox state survives.
   - `RunStatus.PAUSED` graph runs whose `pause_reason` is restart-recoverable
     (reuse `_is_startup_recoverable_pause_reason`).
2. **Per run**, build the graph runtime (`build_graph_runtime(...)` with the
   run's worktree/runner) and an `OutboxDispatcher`, then:
   - `report = await recover(session_factory, dispatcher, run_id=run_id)`
     — retries pending outbox rows idempotently (both `agent_dispatch` AND
     `snapshot_cleanup` kinds) and classifies in-flight leases.
   - `await reconcile_runtime(controller, executor, report)` — for leases
     whose execution is no longer running in-process, send `agent_died`
     through the controller so the kernel revokes the lease and reschedules
     (§13 "active lease with missing process").
3. **Re-arm the driver**: invoke the graph runner (the same
   `make_graph_runner` callable / `_safe_run_graph_driver` path used at
   RUN_START) so `GraphRunDriver.run()` resumes the run to quiescence. Because
   `run()` is re-enterable, it will NOT re-seed (position > 0), will rebuild
   the runtime, and will drive remaining ready nodes to completion, then bridge
   `run_state` → `Run.status`.
4. Stagger re-arms (reuse `_STARTUP_RECOVERY_RUN_STAGGER_SECONDS`) to avoid a
   thundering herd, matching the legacy path.

### 2. Lifespan wiring

In the lifespan/startup block of `api/app.py`, schedule
`_run_graph_startup_recovery(app)` alongside the existing
`_run_startup_recovery(app)` task. The two must be independent: a graph run is
never touched by the legacy recovery and vice versa (selection is gated on
`execution_mode`). Legacy-run recovery behaviour must be unchanged.

### 3. Idempotency / re-entry guards

- Recovery must be safe to run when there is nothing to recover (no graph runs,
  empty outbox) — no-op, no error.
- A run already being driven (driver task live) must not be double-armed; reuse
  the consumer's `_active_graph_runs` set or an equivalent in-process guard so
  startup recovery does not start a second driver for the same run.
- `recover()` + `reconcile_runtime()` are already idempotent; this slice must
  not add any non-idempotent step.

## Tests

### Integration — `tests/integration/test_graph_startup_recovery.py` (new)

Real tmp-file SQLite (a real DB path, NOT `:memory:`, so a "restart" can reopen
it), real tmp git worktree, hand-written `MockAgent` (no `unittest.mock`).
NO server process. "Restart" = discard the controller/dispatcher/executor/driver
objects and build fresh ones over the same DB file (the established pattern in
`test_graph_outbox_crash_points.py` / `test_graph_runner_e2e.py`).

- `test_restart_mid_dispatch_resumes_to_completed()` — seed+start a graph run,
  crash after the builder dispatch outbox row is committed but before the agent
  callback (discard objects); run `_run_graph_startup_recovery`-equivalent over
  the same DB; assert the dispatch is retried, the run advances
  builder→verifier→`accepted`, and the legacy `Run.status` reaches `COMPLETED`.
  **This is the named e2e acceptance drill.**
- `test_restart_with_dead_lease_reschedules()` — an active lease whose
  execution is not running after restart; recovery sends `agent_died`, the
  node is rescheduled, a fresh clean attempt is accepted.
- `test_restart_with_pending_snapshot_cleanup_completes_cleanup()` — a
  committed `cleanup_requested` with a pending `snapshot_cleanup` outbox row;
  startup recovery redispatches it; the compromised ref is gone and a clean
  superseding record exists (assert real git `show-ref`).
- `test_recovery_noop_when_no_graph_runs()` — no graph runs present → recovery
  is a clean no-op.
- `test_recovery_does_not_double_arm_running_driver()` — a run already being
  driven is not started a second time.

### Integration — `tests/integration/test_graph_startup_recovery_routing.py` (new)

- `test_legacy_runs_untouched_by_graph_recovery()` — an ACTIVE/PAUSED legacy
  run is not selected by graph recovery; a graph run is not selected by legacy
  recovery. (Use the existing app/service fixtures; inject recording
  driver/recovery seams as the routing tests in 2.7 do — no mocks.)

### Unit — `tests/unit/test_graph_recovery_selection.py` (new)

Pure selection logic with hand-built run records (no DB):

- `test_selects_active_and_recoverable_paused_graph_runs()` — given a mix of
  runs, the selector returns exactly the ACTIVE graph runs + recoverable-paused
  graph runs, excluding legacy runs and non-recoverable pause reasons.

## Done when

1. On server startup, graph-mode runs that are ACTIVE (orphaned) or paused with
   a restart-recoverable reason are enumerated and recovered; legacy runs are
   untouched and the legacy recovery path is unchanged.
2. `recover()` is invoked per graph run and retries pending outbox rows
   idempotently for BOTH `agent_dispatch` and `snapshot_cleanup` kinds.
3. `reconcile_runtime()` converts leases with missing executions to `agent_died`
   through the controller and the kernel reschedules them (§13).
4. The `GraphRunDriver` is re-armed and drives each recovered run to quiescence,
   bridging `run_state` → `Run.status` (COMPLETED / PAUSED) on finish; no
   re-seed occurs (position > 0).
5. Recovery is a clean no-op when there is nothing to recover, and never
   double-arms a run already being driven.
6. The named e2e drill `test_graph_startup_recovery.py::
   test_restart_mid_dispatch_resumes_to_completed` exists and passes.
7. Full suites green (`tests/unit` + `tests/integration`); ruff + pyright clean;
   kernel purity and the `graph_runtime` import boundary unchanged
   (`grep -r 'fastapi\|orchestrator.api\|orchestrator.workflow'
   src/orchestrator/graph_runtime/` → zero hits).

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written MockAgent + recording
  controller/dispatcher/driver seams injected via constructor only.
- Real SQLite tmp **file** DBs (a restart must reopen the same file) + real tmp
  git worktrees. Never touch `orchestrator.db` / main repo git.
- Kernel purity: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- Import boundary preserved: `graph_runtime/` imports no FastAPI /
  workflow-service internals. Recovery wiring lives in `api/`+`workflow/`
  (above the boundary) and may import both layers.
- §28 rule 1: recovery issues all graph mutations through
  `GraphController.handle_command()`; it never writes `events_v2` directly.
- This slice WIRES existing primitives — it must not reimplement `recover()`,
  `reconcile_runtime()`, the outbox, or the driver loop.

## Note on execution

This slice is itself built by the orchestrator **on the graph execution path**
(`execution_mode: graph`) as the live dogfood gate — the first real graph-mode
run in the server. If that run surfaces `GraphRunDriver` integration gaps, those
fixes are in-scope for closing Phase 2 and are folded into this slice's branch.
