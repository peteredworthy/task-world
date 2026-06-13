# Slice 3.2 — Live graph-run activity timeline

Size: M. First frontend/observability slice after 2.6. Backend wiring + a UI
verification. Fixes a real regression: graph-mode runs currently emit **zero**
`agent_output` activity events (the graph dispatch path never wires
`on_output`), so the §26 "activity/event timeline" is blank for graph runs even
though `GraphPanel` shows node-state transitions.

## Ground truth

- execution-graph-prd-plus.md §26 UI and Observability Requirements
  ("Activity/event timeline" bullet; "projection vs fact must be visible").
- §32 Migration step 7 — introduce graph behind compatibility views; do not
  replace UI surfaces at once.
- Existing: `GraphDispatchExecutor._run_agent` (`graph_runtime/dispatch.py`)
  calls `runner.execute(ctx, on_checklist_update, on_submit, on_grade=...)`
  with **no** `on_output`. `build_graph_runtime` constructs the executor.
  `api/deps.make_graph_runner` builds the `GraphRunDriver` above the import
  boundary (may use the workflow event store / activity emitter).
- Legacy reference: `runners/execution/phase_handler.py` `on_output` →
  `OutputBatcher` → `agent_output` workflow events read by the activity feed.
- UI: `ui/src/components/detail/ActivityFeed.tsx` already renders `agent_output`
  events; `GraphPanel.tsx` shows graph events; `useGraphProjection` hook.

## Scope — what to build

### 1. Thread an output callback through the graph dispatch (import-clean)

- `GraphDispatchExecutor.__init__`: accept optional
  `on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None`.
  In `_run_agent`, define a local `on_output(lines)` that calls it (if set) and
  pass `on_output=on_output` to `runner.execute(...)`. The executor stays
  import-clean (no FastAPI/workflow imports) — it only invokes an injected
  callback.
- `build_graph_runtime`: accept and forward an optional `on_agent_output`
  callback to the executor. Default `None` (tests that don't care are
  unaffected).

### 2. Emit graph-run agent output as activity events (above the boundary)

- In `api/deps.make_graph_runner` (or a small helper it calls, in `workflow/`
  or `api/`): provide an `on_agent_output(context, lines)` that persists
  `agent_output` activity events for `context.run_id`, associated with the
  node's task region (`context.node_payload["task_id"]` / `task_region_id`),
  using the SAME activity/event path the legacy `OutputBatcher` uses so the
  existing `/api/runs/{id}/activity` feed surfaces them. Batch/throttle like the
  legacy batcher to avoid event spam (reuse `OutputBatcher` if practical).
- This emitter lives above the `graph_runtime` import boundary; the boundary is
  preserved (verify grep stays clean).

### 3. UI — graph-run activity surfaced

- The existing `ActivityFeed` renders `agent_output`; confirm graph-run output
  now appears there for a graph-backed run. If the run-detail activity view is
  gated to legacy runs, ungate it for graph runs.
- `GraphPanel`: add a compact "Live activity" affordance — either surface the
  latest agent output lines per running node, or link the node row to the
  activity feed filtered to that node. Keep it small; the raw graph-events modal
  from 2.6 stays.

## Tests

### Unit — `tests/unit/test_graph_dispatch_on_output.py` (new)

Hand-written recording agent + recording output sink (no mocks):
- `test_executor_forwards_agent_output_to_callback()` — a worker agent that
  calls `on_output(["line"])` results in the injected `on_agent_output` being
  called with the context + lines.
- `test_executor_runs_without_output_callback()` — `on_agent_output=None`
  (default) does not error; execution still submits.

### Integration — `tests/integration/test_graph_activity_stream.py` (new)

Real tmp SQLite + tmp git repo + hand-written MockAgent that emits output
(reuse the `test_graph_run_driver` harness):
- `test_graph_run_emits_agent_output_activity_events()` — drive a graph run
  whose worker emits output; assert `agent_output` activity rows exist for the
  run (queried the same way the activity endpoint reads them) and carry the
  run/task association.
- `test_legacy_runs_activity_unchanged()` — a legacy run's activity emission is
  unaffected (no double emission, no regression).

### Frontend — `ui/src/components/**/__tests__`

- A `GraphPanel`/activity test (vitest) asserting that when the graph
  projection + activity include node output, the panel renders the live-activity
  affordance and the feed shows the lines. No network — use the existing
  fixture/mock-data patterns already in the UI tests.

## Done when

1. `GraphDispatchExecutor` forwards agent `on_output` to an injected callback;
   default (no callback) is a no-op and execution still submits.
2. A graph-mode run emits `agent_output` activity events for its worker/verifier
   nodes, visible via `/api/runs/{id}/activity`, associated with the task region.
3. The UI activity feed shows live graph-run output; `GraphPanel` exposes a
   live-activity affordance per node (or a filtered link).
4. Legacy-run activity is unchanged (no regression, no double emission).
5. `graph_runtime` import boundary intact (emitter lives above it); kernel
   purity unchanged.
6. Full suites green: `tests/unit` + `tests/integration`; ruff + pyright clean;
   frontend `npx vitest run` green.

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written recording agents/sinks only.
- Real SQLite tmp dirs + real tmp git worktrees; never touch `orchestrator.db`.
- Kernel purity unchanged; `graph_runtime` imports no FastAPI/workflow internals
  (`grep -r 'fastapi\|orchestrator.api\|orchestrator.workflow' src/orchestrator/graph_runtime/` → zero).
- §28 rule 1 unchanged: only `GraphController.handle_command()` appends graph
  mutation events. `agent_output` activity events use the existing workflow
  activity path, NOT `events_v2` graph mutations.
