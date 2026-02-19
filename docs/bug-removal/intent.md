# Intent: Bug and Gap Removal

## Original Request

Work through all of the bugs and gaps identified in `docs/bugs/`. These span backend agent
lifecycle errors, missing API features, and frontend UI gaps where backend endpoints exist but
no client, hook, or component calls them.

## Goal

Eliminate all 10 identified bugs and UI gaps so that:
1. Runs with `human_approval` gates progress autonomously without manual API intervention.
2. Failed runs can be recovered through the UI without direct SQL manipulation.
3. Every backend endpoint that exists has a corresponding frontend client, hook, and UI surface.
4. MCP tool exposure is scoped to the current task phase, eliminating wasted/invalid tool calls.

## Scope

### In Scope

- **AGENT-DEATH-HUMAN-GATE**: Handle `GateBlockedError` in `cli.py`; rewrite no-op human gate task prompts in `idea-to-plan.yaml` (S-02, S-08) to be actionable.
- **FAILED-RUN-RECOVERY**: Implement `POST /api/runs/{id}/recover` endpoint with git worktree rollback and run status reset; add recovery UI on the run detail page. Only FAILED runs are recoverable (COMPLETED remains a terminal state; COMPLETED recovery is deferred to a follow-up). The endpoint accepts an optional `preserve_checklist` flag; by default, downstream task checklist items are reset to open.
- **MCP-TOOLS-NO-PHASE-FILTERING**: Implement phase-aware MCP tool filtering so builder agents see only builder tools and verifier agents see only verifier tools.
- **UI-STEP-APPROVAL**: Add `approveStep` API client function, `useApproveStep` mutation hook, and a `StepApprovalBanner` component; wire into `usePendingActions`.
- **UI-AGENT-GUIDANCE-PANEL**: Add `agentStarted`, `agentCancelled`, `getGuidance` API client functions and hooks; replace `useTaskPrompt` in `AgentGuidancePanel` with `useGuidance`.
- **UI-BACKWARD-TRANSITIONS**: Add `transitionBack` client function, `useTransitionBack` hook, and a "Revert to this step" action on completed steps in `StepTimeline`.
- **UI-BRANCH-STATUS**: Add `getBranchStatus`, `backMerge` client functions; add `useBranchStatus`, `useBackMerge` hooks; render a `BranchStatusPanel` for active/paused runs.
- **UI-ENV-FILE-MANAGEMENT**: Add all five env file client functions, hooks, and an `EnvFilesPanel` component; surface in `RunDetail`.
- **UI-GLOBAL-CONFIG**: Add `getConfig` client function, `GlobalConfig` type, `useGlobalConfig` hook; display server config in settings panel; use server `max_recent_runs` for pagination.
- **UI-ROUTINE-VALIDATION**: Add `validateRoutine` client function, `useValidateRoutine` hook, and a routine YAML editor/validator page or modal.

### Out of Scope

- Rewriting the overall routine YAML schema or executor architecture.
- Adding new routine steps or changing the idea-to-plan routine beyond S-02/S-08 prompt fixes.
- OpenHands or Codex-specific agent fixes (changes target the shared `cli.py` / MCP layer).
- File/output viewer in the UI for worktree artifacts (noted in AGENT-DEATH-HUMAN-GATE but outside bug scope).
- Question/answer UI for design questions (noted in AGENT-DEATH-HUMAN-GATE but outside bug scope).

## Definition of Complete

- [ ] `GateBlockedError` is re-raised by `cli.py` and treated as a revision signal in `executor.py`; human gate tasks no longer die with `agent_execution_error` on valid agent exits.
- [ ] S-02 and S-08 task prompts in `idea-to-plan.yaml` are actionable (agent verifies artifacts and marks checklist; falls back to blocked if artifacts missing).
- [ ] `POST /api/runs/{id}/recover` endpoint exists, validated by integration test, and correctly resets run/step/task state and restores worktree from `end_commit`. Endpoint only accepts FAILED runs (returns 409 for any other status). Checklist items reset to open by default; `preserve_checklist: true` in the request body preserves prior builder self-reports.
- [ ] Recovery UI is accessible from the run detail page when run is in FAILED status.
- [ ] MCP server exposes only builder tools to builder agents and only verifier tools to verifier agents.
- [ ] `approveStep` in API client, `useApproveStep` hook, and step approval UI exist; pending approval gates appear in `usePendingActions`.
- [ ] `agentStarted`, `agentCancelled`, `getGuidance` wired in client and hooks; `AgentGuidancePanel` uses `useGuidance`; cancel button calls `agentCancelled`.
- [ ] `transitionBack` wired in client and hooks; `StepTimeline` shows "Revert to this step" on completed preceding steps with a confirmation dialog.
- [ ] `useBranchStatus` and `useBackMerge` exist; `BranchStatusPanel` renders behind/ahead counts and "Pull upstream changes" for active/paused runs.
- [ ] `EnvFilesPanel` renders current env files and snapshot history with revert and copy-back actions; shown in `RunDetail` when `env_file_specs` is non-empty.
- [ ] `useGlobalConfig` exists; settings panel shows server-derived config; run list pagination uses server `max_recent_runs`.
- [ ] Routine YAML validation page or modal exists with error display; validated routine can flow into run creation.
- [ ] All new backend code passes `uv run pyright` and `uv run ruff check .`.
- [ ] All new frontend code passes TypeScript type checking (`tsc --noEmit`).
- [ ] At minimum one integration test per new backend endpoint.
