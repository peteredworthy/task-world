# Plan: UI Gaps — Wire Remaining Backend Endpoints to Frontend

## Overview

Six groups of backend endpoints (step approval, SSE settings, agent lifecycle hooks, guidance aggregate, backward transitions, branch status/back-merge) exist with full test coverage but are unreachable from the web UI. This plan wires them up in six focused implementation steps, ordered so lower-risk, foundational API/hook work comes first and UI rendering follows. Each step delivers a functional vertical slice.

## Milestones

### Milestone 1: API & Hook Foundation (Step 1)

Add all missing API client functions and TanStack Query hooks before touching any component code. This de-risks the UI work by confirming the shape of backend responses.

- `approveStep`, `agentStarted`, `agentCancelled`, `getGuidance`, `transitionBack`, `getBranchStatus`, `backMerge` added to `ui/src/api/client.ts`
- `useApproveStep`, `useAgentStarted`, `useAgentCancelled`, `useGuidance`, `useTransitionBack`, `useBranchStatus`, `useBackMerge` hooks added to `ui/src/hooks/useApi.ts`
- TypeScript types: `BranchStatusResponse`, `GuidanceResponse` added to `ui/src/types/`

### Milestone 2: Step Approval + Pending Actions (Step 2)

Unblock the human-in-the-loop step gate workflow. Users blocked at a step approval gate need a clear prompt in the UI.

- New `StepApprovalModal` component (separate from `ApprovalModal` — different endpoint, no reject path)
- Step approval prompt appears both inline in `StepAccordion` AND as a sticky banner at the top of `RunDetail.tsx` (both locations required per Q2 resolution)
- **Backend:** extend `GET /api/runs/{id}/pending-actions` in `src/orchestrator/api/routers/clarifications.py` to include pending step approval gates (steps where `has_approval_gate == True` and `approval_status == "pending"`)
- `usePendingActions` updated to handle the new step-approval action type
- `PendingActionsBadge` updated to show step approval actions

### Milestone 3: External Agent Signaling (Step 3)

Enable the external agent workflow. `AgentGuidancePanel` gains explicit lifecycle buttons; `WaitingIndicator` wires cancel to `agentCancelled`. Guidance panel adds `useGuidance` additively for `mcp_url` and `expected_actions`.

- "I've started my agent" button in `AgentGuidancePanel` wired to `useAgentStarted`
- `WaitingIndicator` cancel calls `agentCancelled` (replaces existing `cancelRun` in this context; run-level cancel remains a separate action)
- **Backend:** `POST /api/runs/{id}/agent-cancelled` updated to transition run to PAUSED instead of FAILED (so users can restart)
- `AgentGuidancePanel` updated to use `useGuidance` additively: `mcp_url` and `expected_actions` from guidance; system/user prompt from existing `useTaskPrompt` (additive, not full refactor per Q4 resolution)

### Milestone 4: Activity SSE Settings Toggle (Step 4)

Expose the existing `useActivityStream` toggle in the settings panel. Add a connection status indicator to the activity feed.

- `activityStreamMode` toggle in the settings panel (already backed by `SettingsContext`)
- SSE connection status indicator in activity feed UI

### Milestone 5: Backward Step Transitions (Step 5)

Let users navigate backward to a previous step when a re-do is needed.

- Dropdown menu ("Revert to step…") on the step progress bar in `RunDetail.tsx` (not per-indicator buttons per Q5 resolution)
- Confirmation dialog explaining state reset consequences
- Cache invalidation for `['run', runId]` and `['activity', runId]`
- **Backend:** improve router docstrings for `POST /api/runs/{id}/transition-back` to document `target_step_index` as a zero-based integer array index

### Milestone 6: Branch Status & Back-Merge (Step 6)

Surface git divergence between the run branch and source branch, and let users pull in source changes.

- Branch status panel on `RunDetail.tsx` (ahead/behind counts, conflict warning)
- Back-merge button with confirmation dialog
- Refetch on WebSocket `run_status_changed` events (no polling)

## Implementation Order

