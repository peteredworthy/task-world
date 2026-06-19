# Slice DG-3.3 - Final Invariant Gate

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-3,
  Slice DG-3.3.
- `docs/graph-approach/mind-the-gap-skill.md`
- `docs/graph-approach/slice-DG-3.1-spec.md`
- `docs/graph-approach/slice-DG-3.2-spec.md`
- `src/orchestrator/graph/projections.py` - pure graph projection state and
  `project_run_state`.
- `src/orchestrator/graph/commands.py` - graph lifecycle and command
  application.
- `src/orchestrator/graph_runtime/dispatch.py` - planner packet context only.
- Existing tests in `tests/unit/test_graph_projections.py`,
  `tests/unit/test_graph_commands.py`, `tests/unit/test_graph_planner.py`,
  `tests/unit/test_graph_planner_packet.py`, and
  `tests/integration/test_graph_planner_flow.py`.

## Scope

Add the first graph-wide final invariant gate. A graph run must not project as
complete, and a lifecycle `complete` command must not be accepted, while any
final invariant blocker remains.

This is a graph-kernel behavior slice. It may add pure projection data/helpers
and graph command checks. It must not add API routes, UI panels, metrics export,
true-comparison behavior, new scheduler workers, or broad workflow-service
behavior.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-3.3",
    "spec_path": "docs/graph-approach/slice-DG-3.3-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.5"
  }
}
```

Use `gpt-5.5` because `gpt-5.3-codex-spark` is quota-limited. If `gpt-5.5`
is unavailable, inspect available Codex models and choose the best Codex option.
Do not use Claude-backed runners.

## What To Build

### 1. Pure Final Invariant Projection

Add a pure invariant projection/helper that returns deterministic blocker facts.
At minimum it must detect:

- open planner proposals that have not been accepted or rejected;
- suspect active regions or nodes when existing graph facts expose them;
- stale support evidence being the only support for an active requirement;
- unsupported active requirements from DG-3.2 freshness facts;
- active semantic/new-behavior requirement revisions that require explicit
  authority and have no authority-resolution fact;
- pending planner or gap-planner nodes;
- blocked must/expected requirement nodes where existing graph facts expose
  priority or requirement status.

Keep the output compact and deterministic, for example:

```python
{
    "ready": False,
    "blockers": [
        {"kind": "stale_support_evidence", "requirement_id": "...", "support_ids": [...]}
    ],
}
```

Use existing event names where possible. If new event names are needed for
authority resolution or invariant decisions, keep them inside the graph kernel
and route them through `GraphController.handle_command` / `apply_command`; do
not append graph events directly outside the controller.

### 2. Completion Blocking

Update graph completion logic so final completion is blocked when invariant
blockers exist.

Required behavior:

- `project_run_state(events)` must remain `active` when lifecycle state is
  completed but final invariant blockers remain.
- `apply_command(..., "complete", ...)` must reject completion while final
  invariant blockers remain and include a compact blocker summary in the
  rejection payload.
- Existing accepted graph runs with no blockers must still complete.

Do not change API response shapes or UI behavior in this slice.

### 3. Planner Packet Compatibility

If the invariant helper creates compact facts useful to planners, expose only a
small deterministic summary in the existing planner packet. Preserve the
DG-3.1 planner mutation contract and DG-3.2 freshness packet.

### 4. Tests

Add or extend focused tests that prove:

- no blockers means existing graph completion behavior is preserved;
- a pending planner or gap planner prevents projected completion;
- open proposals prevent projected completion;
- stale-only or unsupported active requirement evidence prevents projected
  completion;
- unresolved authority-required semantic/new-behavior revisions prevent
  projected completion;
- graph `complete` command is rejected with blocker evidence when blockers are
  present;
- existing planner packet and patch tests still pass.

Prefer unit tests. Use integration only where an existing graph planner flow is
already the narrowest coverage.

## Required Tests

Run and record:

```bash
uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/integration/test_graph_planner_flow.py -q
uv run ruff check src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py
```

## Done When

1. Final invariant blockers are projected from pure graph event state.
2. Graph run projection cannot reach completed while blockers remain.
3. Graph lifecycle `complete` command is rejected while blockers remain.
4. Clean graphs with no blockers still complete.
5. The result remains scoped away from API, UI, metrics export, and true
   comparison behavior.

## Mind-the-gap Validation Requirements

The validator must confirm:

- completion blocking uses pure graph facts and does not rely on live DB/API
  reads;
- stale or missing support evidence from DG-3.2 can block final completion;
- semantic/new-behavior revisions require explicit authority before final
  completion;
- existing planner patch and planner packet behavior remains compatible;
- the result is sufficient for later observability slices to explain why a run
  is not complete.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not add API/UI/metrics/true-comparison behavior.
- Do not append graph events outside `GraphController.handle_command`.
