# Slice DG-4.1 - Activity Events For Graph Grades And Patches

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-4,
  Slice DG-4.1.
- `docs/graph-approach/mind-the-gap-skill.md`
- `docs/graph-approach/slice-DG-3.1-spec.md`
- `docs/graph-approach/slice-DG-3.2-spec.md`
- `docs/graph-approach/slice-DG-3.3-spec.md`
- `src/orchestrator/api/routers/runs.py` - `/api/runs/{run_id}/activity`.
- `src/orchestrator/db/access/event_store_v2.py` - activity rows from durable
  events.
- `src/orchestrator/graph/projections.py` - graph projections and final
  invariant blockers.
- Existing activity tests in `tests/integration/test_api_activity.py` and graph
  activity tests in `tests/integration/test_graph_activity_stream.py`.

## Scope

Make graph-mode runs inspectable through the existing `/activity` endpoint
without reading raw graph events manually. This slice should expose compact,
human-useful activity entries for graph verifier grades, planner patch
accepted/rejected decisions, gap findings where existing graph facts expose
them, and final invariant blockers.

This is an observability slice only. Do not change graph scheduling,
completion-blocking, planner patch validation, API route shapes, UI panels,
metrics export, or true-comparison behavior.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-4.1",
    "spec_path": "docs/graph-approach/slice-DG-4.1-spec.md"
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

### 1. Activity Projection For Patch Decisions

Ensure `/api/runs/{run_id}/activity` returns compact graph activity rows for:

- accepted graph patches;
- rejected graph patches;
- rejected patch commands when malformed or stale;
- the proposer/planner node id, patch id, actor role, rejection reason, and
  successor planner ids where present.

Use the existing activity response shape. Add enrichment or event mapping only;
do not create a new endpoint.

### 2. Activity Projection For Graph Verifier Grades

Expose graph verifier grade summaries in activity when existing graph events
record verifier results, requirement grades, or final invariant blockers.
Prefer compact facts such as candidate id, task region id, grade/pass status,
and failing requirement ids. Do not dump full prompts or raw transcripts.

### 3. Gap Findings And Invariant Blockers

Where existing graph facts expose gap findings or final invariant blockers,
surface concise activity entries so an operator can answer why a graph run is
not complete. At minimum, final invariant blocker events/projections from DG-3.3
must be visible through activity when durable events contain the relevant facts.

### 4. Tests

Add or extend focused integration tests that prove:

- `/activity` includes graph patch accepted and rejected summaries;
- `/activity` includes graph verifier/final-invariant blocker summaries where
  existing graph events expose them;
- legacy non-graph activity behavior is unchanged;
- activity pagination and filtering still work;
- no raw prompt transcript or large graph payload is emitted for these summaries.

Prefer extending `tests/integration/test_graph_activity_stream.py` or
`tests/integration/test_api_activity.py` if that is the narrowest route.

## Required Tests

Run and record:

```bash
uv run pytest tests/integration/test_graph_activity_stream.py tests/integration/test_api_activity.py -q
uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q
uv run ruff check src/orchestrator/api src/orchestrator/db/access src/orchestrator/graph tests/integration/test_graph_activity_stream.py tests/integration/test_api_activity.py tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py
uv run pyright src/orchestrator/api src/orchestrator/db/access src/orchestrator/graph
```

Also run a targeted no-mocks scan over any new or modified tests:

```bash
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/integration/test_graph_activity_stream.py tests/integration/test_api_activity.py tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py
```

## Done When

1. Graph patch accepted/rejected decisions are visible from `/activity`.
2. Graph verifier grade or final invariant blocker facts are visible from
   `/activity` where existing graph events expose them.
3. Activity summaries are compact and do not include full prompts/transcripts.
4. Legacy activity behavior, pagination, and filtering remain compatible.
5. The result remains scoped away from UI panels, metric export, scheduling, and
   true-comparison behavior.

## Mind-the-gap Validation Requirements

The validator must confirm:

- operators can inspect `/activity` to understand patch decisions and invariant
  blockers without raw graph-event spelunking;
- no behavioral graph policy changed while adding observability;
- activity output is deterministic and paginates with existing cursor behavior;
- the result is sufficient input for DG-4.2 UI panels and DG-4.3 metric export.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not add new routes or UI.
- Do not change graph scheduling, patch validation, or completion policy.
