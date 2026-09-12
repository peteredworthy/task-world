# Slice 3F implementation ledger

Status: implementation and independent validation complete. The full
repository gate is green; no live server, historical resume, paid probe,
activation, or commit was performed.

Slice 3F closes the mixed-planning integration seam on top of Slices 3A–3E.
The proof uses disposable Git repositories, SQLite event/outbox stores,
filesystem CAS artifacts, injected scripted runners, and production controller
and dispatch routing. It is infrastructure and contract proof, not a model
reliability claim.

## Requirements and evidence

| ID | Required behavior | Evidence | Status |
|---|---|---|---|
| S3F-1 | Root → discovery brief → plan → independent plan verification → successor runs through one typed, fresh-context production path. | `test_initial_discovery_brief_runs_through_production_dispatch_and_finalization`, including disjoint requirements, continuation horizon, exact successor selection, one effectful batch, duplicate submission handling, and ownership cleanup. | Validated |
| S3F-2 | A rejected batch supplies exact failed evidence to one bounded correction decision. | `test_rejected_batch_dispatches_a_bounded_correction_decision` seeds accepted plan authority plus failed candidate/check/report evidence, dispatches `corrective_work`, verifies one `decision_answer` and `classified_gap`, and checks finalized attempts, no active leases, and one terminal close. | Validated |
| S3F-3 | Claude CLI uses the same decision-v1 contract through a live per-execution graph MCP route. | `test_claude_cli_decision_dispatch_uses_a_live_per_execution_graph_mcp_route` uses `GraphMcpExecutionRegistry`, the production dispatcher, runner preflight, typed submission, and asserts the route was registered and cleaned through finalization. | Validated |
| S3F-4 | Legacy constructor+submit, historical replay, unsupported graph runners, and non-graph OpenHands/CLI behavior remain compatible. | Focused compatibility bundle: 183 passed, 1 skipped across graph MCP, runner boundaries, Codex transport, CLI, replay, and sequential product-path tests. The existing skip is the external CLI environment gate. | Validated |

## Changed files

The 3F-specific source change exports the existing per-execution graph MCP
registry through the public `orchestrator.graph_runtime` API. The behavioral
integration additions and the stale expected topology assertion are:

```text
src/orchestrator/graph_runtime/__init__.py
tests/integration/test_graph_decision_runtime.py
tests/unit/test_initial_planning_decision.py
```

Prior slice production changes remain preserved in the worktree; this ledger
does not rewrite or duplicate their implementation records.

## Source identity after implementation

```text
b7dcbf52989d207690d610597e9173fe214cd3b3615f67382882b60a95936a60  src/orchestrator/graph_runtime/__init__.py
2ce4b4545c554ea24ff910280bcf3037a5bc58ccc9faae78d1ea7635b9a20014  tests/integration/test_graph_decision_runtime.py
1ca32fa0ad951767d834b572cac62e6d4f99183f433e8d5afb2d7dbfe6615243  tests/unit/test_initial_planning_decision.py
f8c4de98203e9e43b841159cf7eb5f6fe308c1768254bd71dd71bfb2f37f315e  src/orchestrator/graph/decisions.py
3c847b5784f52011ee4e2a783015f6eeb4dfc09f8b4e7449a37b303e933632f1  src/orchestrator/graph/macros.py
755a4e40847b76c5a6f6b61612d3e8e9d6a62eb9c69d7aa22cd941f926dab904  src/orchestrator/graph_runtime/dispatch.py
```

## Verification record

Focused mixed-planning suite:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py \
  tests/unit/test_graph_decisions.py tests/unit/test_initial_planning_decision.py \
  tests/unit/test_gap_correction_decision.py tests/unit/test_successor_amendment_decision.py \
  tests/integration/test_recovery_successor_replay.py \
  tests/integration/test_recovery_successor_planner_probe.py --override-ini='addopts='
# 140 passed, 1 warning
```

Compatibility suite:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_mcp_second_runner_smoke.py \
  tests/unit/test_graph_mcp_tools.py tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_codex_server_transport.py tests/unit/test_cli_agent.py \
  tests/unit/test_cli_agent_commit_retry.py tests/integration/test_cli_agent.py \
  tests/integration/test_graph_sequential_product_path.py --override-ini='addopts='
# 183 passed, 1 skipped, 10 warnings
```

Static and boundary checks:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check .
# All checks passed!
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check .
# 785 files already formatted
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
# exit 0
git diff --check
# exit 0
```

Complete repository gate, rerun with process inspection and network access
because two tests require those host capabilities:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q
# 6257 passed, 5 skipped, 16 warnings
```

## Remaining concerns

The behavioral suite uses injected scripted transports and disposable local
state, as required by the implementation prompt. It does not claim that a
live provider will produce reliable answers. The full repository test gate is
green for the complete recovery change in this worktree.
