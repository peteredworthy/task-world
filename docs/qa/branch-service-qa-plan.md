# Branch Service QA Plan

## Scope

This branch is 11 commits ahead of `origin/main` and has additional unstaged edits. The changed surface is broad, but the service QA should focus on the behavior introduced or hardened by the branch:

- Super-parent oversight state: durable facts, projected read state, delegation decisions, child resolution, child acceptance, evidence validation, and max-child guardrails.
- Delegated-work state machine: immutable `DelegationState`, command fencing, idempotency, stale command recording, and fan-out policy decisions.
- Child routine templates and evidence helper: `orchestrator_create_child_from_template`, `ChildSliceSpec`, compiled embedded child routines, `scripts/run_child_evidence.py`, and `run.evidence.v1` validation.
- API and MCP endpoints: child create/list/accept/resolve, run evidence, parent oversight get/update/refresh, run trace, scoped MCP server URLs.
- Runner tool scoping: routine `available_tools` should expose only phase workflow tools plus explicitly granted orchestrator tools through `/mcp-scoped/{tools}/sse`.
- UI/API trace behavior: `/api/runs/{run_id}/trace` should return attempts, phases, action logs, and token metrics in the shape consumed by `RunTraceExplorer`.
- Regression risk around state persistence: repository updates to `oversight_state`, active parent/child transitions, worktree paths, event journal activity, and restart recovery.

## Preconditions

- Preserve the current working tree. Do not reset, stash, or delete `orchestrator.db`.
- Run all Python commands with `uv run`.
- Use the live service through REST/MCP only during QA.
- Prefer `user_managed` or deliberately tiny embedded routines so the service state machine is exercised without spending LLM tokens.
- Record each created run ID, child run ID, worktree path, command, response status, and any failure details in the final QA report.

## Stage 1 Deliverable

This file is the Stage 1 artifact. Later stages should append actual results, created run IDs, and evidence paths to a separate verification report rather than editing this plan into a mixed log.

## Static Verification

- Run the boundary check: `uv run python scripts/check_delegation_boundaries.py`.
- Run targeted backend tests for the touched areas:
  - `uv run pytest tests/unit/test_delegation_models.py tests/unit/test_delegation_fan_out.py tests/unit/test_delegation_boundaries.py`
  - `uv run pytest tests/unit/test_super_parent_oversight.py tests/unit/test_super_parent_service_mechanics.py tests/integration/test_fan_out.py`
  - `uv run pytest tests/unit/test_child_workflow_templates.py tests/unit/test_run_child_evidence_helper.py tests/unit/test_mcp_tool_definitions.py`
  - `uv run pytest tests/integration/test_mcp_tools.py tests/integration/test_api_runs.py`
- Run targeted frontend/API shape tests:
  - `uv run pytest tests/unit/test_run_schemas.py`
  - `npm --prefix ui test -- client.test.ts`
  - Run the RunTraceExplorer-focused UI tests if the local UI test command is available.
- Run `uv run ruff check .` and `uv run pyright` after functional QA if any QA fixes are made.

## Live Service Setup

- Start the service with `./dev.sh` or `uv run uvicorn scripts.serve:app --reload --port 8000`.
- Confirm:
  - `GET /health` returns OK.
  - `GET /api/agent-runners` includes `user_managed`.
  - `GET /api/routines` includes `super-parent`.
  - `GET /mcp-scoped/orchestrator_get_requirements/sse` reaches the scoped MCP transport without exposing unrelated tools.

## Tiny QA Routines

Use embedded routines for service probes. Keep each routine to one step and one task unless the behavior specifically requires parent/child linkage.

### `qa-parent-oversight`

Purpose: create an active parent run with no real LLM work, then exercise oversight and child APIs.

Requirements:
- one task with one critical requirement;
- `agent_runner_type: user_managed`;
- config includes `max_child_runs: 1`;
- the run must be started through `POST /api/runs/{run_id}/start`;
- no source files should be changed by this parent run.

### `qa-child-valid-evidence`

Purpose: produce a child run that can be accepted.

Requirements:
- generated with `POST /api/runs/{parent_run_id}/children` or MCP `orchestrator_create_child_from_template`;
- `parent_slice_id: QA-SLICE-001`;
- one task that writes `docs/run-evidence/QA-SLICE-001-evidence.json`;
- evidence outcome is `behavior_already_correct` or `verified_fix`;
- evidence has matching `slice_id`, `routine_id`, required enum values, `commands_run`, `test_results`, `evidence_files`, and `real_execution_surface`;
- use `scripts/run_child_evidence.py` for at least one harmless command such as `uv run python -c "print('qa child evidence ok')"`.

### `qa-child-invalid-evidence`

