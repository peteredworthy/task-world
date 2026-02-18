<<<<<<< HEAD
# Architecture: frontend-gaps

## Current State

The frontend is a React 19 + TypeScript + Vite 7 application (`ui/src/`) with:
- **Pages:** Dashboard, RunDetail, RoutineLibrary, History (stubbed), Agents, Repos, NotFound
- **API layer:** `api/client.ts` with typed fetch wrappers
- **Hooks:** `hooks/useApi.ts` provides TanStack Query hooks for all current API calls
- **State:** React context providers in `context/` (theme, WebSocket, notifications)
- **Components:** ~90 TSX files organized by domain (dashboard/, detail/, guidance/, routines/, run/)
- **Styling:** TailwindCSS 4

The frontend currently calls most backend endpoints but is missing calls to: branch-status, back-merge, guidance (live), step-approve, and the merge-back strategy parameter. Some backend endpoints for clarifications/pending-actions may need frontend-side implementation.
=======
# Architecture: Close All 21 Frontend Gaps

## Current State

The frontend is a React 19 / TypeScript / Vite 7 / TailwindCSS 4 app in `ui/src/`. It uses TanStack Query for server state, React Router 7 for navigation, and a WebSocket provider for real-time updates on the RunDetail page. The codebase is organized into pages, domain-specific component directories, hooks, types, and a lib of utilities.

**Key architectural patterns already established:**
- API hooks in `hooks/useApi.ts` wrap TanStack Query `useQuery`/`useMutation` calls
- WebSocket events invalidate React Query cache keys for automatic re-rendering
- Modal state managed via React context (`CreateRunContext`, `SettingsContext`)
- Components organized by domain: `dashboard/`, `detail/`, `guidance/`, `routines/`, `run/`
- Shared components (badges, dialogs, spinners) at `components/` root level
- Types in `types/` directory with per-domain files
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5

## Proposed Changes

### New Components

<<<<<<< HEAD
| Component | Location | Purpose | Gap(s) Addressed |
|-----------|----------|---------|-----------------|
| `StepApprovalModal` | `components/detail/` | Step-level human approval with step context | #1 (High) |
| `BranchStatusPanel` | `components/detail/` | Show ahead/behind counts, divergence warning | #2 (High) |
| `BackMergeDialog` | `components/detail/` | Confirm and trigger back-merge operation | #3 (High) |
| `MergeStrategyPicker` | `components/detail/` | Radio/select for squash/merge/rebase | #4 (Medium) |
| `AttemptTimeline` | `components/detail/` | Visual build→verify→revise flow per attempt | #14 (Low) |
| `GradeThresholdExplainer` | `components/detail/` | Show threshold math when verification fails | #15 (Low) |
| `GateTypeBadge` | `components/detail/` | Badge showing gate type (human_approval, etc.) | #8 (Medium) |
| `ElapsedTime` | `components/detail/` | Live elapsed time counter during execution | #17 (Low) |
| `RoutineDetailPanel` | `components/routines/` | Rich routine view with gates, priorities, auto-verify | #12 (Low) |

### Modified Components

