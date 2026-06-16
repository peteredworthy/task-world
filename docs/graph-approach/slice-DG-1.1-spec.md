# Slice DG-1.1 - Planner Graph Packet

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-1, Slice DG-1.1.
- `docs/graph-approach/dynamic-graph-baseline.md` - accepted DG-0.1 baseline and known gaps.
- `docs/graph-approach/slice-DG-0.2-spec.md` - accepted dynamic metric instrumentation and remaining verifier-runner risk.
- `src/orchestrator/graph_runtime/dispatch.py` - current outbox-to-agent bridge and planner prompt construction.
- `src/orchestrator/graph/projections.py` - existing pure graph projection fields.
- `src/orchestrator/graph/patch_validator.py` - allowed planner operations and patch validation boundary.
- Existing planner tests in `tests/unit/test_graph_planner.py`, `tests/unit/test_patch_validator.py`, and `tests/integration/test_graph_planner_flow.py`.

## Scope

Create a compact, structured planner graph packet and use it when dispatching graph planner nodes. This slice is prompt/packet shaping only. It must not change graph scheduling, graph mutation semantics, database schema, API routes, runner behavior, file-state policy, or source-control behavior.

Expected code surface:

- `src/orchestrator/graph_runtime/dispatch.py`
- focused tests under `tests/unit/` and, if needed, one narrow integration test under `tests/integration/`

Adding a small helper module under `src/orchestrator/graph_runtime/` is acceptable if it keeps dispatch readable. Do not put IO in `src/orchestrator/graph/`; pure graph kernel modules must remain IO-free.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-1.1",
    "spec_path": "docs/graph-approach/slice-DG-1.1-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

If that exact model is unavailable, choose an available Codex model. Do not use Claude-backed runners.

Because DG-0.2 exposed a stale-docs worktree risk, the manager may use `routine_embedded` to carry this spec into the run. That does not change the implementation requirements.

## What To Build

### 1. Planner Packet Builder

Add a deterministic packet builder for planner nodes. It should accept the current graph events or projection plus the dispatch context facts already available in `GraphDispatchExecutor._build_dispatch_context`.

The packet must include at least:

- `run_id`
- `node_id`
- `node_kind`
- `role`
- current graph position
- active intent or planner title/context
- planner generation index and planner generation budget
- requirement versions or bound requirement text available to the node
- accepted evidence records bound to the planner, including file-state, region summary, outstanding failures, and session carryover when present
- open proposals, patch rejections, or outstanding failure facts visible from existing events
- current frontier, including ready nodes and blocked/deferred nodes when derivable from existing events/projection
- allowed planner patch operations
- valid patch JSON examples that match `PatchEnvelope` and the current planner op allow-list
- explicit instruction that proposed graph changes must be submitted as graph patches rather than made directly in source files

Use stable JSON-compatible shapes and deterministic ordering. Unknown events must not crash packet building.

### 2. Planner Prompt Integration

Update planner node prompt construction so `context.node_kind == "planner"` receives:

- a short planner instruction block;
- the serialized planner graph packet;
- valid patch JSON examples;
- a reminder of the node authority and the source-change boundary.

Existing worker, verifier, and check prompt behavior must remain unchanged except for harmless refactoring needed to share helpers.

### 3. Test Coverage

Add focused tests with hand-written fixtures only. Do not use `patch`, `MagicMock`, pytest `monkeypatch`, network calls, TestClient, or direct database edits.

At minimum:

1. Unit test packet shaping for a planner node with:
   - planner generation budget and current generation;
   - bound requirements;
   - ready and deferred/blocked node facts;
   - accepted evidence records;
   - a rejected planner patch reason;
   - allowed planner op names and JSON examples.
2. Unit test deterministic behavior:
   - event order noise does not change sorted packet lists where ordering is not semantic;
   - unknown events are ignored.
3. Unit test prompt routing:
   - planner prompts include the packet and patch-submission instructions;
   - worker/verifier prompts retain their current essential content.
4. Integration-style test only if needed to prove dispatch wiring:
   - construct a real `GraphDispatchContext` or controller/dispatch path with hand-written fakes and assert the captured `ExecutionContext.prompt` contains the planner packet.

## Acceptance Commands

Run and record:

```bash
uv run pytest tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/unit/test_graph_planner.py tests/unit/test_patch_validator.py -q
uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py -q
uv run ruff check src/orchestrator/graph_runtime tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py
uv run pyright src/orchestrator/graph_runtime
```

If the final test file names differ, run the narrowest equivalent command and record the exact command.

## Done When

1. Planner node prompts carry a structured packet with graph state, evidence, budget, frontier, and allowed patch operations.
2. Planner patch examples match the existing patch validation boundary.
3. Non-planner prompts are not behaviorally changed.
4. Tests prove packet shape, deterministic ordering, unknown-event tolerance, and prompt routing.
5. No graph scheduler, kernel command, patch validation, API, DB, or runner behavior is changed.
6. The implementation does not claim dynamic graph operational readiness.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-1.1 only makes planner context visible; it does not implement autonomous dynamic planning.
- The packet contains enough state for a future planner to select the next verifiable chunk without full transcript context.
- The packet is compact and durable: it references graph facts, not conversational history.
- The implementation respects module boundaries and keeps pure graph logic IO-free.
- The remaining Codex verifier tool issue is recorded separately if it blocks orchestrator grading.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not change graph runtime scheduling or mutation semantics as part of this slice.

## Validation Outcome

- Status: accepted by orchestrator verifier and independent validation on
  2026-06-14.
- Codex-backed orchestration:
  - Embedded graph run `dba654d3-5213-48eb-8af7-6fbec0adf7ad`.
  - The first verifier dispatch failed with the known `codex_server` /
    `gpt-5.3-codex-spark` unsupported `image_generation` tool error.
  - The automatic retry ran checks, graded every requirement A, and completed
    the run.
- Accepted implementation surface:
  - `src/orchestrator/graph/__init__.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `tests/unit/test_graph_planner_packet.py`
- Independent validation changes before promotion:
  - Exported `PLANNER_OPS` through `orchestrator.graph` and imported it through
    that public API.
  - Moved accepted patches from misleading `open_planner_proposals` into
    `accepted_planner_patches`.
  - Added `allowed_patch_operations` and `patch_examples` directly to the
    planner packet, not only to surrounding prompt text.
- Acceptance commands run in both the run worktree and main checkout:

```bash
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_graph_planner.py tests/unit/test_patch_validator.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py -q
uv run ruff check src/orchestrator/graph_runtime src/orchestrator/graph/__init__.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_planner_packet.py
```

- Results:
  - Targeted combined pytest: `31 passed`.
  - Ruff: `All checks passed!`.
  - Pyright: `0 errors, 0 warnings, 0 informations`.
  - No-mocks scan: no hits.

Remaining risk: DG-1.1 makes planner graph context visible, but planner nodes
still cannot submit graph patches through a fenced callback/tool path. That is
the next selected slice, DG-1.2.
