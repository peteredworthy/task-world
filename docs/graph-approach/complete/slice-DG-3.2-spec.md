# Slice DG-3.2 - Requirement/Evidence Revision Policy

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-3,
  Slice DG-3.2.
- `docs/graph-approach/mind-the-gap-skill.md`
- `docs/graph-approach/slice-DG-3.1-spec.md`
- `src/orchestrator/graph/projections.py` - pure graph projection state.
- `src/orchestrator/graph/patch_validator.py` - stale-patch invalidation
  inputs and patch role permissions.
- `src/orchestrator/graph/commands.py` - graph patch command application.
- `src/orchestrator/graph_runtime/dispatch.py` - planner packet evidence
  fields.
- Existing tests in `tests/unit/test_graph_projections.py`,
  `tests/unit/test_patch_validator.py`, `tests/unit/test_graph_commands.py`,
  and `tests/unit/test_graph_planner_packet.py`.

## Scope

Make requirement/evidence freshness explicit enough for gap planners and later
final invariant checks to reason about stale support. This slice should add
pure graph-kernel state and helper/projector behavior only.

This is not a final invariant gate, scheduler completion-blocking, API, UI,
metrics export, or true-comparison slice. Do not change run completion behavior
or workflow-service behavior here.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-3.2",
    "spec_path": "docs/graph-approach/slice-DG-3.2-spec.md"
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

### 1. Requirement Revision State

Add first-class projected state for active requirement versions. The graph should
be able to distinguish:

- the original requirement node or requirement id;
- its active revision/version;
- whether a later `requirement_amended`-style event supersedes earlier support;
- whether the change is validation-strengthening or semantic/new behavior.

Use existing event names if practical. If adding new command/payload support,
keep it inside the graph kernel and route mutations through
`GraphController.handle_command`; do not append events directly outside the
controller.

### 2. Evidence Freshness

Add pure projection/helper behavior that can answer whether accepted support
evidence is stale for the active requirement version. At minimum:

- accepted evidence bound before a validation-strengthening requirement revision
  must not count as fresh support for that active requirement;
- accepted evidence bound after the active requirement version can count as
  fresh when its selector/record kind still matches;
- existing file-state supersession and compromised-record semantics must remain
  intact.

Expose the result to the planner packet compactly, for example under
`evidence` as stale/missing support facts or under a dedicated requirement
freshness field. Keep the packet deterministic and small.

### 3. Authority Policy Shape

Represent the distinction between validation-strengthening and semantic/new
behavior changes in pure data:

- validation-strengthening of an active must requirement may be recorded by graph
  policy;
- semantic/new behavior changes must be marked as requiring explicit authority.

This slice only records and projects that policy distinction. It must not add
human approval UI or enforce final run completion.

### 4. Tests

Add or extend focused tests that prove:

- requirement revision/version state is projected deterministically;
- validation-strengthening revisions invalidate earlier support evidence;
- semantic/new behavior revisions are projected as requiring explicit authority;
- planner packets expose stale or missing support facts compactly;
- existing patch staleness, planner packet, and graph command behavior remains
  compatible.

Prefer unit tests unless an existing integration test is clearly narrower.

## Required Tests

Run and record:

```bash
uv run pytest tests/unit/test_graph_projections.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/integration/test_graph_planner_flow.py -q
uv run ruff check src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_graph_projections.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_projections.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py
```

## Done When

1. Requirement revisions are represented in replayable graph state.
2. Fresh/stale support evidence for active requirement versions can be queried
   from pure projection data.
3. Validation-strengthening revisions invalidate older support evidence.
4. Semantic/new behavior revisions are marked as requiring explicit authority.
5. Planner packets expose compact freshness facts for gap planners.
6. Final invariant, API, UI, metrics, and true-comparison behavior remain out of
   scope.

## Mind-the-gap Validation Requirements

The validator must confirm:

- the implementation is pure graph/projection policy and does not change final
  completion behavior;
- stale evidence cannot satisfy an active revised requirement in the new helper
  or packet state;
- existing graph planner and patch tests still pass;
- the result is sufficient for DG-3.3 to block final completion on graph-wide
  invariants.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch operations beyond the minimum required for this
  revision policy.
- Do not append graph events outside `GraphController.handle_command`.
