# Architecture: Bug and Gap Removal

## Current State

The orchestrator has a layered architecture:
- **Backend**: FastAPI (`api/`) → `WorkflowService` → `WorkflowEngine` → SQLite (via `RunRepository`)
- **Agent execution**: `executor.py` drives `AgentProtocol` implementations (`cli.py`, `openhands.py`, `user_managed.py`)
- **MCP server**: `mcp/server.py` registers tools unconditionally; `mcp/tools.py` handles calls
- **Frontend**: React + TanStack Query; `ui/src/api/client.ts` wraps all fetch calls; `ui/src/hooks/useApi.ts` provides query/mutation hooks; `ui/src/pages/RunDetail.tsx` composes panels

Known gaps:
- `GateBlockedError` from `on_submit()` falls through to the generic `except Exception` handler in `cli.py`, causing a crash instead of a retry.
- No API or UI mechanism exists to recover a FAILED run.
- MCP server exposes `set_grade` to builder agents; workaround exists but is incomplete.
- Eight frontend API endpoints have no client function, hook, or UI component.

## Proposed Changes

### New Components

**`ui/src/components/detail/StepApprovalBanner.tsx`**
Renders an approval prompt when a step has `has_approval_gate && approval_status === 'pending'`.
Calls `useApproveStep`; invalidates run query on success.

**`ui/src/components/detail/BranchStatusPanel.tsx`**
Shows ahead/behind counts relative to `source_branch`, a "Pull upstream changes" button
(calls `useBackMerge`), and a conflict warning. Visible for ACTIVE/PAUSED runs with a worktree.

**`ui/src/components/detail/EnvFilesPanel.tsx`**
Lists current env files (masked values) and snapshot history. Provides per-snapshot revert and
copy-back actions. Shown only when `run.env_file_specs` is non-empty.

**`ui/src/components/detail/RecoveryPanel.tsx`** (or inline in `RunDetail.tsx`)
Displayed when run status is FAILED. Shows step/task timeline with clickable rollback points
and a confirmation dialog. Calls `useRecoverRun` on confirm.

**Routine validator modal / page**
Simple `<textarea>` + Validate button wired to `useValidateRoutine`. Errors shown inline with
line numbers. "Create run from this routine" shortcut on valid result.

### Modified Components

**`src/orchestrator/agents/cli.py`**
- Import `GateBlockedError` from `workflow/errors.py`
- Add explicit `except GateBlockedError: raise` before the generic `except Exception` block
- This ensures `GateBlockedError` propagates to the caller instead of being wrapped as `AgentExecutionError`

**`src/orchestrator/agents/executor.py`** (in `_execute_task`)
- Catch `GateBlockedError` from `await agent.execute(...)`
- Log a warning and return without calling `on_agent_died` or `on_error`
- Task remains in `BUILDING` state; executor loop re-enters `_execute_task` on next iteration with open-requirement feedback

**`src/orchestrator/mcp/server.py`**
- Accept `phase: Literal["building", "verifying"]` at server initialization or connection time
- `_register_tools()` conditionally registers tools based on phase:
  - Builder set: `get_requirements`, `update_checklist`, `submit`, `request_clarification`, `list_repos`, `list_branches`
  - Verifier set: `get_requirements`, `set_grade`, `submit`

**`src/orchestrator/api/routers/runs.py`**
- Add `POST /api/runs/{id}/recover` route calling new `WorkflowService.recover_run()` method

**`src/orchestrator/workflow/service.py`**
- Add `recover_run(run_id, target_task_id, additional_attempts, preserve_checklist, ...)` async method:
  1. Load run; assert status is FAILED — return 409 Conflict for COMPLETED or any other status (COMPLETED recovery is deferred to a future follow-up)
  2. Identify target task and all downstream tasks in execution order
  3. Reset target task: status → BUILDING, bump `max_attempts`, create new attempt record
  4. Reset downstream tasks: status → PENDING, clear attempt records / grades
  5. Reset downstream task checklist items to open unless `preserve_checklist=True` (default: reset to open)
  6. Un-complete affected steps (set `completed = False`)
  7. Restore worktree: `git checkout {end_commit}` using target task's last attempt `end_commit`
  8. Transition run: FAILED → PAUSED with `pause_reason = "recovered"`, clear `completed_at`

**`routines/idea-to-plan.yaml`**
- S-02 T-01: Replace no-op wait prompt with actionable verification prompt (check artifact files
  for `[HUMAN]` annotations → mark R1 done if confirmed → mark blocked if absent)
- S-08: Apply same pattern to the final review human gate task

**`ui/src/api/client.ts`** — add 12 new functions:
`approveStep`, `agentStarted`, `agentCancelled`, `getGuidance`, `transitionBack`,
`getBranchStatus`, `backMerge`, `getEnvFiles`, `getEnvSnapshots`, `getEnvDefaultTarget`,
`revertEnvSnapshot`, `copyBackEnvFiles`, `getConfig`, `validateRoutine`, `recoverRun`

**`ui/src/hooks/useApi.ts`** — add corresponding mutations and queries for each client function

