# Super Parent Process Report

## Scope

Implemented `docs/super-parent/intent.md` on branch `codex/super-parent` as vertical slices:

- Reusable parent routine: `routines/super-parent/routine.yaml`
- Deterministic parent oversight reducer: `src/orchestrator/workflow/oversight.py`
- REST and MCP parent/child orchestration tools
- Child acceptance merge into the parent run branch
- Run detail UI visibility for parent/child state, oversight, evidence, and modal-confirmed child acceptance
- Evidence filtering so child evidence collection ignores committed example evidence and prefers files changed by the run

## Orchestrator Runs

Parent run:

- Run ID: `96a9647e-57c3-4257-9edb-339dcc00ed21`
- Routine: `super-parent`
- Runner: Codex Server
- Model: `gpt-5.5`
- Role metadata: `gpt-5.5 high`
- Source branch: `codex/super-parent`

Child runs:

- `f6a2e67d-90ce-4a13-86a4-72e9f25b2a1c`
  - Slice: `slice-api-ui-review`
  - Runner: Codex Server
  - Model: `gpt-5.5`
  - Role metadata: `gpt-5.5 medium`
  - Status: `draft`
- `b1bd62c2-6f8a-45ba-92ef-64054f23b670`
  - Slice: `slice-spark-smoke`
  - Runner: Codex Server
  - Model: `gpt-5.3-codex-spark`
  - Status: `completed`
  - Evidence: `docs/super-parent/process-evidence/spark-smoke-evidence.json`, produced in child worktree `worktrees/r89` and carried forward into this branch

Codex Server accepted only `model`, `callback_channel`, and `restrictions` in `agent_config`; the high/medium distinction is recorded in run `config.model_role`.

## Live Evidence

Spark child evidence endpoint:

- `GET /api/runs/b1bd62c2-6f8a-45ba-92ef-64054f23b670/evidence`
- Returned exactly one bundle after the evidence-filter fix:
  - `path`: `docs/super-parent/process-evidence/spark-smoke-evidence.json`
  - `schema_version`: `phase4.evidence.v1`
  - `outcome`: `verified_fix`
  - `next_recommendation`: `proceed`

Parent oversight refresh:

- `POST /api/runs/96a9647e-57c3-4257-9edb-339dcc00ed21/oversight/refresh`
- Result:
  - `child_count`: `2`
  - `child_counts`: `{"completed": 1, "draft": 1}`
  - `merge_queue`: `["b1bd62c2-6f8a-45ba-92ef-64054f23b670"]`
  - `terminal_guard.can_complete`: `false`
  - Blocking children:
    - Spark child: `accepted_child_not_merged`
    - Medium-review child: `child_not_terminal:draft`

This is the intended terminal guard behavior: the parent does not claim completion while accepted child work is unmerged and another linked child remains unresolved.

## Verification

Backend:

- `uv run pyright`
  - `0 errors, 0 warnings`
- `uv run pytest`
  - `3071 passed, 15 skipped`
  - Coverage: `71.85%`, above the `71%` gate
- Focused behavior run:
  - `40 passed`
  - The command itself exits nonzero under partial selection because repo-wide coverage is enforced on every pytest invocation.

Frontend:

- `npm run lint`
  - Passed
- `npm run typecheck`
  - Passed
- `npm run test`
  - `52 passed`, `437 passed`

Commit hook:

- `ruff`
- `ruff format`
- `gitleaks`
- `pyright`
- `pytest`
- `module-imports`
- `signal-routing`
- `ui-lint`
- `ui-typecheck`

All passed during the implementation commit hook.

## Notes

- Acceptance merge requires the parent run to have a worktree. The process evidence parent was left as a draft policy record, so the Spark child was reported in `merge_queue` rather than automatically merged by the Orchestrator.
- Follow-up branch verification found the Spark child branch had one unique committed artifact, `docs/super-parent/process-evidence/spark-smoke-evidence.json`. The full child branch was not merged because it was based on the earlier parent commit, before the evidence-filter fix and this report; only that unique evidence artifact was carried forward into `codex/super-parent`.
- `docs/super-parent/v2.md`, `docs/better-tests/`, and `ui/coverage/` were pre-existing untracked files and were not modified for this implementation.
