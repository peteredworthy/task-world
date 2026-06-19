# Slice DG-1.3 - Planner Prompt Contract

## Ground Truth

- `docs/graph-approach/dynamic-graph-operational-plan.md` - Phase DG-1,
  Slice DG-1.3.
- `docs/graph-approach/slice-DG-1.1-spec.md` - accepted planner packet.
- `docs/graph-approach/slice-DG-1.2-spec.md` - accepted fenced
  `submit_graph_patch` callback/tool path.
- `src/orchestrator/graph_runtime/dispatch.py` - planner prompt construction,
  graph dispatch, and patch callback binding.
- `src/orchestrator/runners/agents/codex/common.py` - Codex prompt assembly and
  dynamic tool specifications.
- `tests/unit/test_graph_planner_packet.py`
- `tests/unit/test_codex_server_common.py`
- `tests/unit/test_codex_server_transport.py`
- `tests/integration/test_graph_planner_flow.py`
- `tests/integration/test_graph_runner_e2e.py`

## Scope

Make graph planner prompts explicit enough that a real Codex planner knows it
must mutate the graph only by calling `submit_graph_patch`, then verify that a
controlled Codex-backed planner session can submit a minimal patch through the
tool path without manual graph event injection.

This is a prompt/tool-contract slice. It must not introduce the full dynamic
feature routine, new graph APIs, UI changes, database schema changes, scheduler
policy changes, or new patch operation permissions.

## Orchestrator Runner

Run this slice through the orchestrator using Codex only:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-1.3",
    "spec_path": "docs/graph-approach/slice-DG-1.3-spec.md"
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

### 1. Planner-Specific Prompt Contract

Refine graph planner prompt construction so generic planner nodes receive a
clear contract:

- The planner's job is to propose graph structure, not edit repository files.
- Graph mutation must be done only by calling `submit_graph_patch`.
- Plain `submit` is only for finishing after at least one accepted or rejected
  graph patch attempt.
- The prompt must point to the structured planner context packet and name the
  key fields the planner must use:
  - `current_graph_position` as `base_graph_position`;
  - `node_id` as planner identity;
  - `allowed_patch_operations`;
  - `patch_examples`;
  - frontier, evidence, open proposals, accepted patches, and rejections.
- The prompt must include compact examples for:
  - create worker/verifier region;
  - create successor planner;
  - create gap planner;
  - create invariant gate/check;
  - terminate with no successor by submitting an explicit rejected/no-op patch
    if no safe graph mutation is available.

Keep examples compact and deterministic. Do not paste long transcripts or
routine-level context into the prompt.

### 2. Codex Tool Instructions Match Planner Contract

When `submit_graph_patch` is available to a planner session, the Codex server
prompt should explain the tool in the available callback tools section:

- accepted argument forms;
- requirement to use `base_graph_position` from the planner packet;
- expected outcome feedback from accepted and rejected patches;
- instruction to repair stale or malformed patches by submitting a corrected
  patch, not by editing graph events directly.

Workers and verifiers must not receive planner patch tool instructions.

### 3. Controlled Real Planner Attempt

Add the narrowest reliable test or harness that runs a controlled Codex-backed
planner session against the actual Codex server adapter and proves the model can
call `submit_graph_patch` for a minimal graph mutation.

Acceptable implementation options:

- a skipped-by-default integration test that requires an explicit environment
  variable and local Codex server availability; or
- a local script under `scripts/` that the orchestrator run executes and records
  in the slice validation notes.

The controlled attempt must:

- use a planner `ExecutionContext` with `node_kind="planner"` and
  `node_role="planner"`;
- expose `submit_graph_patch`;
- provide a minimal planner packet/prompt with a valid example;
- capture the patch payload delivered to the callback;
- reject source-file edits as out of scope;
- complete without manual graph event injection.

If the live Codex attempt is blocked by Codex server/tooling behavior, record a
precise external blocker and keep deterministic unit/integration coverage for
the prompt contract.

## Required Tests

Use hand-written fakes only for deterministic tests. Do not use `patch`,
`MagicMock`, pytest `monkeypatch`, network calls in unit tests, TestClient in
unit tests, or direct DB edits.

At minimum:

1. Planner prompt contract tests:
   - generic planner prompt names `submit_graph_patch`;
   - prompt instructs no source edits;
   - prompt says plain `submit` follows a patch attempt;
   - prompt includes compact examples for worker/verifier region, successor
     planner, gap planner, invariant/check, and no-safe-mutation termination.
2. Codex prompt/tool instruction tests:
   - planner Codex prompt includes `submit_graph_patch` instructions when the
     tool is exposed;
   - worker/verifier prompts do not include planner patch instructions.
3. Regression tests:
   - DG-1.1 planner packet fields remain present;
   - DG-1.2 tool exposure/routing remains planner-only.
4. Controlled real planner evidence:
   - either an explicit live Codex-backed attempt records a callback payload; or
   - a documented blocker explains why the live attempt could not run and what
     deterministic checks still passed.

