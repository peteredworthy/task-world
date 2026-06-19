# Slice DG-0.1 — Dynamic Graph Baseline Matrix

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` — Phase DG-0.
- `docs/graph-approach/true-comparison-plan.md` — dynamic comparison target.
- `docs/graph-approach/mind-the-gap-skill.md` — baseline-first rule and durable
  evidence discipline.
- Current implementation packages:
  - `src/orchestrator/graph/`
  - `src/orchestrator/graph_runtime/`
  - `src/orchestrator/workflow/graph_driver.py`
  - `src/orchestrator/api/routers/graph.py`
  - `src/orchestrator/runners/agents/codex/`

## Scope

Create a durable baseline for dynamic graph operational work. This slice should
not implement planner-agent behavior. It records what is currently passing,
what is missing, and which checks must remain green while later slices modify
the system.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-0.1",
    "spec_path": "docs/graph-approach/slice-DG-0.1-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

If that exact model is unavailable, choose an available Codex model. Do not use
Claude-backed runners for this slice.

## What To Build

### 1. Baseline Evidence Document

Create `docs/graph-approach/dynamic-graph-baseline.md`.

It must include:

- date/time of baseline;
- command list;
- pass/fail status for each command;
- relevant summary output;
- known failures or skipped checks;
- interpretation: which gaps block full dynamic graph operation and which are
  observability-only;
- next recommended slice from `dynamic-graph-operational-plan.md`.

### 2. Baseline Commands

Run and record, at minimum:

```bash
uv run pytest tests/unit/test_graph_*.py tests/unit/test_scheduler.py tests/unit/test_callbacks.py tests/unit/test_patch_validator.py -q
uv run pytest tests/integration/test_graph_run_driver.py tests/integration/test_graph_default_carrier.py tests/integration/test_graph_run_start_routing.py -q
uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py tests/integration/test_graph_parent_child_flow.py -q
uv run pytest tests/integration/test_graph_api.py tests/integration/test_graph_scheduler_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_file_state_report_api.py -q
uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_token_capture.py tests/unit/test_compare_carriers.py -q
uv run ruff check src tests
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime src/orchestrator/workflow/graph_driver.py src/orchestrator/runners/agents/codex
```

If a command is too broad or fails for an environmental reason, record the
reason and run the narrowest meaningful replacement.

### 3. Dynamic Gap Inventory

The baseline document must explicitly classify these current gaps:

- planner-agent patch submission path;
- planner graph packet and prompt contract;
- dynamic feature routine;
- horizon region templates;
- gap planner semantics;
- requirement/evidence revision policy;
- final invariant gate;
- graph verifier grades in `/activity`;
- comparison metric export for dynamic graph facts;
- true-comparison Arm C Mind-the-gap fidelity requirements;
- true-comparison Arm E dynamic graph readiness.

Each gap should be marked:

- `missing`;
- `partial`;
- `implemented but unproven`;
- `verified`.

### 4. No Behavioral Changes

This slice is documentation and measurement only. It must not alter graph
runtime behavior, compiler behavior, scheduler behavior, runner behavior, API
semantics, or UI behavior.

## Done When

1. `docs/graph-approach/dynamic-graph-baseline.md` exists.
2. Baseline commands and outcomes are recorded with enough detail to compare
   future slices.
3. Dynamic operational gaps are classified using the four-state vocabulary
   above.
4. The next recommended implementation slice is named and justified.
5. No source/runtime behavior changes are made.
6. Any failing check is recorded honestly; no failing check is hidden or
   dismissed.

## Mind-the-gap Validation Requirements

The validator must not simply check that the document exists. It must confirm:

- the baseline was established before implementation slices begin;
- the listed commands cover kernel, runtime, API, planner-flow, codex usage, and
  comparison metrics;
- failure classifications are specific enough for the next planner/gap-finder;
- the document does not claim dynamic graph operational status prematurely.

## Hard Constraints

- No mocks or monkeypatching added.
- No DB deletion or direct `orchestrator.db` edits.
- No source behavior changes.
- No main worktree git mutation.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
