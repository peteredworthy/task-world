# Dynamic Graph Baseline Matrix (DG-0.1)

- Slice: DG-0.1
- Baseline date/time (UTC): 2026-06-14 22:58:00Z
- Baseline authoring scope: measurement-only snapshot before dynamic implementation slices.
- Source: orchestrator run `2acb82b5-b58b-4cdf-afb5-0e1793521e20` using `graph-kernel-slice`, `execution_mode=graph`, `agent_runner_type=codex_server`, model `gpt-5.3-codex-spark`.

## Command Matrix

- `uv run pytest tests/unit/test_graph_*.py tests/unit/test_scheduler.py tests/unit/test_callbacks.py tests/unit/test_patch_validator.py -q`
  - Status: PASS
  - Output summary: `244 passed in 8.51s`

- `uv run pytest tests/integration/test_graph_run_driver.py tests/integration/test_graph_default_carrier.py tests/integration/test_graph_run_start_routing.py -q`
  - Status: PASS
  - Output summary: `13 passed in 6.75s`

- `uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py tests/integration/test_graph_parent_child_flow.py -q`
  - Status: PASS
  - Output summary: `6 passed in 3.09s`

- `uv run pytest tests/integration/test_graph_api.py tests/integration/test_graph_scheduler_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_file_state_report_api.py -q`
  - Status: PASS
  - Output summary: `14 passed in 2.81s`

- `uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_token_capture.py tests/unit/test_compare_carriers.py -q`
  - Status: PASS
  - Output summary: `102 passed in 2.14s`

- `uv run pytest tests/unit -q`
  - Status: PASS
  - Output summary: `2635 passed, 3 warnings in 40.14s`

- `uv run pytest tests/integration -q`
  - Status: PASS
  - Output summary: `1162 passed, 4 skipped in 64.10s (0:01:04)`

- `uv run ruff check src tests`
  - Status: PASS
  - Output summary: `All checks passed!`

- `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime src/orchestrator/workflow/graph_driver.py src/orchestrator/runners/agents/codex`
  - Status: PASS
  - Output summary: `0 errors, 0 warnings, 0 informations`
  - Note: environment warned that a newer pyright version is available.

- Purity check: `grep -R -nE "sqlite|subprocess|aiohttp|fastapi|httpx" src/orchestrator/graph/`
  - Status: PASS
  - Output summary: no matches

- Mock policy scan: `grep -R -nE "unittest\.mock|monkeypatch" tests/`
  - Status: PASS for this slice
  - Output summary: only an existing textual reference in `tests/unit/test_cli_agent_commit_retry.py`; no new test files were added in this slice.

## Relevant Output Artifacts

No output files, logs, or temporary artifacts were added as durable build outputs in this slice; all baseline evidence is captured in this document.

## Gap Inventory

- planner-agent patch submission path: `missing`
- planner graph packet and prompt contract: `implemented but unproven`
- dynamic feature routine: `missing`
- horizon region templates: `missing`
- gap planner semantics: `missing`
- requirement/evidence revision policy: `missing`
- final invariant gate: `missing`
- graph verifier grades in `/activity`: `missing`
- comparison metric export for dynamic graph facts: `partial`
- true-comparison Arm C Mind-the-gap fidelity requirements: `missing`
- true-comparison Arm E dynamic graph readiness: `missing`

## Interpretation

The current test matrix is healthy for current graph kernel/runtime/API surfaces and Codex capture tests, but none of the listed dynamic capabilities are complete enough to claim operational readiness.

Blocking gaps for full dynamic graph operation are those marked `missing` above and are implementation-path items that affect planner execution, dynamic region growth, planning-driven correction, and completion safety.

Observability-only or partially operational concerns are marked `implemented but unproven`, `partial`, or `verified` when evidence coverage exists.

## Validation Notes

- The builder submission created this baseline as documentation-only evidence and reported all DG-0.1 checklist items complete.
- The graph run later hit control-plane problems: it first paused as `graph_blocked` after builder submission, then an auto-check node overran its intended file-existence scope and edited source files in the run worktree.
- Those later source edits are rejected as out of scope for DG-0.1 and are not carried into durable state. DG-0.1 acceptance is limited to this baseline document and the command evidence recorded above.

## Recommended Next Slice

Recommended next slice from `docs/graph-approach/dynamic-graph-operational-plan.md`: **DG-0.2 — Dynamic Metrics Schema**.

Reason: it establishes metric instrumentation needed to measure planner patches, gap findings, region growth, and invariant behavior before implementing DG-1.x planner execution changes.

## Risk/Failure Notes

- No baseline checks failed in the builder-recorded command matrix.
- No production behavior changes are accepted from this slice.
- Baseline claim is intentionally conservative and does not assert dynamic graph operational readiness.
- Follow-up risk: graph-mode auto-verify/verifier routing needs attention before relying on it for narrow documentation-only slices, because the DG-0.1 auto-check acted like an implementation agent after resume.
