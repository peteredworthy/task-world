# Plan: frontend-gaps

## Overview

Close all 21 frontend gaps in 7 implementation steps, ordered by severity and dependency. Each step produces a shippable increment — the UI gets progressively more capable. Steps are grouped so that shared infrastructure (new hooks, types, API client methods) is built first and consumed by later steps.

## Milestones

### Milestone 1: Critical Path (Steps 1-2)

Unblock the three user story journeys that are currently broken:
- Step 1: API client + hooks foundation (branch-status, back-merge, merge-back with strategy, step approval, pending-actions enrichment)
- Step 2: High-severity UI — step-level approval, branch status display, back-merge dialog

### Milestone 2: Transparency (Steps 3-4)

Make the revision loop and human-in-the-loop stories comprehensible:
- Step 3: Revision loop improvements — per-attempt costs, auto-verify output, grade threshold math, visual timeline
- Step 4: Human-in-the-loop improvements — clarification context, gate type badges, "blocked on human" state

### Milestone 3: Git & Navigation (Step 5)

Complete the long-running run story:
- Step 5: Merge strategy picker, textual step progress, history page, elapsed time

### Milestone 4: Polish & Real-time (Steps 6-7)

Close remaining low-severity gaps and add real-time updates:
- Step 6: Routine inspection, agent flow, guidance panel, validation, env files
- Step 7: Dashboard SSE streaming, conditional step transitions

## Implementation Order

1. **Step 1: API Client & Hook Extensions**
   - Prerequisites: None
   - Deliverables: New API client methods for branch-status, back-merge, merge-back (with strategy param), step-approve, guidance polling; new/updated hooks; updated TypeScript types
   - Files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/runs.ts`, new `ui/src/hooks/useBranchStatus.ts`, new `ui/src/hooks/useGuidance.ts`

2. **Step 2: High-Severity UI Components**
   - Prerequisites: Step 1
   - Deliverables: StepApprovalModal, BranchStatusPanel, BackMergeDialog, updated RunDetail page wiring
   - Files: new `ui/src/components/detail/StepApprovalModal.tsx`, new `ui/src/components/detail/BranchStatusPanel.tsx`, new `ui/src/components/detail/BackMergeDialog.tsx`, modified `ui/src/pages/RunDetail.tsx`

3. **Step 3: Revision Loop Enhancements**
   - Prerequisites: Step 1
   - Deliverables: Per-attempt cost in AttemptHistory, auto-verify output in ActivityFeed, grade threshold explanation, visual attempt timeline
   - Files: modified `ui/src/components/detail/AttemptHistory.tsx`, modified `ui/src/components/detail/ActivityFeed.tsx`, new `ui/src/components/detail/GradeThresholdExplainer.tsx`, new `ui/src/components/detail/AttemptTimeline.tsx`

4. **Step 4: Human-in-the-Loop Enhancements**
   - Prerequisites: Step 1
   - Deliverables: Clarification context display, gate type badges, "waiting for human" state indicator
   - Files: modified `ui/src/components/detail/ClarificationModal.tsx`, new `ui/src/components/detail/GateTypeBadge.tsx`, modified `ui/src/pages/RunDetail.tsx`, modified `ui/src/components/dashboard/PendingActionsBadge.tsx`

5. **Step 5: Long-Running Run Enhancements**
   - Prerequisites: Step 2 (merge strategy needs merge-back flow)
   - Deliverables: MergeStrategyPicker, textual step progress on RunCard, functional History page, elapsed time display
   - Files: new `ui/src/components/detail/MergeStrategyPicker.tsx`, modified `ui/src/components/dashboard/RunCard.tsx`, rewritten `ui/src/pages/History.tsx`, new `ui/src/components/detail/ElapsedTime.tsx`, modified `ui/src/components/detail/MetricsBar.tsx`

6. **Step 6: Routine & Agent Polish**
   - Prerequisites: Step 1
   - Deliverables: Rich routine inspection (gate types, priorities, auto-verify), agent→run creation flow, live guidance panel, routine validation button, env file management
   - Files: modified `ui/src/pages/RoutineLibrary.tsx`, new `ui/src/components/routines/RoutineDetailPanel.tsx`, modified `ui/src/components/dashboard/CreateRunModal.tsx`, modified `ui/src/components/guidance/AgentGuidancePanel.tsx`, new `ui/src/pages/EnvFiles.tsx` or section in settings

7. **Step 7: Real-time & Edge Cases**
   - Prerequisites: Steps 2-6
   - Deliverables: Dashboard SSE streaming (replace polling), conditional step transition visualization in StepTimeline
   - Files: new `ui/src/hooks/useDashboardStream.ts`, modified `ui/src/pages/Dashboard.tsx`, modified `ui/src/components/detail/StepTimeline.tsx` (or equivalent)

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Step approval vs task approval separation | Separate StepApprovalModal component | Step gates have different semantics (block all tasks vs one task); separate modal avoids overloading ApprovalModal |
| Branch status polling interval | 30s with manual refresh button | Balance between freshness and API load; divergence doesn't change rapidly |
| History page approach | Build functional page, not just filter existing dashboard | Story 04 implies distinct UX with date ranges and outcome summaries; dashboard filters are insufficient |
| SSE vs WebSocket for dashboard | SSE | Dashboard needs one-way server→client updates; SSE is simpler, already used for activity stream |
| Merge strategy UI placement | Inline in merge-back dialog, not a separate settings page | Strategy is a per-merge decision, not a global setting |

## References

- `docs/stories/GAP-ANALYSIS-FRONTEND.md` — source gap analysis
- `docs/intent/16-SLICES-PHASE-6.md` — original Phase 6 frontend spec
- `ui/src/api/client.ts` — existing API client
- `ui/src/hooks/useApi.ts` — existing hooks
- Backend routers: `src/orchestrator/api/routers/runs.py`, `tasks.py`
