# Slice DG-3.1 - Gap Planner Node Semantics

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-3,
  Slice DG-3.1.
- `docs/graph-approach/mind-the-gap-skill.md`
- `docs/graph-approach/slice-DG-2.2-spec.md`
- `src/orchestrator/graph_runtime/dispatch.py` - planner/gap-planner prompt,
  packet, and graph patch callback routing.
- `src/orchestrator/graph_runtime/horizon_templates.py` - corrective-work and
  final-invariant templates.
- `src/orchestrator/graph/patch_validator.py` - actor role patch permissions.
- `src/orchestrator/graph/commands.py` - accepted/rejected graph patch events.
- `tests/unit/test_graph_planner_packet.py`
- `tests/unit/test_graph_dispatch_on_output.py`
- `tests/unit/test_patch_validator.py`
- `tests/integration/test_graph_planner_flow.py`

## Scope

Make `gap_planner` a first-class graph planner role for native Mind-the-gap
loops. This slice only gives gap planner nodes a validated patch submission
path and a compact gap-analysis prompt/packet contract.

This is not a final invariant, requirement revision, API, UI, metrics export,
or true-comparison slice. Do not implement graph-wide completion blocking,
validation-strengthening authority, or activity/UI rendering here.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-3.1",
    "spec_path": "docs/graph-approach/slice-DG-3.1-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.5"
  }
}
```

Use `gpt-5.5` because `gpt-5.3-codex-spark` is currently quota-limited. If
`gpt-5.5` is unavailable, inspect the Codex runner model options and choose the
best available Codex model. Do not use Claude-backed runners.

## What To Build

### 1. Gap Planner Patch Authority

Allow nodes with `kind: planner` and `role: gap_planner` to use the same fenced
`submit_graph_patch` callback path as generic planners, with stricter semantics:

- gap planners may create corrective worker/verifier regions using existing
  `PLANNER_OPS`;
- gap planners may submit an accepted no-op patch to record "no corrective graph
  mutation needed";
- gap planners must not create generic successor planner nodes with
  `role: planner`;
- gap planners must not broaden patch operation permissions beyond existing
  planner operations.

Plain `submit` from a gap planner should require at least one accepted or
rejected `submit_graph_patch` attempt, matching the generic planner discipline.

### 2. Gap Planner Prompt/Packet Contract

Generic planner prompts stay intact, but gap planners should get explicit
Mind-the-gap instructions:

- inspect bound requirements, accepted evidence, verifier/check results,
  outstanding failures, stale or missing support evidence, and the original
  active intent;
- decide between no-gap, corrective-work patch, validation-strengthening
  proposal placeholder, or human/policy escalation placeholder;
- use `corrective_work_region` from `horizon_region_templates` for corrective
  work;
- do not edit repository files from the gap planner node.

Keep the packet compact. It may reuse `horizon_region_templates` and add a small
`gap_analysis_contract` field; do not include long transcripts.

### 3. Tests

Add or extend focused tests that prove:

- `gap_planner` receives a graph patch callback and cannot plain-submit before a
  patch attempt;
- `gap_planner` patches using corrective worker/verifier ops validate and are
  accepted;
- `gap_planner` no-op patches validate and are accepted;
- `gap_planner` attempts to create a generic `role: planner` successor are
  rejected;
- prompt text for gap planners names the gap-analysis contract and
  `corrective_work_region`;
- worker and verifier prompts still do not receive planner/gap-planner patch
  instructions.

Prefer unit tests unless an existing integration flow is the narrower fit.

## Required Tests

Run and record:

```bash
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py -q
uv run pytest tests/integration/test_graph_planner_flow.py -q
uv run ruff check src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py tests/integration/test_graph_planner_flow.py
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py tests/integration/test_graph_planner_flow.py
```

## Done When

1. Gap planner nodes can submit graph patches through the fenced callback path.
2. Corrective-work and no-op/no-gap gap planner patches are accepted through the
   normal controller validation path.
3. Gap planners cannot create generic successor planner nodes.
4. Gap planner prompt/packet text is compact, Mind-the-gap specific, and points
   at `corrective_work_region`.
5. Non-planner prompts remain free of planner/gap-planner patch instructions.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-3.1 only gives gap planner nodes patch semantics and prompt/packet
  guidance;
- final invariant gate behavior and requirement/evidence revision policy remain
  untouched;
- the result is sufficient for DG-3.2 to add requirement/evidence revision
  policy and for DG-3.3 to block final completion on graph-wide invariants.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch operations beyond `patch_validator.py`.
- Do not append graph events outside `GraphController.handle_command`.
