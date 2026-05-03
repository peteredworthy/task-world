# Super Parent Implementation Plan

This plan implements `docs/super-parent/intent.md` as vertical, verifiable slices. Each
slice exercises the full path needed for its behavior instead of introducing isolated
models or UI without a running proof.

## Operating Model

- Branch: `codex/super-parent`.
- Primary runner: Codex Server through the Orchestrator API.
- Model mix: use `gpt-5.5` for architecture/reducer work, `gpt-5.5` with medium effort for
  API/UI integration work, and `gpt-5.3-codex-spark` for focused validation and small fixes.
- Parent loop shape: plan one slice, run it, collect evidence, refresh parent understanding,
  then choose the next slice.
- Child routines are embedded in run records unless a human explicitly promotes them.

## Slice 1: Parent Routine And Planning Contract

Goal: make Super Parent an authorable routine policy, not a hard-coded one-off flow.

Implementation:

- Add a reusable `super-parent` routine under `routines/super-parent/`.
- Define intake inventory, slice selection, child creation, evidence evaluation, and final
  report tasks with stable requirement IDs.
- Require every generated child routine to include `run.evidence.v1` output.
- Document the implementation slices in this file.

Verifiable requirements:

- `routines/super-parent/routine.yaml` validates through `RoutineConfig`.
- The routine references MCP/API child-run operations and evidence collection.
- The routine requires a target inventory with stable IDs.
- The routine requires a readable parent-understanding artifact before human input or terminal
  outcomes.

Validation:

- `uv run python -c "from pathlib import Path; from orchestrator.config import load_routine; load_routine(Path('routines/super-parent/routine.yaml')); print('OK')"`

## Slice 2: Deterministic Oversight Reducer

Goal: give the engine a pure, testable way to summarize parent/child state and reject illegal
or terminal-unsafe combinations.

Implementation:

- Add a pure `workflow.oversight` reducer with typed payloads for child summaries, evidence
  outcomes, attention items, attempt counts, merge queue, and terminal guards.
- Expand the `run.evidence.v1` API schema to distinguish the outcomes required by the
  intent: `verified_fix`, `bug_not_reproduced`, `behavior_already_correct`,
  `environment_blocked`, `needs_revision`, `partial_progress`, and `unrelated_failure`.
- Compute stalled slices when the same `parent_slice_id` reaches three failed or revision
  attempts.

Verifiable requirements:

- Reducer output is deterministic for the same parent, child summaries, and prior oversight
  payload.
- Active parent snapshots flag more than one active child as illegal in v1.
- Terminal parent snapshots block completion when active, queued, unmerged accepted, stalled,
  or human-action children remain unresolved.
- `bug_not_reproduced` produces a human attention item instead of silently closing a target.

Validation:

- `uv run pytest tests/unit/test_super_parent_oversight.py -q`

## Slice 3: Parent Oversight API And MCP Mechanics

Goal: expose deterministic parent mechanics through service-owned APIs and MCP tools so a
parent routine does not have to remember state from conversation.

Implementation:

- Add service methods to refresh and persist a parent oversight snapshot.
- Add REST endpoints:
  - `GET /api/runs/{run_id}/oversight`
  - `POST /api/runs/{run_id}/oversight/refresh`
- Add MCP tools:
  - `orchestrator_refresh_parent_oversight`
  - `orchestrator_get_parent_oversight`
- Add terminal guard wiring so a parent run cannot complete while blocking child work remains.

Verifiable requirements:

- Refresh recomputes `oversight_state` from durable child run state and evidence files.
- The API returns child summaries and attention items without scanning UI-only data.
- MCP tools call the same service methods as REST.
- Parent completion pauses with a clear reason when unresolved child work exists.

Validation:

- `uv run pytest tests/integration/test_super_parent_oversight_api.py tests/integration/test_mcp_tools.py -q`

## Slice 4: Child Acceptance And Parent-Branch Integration

Goal: make accepted child work merge into the parent worktree only, with service-owned guardrails.

Implementation:

- Add a git operation that merges `orchestrator/run-{child_id}` into
  `orchestrator/run-{parent_id}` from the parent worktree.
- Block merges into `main`, `master`, the source branch, or sibling child branches.
- Add service and API/MCP acceptance operations:
  - `POST /api/runs/{parent_id}/children/{child_id}/accept`
  - `orchestrator_accept_child_run`
- Record merge results, conflicts, and accepted evidence in `oversight_state`.

Verifiable requirements:

- Only a completed child linked to the parent can be accepted.
- Missing or non-acceptance evidence rejects acceptance.
- A failed child is never merged.
- Merge operations execute in the parent worktree and leave conflicts recorded for the parent.

Validation:

- `uv run pytest tests/unit/test_super_parent_merge_ops.py tests/integration/test_super_parent_child_merge.py -q`

## Slice 5: Parent/Child UI Visibility

Goal: make child runs visible without crowding the normal run surfaces.

Implementation:

- Add compact parent context to child run detail pages with a link back to the parent.
- Add a parent oversight panel showing current understanding, attention items, child counts,
  accepted merges, and stalled slices.
- Add dashboard grouping so child runs are visually nested under their parent when present.

Verifiable requirements:

- Parent detail pages show child summaries without replacing normal task rendering.
- Child detail pages show parent and slice context.
- Children needing human input are surfaced before secondary counts.
- No inline destructive confirmation is introduced.

Validation:

- `cd ui && npm run test -- RunDetail`
- Browser smoke against a parent run with at least one child.

## Slice 6: Integrated Validation And Final Report

Goal: prove Super Parent behavior on the integrated branch and leave a concise audit trail.

Implementation:

- Run focused Python and UI tests for all changed surfaces.
- Run a real Orchestrator parent/child smoke with Codex Server and embedded routines.
- Write `docs/super-parent/process-report.md` with run IDs, model usage, evidence paths,
  commands run, failures, and remaining risks.

Verifiable requirements:

- Focused tests pass.
- Broad static checks pass.
- The report includes evidence of child creation, oversight refresh, evidence collection,
  and acceptance/merge behavior.
- Remaining blocked or deferred items are explicit.

Validation:

- `uv run pytest tests/unit/test_super_parent_oversight.py tests/unit/test_super_parent_merge_ops.py tests/integration/test_super_parent_oversight_api.py tests/integration/test_super_parent_child_merge.py -q`
- `uv run ruff check .`
- `uv run pyright`
