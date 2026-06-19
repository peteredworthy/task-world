# Slice DG-2.1 - Dynamic Feature Routine Skeleton

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-2,
  Slice DG-2.1.
- `docs/graph-approach/slice-DG-1.1-spec.md` - accepted planner packet.
- `docs/graph-approach/slice-DG-1.2-spec.md` - accepted fenced
  `submit_graph_patch` callback/tool path.
- `docs/graph-approach/slice-DG-1.3-spec.md` - accepted planner prompt
  contract and controlled live Codex planner evidence.
- `routines/graph-kernel-slice/routine.yaml` - current narrow slice routine.
- `src/orchestrator/config/models.py` - routine schema, including planner
  steps and `planner_generation_budget`.
- `src/orchestrator/graph/compiler.py` - routine-to-graph compiler.
- `tests/integration/test_graph_routine_compile.py`

## Scope

Add a production routine skeleton for dynamic graph feature work. The routine
must seed a planner head in graph execution mode and give that planner enough
compact context to create future worker, verifier, gap-planner, and invariant
check regions through `submit_graph_patch`.

This is a routine/configuration slice. Do not change graph patch permissions,
database schema, API routes, UI, scheduler policy, final invariant semantics, or
Codex runner internals unless a failing test proves a minimal routine-loading or
compilation defect.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-2.1",
    "spec_path": "docs/graph-approach/slice-DG-2.1-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

The manager may use `routine_embedded` to avoid stale-docs worktree drift. Do
not use Claude-backed runners.

## What To Build

### 1. Dynamic Feature Routine

Create `routines/dynamic-graph-feature/routine.yaml`.

Required routine properties:

- `id: dynamic-graph-feature`
- `execution_mode: graph`
- `planner_generation_budget` is explicit and finite.
- Inputs:
  - `feature_spec_path` required.
  - `acceptance_command` required.
  - `hidden_oracle_command` optional, default empty string.
  - `patch_budget` optional, default finite integer.
  - `gap_policy_profile` optional, default `standard`.
- The first executable step is `kind: planner`, not a static implementation
  task.
- The planner step names the roles the planner must create dynamically:
  worker/builder, verifier, gap planner, and invariant gate/check.
- The planner step context tells the planner to mutate the graph only through
  `submit_graph_patch` and to use the DG-1.3 planner packet fields.
- The routine must not include static worker/verifier tasks for the feature
  implementation path. Any later work must be created by accepted graph
  patches.

Keep `step_context` compact. It is injected into prompts and should not contain
long transcripts or broad documentation dumps.

### 2. Compile/Load Tests

Add focused tests proving the skeleton is operationally seedable:

- The routine loads from disk through the normal routine loader.
- `execution_mode` is `graph`.
- The routine has a planner step as its first executable step.
- Compiling the routine creates:
  - `root`;
  - `routine-snapshot`;
  - exactly one initial generic planner node for the planner step.
- The compiled graph does not pre-seed feature worker or verifier nodes.
- The planner node has graph-write authority, `graph_patch` output,
  `completion` output, and a routine snapshot input binding.
- The root node records the configured planner generation budget.

Prefer adding to `tests/integration/test_graph_routine_compile.py` if that file
already covers routine compilation from disk. Otherwise add the narrowest new
integration test file. Unit tests must not start the HTTP layer.

### 3. Optional Smoke Evidence

If the orchestrator server is available, create a run from
`dynamic-graph-feature` with a tiny local feature spec and confirm via graph API
that the seeded graph begins with a planner node and no static feature
worker/verifier nodes.

This smoke evidence is useful but not required if the compile/load tests prove
the same behavior and the server is unavailable.

## Required Tests

Run and record:

```bash
uv run pytest tests/integration/test_graph_routine_compile.py -q
uv run ruff check routines/dynamic-graph-feature tests/integration/test_graph_routine_compile.py
uv run pyright src/orchestrator/config src/orchestrator/graph
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/integration/test_graph_routine_compile.py
```

## Done When

1. `routines/dynamic-graph-feature/routine.yaml` exists and validates through
   the normal routine loader.
2. Creating/compiling the routine seeds a planner chain, not a static
   worker/verifier-only graph.
3. The planner head has explicit graph-write authority and patch/completion
   outputs.
4. The routine declares the required dynamic feature inputs with safe defaults
   for optional values.
5. No source behavior beyond routine configuration and focused tests is changed
   unless needed to fix a directly observed routine-load/compile defect.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-2.1 only introduces the routine skeleton and focused tests.
- The skeleton is enough for DG-2.2 to add reusable horizon region templates.
- The routine does not smuggle a static task list under the dynamic feature
  name.
- The planner context preserves DG-1.3's fenced mutation contract.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch permissions beyond `patch_validator.py`.
- Do not append graph events outside `GraphController.handle_command`.

## Validation Outcome - 2026-06-15

Status: accepted by independent manager validation after the Codex-backed graph
run was paused during auto-verification.

Orchestrator evidence:

- Run `4944cd08-bf5d-403b-bcbc-ce18fd895edf`, worktree
  `/Users/peter/code/task-world/worktrees/r265`, runner `codex_server` with
  `gpt-5.3-codex-spark`.
- The run was created from `routine_embedded` and seeded with this slice spec
  because the registered source branch did not include current durable docs.
- The Codex builder submitted the routine/test changes. A subsequent graph
  auto-verify `no_mocks` check node entered a read-heavy loop; the run was
  manually paused to stop token spend. Accepted output is therefore based on
  manager validation, not a completed graph verifier grade.

Accepted DG-2.1 files:

- `routines/dynamic-graph-feature/routine.yaml`
- `tests/integration/test_graph_routine_compile.py`

Verified behavior:

- `dynamic-graph-feature` loads through `load_routine_from_path`.
- The routine declares `execution_mode: graph`, finite
  `planner_generation_budget`, required `feature_spec_path` and
  `acceptance_command` inputs, and optional `hidden_oracle_command`,
  `patch_budget`, and `gap_policy_profile` defaults.
- The only initial executable step is `kind: planner`; it has no static feature
  tasks and preserves the fenced `submit_graph_patch` mutation contract.
- Compiling the routine seeds `root`, `routine-snapshot`, and one generic
  planner node with graph-write authority, `graph_patch` and `completion`
  outputs, and a routine-snapshot input binding.
- The initial compiled graph has no pre-seeded feature worker or verifier
  nodes.

Validation commands:

```bash
uv run pytest tests/integration/test_graph_routine_compile.py -q
# 35 passed in 5.98s

uv run ruff check routines/dynamic-graph-feature tests/integration/test_graph_routine_compile.py
# All checks passed.

uv run pyright src/orchestrator/config src/orchestrator/graph
# 0 errors, 0 warnings, 0 informations

rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/integration/test_graph_routine_compile.py
# no matches
```

Remaining risk:

- The dynamic feature routine only seeds the planner head. DG-2.2 must add
  reusable horizon region templates so planners can instantiate standard
  discovery, implementation, verification, gap-analysis, corrective-work, and
  final invariant regions through accepted graph patches.
- Graph-mode auto-verify/check nodes still need a control-plane fix; this slice
  was accepted by independent validation after pausing a read-heavy check loop.