| Component | Changes | Gap(s) Addressed |
|-----------|---------|-----------------|
| `RunDetail.tsx` | Add BranchStatusPanel, StepApprovalModal trigger, "blocked on human" state, elapsed time | #1, #2, #3, #16, #17 |
| `AttemptHistory.tsx` | Add per-attempt token/cost columns | #5 (Medium) |
| `ActivityFeed.tsx` | Render auto-verify stdout/stderr inline | #6 (Medium) |
| `ClarificationModal.tsx` | Display `context` field from ClarificationQuestion | #7 (Medium) |
| `PendingActionsBadge.tsx` | Show gate type alongside action type | #8 (Medium) |
| `RunCard.tsx` | Add "Step X of Y" text label | #9 (Medium) |
| `History.tsx` | Replace stub with functional page | #10 (Medium) |
| `AgentGuidancePanel.tsx` | Poll guidance endpoint, render live prompt | #11 (Medium) |
| `CreateRunModal.tsx` | Accept pre-selected agent from Agents page (via URL param or context) | #13 (Low) |
| `MetricsBar.tsx` | Show elapsed time for active runs | #17 (Low) |
| `Dashboard.tsx` | SSE subscription for real-time updates | #21 (Low) |
| `StepTimeline` (or equivalent) | Handle non-linear step transitions | #20 (Low) |
=======
| Component | Path | Purpose | Gap |
|-----------|------|---------|-----|
| `StepApprovalModal` | `components/detail/StepApprovalModal.tsx` | Step-level human approval gate | 1 |
| `BranchStatusPanel` | `components/detail/BranchStatusPanel.tsx` | Shows ahead/behind counts, conflict status | 2 |
| `BackMergeDialog` | `components/detail/BackMergeDialog.tsx` | Confirm and trigger back-merge with strategy | 3 |
| `MergeStrategyPicker` | `components/detail/MergeStrategyPicker.tsx` | Shared strategy selector (squash/merge/rebase) | 4 |
| `GateTypeBadge` | `components/GateTypeBadge.tsx` | Badge showing gate type (human_approval, grade_threshold, checklist) | 8 |
| `AttemptMetrics` | `components/detail/AttemptMetrics.tsx` | Per-attempt token/cost display | 5 |
| `AutoVerifyOutput` | `components/detail/AutoVerifyOutput.tsx` | Collapsible auto-verify stdout/stderr block | 6 |
| `GradeThresholdExplainer` | `components/detail/GradeThresholdExplainer.tsx` | Shows threshold calculation and why verification failed | 15 |
| `ElapsedTimer` | `components/detail/ElapsedTimer.tsx` | Live elapsed time counter for active runs | 17 |
| `EnvFileTemplates` | `components/EnvFileTemplates.tsx` | Base env file template management in config area | 19 |
| `EnvFileOverrides` | `components/run/EnvFileOverrides.tsx` | Per-run env file overrides in CreateRunModal | 19 |

### Modified Components

| Component | Changes | Gaps |
|-----------|---------|------|
| `pages/RunDetail.tsx` | Add BranchStatusPanel, BackMergeDialog, step approval routing, blocked-on-human state | 1, 2, 3, 16 |
| `pages/History.tsx` | Replace "Coming soon" with functional history page | 10 |
| `pages/Dashboard.tsx` | Add WebSocket/SSE for real-time updates | 21 |
| `pages/RoutineLibrary.tsx` | Show gate types, priorities, auto-verify commands in routine detail; add validate button | 12, 18 |
| `pages/Agents.tsx` | Add "Create run with this agent" action | 13 |
| `components/detail/ApprovalModal.tsx` | No changes (step approval handled by new StepApprovalModal) | — |
| `components/detail/ClarificationModal.tsx` | Render `context` field from ClarificationQuestion | 7 |
| `components/detail/ActivityFeed.tsx` | Embed AutoVerifyOutput in auto-verify events | 6 |
| `components/detail/AttemptHistory.tsx` | Add AttemptMetrics per attempt, visual connectors (arrows/flow indicators) between attempts | 5, 14 |
| `components/detail/ChecklistTable.tsx` | Add GradeThresholdExplainer when verification fails | 15 |
| `components/detail/MetricsBar.tsx` | Add ElapsedTimer for active runs | 17 |
| `components/dashboard/RunCard.tsx` | Add "Step X of Y" text alongside StepTimeline | 9 |
| `components/dashboard/StepTimeline.tsx` | Visualize non-linear transitions (backward jumps) | 20 |
| `components/dashboard/PendingActionsBadge.tsx` | Show gate type in badge tooltip/label | 8 |
| `components/StatusBadge.tsx` | Add blocked-on-human variant | 16 |
| `components/guidance/AgentGuidancePanel.tsx` | Poll live guidance endpoint, render prompt + expected actions | 11 |
| `context/CreateRunContext.tsx` | Accept pre-filled agent type from Agents page navigation | 13 |

### New Hooks / API Additions

Add to `hooks/useApi.ts`:

