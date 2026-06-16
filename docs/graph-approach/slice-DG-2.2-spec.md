# Slice DG-2.2 - Horizon Region Templates

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-2,
  Slice DG-2.2.
- `docs/graph-approach/slice-DG-2.1-spec.md` - accepted dynamic feature
  routine skeleton.
- `routines/dynamic-graph-feature/routine.yaml`
- `src/orchestrator/graph_runtime/dispatch.py` - planner packet and prompt
  construction.
- `src/orchestrator/graph/patch_validator.py` - allowed planner patch
  operations and validation rules.
- `tests/unit/test_graph_planner_packet.py`
- `tests/integration/test_graph_routine_compile.py`

## Scope

Give dynamic planners a compact, deterministic catalog of standard horizon
region patch templates. The catalog must be visible in planner packets/prompts
and must map directly to currently accepted graph patch operations.

This is not a scheduler, API, UI, database, or final-invariant slice. Do not
add new patch operations or broaden planner permissions. Do not implement gap
planner semantics or final completion blocking here; those are DG-3 slices.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-2.2",
    "spec_path": "docs/graph-approach/slice-DG-2.2-spec.md"
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

### 1. Horizon Template Catalog

Add a small graph-runtime template catalog, for example
`src/orchestrator/graph_runtime/horizon_templates.py`, with a public function
that returns compact template records.

Required template purposes:

- `discovery_region`
- `implementation_region`
- `validation_region`
- `gap_analysis_region`
- `corrective_work_region`
- `final_invariant_region`

Each template record must include:

- `purpose`
- `description`
- `ops`
- `expected_successor_readiness`

Each `ops` list must use only currently allowed planner operations from
`PLANNER_OPS`, primarily `create_node` and `create_edge`.

The templates must be compact and deterministic. Use placeholder-like IDs only
where the planner must substitute concrete IDs. Do not include long prose,
transcripts, or full routine docs.

### 2. Planner Packet/Prompt Exposure

Expose the catalog to generic planner sessions:

- Add a planner packet field such as `horizon_region_templates`.
- Mention the field in the planner prompt contract.
- Keep existing DG-1.3 `patch_examples` for small examples, but make the
  horizon catalog the standard set of region-building templates.
- Ensure worker/verifier prompts still do not receive planner patch
  instructions or horizon templates.

### 3. Template Validity Tests

Add focused tests that:

- assert all six required template purposes are present;
- assert every operation is in `PLANNER_OPS`;
- instantiate at least the implementation/validation/gap/final templates with
  concrete IDs and validate them through `validate_patch` where possible;
- assert planner packets include `horizon_region_templates`;
- assert planner prompt text names the six template purposes compactly;
- assert workers/verifiers do not receive horizon template prompt text.

Prefer adding a new unit test file for the template catalog and extending
`tests/unit/test_graph_planner_packet.py` for packet/prompt exposure.

### 4. Dynamic Routine Context

Update `routines/dynamic-graph-feature/routine.yaml` only if needed to point
the planner at the standard horizon templates. Keep `step_context` short.

## Required Tests

Run and record:

```bash
uv run pytest tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/integration/test_graph_routine_compile.py -q
uv run ruff check src/orchestrator/graph_runtime tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py routines/dynamic-graph-feature
uv run pyright src/orchestrator/graph_runtime src/orchestrator/graph
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py
```

## Done When

1. The six standard horizon templates exist in a runtime-accessible catalog.
2. Generic planner packets/prompts expose the catalog compactly.
3. Template operations stay inside existing `PLANNER_OPS`; no permission
   broadening occurs.
4. Tests prove the dynamic feature routine still seeds a planner head and that
   planner prompts can see the horizon templates.
5. Worker and verifier prompts remain free of planner horizon-template
   instructions.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-2.2 only adds region templates and packet/prompt exposure.
- Template readiness is explicit through graph edges/records or documented
  expected readiness, not implicit static sequence.
- The result is sufficient for DG-3.1 to give gap planner nodes real semantics.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch permissions beyond `patch_validator.py`.
- Do not append graph events outside `GraphController.handle_command`.

## Result

Accepted on 2026-06-15 from Codex-backed graph run
`e3e47df2-a803-45fb-8f66-51132e997c18` and run worktree
`/Users/peter/code/task-world/worktrees/r266`.

Accepted files:

- `src/orchestrator/graph_runtime/horizon_templates.py`
- `src/orchestrator/graph_runtime/__init__.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- `routines/dynamic-graph-feature/routine.yaml`
- `tests/unit/test_graph_horizon_templates.py`
- `tests/unit/test_graph_planner_packet.py`
- `tests/integration/test_graph_routine_compile.py`

Verified evidence in the run worktree and main checkout:

```bash
uv run pytest tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/integration/test_graph_routine_compile.py -q
uv run ruff check src/orchestrator/graph_runtime tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py routines/dynamic-graph-feature
uv run pyright src/orchestrator/graph_runtime src/orchestrator/graph
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py
```

The `rg` no-mocks scan returned no matches. The orchestrator run itself paused
as `graph_blocked` after repeated Codex server worker failures caused by a
`gpt-5.3-codex-spark` usage limit, so acceptance comes from independent
validation rather than a completed graph verifier grade.
