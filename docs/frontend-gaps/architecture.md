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

## Proposed Changes

### New Components

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

### Interactions

```
Dashboard ──SSE──→ Backend (replaces polling)
RunDetail ──WS/SSE──→ Backend (existing, enhanced)
RunDetail ──GET /branch-status──→ Backend (new, polling 30s)
RunDetail ──POST /back-merge──→ Backend (new, user-triggered)
RunDetail ──POST /steps/{id}/approve──→ Backend (new)
RunDetail ──POST /merge-back + strategy──→ Backend (enhanced)
AgentGuidancePanel ──GET /guidance──→ Backend (new, polling)
History ──GET /runs?status=completed──→ Backend (existing, new filters)
RoutineLibrary ──POST /routines/validate──→ Backend (new)
```

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
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