```typescript
// Gap 2: Branch status
useBranchStatus(runId) → GET /api/runs/{id}/branch-status
  // Returns: { behind_count, ahead_count, can_merge_cleanly, has_conflicts, source_branch, run_branch }
  // Refetch: on page load + on WebSocket `run_status_changed` events (no polling)

// Gap 3: Back-merge
useBackMerge() → POST /api/runs/{id}/back-merge
  // Returns: { merge_commit, message }

// Gap 1: Step approval
useApproveStep() → POST /api/runs/{id}/steps/{step_id}/approve
  // Body: { approved_by, comment }

// Gap 11: Live guidance
useGuidance(runId) → GET /api/runs/{id}/guidance
  // Returns: { run_id, task_id, prompt, phase, mcp_url, expected_actions }
  // Refetch: 10s when guidance panel open

// Gap 18: Routine validation
useValidateRoutine() → POST /api/routines/validate
  // Body: { yaml_content }
  // Returns: { valid, errors, builder_feedback }

// Gap 19: Env files
useEnvFiles(runId) → GET /api/runs/{id}/env-files
useEnvFileSnapshots(runId) → GET /api/runs/{id}/env-files/snapshots
useRevertEnvFile() → POST /api/runs/{id}/env-files/revert
useCopyBackEnvFile() → POST /api/runs/{id}/env-files/copy-back
```

### Type Additions

Add to `types/`:

```typescript
// types/branches.ts
interface BranchStatus {
  behind_count: number;
  ahead_count: number;
  can_merge_cleanly: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
}

// types/steps.ts (extend existing)
interface StepApprovalRequest {
  approved_by: string;
  comment?: string;
}

// types/guidance.ts
interface GuidanceResponse {
  run_id: string;
  task_id: string | null;
  prompt: string | null;
  phase: string | null;
  mcp_url: string;
  expected_actions: string[];
}

// types/envfiles.ts
interface EnvFileSnapshot { ... }
interface RevertEnvFileRequest { ... }
interface CopyBackRequest { ... }

// types/routines.ts (extend existing)
interface ValidateRoutineRequest { yaml_content: string; }
interface ValidateRoutineResponse { valid: boolean; errors: string[]; builder_feedback: string[]; }
```
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5

### Interactions

```
<<<<<<< HEAD
Dashboard ──SSE──→ Backend (replaces polling)
RunDetail ──WS/SSE──→ Backend (existing, enhanced)
RunDetail ──GET /branch-status──→ Backend (new, polling 30s)
RunDetail ──POST /back-merge──→ Backend (new, user-triggered)
RunDetail ──POST /steps/{id}/approve──→ Backend (new)
RunDetail ──POST /merge-back + strategy──→ Backend (enhanced)
AgentGuidancePanel ──GET /guidance──→ Backend (new, polling)
History ──GET /runs?status=completed──→ Backend (existing, new filters)
RoutineLibrary ──POST /routines/validate──→ Backend (new)
=======
RunDetail page
├── BranchStatusPanel ──→ useBranchStatus (fetches on load, refetches on WS events)
│   └── BackMergeDialog ──→ useBackMerge (POST /back-merge)
│       └── MergeStrategyPicker (shared)
├── StepApprovalModal ──→ useApproveStep (POST /steps/{id}/approve)
├── ActivityFeed
│   └── AutoVerifyOutput (inline in events)
├── AttemptHistory
│   ├── AttemptMetrics (per attempt)
│   └── Visual connectors (arrows between attempts)
├── ChecklistTable
│   └── GradeThresholdExplainer
├── MetricsBar
│   └── ElapsedTimer
├── (Env file management moved to config area — see Settings/Config page)
└── AgentGuidancePanel ──→ useGuidance (polls GET /guidance)

Dashboard page
├── RunCard ──→ "Step X of Y" text
├── StepTimeline ──→ non-linear visualization
└── WebSocket/SSE ──→ live run status updates

RoutineLibrary page
├── Rich routine detail ──→ gate types, priorities
└── Validate button ──→ useValidateRoutine

Agents page
└── "Create run" button ──→ navigate to Dashboard with agent pre-filled

Config/Settings area
└── EnvFileTemplates ──→ useEnvFiles (base env file template CRUD)

CreateRunModal
└── EnvFileOverrides ──→ select base template + override values per-run
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5
```

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
<<<<<<< HEAD
| Branch status polling | TanStack Query `refetchInterval: 30000` | Consistent with existing patterns; automatic cache invalidation |
| SSE for dashboard | `EventSource` wrapped in custom hook | Already used for activity stream; simpler than WebSocket for one-way data |
| Elapsed time | `useEffect` with `setInterval(1000)` | Standard pattern; `Date.now() - run.started_at` |
| Merge strategy | Radio group in dialog | Simple, fits existing modal patterns |
| History page | New page with shared RunCard component | Reuse RunCard but add date/outcome-specific filters |

