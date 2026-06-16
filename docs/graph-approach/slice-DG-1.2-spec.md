# Slice DG-1.2 - Fenced Planner Patch Tool

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-1, Slice DG-1.2.
- `docs/graph-approach/slice-DG-1.1-spec.md` - accepted planner graph packet and prompt contract.
- `src/orchestrator/graph_runtime/dispatch.py` - graph dispatch, callback submission, and planner prompt packet.
- `src/orchestrator/graph/commands.py` - `submit_patch` command and callback boundary.
- `src/orchestrator/graph/patch_validator.py` - allowed patch operations, role permissions, stale read-set validation.
- `src/orchestrator/runners/types.py` - runner callback protocol types.
- `src/orchestrator/runners/agents/codex/common.py` and `src/orchestrator/runners/agents/codex/agent.py` - Codex dynamic tool specs and tool-call routing.
- Existing tests:
  - `tests/unit/test_codex_server_transport.py`
  - `tests/unit/test_codex_server_common.py`
  - `tests/unit/test_graph_commands.py`
  - `tests/unit/test_graph_planner_packet.py`
  - `tests/integration/test_graph_planner_flow.py`
  - `tests/integration/test_graph_runner_e2e.py`

## Scope

Add a fenced graph-patch submission path for graph planner nodes. This slice makes planner patch submission callable by a real Codex planner agent, while preserving the existing controller and patch validator as the only graph mutation authority.

Expected code surface:

- `src/orchestrator/runners/types.py`
- `src/orchestrator/runners/agents/codex/common.py`
- `src/orchestrator/runners/agents/codex/agent.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- `src/orchestrator/graph/commands.py` only for event payload fidelity needed by accepted/rejected patch evidence
- focused unit/integration tests

Do not change database schema, API routes, UI behavior, scheduler semantics, patch operation validation rules, or graph compile behavior.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-1.2",
    "spec_path": "docs/graph-approach/slice-DG-1.2-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

The manager may use `routine_embedded` to avoid stale-docs worktree drift. Do not use Claude-backed runners.

## What To Build

### 1. Payload-Carrying Graph Patch Callback

Add a typed callback path that lets a runner deliver one planner graph patch payload to the graph runtime. The callback must:

- accept a JSON-compatible patch payload matching `PatchEnvelope`;
- bind the current graph planner identity from dispatch context:
  - `run_id`;
  - `node_id` / `proposed_by_node_id`;
  - lease id and generation;
  - execution id;
  - base snapshot id;
  - observed graph position;
  - idempotency key or deterministic patch-call key;
- call `GraphController.handle_command(..., "submit_patch", ...)` rather than appending graph events directly;
- return actionable success/rejection text to the runner/tool caller;
- keep malformed, stale, unauthorized, and budget-exhausted submissions durable through existing command rejection or `graph_patch_rejected` events.

Do not mutate graph state from runner code or dispatch code except through `GraphController.handle_command`.

### 2. Planner-Only Codex Dynamic Tool

Add a Codex dynamic tool named `submit_graph_patch`.

Tool exposure rules:

- Expose it only for graph planner nodes. Do not expose it to ordinary workers or verifiers.
- The tool input schema must be explicit and bounded. It must accept either:
  - a top-level `patch` object with `patch_id`, `base_graph_position`, `ops`, and optional `rationale_record_id`; or
  - equivalent top-level fields that are normalized to a `PatchEnvelope`.
- The runner must route `submit_graph_patch` to the new graph patch callback.
- Calling `submit_graph_patch` without a graph patch callback registered must fail fast with a clear error.
- Disallowed tools must remain rejected by the existing allow-list logic.

### 3. Planner Submit Guard

Generic planner nodes must not be able to complete by calling plain `submit` without submitting at least one graph patch first.

Rules:

- For `context.node_kind == "planner"` and `role == "planner"`, plain `submit` before any accepted or rejected `submit_graph_patch` call should fail with feedback telling the planner to call `submit_graph_patch`.
- Preserve existing special planner roles already handled by `_output_records_for_submit`, such as `fan_out_reader` and `fan_out_join`.
- Ordinary worker and verifier `submit` behavior must remain unchanged.

### 4. Patch Event Fidelity

Accepted and rejected planner patch events must carry enough evidence for DG-1.1 packet history and DG-0.2 metrics:

- `patch_id`
- `proposed_by_node_id`
- `actor_role`
- `base_graph_position`
- rejection `reason` when rejected
- accepted successor planner ids where applicable

If existing `submit_patch` rejection events lack some of those fields, add them without changing the meaning of accepted/rejected validation.

## Required Tests

Use hand-written fakes only. Do not use `patch`, `MagicMock`, pytest `monkeypatch`, network calls, TestClient, or direct DB edits.

At minimum:

1. Codex dynamic tool spec test:
   - ordinary builder context does not expose `submit_graph_patch`;
   - graph planner context exposes `submit_graph_patch` with a bounded schema;
   - verifier context does not expose `submit_graph_patch`.
2. Codex tool routing test:
   - `submit_graph_patch` invokes the graph patch callback with normalized payload;
   - `submit_graph_patch` without a registered graph patch callback returns/fails with a clear error;
   - existing `submit`, `grade`, and disallowed-tool behavior remains covered.
3. Graph dispatch test:
   - planner `submit_graph_patch` callback calls `GraphController.handle_command("submit_patch", ...)` with dispatch identity and actor role `planner`;
   - plain planner `submit` without a prior patch is rejected for generic planner role;
   - special planner roles such as `fan_out_reader` and `fan_out_join` still submit normally.
4. Graph command tests:
   - valid planner patch creates `graph_patch_accepted` with proposer evidence;
   - stale or unauthorized planner patch creates durable rejection evidence with proposer and reason;
   - malformed patch is rejected without partial graph mutation.
5. Integration-style test:
   - a fake planner runner in the graph dispatch stack submits a patch through the new callback and the controller records accepted graph patch events.

## Acceptance Commands

Run and record:

```bash
uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py -q
uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q
uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q
uv run ruff check src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
uv run pyright src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime
```

If the final test file names differ, run the narrowest equivalent command and record the exact command.

## Done When

1. A graph planner Codex session can call `submit_graph_patch` and have that patch processed by `GraphController.handle_command("submit_patch", ...)`.
2. Valid planner patches produce accepted graph patch events and created nodes/edges.
3. Malformed, stale, and unauthorized patches produce durable rejection evidence without partial mutation.
4. Generic planner `submit` without a graph patch is rejected with actionable feedback; worker/verifier submit behavior is unchanged.
5. `submit_graph_patch` is not exposed to ordinary workers or verifiers.
6. Tests prove the runner tool spec, runner routing, graph dispatch callback, command events, and integration path.
7. No database schema, API route, UI, scheduler, or patch validation rule changes are made.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-1.2 implements only the fenced submission path; it does not build dynamic feature routines or horizon templates.
- The controller remains the only accepted graph mutation writer.
- Tool exposure is least-authority: planner-only.
- Rejection feedback is useful enough for a planner agent to repair malformed/stale patches.
- DG-1.2 plus DG-1.1 is sufficient for a controlled real planner run to attempt a patch in DG-1.3.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch permissions beyond `patch_validator.py`.
- Do not append graph events outside `GraphController.handle_command`.

## Validation Outcome - 2026-06-14

Status: accepted by independent manager validation after the Codex-backed run
blocked.

Orchestrator evidence:

- Run `40839c41-316c-4627-a494-1c06ab3c7ded`, worktree
  `/Users/peter/code/task-world/worktrees/r263`, runner `codex_server` with
  `gpt-5.3-codex-spark`.
- The run was paused manually after the Codex worker entered a long read-only
  loop and did not complete the slice. The stale worker process was stopped
  after pause. The accepted implementation was completed and validated in the
  run worktree, then promoted to the main checkout.

Accepted files:

- `src/orchestrator/runners/types.py`
- `src/orchestrator/runners/agents/codex/common.py`
- `src/orchestrator/runners/agents/codex/agent.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- `src/orchestrator/graph/commands.py`
- `tests/unit/test_codex_server_agent.py`
- `tests/unit/test_codex_server_common.py`
- `tests/unit/test_codex_server_transport.py`
- `tests/unit/test_graph_commands.py`
- `tests/unit/test_graph_dispatch_on_output.py`
- `tests/unit/test_graph_planner_packet.py`

Main-checkout validation:

```bash
uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py -q
# 127 passed in 5.62s

uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q
# 52 passed in 1.91s

uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q
# 10 passed in 5.43s

uv run ruff check src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
# All checks passed.

uv run pyright src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime
# 0 errors, 0 warnings, 0 informations

rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/unit/test_codex_server_agent.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
# no matches
```

Verified behavior:

- `submit_graph_patch` is exposed only to graph planner nodes with role
  `planner`, not ordinary workers or verifiers.
- The Codex dynamic tool router normalizes nested or top-level patch payloads,
  requires a registered graph patch callback, and returns callback feedback to
  the model.
- Generic planner nodes cannot complete with plain `submit` until they call
  `submit_graph_patch`; special fan-out planner roles retain existing submit
  behavior.
- Graph dispatch binds planner identity, lease, generation, execution,
  snapshot, observed position, and idempotency evidence before calling
  `GraphController.handle_command("submit_patch", ...)`.
- Accepted, rejected, and malformed patch paths carry planner evidence required
  by packet history and metrics.

Remaining risk:

- DG-1.2 proves the fenced callback and controller path with fake agents and
  graph integration flows. DG-1.3 must prove a controlled real Codex planner can
  follow the prompt contract and call `submit_graph_patch` without manual graph
  event injection.
