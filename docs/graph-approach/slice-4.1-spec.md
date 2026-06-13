# Slice 4.1 — Graph runs become the default carrier

Size: M. Phase 4 opener. Today every run defaults to `execution_mode="legacy"`
(`api/routers/runs.py` ~L454: `request.execution_mode or routine_execution_mode
or "legacy"`); graph mode is opt-in and exercised only by the dogfood gate. This
slice flips the default so new runs execute as graph runs through
`GraphRunDriver`, with legacy still selectable as an explicit opt-out, and makes
the flip safe to roll back via a single config switch.

## Prerequisites

- Dogfood gate (D): at least one fully-green live graph run to COMPLETED
  (worker → verifier → accepted → run COMPLETED) through the production driver.
  Do NOT flip the default until the gate is green.
- The §26 frontend track (3.2–3.6) is merged so graph runs are fully inspectable.

## Ground truth

- execution-graph-evaluation.md §4.5 minimal graphs; §6.1 (the loop is graph
  readiness); the convergence intent in slice-process.md Phase 4.
- execution-graph-prd-plus.md §13/§16/§28 runtime + controller rules.
- `config/models.py` `execution_mode: Literal["legacy","graph"] = "legacy"`;
  `api/routers/runs.py` run-creation default resolution; `graph_runtime`
  `GraphRunDriver`, seeding, recovery (slices 2.7/2.8).

## Scope — what to build

### 1. Default-carrier switch (config + run creation)

- Introduce a single source of truth for the default carrier — a global/config
  setting `default_execution_mode` (default `"graph"` after this slice) so the
  flip is one line to revert. Run-creation precedence becomes:
  `request.execution_mode or routine_execution_mode or settings.default_execution_mode`.
- Routines may still pin `execution_mode: "legacy"`; explicit request overrides
  win. No run silently changes carrier mid-flight.

### 2. Graph-seeding for ordinary routines

- Ensure ANY compilable routine (not just planner routines) seeds a valid graph
  via the 2.2 compiler + 2.7 driver — the minimal-graph guarantee (§4.5) means a
  plain routine compiles to worker/verifier nodes with no planner. Add a
  conformance check / test matrix proving the catalog's common routine shapes
  (single-step, fan-out, auto-verify, checklist-gate) all seed and drive to
  COMPLETED under graph mode.
- Any routine shape that cannot yet run as a graph is explicitly pinned to
  `legacy` with a recorded reason (a small allow-list), so the flip never breaks
  an un-portable routine silently.

### 3. Observability parity gate

- A graph run must surface the same operator-facing facts a legacy run does
  (status, activity timeline, task/node states, grades) — covered by 2.6 + 3.2–3.6.
  Add an integration check that a graph run exposes status + activity + node/grade
  facts through the existing run APIs the UI consumes.

## Tests

### Integration — `tests/integration/test_graph_default_carrier.py` (new)

Real SQLite tmp DB + real tmp git worktree; production driver, no mocks:
- `test_new_run_defaults_to_graph_mode()` — creating a run without
  `execution_mode` yields `execution_mode="graph"` when the default is graph.
- `test_routine_pinned_legacy_still_runs_legacy()` — a routine pinned to legacy
  (or an explicit request) runs legacy; precedence respected.
- `test_default_carrier_switch_round_trips()` — toggling
  `settings.default_execution_mode` back to `legacy` restores prior behaviour
  (rollback safety).
- `test_common_routine_shapes_seed_and_complete_as_graph()` — single-step,
  fan-out, auto-verify, and checklist-gate routine shapes each seed a graph and
  drive to COMPLETED through the driver (no-op/commit-clean workers).

### Frontend — vitest

- Run-creation UI shows the carrier (graph default) and lets an operator opt into
  legacy; the run detail renders graph facts for a graph run.

## Done when

1. New runs default to graph mode via a single `default_execution_mode` setting;
   explicit request / routine-pinned legacy override it; flip is one-line
   reversible (round-trip tested).
2. Common catalog routine shapes seed a graph and drive to COMPLETED; any
   un-portable shape is explicitly legacy-pinned with a recorded reason.
3. Graph runs expose status/activity/node/grade facts through the run APIs the UI
   consumes (observability parity).
4. Full suites green (unit/integration/vitest); ruff/pyright clean; kernel purity
   + `graph_runtime` boundary unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; hand-written fakes; real SQLite tmp + real tmp git
  worktrees; never touch `orchestrator.db` / main repo git.
- Kernel purity + `graph_runtime` import boundary unchanged.
- §28 rule 1: only `GraphController.handle_command()` appends graph events.
- The flip must be reversible by one config value — no scattered carrier
  conditionals.
