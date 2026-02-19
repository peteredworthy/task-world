# Plan: Bug and Gap Removal

## Overview

Fix 10 identified bugs and UI gaps in priority order: backend agent lifecycle issues first
(they block autonomous operation), then the recovery API (critical for non-technical users),
then MCP phase filtering (reduces wasted tool calls), and finally all frontend-only gaps
ordered by severity. Each step is independently deployable and verified before the next begins.

## Milestones

### Milestone 1: Backend Agent Reliability (High Severity)

- Fix `GateBlockedError` propagation in `cli.py` and handling in `executor.py`
- Rewrite no-op human gate task prompts in `idea-to-plan.yaml` (S-02, S-08)
- Implement `POST /api/runs/{id}/recover` with git worktree rollback
- Add recovery UI surface to run detail page

### Milestone 2: MCP Phase Filtering + High-Severity UI Gaps

- Implement phase-aware MCP tool filtering (builder vs verifier tool sets)
- Wire step-level human approval to the frontend (client → hook → UI → pending actions)

### Milestone 3: Medium-Severity UI Gaps

- Wire `AgentGuidancePanel` to lifecycle hooks (`agentStarted`, `agentCancelled`) and aggregate guidance endpoint
- Add backward step transition UI to `StepTimeline`
- Add branch status panel and back-merge action for active/paused runs

### Milestone 4: Low-Severity UI Gaps

- Add env file management UI (`EnvFilesPanel` in `RunDetail`)
- Surface server `GlobalConfig` in the settings panel
- Add routine YAML validation editor/modal

## Implementation Order

1. **Step 1: Fix GateBlockedError handling (AGENT-DEATH-HUMAN-GATE — backend)**
   - Prerequisites: None
   - Files: `src/orchestrator/agents/cli.py`, `src/orchestrator/agents/executor.py`
   - Deliverables:
     - `GateBlockedError` imported and re-raised explicitly in `cli.py` (not wrapped as `AgentExecutionError`)
     - `executor.py` catches `GateBlockedError` and leaves task in `BUILDING` state for retry
   - Verification: Unit test for cli.py error propagation; integration test that simulates gate-blocked submit and confirms task stays in BUILDING

2. **Step 2: Rewrite human gate task prompts (AGENT-DEATH-HUMAN-GATE — routine)**
   - Prerequisites: Step 1
   - Files: `routines/idea-to-plan.yaml`
   - Deliverables:
     - S-02 T-01 prompt instructs agent to check artifact files for `[HUMAN]` annotations, mark R1 done if present, mark blocked if absent
     - S-08 task prompt updated with same pattern
   - Verification: Manual inspection; integration test with a stub agent that reads the prompt confirms actionable instructions

3. **Step 3: Implement failed-run recovery API (FAILED-RUN-RECOVERY — backend)**
   - Prerequisites: None (independent of Steps 1-2)
   - Files: `src/orchestrator/api/routers/runs.py`, `src/orchestrator/workflow/service.py`, `src/orchestrator/workflow/engine.py` (or `transitions.py`)
   - Deliverables:
     - `POST /api/runs/{id}/recover` endpoint accepting `{ target_task_id, additional_attempts?, agent_type?, agent_config?, preserve_checklist? }`
     - Service method: validates run is in FAILED status (returns 409 for COMPLETED or any other status), resets target task to BUILDING, resets downstream tasks to PENDING, resets downstream checklist items to open (unless `preserve_checklist: true` is passed), un-completes affected steps, restores worktree to `end_commit`
     - Schema: `RecoverRequest` / `RecoverResponse` in `api/schemas/runs.py`
     - Note: COMPLETED run recovery is explicitly out of scope and deferred to a follow-up
   - Verification: Integration test covering reset logic and git checkout behavior

4. **Step 4: Add recovery UI (FAILED-RUN-RECOVERY — frontend)**
   - Prerequisites: Step 3
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/pages/RunDetail.tsx` (or new `RecoveryPanel` component)
   - Deliverables:
     - `recoverRun(runId, data)` API client function
     - `useRecoverRun` mutation hook
     - When run status is FAILED, display recovery panel showing step/task timeline with clickable rollback points and confirmation dialog
   - Verification: TypeScript compiles; component renders for a FAILED run in Vitest

5. **Step 5: Phase-aware MCP tool filtering (MCP-TOOLS-NO-PHASE-FILTERING)**
   - Prerequisites: None (independent)
   - Files: `src/orchestrator/mcp/server.py`, `src/orchestrator/mcp/tools.py`
   - Deliverables:
     - MCP server accepts a `phase` parameter (or derives it from task status at connection time)
     - Builder connections expose only: `get_requirements`, `update_checklist`, `submit`, `request_clarification`, `list_repos`, `list_branches`
     - Verifier connections expose only: `get_requirements`, `set_grade`, `submit`
   - Verification: Unit test that connects as builder, confirms `set_grade` absent; connects as verifier, confirms `update_checklist` absent

6. **Step 6: Wire step-level human approval (UI-STEP-APPROVAL)**
   - Prerequisites: None (independent)
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/pages/RunDetail.tsx` (or new `StepApprovalBanner`), `ui/src/hooks/usePendingActions.ts`
   - Deliverables:
     - `approveStep(runId, stepId, data)` in client
     - `useApproveStep` mutation hook
     - `StepApprovalBanner` renders when `has_approval_gate && approval_status === 'pending'`
     - `usePendingActions` includes pending step approval gates in its count
   - Verification: TypeScript compiles; Vitest renders banner for a mock step with pending gate

