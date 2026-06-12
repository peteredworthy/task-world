# Slice 2.2 — Routine compiler (BUILDER)

You are the BUILDER agent for slice 2.2 of the task-world execution-graph kernel (Phase 2, effectful shell).

## Ground truth (read these first, in order)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §23.1–23.3 (routine compilation mapping table), §10 (node/edge/port model), §11.3 (graph record), §15 (node kinds/lifecycle), §6 (canonical terms), §29 (minimum viable graph kernel, item 1)
2. `docs/graph-approach/execution-graph-evaluation.md` — §4.5 ("nothing guarantees minimal graphs for simple tasks") — this slice carries the fix: the minimal-graph requirement
3. The slice definition (sequencing deck): "2.2 Routine compiler — Routine YAML → initial graph per §23.2 mapping table. Includes the minimal-graph requirement: a single-task routine compiles to the minimum executable graph. Done when: existing routines (incl. demo-task.yaml) compile; minimal-graph test passes; per-node controller overhead measured and bounded."
4. Existing routine model: `src/orchestrator/config/models.py` (`RoutineConfig`, `StepConfig`, task config with `requirements`, `auto_verify`, `verifier`, `fan_out`, gates), loader `src/orchestrator/config/routines/loader.py` (`load_routine_from_path`)
5. Existing kernel: `src/orchestrator/graph/` (models, commands.apply_command, projections); slice 2.1 runtime: `src/orchestrator/graph_runtime/` (GraphController, store, outbox)
6. Real routine corpus: `routines/demo-task.yaml`, `routines/*/routine.yaml`, `examples/routines/*.yaml`

## Scope — what to build

### 1. Pure compiler in the kernel

New module `src/orchestrator/graph/compiler.py` — PURE (no IO, no YAML loading, no DB; injected `Clock`/`IdGenerator` from `orchestrator.graph.commands`):

```python
compile_routine(routine: RoutineConfig, clock: Clock, id_gen: IdGenerator, *, run_id: str) -> list[EventEnvelope]
```

Returns the ordered event list that seeds an initial graph for the run (node_created / edge_created / input-binding events — whatever the existing reducers already consume; if a needed event type lacks a reducer, add the reducer too). Importing `orchestrator.config.models` into the kernel is acceptable (pure Pydantic), but NOT the loader (IO) — the caller loads YAML.

Implement the §23.2 mapping table — every row:

| Routine concept | Graph representation |
|---|---|
| Routine | Root node plus routine snapshot record (record node carrying the routine identity/version; see §11.3) |
| Step | Plan region or grouping projection (NOT necessarily a node per step — choose the minimal faithful representation and document it; steps order task regions sequentially: tasks in step N+1 depend on step N completing, matching current workflow-engine semantics) |
| Task | Task projection (task_region_id) plus worker node; verifier node only if the task has a `verifier` rubric; check node(s) only if `auto_verify` items exist |
| Requirement | Requirement nodes and edges to worker/verifier ports |
| Auto-verify | Check nodes (one per auto_verify item or one per task — pick one, document why; the §23.2 row says "Check nodes") |
| Human approval gate | Gate node (only when the routine/task configures one) |
| Context/artifact dependency | Input binding edge |
| Fan-out | Reader nodes plus synthesis/join node (only when `fan_out` configured) |

MINIMAL-GRAPH REQUIREMENT (binding, from the slice definition): a routine with one step, one task, no requirements, no auto_verify, no verifier rubric, no gates, no fan-out compiles to the MINIMUM executable graph — root + routine snapshot record + the single worker node + the edges required for execution, and nothing else. No empty gate nodes, no placeholder verifier, no per-step scaffolding nodes for absent features. Conversely the graph must still be executable: a `schedule_tick` through the kernel can grant the worker a lease.

### 2. Effectful seeding through the 2.1 controller