Purpose: verify invalid evidence blocks acceptance and records review state.

Requirements:
- linked to the same kind of parent, but use a fresh parent if max-child guardrails would interfere;
- write a malformed or identity-mismatched `run.evidence.v1` JSON file;
- complete or pause the child enough for evidence collection;
- `POST /api/runs/{parent_run_id}/children/{child_run_id}/accept` must fail with a useful error;
- parent oversight must include an `InvalidEvidence` review state.

### `qa-trace-single-task`

Purpose: verify `/trace` response and UI assumptions.

Requirements:
- one task, `user_managed` runner;
- update checklist and submit through REST/MCP;
- fetch `/api/runs/{run_id}/trace`;
- verify attempts include builder/verifier phases, prompts or notes as applicable, action log presence flags, token totals, and no schema mismatch against the UI types.

## Live Service Checks

1. Parent creation and oversight update:
   - Create `qa-parent-oversight`.
   - Start it.
   - `PATCH /api/runs/{parent_id}/oversight` with a compact `target_inventory`, `current_understanding`, and one decision.
   - Verify `GET /api/runs/{parent_id}` and `GET /api/runs/{parent_id}/oversight` expose projected oversight without losing durable facts.

2. Child creation from template:
   - Call MCP `orchestrator_create_child_from_template` or the equivalent REST child create path with a compact slice spec.
   - Verify the child inherits parent repo, source branch/accumulation branch, runner type, and runner config.
   - Verify child start is enqueued automatically and `GET /api/runs/{parent_id}/children` shows the linked child.
   - Verify parent oversight records `slices`, `last_child_run_id`, `last_decision`, `delegated_work`, and a launch decision.

3. Unresolved-child guardrail:
   - Attempt to create a second child while the first is unresolved.
   - Expect 409 or equivalent transition failure.
   - Verify parent oversight records the review/wait decision rather than corrupting child state.

4. Evidence collection:
   - In the child worktree, create one valid evidence bundle and one irrelevant JSON file.
   - `GET /api/runs/{child_id}/evidence` must return only `run.evidence.v1` evidence candidates.
   - Verify invalid evidence reports structured field errors and valid evidence is JSON-safe.

5. Child resolve:
   - Resolve a paused/failed/completed child with `reject`.
   - Repeat the same resolve call.
   - Verify the first call records `rejected_child_run_ids` and a child-resolution decision; the duplicate is idempotent and records `StaleCommandIgnored`.
   - Verify a rejected child allows the parent to create a replacement child.

6. Child acceptance:
   - Complete a valid child with acceptable evidence.
   - Accept it into the parent.
   - Verify clean merge status or conflict status, parent oversight accepted-child fields, delegation result, closed child IDs, and merge conflict details when applicable.
   - Repeat acceptance and verify idempotent behavior.

7. Acceptance rejection paths:
   - Attempt to accept a child with malformed evidence.
   - Attempt to accept a child whose evidence outcome is `needs_revision` or `bug_not_reproduced`.
   - Expect failures and `InvalidEvidence` review state.

8. Scoped MCP tool exposure:
   - Inspect full `/mcp/sse` and scoped `/mcp-scoped/{tools}/sse`.
   - Verify a super-parent task with `available_tools: [orchestrator_get_parent_oversight]` gets workflow tools plus that tool, not raw child creation unless granted.
   - Verify verifier phase gets verifier workflow tools rather than builder-only tools.

9. Run trace:
   - Fetch `/api/runs/{run_id}/trace` for a run with at least one submitted attempt.
   - Verify stable ordering, phase labels, prompt/note fields, attempt metadata, action log shape, and token/cost totals.
   - Open the UI run detail and confirm the trace view renders without overlapping or blank states.

10. Restart recovery smoke:
    - With a parent and child in a non-terminal state, restart the service.
    - Verify API state remains readable, worktree paths are preserved, and refreshed parent oversight still projects child state from durable facts plus live children.

## Failure Criteria

- Any invalid enum or malformed request returns 500 instead of 422/409 with a useful message.
- Parent oversight loses durable facts after refresh.
- Projection-only fields are persisted back as control facts unexpectedly.
- A second unresolved child can be launched when guardrails should block it.
- Child acceptance succeeds without acceptable evidence.
- Duplicate accept/resolve mutates state beyond an idempotency/stale-command audit record.
- Scoped MCP exposes tools outside the task/phase allowlist.
- `/trace` returns a shape that the UI type definitions cannot consume.
- Service restart changes parent/child linkage, worktree paths, or pending run status incorrectly.

## QA Report Template

For each check, record:

- command or endpoint;
- run IDs and worktree paths;
- expected result;
- actual result;
- pass/fail;
- evidence file or screenshot path;
- follow-up bug or code location if failed.