1. **Step 1: API Client & Hooks**
   - Prerequisites: None
   - Deliverables:
     - All 7 API client functions added to `ui/src/api/client.ts`
     - All 7 TanStack Query hooks added to `ui/src/hooks/useApi.ts`
     - `BranchStatusResponse` in `ui/src/types/runs.ts` (or `branches.ts`)
     - `GuidanceResponse` in `ui/src/types/` (new file or extend existing)
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/`

2. **Step 2: Step-Level Approval UI**
   - Prerequisites: Step 1 (`useApproveStep`)
   - Deliverables:
     - New `StepApprovalModal` component in `ui/src/components/detail/StepApprovalModal.tsx`
     - `RunDetail.tsx` detects `has_approval_gate && approval_status === 'pending'`: renders inline prompt in `StepAccordion` AND sticky banner at page top
     - Backend: extend `GET /api/runs/{id}/pending-actions` to include step-gate items
     - `usePendingActions` updated to handle step approval action type
     - `PendingActionsBadge` renders step approval pending actions
   - Files: `ui/src/pages/RunDetail.tsx`, `ui/src/hooks/usePendingActions.ts`, `ui/src/components/dashboard/PendingActionsBadge.tsx`, new `ui/src/components/detail/StepApprovalModal.tsx`, `src/orchestrator/api/routers/clarifications.py`

3. **Step 3: External Agent Lifecycle & Guidance Additive Update**
   - Prerequisites: Step 1 (`useAgentStarted`, `useAgentCancelled`, `useGuidance`)
   - Deliverables:
     - "I've started my agent" button in `AgentGuidancePanel`
     - `WaitingIndicator` cancel wired to `agentCancelled` (replaces run-level cancel in that context)
     - Backend: `POST /api/runs/{id}/agent-cancelled` updated to transition to PAUSED
     - `AgentGuidancePanel` uses `useGuidance` additively for `mcp_url` and `expected_actions`; keeps `useTaskPrompt` for prompt text
   - Files: `ui/src/components/guidance/AgentGuidancePanel.tsx`, `ui/src/components/guidance/WaitingIndicator.tsx`, `src/orchestrator/api/routers/runs.py`, `src/orchestrator/workflow/service.py`

4. **Step 4: Activity SSE Settings Toggle**
   - Prerequisites: None (settings already have `activityStreamMode` in context)
   - Deliverables:
     - Settings panel toggle for `activityStreamMode`
     - Connection status indicator in the activity feed area
   - Files: Settings panel component (to be identified), `ui/src/hooks/useActivitySSE.ts` (expose `isConnected`), activity feed component

5. **Step 5: Backward Step Transitions UI**
   - Prerequisites: Step 1 (`useTransitionBack`)
   - Deliverables:
     - Dropdown menu ("Revert to step…") on step progress bar in `RunDetail.tsx` (passes zero-based index to `transitionBack`)
     - Confirmation dialog listing what will be reset
     - Backend: improve `POST /api/runs/{id}/transition-back` router docstrings to document `target_step_index`
   - Files: `ui/src/pages/RunDetail.tsx`, possibly new `ui/src/components/detail/TransitionBackDialog.tsx`, `src/orchestrator/api/routers/runs.py`

6. **Step 6: Branch Status & Back-Merge UI**
   - Prerequisites: Step 1 (`useBranchStatus`, `useBackMerge`)
   - Deliverables:
     - `BranchStatusPanel` component showing ahead/behind counts and conflict state
     - Back-merge confirmation dialog
     - Wired into `RunDetail.tsx`
   - Files: `ui/src/pages/RunDetail.tsx`, new `ui/src/components/detail/BranchStatusPanel.tsx`, possibly new `ui/src/components/detail/BackMergeDialog.tsx`

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Step approval UI pattern | New `StepApprovalModal` (Q1→1) | Step approval has no reject flow and calls a different endpoint; reusing `ApprovalModal` would require conditional logic that obscures each case's semantics. [HUMAN] |
| Step approval location | Both sticky banner AND inline in accordion (Q2→3) | Banner ensures visibility when the step is collapsed; inline provides decision context. [HUMAN] |
| Step approval in pending-actions | Extend backend `GET /api/runs/{id}/pending-actions` (Q3→backend) | Step approvals not in response by default; backend extension preferred over client-side detection. [HUMAN] |
| Guidance endpoint usage | Additive — keep `useTaskPrompt`, add `useGuidance` for `mcp_url` and `expected_actions` (Q4→2) | `GET /guidance` (run-level aggregate) and `GET /tasks/{id}/prompt` (task-specific with callback instructions) serve different purposes; additive approach retains rich callback detail. [HUMAN] |
| Backward transition trigger | Dropdown on step progress bar (Q5→2) | Balances discoverability and UI cleanliness vs per-indicator buttons. [HUMAN] |
| `agentCancelled` behavior | Transitions run to PAUSED; replaces cancel in `WaitingIndicator` (Q6→PAUSED) | User may wish to restart after agent stops; PAUSED is the correct intermediate state. Backend change required. [HUMAN] |
| `target_step_index` type | Zero-based integer array index (Q7→3) | Confirmed by backend code; router docstrings to be improved. [HUMAN] |
| Branch status refresh | Fetch on page load + refetch on WebSocket `run_status_changed` events | No polling overhead; refreshes when state actually changes |
| Activity SSE default | Default to `'sse'` mode with polling fallback on connection failure | SSE is already implemented; this surfaces it as the better default |
| Backward transition confirmation | Required confirmation dialog | Going back resets task states irreversibly; warn user explicitly |
| Back-merge confirmation | Required confirmation dialog | Merge operations are destructive to branch history if there are conflicts |

## References

- `docs/PARTIAL-FEATURES.md` — source list of unwired endpoints
- `ui/src/api/client.ts` — existing API client (add new functions here)
- `ui/src/hooks/useApi.ts` — existing TanStack Query hooks (add new hooks here)
- `ui/src/hooks/useActivitySSE.ts` — SSE hook with `isConnected`
- `ui/src/hooks/useActivityStream.ts` — unified stream hook switching sse/polling
- `ui/src/types/runs.ts` — `StepSummary` type with `has_approval_gate` and `approval_status`
- `src/orchestrator/api/routers/runs.py` — backend endpoint implementations
- `tests/integration/test_approval_workflow.py` — step approval test coverage