## Acceptance Commands

Run and record:

```bash
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py -q
uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q
uv run ruff check src/orchestrator/graph_runtime src/orchestrator/runners/agents/codex tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
uv run pyright src/orchestrator/graph_runtime src/orchestrator/runners
```

If a live Codex attempt is implemented as a gated test or script, run it only
with the required environment explicitly set and record the exact command and
result.

## Done When

1. Generic planner prompts give an explicit graph-patch-only mutation contract.
2. Codex planner sessions receive matching `submit_graph_patch` tool
   instructions.
3. Workers and verifiers do not receive planner patch instructions or tool
   exposure.
4. A controlled Codex planner attempt either successfully delivers a minimal
   patch payload to the callback, or records a precise external blocker.
5. No database schema, API route, UI, scheduler, or patch validator permission
   changes are made.

## Mind-the-gap Validation Requirements

The validator must confirm:

- DG-1.3 is limited to planner prompt/tool contract and controlled evidence.
- Prompt examples are compact enough to preserve context discipline.
- Graph mutation still goes through `submit_graph_patch` and
  `GraphController.handle_command`.
- The result is sufficient to start DG-2.1, the dynamic feature routine
  skeleton, unless the live Codex attempt exposes a blocker that requires a
  smaller repair slice first.

## Hard Constraints

- No mocks or monkeypatching.
- No DB deletion or direct `orchestrator.db` edits.
- No main worktree git operations.
- Use `uv run` for Python commands.
- Use Codex, not Claude, for orchestrator execution.
- Do not broaden graph patch permissions beyond `patch_validator.py`.
- Do not append graph events outside `GraphController.handle_command`.

## Validation Outcome - 2026-06-14

Status: accepted by independent manager validation after the Codex-backed
orchestrator builder was paused for a read-only loop.

Orchestrator evidence:

- Run `277ab91b-2569-4f6b-a3d3-3e0766b30a55`, worktree
  `/Users/peter/code/task-world/worktrees/r264`, runner `codex_server` with
  `gpt-5.3-codex-spark`.
- The run was created from `routine_embedded` and seeded with accepted DG-1.1
  and DG-1.2 files because the registered source branch did not include the
  durable but uncommitted previous slices.
- The builder was paused after repeated read-only inspection. It left partial
  prompt/example edits, which were corrected by the manager before validation.

Accepted DG-1.3 files:

- `src/orchestrator/graph_runtime/dispatch.py`
- `src/orchestrator/runners/agents/codex/common.py`
- `src/orchestrator/runners/agents/codex/agent.py`
- `tests/unit/test_graph_planner_packet.py`
- `tests/unit/test_codex_server_common.py`
- `tests/unit/test_codex_server_transport.py`
- `tests/unit/test_codex_server_tool_filtering.py`

Verified behavior:

- Generic planner prompts include an explicit mutation contract:
  `submit_graph_patch` only for graph mutation, no source edits, use
  `current_graph_position` as `base_graph_position`, choose only
  `allowed_patch_operations`, repair rejected/stale/malformed feedback, and
  call plain `submit` only after a patch attempt.
- Planner packets include compact examples for worker/verifier region,
  successor planner, gap planner, invariant check, and no-safe-mutation
  termination.
- Codex planner sessions receive `submit_graph_patch` instructions only when
  `node_kind == "planner"` and `node_role == "planner"`; worker and verifier
  prompts do not include them.
- Legacy `item/started` tool-call notification handling now receives the graph
  patch callback as well as the current `item/tool/call` request path.
- Controlled live Codex planner evidence passed with:

```bash
uv run python /private/tmp/run_live_codex_planner.py
```

Result:

```json
{
  "success": true,
  "submitted": true,
  "changed_files": [],
  "received": [
    {
      "patch_id": "live-dg13-worker",
      "base_graph_position": 0,
      "ops": [
        {
          "op": "create_node",
          "node": {
            "node_id": "worker-live-dg13",
            "kind": "worker",
            "role": "builder",
            "state": "planned",
            "task_region_id": "region-live-dg13"
          }
        }
      ]
    }
  ]
}
```

Validation commands:

```bash
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py -q
# 134 passed in 5.10s

uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q
# 10 passed in 6.09s

uv run ruff check src/orchestrator/graph_runtime src/orchestrator/runners/agents/codex tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
# All checks passed.

uv run pyright src/orchestrator/graph_runtime src/orchestrator/runners
# 0 errors, 0 warnings, 0 informations

rg -n "unittest\\.mock|MagicMock|monkeypatch|\\bpatch\\(" tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py
# no matches
```

Remaining risk:

- DG-1.3 proves a real Codex planner can call the fenced tool and receive
  callback feedback, but the live harness used a direct `CodexServerAgent`
  session rather than a full graph-dispatched planner node in a dynamic feature
  routine. DG-2.1 should convert this into a production routine skeleton.
