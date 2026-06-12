# Slice 2.2 — Routine compiler (FIXER)

You are the FIXER agent for slice 2.2. The AUDITOR returned BOUNCE. Close EVERY HIGH and MEDIUM finding (LOWs where cheap). Do not regress anything green.

## Ground truth (read first)

1. Audit report: `/tmp/codex-graph/audit-2.2-report.md`
2. `docs/graph-approach/execution-graph-prd-plus.md` — §17 (readiness criteria, esp. criterion 3 "required input ports have accepted records" vs criterion 4 "upstream required dependency"), §10.5 (edge model), §23.2 (mapping table), §28 rule 1 (only the controller appends accepted graph mutation events), §11.3 (graph record / routine snapshot)
3. Implementation: `src/orchestrator/graph/compiler.py`, `src/orchestrator/graph_runtime/seeding.py`, kernel `commands.py`/`scheduler.py`/`projections.py`, tests `tests/unit/test_graph_compiler.py`, `tests/integration/test_graph_routine_compile.py`

## Findings to close

### HIGH-1 — Multi-step graphs are not executable past step 1

Reproduced by the auditor: compiler emits required `prior_step_completion` input-binding edges between steps; `evaluate_readiness` requires an accepted record bound to that port; the callback completion path never produces one. After step-1 worker completes, step-2 worker stays deferred with `missing_required_input:prior_step_completion` forever.

Fix it per the PRD, not with a hack. Decide between (document the choice in code):
- (a) Model step ordering as a STATE-DEPENDENCY edge (§17 criterion 4: upstream required dependency must be completed; failed/cancelled blocks), not an input-binding edge. The kernel's readiness already (or should) evaluate dependency edges from upstream node state. Compiler emits the dependency-typed edge; no record needed.
- (b) Keep input-binding edges and make the kernel's callback-completion path emit the output record / `input_bound` events that satisfy downstream ports when a node completes.

Option (a) is likely truer to §17 (criterion 3 is about data ports, step ordering is control flow), but verify against §10.5's edge types and pick what the kernel supports cleanly. Whatever you choose, the kernel change stays pure.

Required tests:
- Pure kernel end-to-end: compile a 2-step routine, start run, tick → lease step-1 worker, complete it via the kernel's callback command, tick again → step-2 worker becomes ready and leasable. Also negative: step-1 worker FAILS → step-2 stays blocked (criterion 4 semantics).
- Integration: same flow through `GraphController` on tmp SQLite (schedule_tick → dispatch → acknowledge → submit_callback completion → next tick leases step 2).
- demo-task.yaml (2 steps, 3 tasks) specifically: full traversal to all workers leased/completable in step order.

### MEDIUM-1 — Seeding bypasses the controller (§28 rule 1)

`seed_run` appends via `GraphEventStore` directly. Fix: route seeding through `GraphController` as a command (e.g. `seed_compiled_events` / `compile_routine` command handled in pure `apply_command`, validating the run has no prior topology and the events are well-formed, or have the controller accept a `seed_run` boundary input that calls the pure compiler inside its command-handling path). The controller must remain the single append path for graph mutation events; expected-position guard and no-outbox behavior preserved. Update the seeding tests to go through the controller; remove or de-export the direct path.

### MEDIUM-2 — Fan-out mapping weaker than §23.2

§23.2: "Reader nodes plus synthesis/join node." Current: one reader template node, worker doubles as join. Fix minimally but faithfully: emit a DISTINCT synthesis/join node downstream of the reader template, with edges reader → join → worker (or join as the worker's input port source). Per-input reader expansion from glob results is legitimately runtime work — state that explicitly in the compiler docstring AND in the test for the fan-out row, asserting the template + join structure that runtime expansion will multiply.

### MEDIUM-3 — Routine snapshot lacks durable version identity

Add to the snapshot record payload: a deterministic content hash of the routine definition (pure — canonical JSON of the RoutineConfig dump, sha256; computable inside the pure compiler) plus optional caller-supplied source metadata (e.g. `source_path`, `source_ref`) threaded through the seeding path. Test: same routine → same hash; changed routine field → different hash; seeding records source metadata.

### LOW (cheap) — paired gate/no-gate test; corpus docstring states scope is active top-level routines + examples.

## Done when

1. HIGH-1: multi-step execution proven end-to-end in pure kernel AND through controller on SQLite, including the failure-blocks-downstream negative.
2. MEDIUM-1: no graph-mutation append path outside the controller in `graph_runtime` public API; seeding tests use the controller.
3. MEDIUM-2: distinct join node emitted + tested; runtime expansion deferral documented.
4. MEDIUM-3: content hash + source metadata in snapshot record, tested.
5. Fresh green: `uv run pytest tests/unit -q`; `uv run pytest tests/integration -q`; `uv run ruff check src tests`; `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`. Kernel suite stays under 5s, kernel stays pure (no IO imports).

## Hard constraints

- NO mocks, NO monkeypatching. Real tmp SQLite, real repo YAML. Never touch main `orchestrator.db`, no server, no git mutation (read-only git fine).
- Touch ONLY: `src/orchestrator/graph/**` (compiler, commands, scheduler, projections, models, __init__), `src/orchestrator/graph_runtime/**`, `tests/unit/test_graph_compiler.py`, `tests/unit/test_graph_commands.py`, `tests/unit/test_scheduler.py`, `tests/integration/test_graph_routine_compile.py`, `tests/integration/test_graph_outbox_crash_points.py` (only if controller seeding touches it), `tests/fixtures/graph/**` + COVERAGE.md if fixtures added. Nothing else.
- Do not modify routine YAMLs.

When done: summary mapping finding → fix → test, the step-ordering design choice taken (a/b) and why, fresh test output.