In `src/orchestrator/graph_runtime/` add a thin seeding path (e.g. `seed_run(session_factory, routine, run_id, clock, id_gen)` or a `compile_routine` command routed through `GraphController.handle_command`) that appends the compiled events transactionally via the slice-2.1 store (expected_position guard, same atomicity rules). No outbox rows are produced by compilation events. Decide and document: seeding as one `compile_routine` command through `apply_command` (preferred if it keeps the controller the single append path per §28 rule 1) vs direct store append; justify in code docstring.

### 3. Tests

`tests/unit/test_graph_compiler.py` (pure, fast — part of the kernel suite):
- §23.2 mapping: one test per table row asserting the produced nodes/edges/records for a routine fragment exercising that row (requirements → requirement nodes + edges; auto_verify → check nodes; verifier rubric → verifier node; fan_out → reader + join; gate → gate node; step ordering → cross-step dependency edges).
- Minimal-graph test: the single-task routine above → assert the EXACT node set (count and kinds) and that `evaluate_readiness`/`schedule` can lease the worker after run start.
- Determinism: same routine + same id_gen/clock seeds → identical event list.
- Events replay: `reduce_event` over compiler output yields a projection with the expected nodes/edges/task regions (no unknown-event warnings, every emitted event type has a reducer).
- Compiled projection is schedulable end-to-end in the pure kernel: run lifecycle start → schedule_tick grants lease on the first worker; downstream tasks stay blocked until upstream completes (use existing kernel commands).

`tests/integration/test_graph_routine_compile.py`:
- Corpus test: every routine in `routines/` (including `routines/demo-task.yaml` and `routines/*/routine.yaml`) and `examples/routines/*.yaml` loads via `load_routine_from_path` and compiles without error; sanity-assert per routine: worker-node count == task count, verifier/check/gate counts match config, event list replays into a projection cleanly.
- Seeding through SQLite: compile demo-task.yaml, seed via the 2.1 path into a tmp-file DB, read back, rebuilt projection == in-memory projection from compiler output.
- PER-NODE CONTROLLER OVERHEAD measured and bounded (done-when item): measure compile+seed+first-schedule-tick wall time and events-per-node for demo-task.yaml through the real controller on tmp SQLite; assert a generous but real bound (e.g. < 50ms per node on this machine and a fixed events-per-node ceiling — pick bounds that fail on pathological regressions, not on CI noise; record the measured numbers in the test docstring or via a printed report line).

## Done when (all must hold)

1. Every §23.2 mapping-table row has a dedicated compiler test.
2. Minimal-graph test passes: single-task routine → exact minimum executable node set, schedulable.
3. All existing routines in `routines/` and `examples/routines/` compile; corpus test proves it.
4. Per-node controller overhead is measured in a test and bounded by an assertion.
5. Kernel purity: `src/orchestrator/graph/compiler.py` imports no IO/DB/YAML/loader modules; kernel suite (now incl. compiler tests) stays under 5s.
6. Fresh runs green: `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `uv run ruff check src tests`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`.

## Hard constraints

- NO mocks, NO monkeypatching anywhere. Real YAML files from the repo, real tmp SQLite.
- NEVER touch main `orchestrator.db`, never run the server, no git mutation commands (read-only git fine).
- Touch ONLY: `src/orchestrator/graph/compiler.py` (new), `src/orchestrator/graph/__init__.py` (export), `src/orchestrator/graph/projections.py` + `models.py` (only if a reducer/model addition is needed), `src/orchestrator/graph_runtime/**` (seeding path), `tests/unit/test_graph_compiler.py` (new), `tests/integration/test_graph_routine_compile.py` (new), `tests/fixtures/graph/**` + COVERAGE.md if you add fixtures. Nothing else. Working tree is clean at start — leave unrelated files untouched.
- Do not modify any routine YAML in `routines/` or `examples/routines/` — they are inputs, not fixtures to bend.

When done, write a summary: mapping-table design decisions (step representation, check-node granularity, seeding path), the minimal-graph node set, measured overhead numbers, and fresh test output.