**`ui/src/types/`** — add new types:
`GuidanceResponse`, `BranchStatusResponse`, `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget`, `GlobalConfig`, `RecoverRequest` (fields: `target_task_id`, `additional_attempts?`, `agent_type?`, `agent_config?`, `preserve_checklist?: boolean`), `RecoverResponse`

**`ui/src/hooks/usePendingActions.ts`**
- Include pending step approval gates (steps with `has_approval_gate && approval_status === 'pending'`) in the returned action list and badge count

**`ui/src/components/StepTimeline.tsx`**
- Add "Revert to this step" action on each completed step preceding the current step
- Renders a confirmation dialog with optional reason field; calls `useTransitionBack` on confirm

**`ui/src/components/guidance/AgentGuidancePanel.tsx`**
- Replace `useTaskPrompt()` and hardcoded MCP URL with `useGuidance(runId)` hook
- Add "I've started my agent" button calling `useAgentStarted`
- Wire cancel to `useAgentCancelled`

**`ui/src/pages/RunDetail.tsx`**
- Mount `StepApprovalBanner` per step where `has_approval_gate && approval_status === 'pending'`
- Mount `BranchStatusPanel` for ACTIVE/PAUSED runs with worktree
- Mount `EnvFilesPanel` when `run.env_file_specs` is non-empty
- Mount `RecoveryPanel` when run status is FAILED

### Interactions

```
GateBlockedError fix:
  agent.execute() → GateBlockedError → cli.py re-raises → executor.py catches
  → task stays BUILDING → executor loop retry with open-requirement context

Recovery flow:
  UI RecoveryPanel → POST /api/runs/{id}/recover
  → WorkflowService.recover_run()
  → git.checkout(end_commit) in worktree
  → run: FAILED → PAUSED
  → POST /api/runs/{id}/resume to restart agent loop

MCP phase filtering:
  executor.py spawns agent → passes phase="building" to MCPServer init
  → MCPServer._register_tools() exposes only builder tool set
  → verifier spawned with phase="verifying" → exposes only verifier tool set

Step approval flow:
  StepApprovalBanner → useApproveStep → POST /api/runs/{id}/steps/{stepId}/approve
  → run query invalidated → WebSocket broadcast → UI reflects approved status

Frontend-only gaps (common pattern):
  New client function → new query/mutation hook → new/modified component
  → RunDetail mounts component → TanStack Query caches response
```

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| MCP phase parameter | Initialization-time `phase` argument | Avoids per-call lookup; cleaner than separate endpoints |
| Recovery git restore | `git checkout {end_commit}` via `GitPython` (existing `git/` module) | Consistent with existing worktree operations; no new dependencies |
| Step approval UI | `StepApprovalBanner` component in step list | Mirrors existing `ApprovalModal` pattern; visible inline without navigation |
| Branch status polling | TanStack Query with `refetchInterval` (e.g., 30s) | Branch drift is slow-changing; avoid polling too frequently |
| GlobalConfig staleTime | Long (`staleTime: Infinity` or 5 minutes) | Config rarely changes; no need to refetch on every mount |
| Routine validator | Modal (not separate page) | Keeps routing simple; integrates naturally with `CreateRunModal` |

## Testing Strategy

- **Unit Tests:**
  - `cli.py` GateBlockedError propagation: assert `GateBlockedError` is not wrapped as `AgentExecutionError`
  - `executor.py` retry logic: mock agent that raises `GateBlockedError`; assert task remains BUILDING
  - MCP phase filtering: connect as builder, assert `set_grade` absent from tool list; connect as verifier, assert `update_checklist` absent
  - Recovery service: mock run in FAILED state with known tasks; assert correct status resets and git checkout call

- **Integration Tests:**
  - `POST /api/runs/{id}/recover`: real in-memory DB run in FAILED state; assert run transitions to PAUSED, tasks reset correctly
  - Human gate task prompt: spin up a stub CLI agent with the new prompt; assert it produces a checklist update (R1 done) rather than exiting with no-op
  - Env file endpoints (already tested): existing `tests/integration/test_api_runs_envfiles.py` covers backend; add client-layer smoke test

- **E2E Tests:**
  - Full idea-to-plan run through S-02 human gate: approve via UI step approval button; confirm run progresses without agent_execution_error
  - Failed run recovery: create a run, force it to FAILED, use recovery UI to roll back, resume, confirm execution continues

## Security Considerations

- `POST /api/runs/{id}/recover` must validate that `target_task_id` belongs to the specified run (return 404 for mismatched IDs) and that the run is in FAILED status (return 409 for any other status, including COMPLETED).
- `git checkout` in worktree must use the recorded `end_commit` from the DB (not user-supplied arbitrary refs) to prevent repo manipulation.
- Env file panel displays masked values (existing backend behavior); copy-back writes to the user-selected path only after confirmation.

## Performance Considerations

- `useBranchStatus` uses a polling interval (30s default) rather than WebSocket subscription; `behind_count` and `ahead_count` are cheap git operations.
- `useGlobalConfig` uses a long `staleTime` to avoid redundant fetches on every mount.
- Recovery endpoint is a write operation with a git checkout; it is not on a hot path and can tolerate several hundred milliseconds of latency.
