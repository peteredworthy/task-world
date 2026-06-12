# Slice 3.1 — Recursive Horizon Planner (kernel)

Size: M. Phase 3 opener: the planner chain becomes structural. Builds on the
existing `submit_patch` command (slice 1.7 validator + 2.5-era handler in
`commands.py`). Kernel + minimal compiler support only — NO runner/LLM planner
agent in this slice; planners are exercised through commands in tests.

## Ground truth

- execution-graph-evaluation.md §6.1 Recursive horizon planning — THE source
  for loop semantics, termination, budget, successor input bindings.
- execution-graph-prd-plus.md §15.6 Planner lifecycle; §16 Graph Patch Model
  (envelope, allowed ops, validation rules 1–8, stale-base revalidation);
  §17 readiness; §14 projection rules.
- `src/orchestrator/graph/commands.py` — `_apply_patch_command` (`submit_patch`)
- `src/orchestrator/graph/patch_validator.py` — `validate_patch`
- `src/orchestrator/graph/compiler.py` — node/edge construction patterns

## Scope — what to build

### 1. Planner node kind in the kernel

- `models.py`: ensure node kind `planner` is a first-class executable kind
  (role `planner`). Lifecycle per §15.6: planner completion does NOT imply
  patch acceptance — patch acceptance stays a separate accepted record/event.
- Scheduler (`scheduler.py`): planner nodes participate in readiness exactly
  like workers (required input ports bound → ready). No special-case re-entry
  logic — the loop IS graph readiness (§6.1).

### 2. Horizon patch: region + successor planner

Extend patch handling (`commands.py`, `patch_validator.py`) so one accepted
patch from a planner lease can contain:

- (a) an executable region: worker/verifier/check/gate nodes + edges
  (existing `create_node`/`create_edge` ops — no new op types), and
- (b) zero or more successor planner nodes (`create_node` with kind
  `planner`) whose REQUIRED input ports bind via edge selectors to region
  milestone records:
  - `region_summary` — region's summary output record
  - `accepted_file_state` — region's last accepted file-state record
  - `outstanding_failures` — failure/suspect records (optional port; binds
    empty-allowed)

`bind_input` stays controller-only (§16): the successor's ports bind only
when accepted records satisfy the immutable edge selectors. No new bind
authority for planners.

### 3. Termination invariant in projections

`projections.py`:

- `project_run_state` returns `completed` only when BOTH: no planner node is
  in a pending state (`planned`/`ready`/`leased`/`running`) AND all task
  projections are accepted (§6.1 "Termination is checkable").
- A final planner that emits a patch with no successor planner node ends the
  chain: once its region completes, no pending planner remains.
- New pure helper `project_planner_chain(events)` → ordered list of
  `{node_id, generation_index, state, successor_node_id | None}` for UI/audit.

### 4. Planner-generation budget

- Run-level budget (compiler seeds it from routine config; default 8) carried
  in the seeded graph (e.g. `run_created`/seed payload), not hardcoded.
- `submit_patch` from a planner whose patch creates a successor planner is
  REJECTED (`graph_patch_rejected`, reason `planner_generation_budget_exhausted`)
  when accepting it would exceed the budget. The rejection event payload names
  the budget and the count.
- On exhaustion the controller path routes to a human gate: the same command
  emits an accepted `create_gate`-shaped event (`node_state_changed` to a new
  gate node guarding further planning), per §6.1 "exhaustion routes to a
  human gate".

### 5. Compiler: seed a planner chain

`compiler.py`: a routine step may declare `kind: planner` (routine config
opt-in). Compiling it produces the FIRST planner node of the chain with its
input ports pre-bound to the run's initial context (no region precedes it).
Existing non-planner routines compile exactly as before — zero behavior
change when no planner step is declared (minimal-graph guarantee from 2.2
must keep holding).

## Tests

### Unit — `tests/unit/test_graph_planner.py` (new)

- `test_planner_lifecycle_states` — §15.6 table transitions accepted/rejected.
- `test_horizon_patch_creates_region_and_successor` — accepted patch yields
  region nodes + successor planner with selector-bound required ports;
  successor NOT ready while region incomplete.
- `test_successor_readiness_via_milestone_records` — region summary +
  accepted file-state records bind successor ports; successor becomes ready;
  scheduler leases it (pure scheduler call).
- `test_final_planner_no_successor_terminates` — chain with no successor →
  after region accepted, `project_run_state` == `completed`.
- `test_run_not_complete_with_pending_planner` — all tasks accepted but a
  planner still pending → run NOT completed.
- `test_generation_budget_rejects_and_gates` — budget N: Nth successor
  attempt rejected with `planner_generation_budget_exhausted` + gate node
  event emitted; gate guards further planning.
- `test_project_planner_chain` — ordered chain projection with states.
- `test_patch_acceptance_separate_from_planner_completion` — planner node
  `completed` while its patch is rejected → no region nodes; replan path open.

### Unit — `tests/unit/test_graph_compiler.py` (extend)

- `test_compile_planner_step_seeds_chain_head` — planner step → one planner
  node, ports bound to initial context.
- `test_compile_without_planner_unchanged` — existing fixtures byte-identical
  (minimal-graph regression guard).

### Integration — `tests/integration/test_graph_planner_flow.py` (new)

Real SQLite tmp DB, `GraphController` only (no HTTP, no runner):

- `test_planner_chain_two_horizons_end_to_end` — seed run with planner step;
  planner lease submits horizon-1 patch (1 worker + 1 verifier + successor);
  drive region to accepted via commands; successor becomes ready; horizon-2
  patch with NO successor; drive to accepted; run state `completed`; replay
  from events reproduces identical projections.
- `test_budget_exhaustion_routes_to_gate_through_controller` — budget 1,
  second successor rejected, gate node visible in projection, run NOT
  completed.

## Done when

1. Accepted planner patch creates region + successor planner whose required
   ports are selector-bound to region milestone records; successor readiness
   is pure graph readiness (no special scheduler policy).
2. Termination invariant: run completes only with no pending planner AND all
   tasks accepted; final planner = no successor.
3. Generation budget enforced at patch acceptance; exhaustion emits rejection
   + human-gate node; both visible in projections.
4. Planner completion and patch acceptance are independent facts (§15.6).
5. Compiler seeds planner chain head from routine config; non-planner
   routines compile unchanged (existing compiler tests untouched and green).
6. `project_planner_chain` returns the chain in order with states.
7. All listed tests pass; full unit + integration suites green; kernel-only
   graph tests still fast (~2s ballpark).
8. Kernel purity unchanged; §28 rule 1 unchanged (controller is the single
   append path).

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written fake/recording classes only.
- Real SQLite tmp dirs only. Never touch `orchestrator.db` / main repo git.
- Kernel purity: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- `graph_runtime` imports no FastAPI / workflow-service internals.
- §28 rule 1: only `GraphController.handle_command()` appends graph events.
- v1 keeps §6.1's deliberate smallness: single planner chain, the three
  successor binding kinds above only. No parallel planners, no retained
  planner session in this slice.