7. **Step 7: Wire AgentGuidancePanel lifecycle hooks and guidance endpoint (UI-AGENT-GUIDANCE-PANEL)**
   - Prerequisites: None (independent)
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/` (new `GuidanceResponse`), `ui/src/components/guidance/AgentGuidancePanel.tsx`, `ui/src/components/WaitingIndicator.tsx`
   - Deliverables:
     - `agentStarted`, `agentCancelled`, `getGuidance` in client
     - `useAgentStarted`, `useAgentCancelled`, `useGuidance` hooks
     - `AgentGuidancePanel` calls `useGuidance` instead of `useTaskPrompt` + hardcoded MCP
     - Cancel button calls `useAgentCancelled`
     - "I've started my agent" button calls `useAgentStarted`
   - Verification: TypeScript compiles; component renders guidance from mock API response

8. **Step 8: Add backward step transition UI (UI-BACKWARD-TRANSITIONS)**
   - Prerequisites: None (independent)
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/components/StepTimeline.tsx`
   - Deliverables:
     - `transitionBack(runId, data)` in client
     - `useTransitionBack` hook
     - Each completed step preceding the current one shows a "Revert to this step" action
     - Confirmation dialog with optional reason field; calls `useTransitionBack` on confirm
   - Verification: TypeScript compiles; dialog renders on completed step click

9. **Step 9: Branch status panel and back-merge (UI-BRANCH-STATUS)**
   - Prerequisites: None (independent)
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/` (new `BranchStatusResponse`), new `BranchStatusPanel` component, `ui/src/pages/RunDetail.tsx`
   - Deliverables:
     - `getBranchStatus`, `backMerge` in client
     - `useBranchStatus`, `useBackMerge` hooks
     - `BranchStatusPanel` shows ahead/behind counts, "Pull upstream changes" button, conflict warning
     - Rendered in `RunDetail` for ACTIVE/PAUSED runs with a worktree
   - Verification: TypeScript compiles; panel renders for mock branch status data

10. **Step 10: Env file management UI (UI-ENV-FILE-MANAGEMENT)**
    - Prerequisites: None (independent)
    - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/` (new env file types), new `EnvFilesPanel` component, `ui/src/pages/RunDetail.tsx`
    - Deliverables:
      - Five env file client functions, five hooks (three queries, two mutations)
      - `EnvFilesPanel`: current files list with masked values, snapshot history table, revert and copy-back actions
      - Shown in `RunDetail` only when `run.env_file_specs` is non-empty
    - Verification: TypeScript compiles; panel renders for mock snapshot data

11. **Step 11: Surface server GlobalConfig (UI-GLOBAL-CONFIG)**
    - Prerequisites: None (independent)
    - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/` (new `GlobalConfig`), settings panel component
    - Deliverables:
      - `getConfig` in client, `GlobalConfig` type, `useGlobalConfig` hook
      - Settings panel "Server" section shows DB path, active agent types, dashboard limits
      - Run list uses `max_recent_runs` from server config instead of hardcoded constant
    - Verification: TypeScript compiles; settings panel renders server section from mock config

12. **Step 12: Routine YAML validation UI (UI-ROUTINE-VALIDATION)**
    - Prerequisites: None (independent)
    - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, new routine validator page or modal, `ui/src/components/CreateRunModal.tsx`
    - Deliverables:
      - `validateRoutine` in client, `useValidateRoutine` hook
      - Textarea + Validate button + inline error list with line numbers
      - On valid result, "Create run from this routine" shortcut
    - Verification: TypeScript compiles; error list renders from mock validation response

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GateBlockedError handling location | Catch in `executor.py`, re-raise from `cli.py` | Keeps executor as the single authority on task lifecycle; cli.py stays thin |
| Recovery endpoint target parameter | `target_task_id` required, `target_step_id` optional (inferred) | Tasks are the atomic unit; step can always be inferred from task |
| Recovery valid starting status | FAILED only; COMPLETED remains terminal | COMPLETED recovery deferred to a follow-up; keeps the common case simple |
| Recovery checklist reset | Reset to open by default; optional `preserve_checklist: true` flag | Safest default (avoids stale state); flag allows fast recovery when builder work was sound |
| MCP phase filtering approach | Derive phase from task status at connection time (Option A, server-side) | Avoids separate endpoints; single MCP endpoint stays simpler for agent config |
| Routine YAML validation UI placement | Modal accessible from `RoutineSelector` or `CreateRunModal` | Minimizes new routes; validation naturally leads to run creation |
| Frontend-only gaps implementation order | High severity first (step approval), then medium, then low | Users blocked on step approval need it most urgently |

## References

- `docs/bugs/AGENT-DEATH-HUMAN-GATE.md`
- `docs/bugs/FAILED-RUN-RECOVERY.md`
- `docs/bugs/MCP-TOOLS-NO-PHASE-FILTERING.md`
- `docs/bugs/UI-STEP-APPROVAL.md`
- `docs/bugs/UI-AGENT-GUIDANCE-PANEL.md`
- `docs/bugs/UI-BACKWARD-TRANSITIONS.md`
- `docs/bugs/UI-BRANCH-STATUS.md`
- `docs/bugs/UI-ENV-FILE-MANAGEMENT.md`
- `docs/bugs/UI-GLOBAL-CONFIG.md`
- `docs/bugs/UI-ROUTINE-VALIDATION.md`
- `src/orchestrator/agents/cli.py` — GateBlockedError propagation target
- `src/orchestrator/agents/executor.py` — GateBlockedError retry handling target
- `src/orchestrator/mcp/server.py` — MCP tool registration
- `src/orchestrator/api/routers/runs.py` — all backend endpoints referenced
- `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts` — frontend integration points