## Testing Strategy

- **Unit Tests (Vitest):** New components get unit tests with `@testing-library/react`. Test rendering, user interactions, and edge cases (empty states, loading, errors). Mock API responses at the hook level using TanStack Query's test utilities.
- **Integration Tests:** Test hooks against MSW (Mock Service Worker) or direct API mocking to verify correct endpoint calls and response handling.
- **E2E Tests:** Not in scope for this feature — existing E2E coverage applies.

## Security Considerations

- Env file management (if implemented) must never display raw secret values — always mask
- Branch operations (back-merge, merge-back) should confirm before executing to prevent accidental merges
- Step/task approval should prevent double-submit (disable button after click, optimistic update)

## Performance Considerations

- SSE on dashboard replaces 10s polling — reduces unnecessary requests but maintains a persistent connection per client
- Branch status polling at 30s is lightweight (single GET returning counts)
- History page should paginate — completed runs could number in hundreds
- ElapsedTime `setInterval` should be cleaned up on unmount to prevent memory leaks
=======
| State management | TanStack Query (existing) | All new features are server-state; no new client-state library needed |
| Real-time (RunDetail) | WebSocket (existing) | Already wired up; just add cache invalidation for new query keys |
| Real-time (Dashboard) | Dashboard-level WebSocket/SSE aggregate channel | Single connection for all runs; may need new backend endpoint (Q4→B) |
| Elapsed timer | `useEffect` + `setInterval` | Simple client-side timer; no server dependency |
| Strategy picker | Native `<select>` with TailwindCSS | Consistent with existing form patterns in CreateRunModal |
| Auto-verify output | `<pre>` with collapsible wrapper | Matches log viewer patterns already in the codebase |

## Testing Strategy

- **Unit Tests:** Not applicable — this project has no frontend unit test infrastructure (no Vitest test files exist). Adding test infra is out of scope per the intent document.
- **Integration Tests:** Backend API integration tests already exist for all endpoints being wired. No new backend tests needed.
- **E2E Tests:** Manual verification against the four user stories after each milestone. Walk through each story journey in the UI to confirm gaps are closed.
- **Type Safety:** `tsc --noEmit` must pass after every step. TypeScript catches API contract mismatches at compile time.
- **Lint/Format:** `uv run pre-commit run --all-files` must pass (includes frontend linting if configured).
- **Regression:** Verify existing UI flows (create run, start, pause, resume, clarification, task approval, merge-back) still work after each milestone.

## Security Considerations

- No new authentication or authorization changes. All new API calls go through the existing `api/client.ts` which handles auth headers.
- Env file management UI displays file names and snapshot metadata but does not render env file contents in the browser (values stay server-side).
- User input in approval comments and clarification responses is already sanitized by the backend.

## Performance Considerations

- Branch status fetches on page load and on WebSocket events — no continuous polling overhead. Stops when run is completed/failed.
- Dashboard WebSocket aggregate channel adds one connection per browser tab. Falls back to polling if connection fails.
- Auto-verify output can be large. Render inside a collapsible block with max-height and overflow scroll to avoid layout thrash.
- History page should use pagination (cursor-based, matching existing `useActivity` pattern) to avoid loading all completed runs at once.
- Live elapsed timer uses `requestAnimationFrame` or 1s interval — negligible CPU impact.
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5
