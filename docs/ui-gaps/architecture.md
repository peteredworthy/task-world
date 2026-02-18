# Architecture: UI Gaps — Wire Remaining Backend Endpoints to Frontend

## Current State

The frontend is a React 19 / TypeScript / Vite 7 / TailwindCSS 4 app in `ui/src/`. Key architectural patterns:

- **API layer:** `ui/src/api/client.ts` — typed `fetch` wrappers; all API functions are on the `api` object
- **Data hooks:** `ui/src/hooks/useApi.ts` — TanStack Query `useQuery`/`useMutation` wrappers; cache keys follow `['resource', id]` convention
- **Real-time:** `ui/src/context/WebSocketContext.tsx` — per-run WebSocket that broadcasts events; SSE handled by `useActivitySSE`/`useActivityStream`
- **Settings:** `ui/src/hooks/useSettings.ts` — `SettingsContext` with `activityStreamMode` already persisted; `SettingsModal.tsx` already has the SSE/polling radio toggle
- **Types:** `ui/src/types/` — per-domain TS files; `runs.ts` already has `StepSummary.has_approval_gate` and `StepSummary.approval_status`
- **Components:** ~50 TSX files organized under `pages/`, `components/dashboard/`, `components/detail/`, `components/guidance/`

Currently missing API calls: `approveStep`, `agentStarted`, `agentCancelled`, `getGuidance`, `transitionBack`, `getBranchStatus`, `backMerge`.

## Proposed Changes

### New Components

| Component | Path | Purpose | Feature |
|-----------|------|---------|---------|
| `StepApprovalModal` | `components/detail/StepApprovalModal.tsx` | Step-gate approval prompt with comment field (no reject path; separate from `ApprovalModal`) | Step approval |
| `TransitionBackDialog` | `components/detail/TransitionBackDialog.tsx` | Confirmation + step picker for backward transitions (passes zero-based index) | Backward transitions |
| `BranchStatusPanel` | `components/detail/BranchStatusPanel.tsx` | Shows ahead/behind counts, conflict state, back-merge button | Branch status |
| `BackMergeDialog` | `components/detail/BackMergeDialog.tsx` | Confirmation before back-merge (existing `ConfirmDialog` may suffice) | Branch status |
| `SSEConnectionIndicator` | Inline in activity feed | Shows connected/disconnected status for SSE stream | SSE status |

Note: The existing `ConfirmDialog` component may handle simple confirmations without a new component.

### Modified Components

| Component | Changes | Feature |
|-----------|---------|---------|
| `ui/src/api/client.ts` | Add `approveStep`, `agentStarted`, `agentCancelled`, `getGuidance`, `transitionBack`, `getBranchStatus`, `backMerge` | All 6 feature groups |
| `ui/src/hooks/useApi.ts` | Add `useApproveStep`, `useAgentStarted`, `useAgentCancelled`, `useGuidance`, `useTransitionBack`, `useBranchStatus`, `useBackMerge` | All 6 feature groups |
| `ui/src/types/runs.ts` (or new files) | Add `BranchStatusResponse`, `GuidanceResponse`, `StepApprovalRequest` | Type definitions |
| `ui/src/pages/RunDetail.tsx` | Render step approval prompt for gated steps; add branch status panel; add backward transition control | Step approval, branch status, backward transitions |
| `ui/src/components/guidance/AgentGuidancePanel.tsx` | Add "I've started my agent" button (`useAgentStarted`); refactor to use `useGuidance` as primary data source | Agent lifecycle, guidance |
| `ui/src/components/guidance/WaitingIndicator.tsx` | Wire cancel to `agentCancelled` (replaces existing `cancelRun` in this context) | Agent lifecycle |
| `ui/src/hooks/usePendingActions.ts` | Extend to handle new step-approval action type from updated backend response | Step approval |
| `ui/src/components/dashboard/PendingActionsBadge.tsx` | Render step approval pending actions | Step approval |
| `ui/src/components/detail/ActivityFeed.tsx` | Add SSE connection status indicator when in SSE mode | SSE status |

### New Types

Add to `ui/src/types/`:

```typescript
// In runs.ts or a new branches.ts
interface BranchStatusResponse {
  ahead: number;
  behind: number;
  mergeable: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
}

// In a new guidance.ts or runs.ts
interface GuidanceResponse {
  run_id: string;
  task_id: string | null;
  prompt: string | null;
  phase: string | null;
  mcp_url: string;
  expected_actions: string[];
}

// In runs.ts (extends existing step types)
interface StepApprovalRequest {
  approved_by: string;
  comment?: string;
}
```

### New API Client Functions

Add to `ui/src/api/client.ts`:

```typescript
approveStep(runId: string, stepId: string, data: StepApprovalRequest): Promise<TransitionResponse>
  // POST /api/runs/{id}/steps/{step_id}/approve

agentStarted(runId: string): Promise<RunResponse>
  // POST /api/runs/{id}/agent-started

agentCancelled(runId: string): Promise<RunResponse>
  // POST /api/runs/{id}/agent-cancelled

getGuidance(runId: string): Promise<GuidanceResponse>
  // GET /api/runs/{id}/guidance

transitionBack(runId: string, data: { target_step_index: number }): Promise<RunResponse>
  // POST /api/runs/{id}/transition-back  (target_step_index is zero-based integer)

getBranchStatus(runId: string): Promise<BranchStatusResponse>
  // GET /api/runs/{id}/branch-status

backMerge(runId: string): Promise<{ merge_commit: string; message: string }>
  // POST /api/runs/{id}/back-merge
```

### New Hooks

Add to `ui/src/hooks/useApi.ts`:

```typescript
useApproveStep()    // mutation → approveStep; invalidates ['run', runId]
useAgentStarted()   // mutation → agentStarted; invalidates ['run', runId]
useAgentCancelled() // mutation → agentCancelled; invalidates ['run', runId]

useGuidance(runId)  // query → getGuidance; refetchInterval: 10000 while panel open
                    // stops refetching when run is completed/failed
                    // used additively in AgentGuidancePanel (alongside useTaskPrompt)

useTransitionBack() // mutation → transitionBack; invalidates ['run', runId], ['activity', runId]

useBranchStatus(runId)  // query → getBranchStatus; enabled by WS event or manual trigger
                         // refetchOnWindowFocus: false (avoid git calls on tab switch)
useBackMerge()      // mutation → backMerge; invalidates ['run', runId]
```

### Interactions

```
RunDetail.tsx
├── Step approval (banner): sticky banner at top → StepApprovalModal → useApproveStep → POST /steps/{id}/approve
├── Step approval (inline): StepAccordion → StepApprovalModal (same modal, different trigger)
├── Branch status: BranchStatusPanel → useBranchStatus → GET /branch-status
│                                    → BackMergeDialog → useBackMerge → POST /back-merge
│                                    (refetch triggered by WebSocket run_status_changed)
└── Backward transitions: step progress bar dropdown → TransitionBackDialog → useTransitionBack
                          → POST /transition-back { target_step_index: int (zero-based) }

AgentGuidancePanel
├── "I've started my agent" button → useAgentStarted → POST /agent-started
├── Prompt text → useTaskPrompt → GET /tasks/{task_id}/prompt (kept for separated prompts + callback instructions)
└── mcp_url, expected_actions → useGuidance → GET /guidance (additive)

WaitingIndicator
└── Cancel button → useAgentCancelled → POST /agent-cancelled → run transitions to PAUSED

ActivityFeed / RunDetail
└── SSE connection status → isConnected from useActivitySSE (already available, just needs UI)

usePendingActions → GET /api/runs/{id}/pending-actions
└── Step approval gate items (after backend extension)
└── Task-level clarification and approval items (existing)
```

### Backend Changes Required

| Change | File | Reason |
|--------|------|--------|
| Extend `GET /api/runs/{id}/pending-actions` to include step approval gates | `src/orchestrator/api/routers/clarifications.py` | Step approvals not currently in response; needed for `PendingActionsBadge` |
| Change `POST /api/runs/{id}/agent-cancelled` to transition run to PAUSED | `src/orchestrator/api/routers/runs.py`, `src/orchestrator/workflow/service.py` | Currently goes to FAILED; should be PAUSED so user can restart |
| Improve docstrings for `POST /api/runs/{id}/transition-back` | `src/orchestrator/api/routers/runs.py` | Clarify that `target_step_index` is a zero-based integer array index |

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| State management | TanStack Query (existing) | All additions are server state; no new client-state library |
| Real-time (branch status) | Refetch on WebSocket `run_status_changed` event | Avoids polling on git operations; branch status only changes when run state changes |
| Guidance endpoint usage | Additive: keep `useTaskPrompt` for prompt text; add `useGuidance` for `mcp_url` + `expected_actions` | `/guidance` (run-level) and `/tasks/{id}/prompt` (task-specific + callback instructions) serve distinct purposes |
| Guidance polling | `refetchInterval: 10000` | Guidance can change between task phases; lightweight endpoint |
| SSE status indicator | Consume existing `isConnected` from `useActivitySSE` | Already emitted by the hook; just needs a UI element |
| Confirmation dialogs | Extend existing `ConfirmDialog` component | Project already has a reusable confirm dialog pattern |
| New type files | Inline in `runs.ts` or dedicated domain files | Prefer `runs.ts` for run-scoped types to avoid proliferation of small files |

## Testing Strategy

- **Unit Tests:** No Vitest component test infrastructure exists; adding it is out of scope. TypeScript compilation (`tsc --noEmit`) serves as the primary type-level check.
- **Integration Tests:** New backend tests required for:
  - `GET /api/runs/{id}/pending-actions` returning step approval gate items (after extension)
  - `POST /api/runs/{id}/agent-cancelled` transitioning run to PAUSED
- **Manual Verification:** After each step, manually walk through the relevant user story:
  - Step 2 (step approval): Create a routine with an approval gate, trigger it, confirm banner and inline prompt appear and approve works
  - Step 3 (agent lifecycle): Use user-managed agent mode, confirm "I've started" and cancel buttons work
  - Step 4 (SSE status): Observe connection indicator in activity feed in SSE mode
  - Step 5 (backward transitions): Confirm a completed step shows "go back" option and confirmation dialog appears
  - Step 6 (branch status): Confirm ahead/behind counts appear and back-merge dialog works
- **Type Safety:** `tsc --noEmit` must pass after each step's changes before proceeding
- **Regression:** Verify existing flows (create run, start, task approval, clarification, merge-back) still work after each step

## Security Considerations

- No new authentication or authorization changes. All API calls go through `fetchApi` which attaches the existing auth token.
- Auth token displayed in `AgentGuidancePanel` comes from `getAuthToken()` — no change to token handling.
- Backward transition and back-merge operations require confirmation dialogs to prevent accidental destructive actions.

## Performance Considerations

- `getBranchStatus` calls a git operation on the server; avoid polling it. Refetch only on WebSocket events, not on timer.
- `getGuidance` is lightweight (no git ops); 10s polling is acceptable when the panel is open.
- `useApproveStep`, `useAgentStarted`, `useAgentCancelled` are point-in-time mutations — no polling overhead.
- `useBranchStatus` should stop refetching when the run is completed or failed (same pattern as `useRun`).
