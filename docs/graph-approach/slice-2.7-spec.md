# Slice 2.7 — Production graph run driver (retires the dogfood gate)

Size: L. Built after 3.1 but logically completes **Phase 2**: it is the first
slice that executes a graph-backed run **through the running server**, not a
test harness. It retires the dogfood gate deferred since 2.3.

The whole graph runtime already exists and is tested — kernel, compiler,
`GraphController`, a `GraphDispatchExecutor` that runs real agents,
the at-least-once outbox, file-state boundary, gatekeeper, and `recover()` /
`reconcile_runtime()`. `tests/integration/test_graph_runner_e2e.py` drives a
full builder→verifier→accept cycle today — but by **hand-calling the loop**.
No server path does that. `RUN_START` always routes to the legacy
`RunWorkflow` loop, which knows nothing about graphs. This slice builds the
production driver and the plumbing around it.

## Ground truth

- execution-graph-prd-plus.md §12.3 (agent dispatch as side effect),
  §14 (projection rules — task `accepted` is the target), §15.6 (planner
  lifecycle), §17 (readiness/scheduling), §32 Migration steps 2+5
  (graph projections behind compat APIs; runs execute on the graph).
- execution-graph-evaluation.md §6.1 (run-completion invariant: no pending
  planner AND all tasks accepted).
- `docs/graph-approach/slice-2.6-spec.md` "Dogfood gate" (§ lines 187-200) —
  THE acceptance scenario this slice makes real.
