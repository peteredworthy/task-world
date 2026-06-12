# Slice 1.8 — FIXER

You are the FIXER agent in a builder→auditor→fixer pattern for slice 1.8 of the task-world execution-graph kernel. The builder implemented; the auditor BOUNCED with findings. Your job: close every HIGH and MEDIUM finding, then re-run the suite.

## Read first

1. The audit report: `/tmp/codex-graph/audit-1.8-report.md` — the findings table is your work list.
2. Ground truth: `docs/graph-approach/execution-graph-prd-plus.md` §10.1, §14, §16, §19, §27.3; `docs/graph-approach/phase-1-punch-list.md` (P1-1, P1-2, P1-3, P1-7, P1-8).
3. The code under audit: `src/orchestrator/graph/`, `tests/unit/test_graph_*.py`, `tests/fixtures/graph/`.

## Required fixes (from the audit findings)

1. **§14 configured-gate gap (HIGH).** Track configured gates per task region (gate `node_created` with `task_region_id` configures a gate; an `approval_decision_recorded` for it decides it). A latest candidate with verifier pass but ANY configured undecided or rejected gate must NOT be `accepted`. Add unit test: configured gate, no decision → not accepted; decision approved → accepted; decision rejected → not accepted.

2. **`record_decision` validation (HIGH).** Validate payload shape (required: decision target node_id, decision value in allowed set, decider actor), target node exists and is not terminal/retired, run not cancelled/failed. Invalid → `command_rejected` with reason. Add unit tests for each rejection path.

3. **Stubbed patch-op event emission (HIGH).** `_patch_op_events` must emit real graph events for every v1 op that validate_patch can accept: `create_gate`, `create_revision_attempt`, `create_appeal`, `set_resource_claims`, `set_allowed_actions`, `mark_plan_region_suspect`. Use event types consistent with the PRD §11.3 graph record list (`node_created` for gate/revision/appeal nodes with correct kinds, `node_authority_changed` or similar for claims/actions narrowing, `plan_region_marked_suspect`). Reduce any new event types in `reduce_event` where they affect projection state. Unit test: each op through `apply_command` emits its event(s).

4. **Lying invariant fixture (HIGH).** `invariants.yaml::invariant_snapshot_mismatch_not_consumed` currently asserts `callback_accepted` for a base-snapshot mismatch. Implement the real behavior now (this is punch-list P1-8, pulled forward): `validate_callback` must reject a callback whose `base_snapshot_id` does not match the lease's recorded `base_snapshot_id` (track it in the lease projection from `lease_granted` payload) with a distinct reason (`snapshot_incompatible`), and `apply_command` must emit `callback_rejected_stale` (or a dedicated `callback_rejected_snapshot` — pick one and document in COVERAGE.md). Also validate `execution_id` against the lease's recorded `execution_id` when present (other half of P1-8). Rewrite the fixture to assert the rejection. Unit tests for both checks.

5. **Echo event assertions in pure-projection scenarios (MEDIUM).** For the 32 `when_command: null` scenarios: keep them as pure-projection scenarios but strip `then_events` entries that merely repeat `given_events` UNLESS the event is the subject of the assertion; the projection assertion is the test. Simplest compliant form: drop `then_events` (or leave empty) and rely on nonempty `then_projection`. Do not delete scenarios.

6. **`then_projection: {}` scenarios (MEDIUM).** All 8 listed in the audit must assert real derived state: rejected-callback scenarios assert node/lease state unchanged (e.g. node still `completed` / lease still `revoked`), patch-rejection scenarios assert the target node state unchanged, duplicate-callback scenarios assert lease/node state. None may remain `{}`. Also fix `test_graph_projections.py:337-340` if it skips falsy projections — the corpus check must not skip empty `then_projection`; instead require every scenario to have a nonempty `then_projection`.

7. **Missing formula tests (MEDIUM).** Add unit tests: (a) latest-candidate event-position tie-break isolated (same attempt_number, later creation position wins); (b) active appeal overrides latest verifier failure (state not `needs_revision`); (c) accepted invalid-test appeal followed by replacement verification pass leaves `blocked_invalid_test` (per PRD: blocked only while "no replacement verification has passed" — so replacement pass should EXIT the blocked state; the auditor's probe showed `accepted`, which is correct per PRD — write the test to pin the PRD behavior, and if current code already does this, the test just locks it in).

8. **Unchanged fixture files (MEDIUM).** `node_lifecycle_appeal.yaml`, `node_lifecycle_gate.yaml`, `readiness.yaml`: apply the same standard — pure-projection scenarios assert nonempty `then_projection`; transitions that now have a command path (`record_decision` for gate approval/rejection, `raise_appeal` for appeal open) must be driven by `when_command`. Update `COVERAGE.md` to reflect all fixture changes.

## Done when

1. Every HIGH and MEDIUM audit finding has a code/test/fixture change closing it.
2. `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q` green, under 5 seconds.
3. No fixture has `then_projection: {}` and no `when_command: null` scenario asserts only events it injected.
4. `uv run ruff check src/orchestrator/graph tests/unit` passes; `uv run pyright src/orchestrator/graph` passes.

## Hard constraints (same as builder)

- Pure kernel: no IO/network/DB/FastAPI/runner imports in `src/orchestrator/graph/`.
- NO mocks, NO monkeypatching in tests.
- Touch ONLY `src/orchestrator/graph/**`, `tests/unit/test_graph_*.py`, `tests/unit/test_scenario_harness.py`, `tests/unit/test_fixture_corpus.py`, `tests/unit/test_callbacks.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_patch_validator.py`, `tests/fixtures/graph/**`.
- No git state mutation (no commit/stash/checkout/reset). No touching `orchestrator.db` or `.orchestrator/`.

## Output

End with: findings closed (list by audit table row), test count + wall clock, anything NOT closed and why.
