# Slice 1.9 — FIXER

You are the FIXER agent in a builder→auditor→fixer pattern for slice 1.9 of the task-world execution-graph kernel. The auditor BOUNCED. Close every finding, re-run, report.

## Read first

1. Audit report: `/tmp/codex-graph/audit-1.9-report.md` — findings table is the work list.
2. Ground truth: `docs/graph-approach/execution-graph-prd-plus.md` §17, §18, §15.6, §15.7.
3. Code: `src/orchestrator/graph/scheduler.py`, `models.py`, `commands.py`, `projections.py`; tests + `tests/fixtures/graph/`.

## Required fixes

1. **HIGH — §17 criterion 8, node-specific preconditions.** Add a precondition surface to readiness: `NodeScheduleInfo` gets `preconditions: list[str]` (declarative, deterministic — evaluated against the projection, NOT callables, to keep fixtures expressible). Support at minimum the v1 precondition kinds derivable from PRD §15: `check` nodes require a command definition present (`has_command_definition`), `verifier` nodes require a bound candidate file-state (already via required inputs — fine), gate-kind nodes are never leased (already excluded by kind handling — verify). Evaluate in `evaluate_readiness` with reason `precondition_failed:<name>` and wire through `schedule_tick` (populate from node payload at `node_created`). Tests: precondition unmet → not ready with exact reason; met → ready; node with no preconditions unaffected.

2. **MEDIUM — external claim key validity (§18.1).** An `external` mode claim without `external_resource_key` is INVALID: `claims_conflict` treats it as conflicting (conservative), and `evaluate_readiness` returns `invalid_claim:external_missing_key` for a node requesting one. Add a Pydantic model validator on the graph `ResourceClaim` (models.py) rejecting `mode="external"` with no key. Tests for all three surfaces.

3. **LOW — COVERAGE.md §18 rows.** Add one row per §18 matrix cell (25) mapping to the test name in `tests/unit/test_scheduler.py`, plus rows for path rules and §18.2 policy tests. Coverage index must reflect reality.

4. **LOW — planner/review fixtures injecting asserted state.** For rows whose transition has a command path, drive via `when_command`: `leased -> running` via a start/ack callback or state command through `apply_command` (pick the mechanism `apply_command` already supports; if none exists for runtime-start acknowledgement, add a minimal `acknowledge_start` command that validates lease identity then emits `node_state_changed` to running). No fixture may both inject and assert the same terminal `node_state_changed` with `when_command: null` — rows that are genuinely pure projection records keep state injection but must then assert a DERIVED consequence (e.g. ready_nodes membership), not just echo the state back. Update both planner and review fixture files.

5. **LOW — `node_ready`/`node_deferred` semantics.** Decide and document: they are audit/activity events; projection state changes ONLY via `node_state_changed`. Enforce: `schedule_tick` must emit `node_state_changed` (planned/blocked → ready) alongside `node_ready` so projections and events agree; `reduce_event` ignores `node_ready`/`node_deferred` (add a comment in projections.py stating this is intentional). Add a test asserting projection ready state after a schedule_tick comes from the emitted `node_state_changed`.

## Done when

1. All five findings closed with code/test/fixture evidence.
2. Kernel suite green, under 5s:
   `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q`
   (Use UV_CACHE_DIR=/private/tmp/task-world-uv-cache if needed.)
3. `uv run ruff check src/orchestrator/graph tests/unit` and `uv run pyright src/orchestrator/graph` pass.
4. No regression: 1.8 behaviors (configured-gate blocking, snapshot_incompatible, record_decision validation, patch-op emission) still tested and green.

## Hard constraints (unchanged)

- Pure kernel; no IO/network/DB; stdlib posixpath/fnmatch only for paths.
- NO mocks, NO monkeypatching.
- Touch ONLY `src/orchestrator/graph/**`, `tests/unit/test_graph_*.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_scenario_harness.py`, `tests/unit/test_fixture_corpus.py`, `tests/unit/test_callbacks.py`, `tests/unit/test_patch_validator.py`, `tests/fixtures/graph/**`.
- No git state mutation; no `orchestrator.db`; no `.orchestrator/`.

## Output

End with: findings closed (by number), test count + wall clock, anything NOT closed and why.