- `docs/graph-approach/slice-process.md` (this slice is itself run via the
  orchestrator's `graph-kernel-slice` routine on the legacy path).
- Existing runtime (do NOT rebuild): `src/orchestrator/graph_runtime/`
  — `seed_run`, `build_graph_runtime` (returns `(GraphController,
  GraphDispatchExecutor)`), `OutboxDispatcher.dispatch_pending`,
  `GraphDispatchExecutor.wait_for_all` / `is_running`,
  `project_run_state` / `project_task_states` / `project_ready_nodes` /
  `project_leases`.
- Read-only projection API + UI (slice 2.6): `GET /api/runs/{id}/graph`,
  `is_graph_backed`, `GraphIndicator`/`GraphPanel`.
- Graph stream namespacing: `graph_aggregate_id()` in `graph_runtime/store.py`.

## Scope — what to build

### 1. Run-level routing flag (DB + create path)

No flag today decides "execute this run via the graph runtime"
(`is_graph_backed` is *derived* from event existence, not a *decision*).

- Add `execution_mode` column to the `runs` table: values `"legacy"`
  (default) | `"graph"`. **Alembic migration required** (per project rule:
  `create_all` does not add columns; never reset `orchestrator.db`).
- `state/models.py` `Run`: `execution_mode: str = "legacy"`.
- Create path (`api/routers/runs.py` `create_run` / `_build_run_from_request`):
  accept optional `execution_mode` on `CreateRunRequest` (default `"legacy"`).
  A routine may also declare `execution_mode: graph` in its config; request
  value wins if both present.
- `RunResponse` already exposes `is_graph_backed`; add `execution_mode` so the
  UI can distinguish "intended graph run" from "happens to have graph events".

### 2. The graph run driver — `src/orchestrator/workflow/graph_driver.py` (new)

This is the core. It lives **above** the `graph_runtime` import boundary
(it may import both `graph_runtime` and the workflow service; `graph_runtime`
must still import neither FastAPI nor the workflow service).

`class GraphRunDriver`:

```python
async def run(self, run_id: str) -> GraphRunOutcome
```

On invocation for a graph-mode run:

1. **Seed** (idempotent): if `current_position(run_id) == 0`, call `seed_run`
   (compile routine embedded on the run → initial graph). If already seeded
   (recovery / re-entry), skip.
2. **Build runtime**: `build_graph_runtime(..., worktree_path=<run worktree>,
   runner_type=<run.agent_runner_type>, runner_config=<run.agent_runner_config>)`.
   Construct an `OutboxDispatcher(session_factory, executor, clock)`.
3. **Self-advancing loop** (the missing mechanism):
   ```
   loop:
     result = controller.handle_command(run_id, pos, "schedule_tick", {...})
     await dispatcher.dispatch_pending()      # starts agents for new leases
     await executor.wait_for_all()            # await this wave's callbacks
     proj = rebuild projection from store
     if no ready nodes AND no active leases:
        break                                  # quiescent
   ```
   The loop re-ticks after each wave because an accepted `submit_callback`
   completes a node and may make downstream nodes ready (builder→verifier→
   accept). Termination is graph quiescence, matching the e2e test structure —
   just automated, with no hard-coded tick count.
4. **Classify terminal state** from `project_run_state`:
   - `completed` → success.
   - quiescent but not completed (e.g. blocked on a human gate, budget
     exhaustion gate, or all attempts failed) → return a `paused`/`blocked`
     outcome with the reason; do NOT mark the run completed.
5. The driver must be safe to **re-enter** (recovery slice 2.8 will call it
   after `recover()`): seeding is conditional on position, dispatch is
   idempotent via the outbox.

`GraphRunOutcome`: `{run_id, run_state, completed: bool, blocked_reason: str | None}`.

### 3. Worktree provisioning for graph runs

`build_graph_runtime` needs a `worktree_path`. Reuse the existing worktree
creation used by the legacy start path (`git/worktree.py` /
`WorktreeManager`); do not invent a second mechanism. The driver must receive
a ready worktree path before step 2.

### 4. Lifecycle bridge: graph `run_state` → legacy `Run.status`

The UI run status, completion, and list views read the legacy `Run` row.
Bridge the graph terminal state onto it via the existing workflow service
(no new event table; the GraphPanel already shows per-node/task graph state
directly from 2.6, so legacy per-task status need NOT be mirrored here):

- On graph run start: legacy `Run.status` → `ACTIVE` (reuse `start_run` /
  `apply_start_run`).
- On driver success (`run_state == completed`): transition `Run.status`
  → `COMPLETED` through the service.
- On driver blocked/failed: `Run.status` → `PAUSED` (with reason) or `FAILED`
  using existing service methods (`apply_pause_run` / fail path).
- Mirroring graph `task_states` onto legacy per-task `TaskStatus` is **out of
  scope** (the GraphPanel covers task visibility for the gate; full task
  projection bridging is a §32 follow-up).

### 5. RUN_START integration

In the signal consumer (`workflow/signals/consumer.py` `RUN_START` handler):
branch on `run.execution_mode`. `"graph"` → spawn the `GraphRunDriver` as the
run's execution task (the graph analog of registering a `RunWorkflow`).
`"legacy"` → unchanged. The branch must be a thin dispatch; all graph logic
lives in `graph_driver.py`.

### Explicitly OUT of scope (deferred to slice 2.8 — Graph startup recovery)

`recover()` / `reconcile_runtime()` already exist and are integration-tested
(2.1/2.3 crash-point suites) but are **not wired into the server lifespan**.
Wiring them — enumerating active graph runs on startup, retrying pending
outbox, reconciling dead leases, re-arming the driver — needs its own
crash-point integration tests to be meaningful, and bundling it would make
this slice unauditable. This slice delivers the **forward happy path** that
the dogfood gate exercises (no crash). 2.8 adds restart resilience. This is a
principled split, not avoidance: the gate scenario in 2.6 does not restart the
server mid-run.

## Tests

### Integration — `tests/integration/test_graph_run_driver.py` (new)

Real tmp-file SQLite, real tmp git worktree, hand-written `MockAgent`
(`runners/agents/mock/agent.py` — a real configurable adapter, NOT
`unittest.mock`). NO server, NO `orchestrator.db`. This file contains the
**named e2e acceptance drill** for the slice.

- `test_driver_runs_single_worker_verifier_to_accepted()` — seed a one-task
  routine (worker + verifier), run the driver end-to-end; assert: agents were
  dispatched in order, `project_task_states` reaches `accepted`,
  `project_run_state` is `completed`, `GraphRunOutcome.completed is True`,
  and the legacy `Run.status` is `COMPLETED`. **This is the e2e drill.**
- `test_driver_self_advances_across_node_boundaries()` — prove the loop
  re-ticks: with a configured agent that completes the worker, the verifier
  is leased and dispatched WITHOUT a second manual `schedule_tick` from the
  test (the driver issues it).
- `test_driver_blocks_on_verifier_fail_without_completing()` — verifier returns
  fail/needs-revision; driver reaches quiescence with `run_state != completed`;
  outcome `completed is False` with a reason; legacy run NOT `COMPLETED`.
- `test_driver_seed_is_idempotent_on_reentry()` — call the driver twice over
  the same DB; the second call does not double-seed (position unchanged before
  first tick) and does not double-dispatch.
- `test_driver_planner_run_completes_only_when_no_pending_planner()` — a
  routine with a planner step (3.1): the driver does not mark the run complete
  while a planner node is pending; completes after the chain terminates.

### Integration — `tests/integration/test_graph_run_start_routing.py` (new)

Real SQLite + the test app/service pattern (see existing
`tests/integration/test_graph_api.py` for app/session fixtures). NO real LLM.

- `test_create_run_records_execution_mode()` — POST a run with
  `execution_mode: "graph"`; `GET /api/runs/{id}` returns
  `execution_mode == "graph"`.
- `test_legacy_run_defaults_execution_mode_legacy()` — default omitted →
  `"legacy"`; routing unchanged.
- `test_run_start_routes_graph_mode_to_driver()` — RUN_START for a graph-mode
  run invokes the driver path (inject a recording driver via the same
  service/consumer seam tests already use; assert the driver was called for
  the run and the legacy `RunWorkflow` was not).

### Unit — `tests/unit/test_graph_driver_logic.py` (new)

Pure logic with a hand-written fake controller/dispatcher/executor (recording
classes injected via constructor — no mocks):

- `test_loop_terminates_on_quiescence()` — given a scripted projection
  sequence (ready nodes → leases → quiescent), the loop stops re-ticking.
- `test_outcome_classification()` — completed vs blocked-on-gate vs
  all-attempts-failed map to the correct `GraphRunOutcome`.

### Migration test

- `tests/integration/test_migrations.py` (or existing migration test) covers
  upgrade/downgrade of the `execution_mode` column if such a test exists;
  otherwise add a focused test that the column exists after `init_db`.

## Done when

1. A run created with `execution_mode: "graph"` is routed at RUN_START to the
   `GraphRunDriver`, not the legacy `RunWorkflow`; a `"legacy"`/default run is
   unchanged.
2. The driver seeds the graph (once), then self-advances
   schedule_tick→dispatch→await→re-tick with no hard-coded tick count, running
   real agents through the existing `GraphDispatchExecutor`.
3. A one-task graph run drives builder→verifier→`accepted`
   (`project_task_states`), `project_run_state` reaches `completed`, and the
   legacy `Run.status` reaches `COMPLETED` via the lifecycle bridge.
4. A verifier-fail run reaches quiescence WITHOUT completing; the run is not
   marked `COMPLETED`; outcome carries a reason.
5. A planner-bearing run (3.1) completes only when no planner node is pending
   AND all tasks accepted (§6.1 invariant honoured by the driver's terminal
   check).
6. `execution_mode` is a real `runs` column added by an Alembic migration and
   surfaced on `RunResponse`; the gate run shows `is_graph_backed` true and the
   `[Graph]` panel renders node/task states (2.6 UI, unchanged).
7. The named e2e drill `test_graph_run_driver.py::
   test_driver_runs_single_worker_verifier_to_accepted` exists and passes.
8. Full suites green: `tests/unit` + `tests/integration`; ruff + pyright clean;
   kernel purity and the `graph_runtime` import boundary unchanged.

## Manual dogfood gate (post-merge, documented — not an automated test)

After merge, run the 2.6 dogfood scenario for real:
1. `uv run orchestrator serve --reload` (or `bash dev.sh`).
2. Create a run on a trivial one-task spec with `execution_mode: "graph"`,
   `runner_type: codex_server` (model per `feedback-codex-model`).
3. Start it; confirm `[Graph]` shows and the Graph panel updates as the agent
   works; let it complete; confirm the run reaches COMPLETED.

This is the v1 implementation acceptance the project has tracked since 2.3.

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written MockAgent + fake
  controller/dispatcher/executor injected via constructor only.
- Real SQLite tmp dirs + real tmp git worktrees. Never touch
  `orchestrator.db` / main repo git. New column lands via Alembic migration.
- Kernel purity unchanged: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- **Import boundary preserved**: `src/orchestrator/graph_runtime/` must STILL
  import no FastAPI / workflow-service internals. The new driver lives in
  `workflow/` (above the boundary) and may import both layers — verify with
  `grep -r 'fastapi\|orchestrator.api\|orchestrator.workflow' src/orchestrator/graph_runtime/`
  → zero hits after this slice.
- §28 rule 1: only `GraphController.handle_command()` appends accepted graph
  events. The driver issues commands through the controller; it never writes
  `events_v2` directly.
- No new N+1 in the run create/list path (routing flag read is on the existing
  per-run/batch queries from 2.6).
