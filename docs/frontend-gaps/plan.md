<<<<<<< HEAD
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
=======
# Plan: Close All 21 Frontend Gaps

## Overview

Implement all 21 frontend gaps identified in the gap analysis, organized into iterative milestones that deliver value incrementally. Each milestone produces a fully functional UI increment -- HIGH-severity gaps first (story-blocking), then MEDIUM (story-degrading), then LOW (polish). All work is frontend-only in `ui/src/`, wiring to existing backend API endpoints.

## Milestones

### Milestone 1: HIGH Gaps — Story-Blocking (3 gaps)

Unblock the three user story journeys that currently cannot be completed through the web UI.

- **Gap 1: Step-level approval UI** — Add step gate approval flow to RunDetail, distinct from task-level approval. Detect `step_approval` pending actions and route to `POST /api/runs/{id}/steps/{step_id}/approve`.
- **Gap 2: Branch status display** — Add a BranchStatusPanel to RunDetail that fetches `GET /api/runs/{id}/branch-status` on page load and refetches on WebSocket `run_status_changed` events (not polling). Shows ahead/behind counts, conflict warnings, source branch name.
- **Gap 3: Back-merge UI** — Add a back-merge button/dialog on RunDetail (visible when run is ACTIVE or PAUSED) that calls `POST /api/runs/{id}/back-merge` with confirmation.

### Milestone 2: MEDIUM Gaps — Story-Degrading (8 gaps)

Improve transparency and control for all four story journeys.

- **Gap 4: Merge strategy selection** — Add strategy picker (squash/merge/rebase) to the merge-back dialog on RunDetail and to CreateRunModal's advanced config.
- **Gap 5: Per-attempt cost breakdown** — Extend AttemptHistory to show token counts (read/write) and estimated cost per attempt from `attempts_summary` data.
- **Gap 6: Auto-verify output surfacing** — Display auto-verify stdout/stderr as a collapsible code block within the auto-verify event in ActivityFeed. Collapsed by default, expandable inline.
- **Gap 7: Clarification context display** — Render the `context` field from ClarificationQuestion in ClarificationModal, above the options.
- **Gap 8: Gate type indication** — Add gate type badges (human_approval, grade_threshold, checklist) to pending action displays and step progress indicators.
- **Gap 9: Textual step progress on dashboard** — Add "Step X of Y" text to RunCard alongside the existing visual StepTimeline.
- **Gap 10: History page implementation** — Replace the "Coming soon" stub with a functional history page: completed/failed runs, date range filter, outcome summaries, search.
- **Gap 11: Live guidance rendering** — Make AgentGuidancePanel poll `GET /api/runs/{id}/guidance` and display the current prompt, phase, and expected actions in real-time.

### Milestone 3: LOW Gaps — Polish & Friction (10 gaps)

Remove minor friction points and add missing visual feedback.

- **Gap 12: Rich routine inspection** — Show gate types, auto-verify commands, and requirement priorities in RoutineLibrary detail view.
- **Gap 13: Agents → CreateRunModal flow** — Add "Create run with this agent" action on Agents page that pre-fills CreateRunModal.
- **Gap 14: Visual revision loop indicator** — Keep flat attempt list in AttemptHistory but add visual connectors (arrows, status flow indicators) between attempts to show the build→verify→revise cycle.
- **Gap 15: Grade threshold explanation** — Show threshold calculation (average score vs threshold, critical item failures) when verification fails.
- **Gap 16: Blocked-on-human visual state** — Add a distinct visual state (badge, icon, color) when a run is ACTIVE but blocked on human input.
- **Gap 17: Elapsed time during execution** — Add a live elapsed time counter to MetricsBar for active runs.
- **Gap 18: Routine validation UI** — Add "Validate" button in RoutineLibrary that calls `POST /api/routines/validate` and shows results.
- **Gap 19: Env file management UI** — Add env file management in the config/settings area as base env file templates that can be referenced when creating runs. The CreateRunModal should allow overriding and adjusting env file values per-run.
- **Gap 20: Conditional step transitions** — Visualize non-linear step transitions (backward jumps) in the step progress bar with arrows or annotations.
- **Gap 21: Real-time dashboard updates** — Add a dashboard-level WebSocket/SSE channel that broadcasts status changes for all runs, replacing 10s polling. May require a new backend endpoint.

### New Gap (from human feedback)

- **Gap 22: Design-question UI** — Add a mechanism for the LLM to define questions in a structured format that the frontend can present to users, capturing answers and feeding them back to the orchestrator. This enables human-in-the-loop workflows during planning phases. (See Q8 in design-questions.md)

## Implementation Order

1. **Step 1: Step-level approval (Gap 1)**
   - Prerequisites: None
   - Deliverables: StepApprovalModal component, updated pending action routing in RunDetail, `useApproveStep` hook, step approval types
   - Files: `components/detail/StepApprovalModal.tsx`, `pages/RunDetail.tsx`, `hooks/useApi.ts`, `types/index.ts`

2. **Step 2: Branch status + back-merge (Gaps 2, 3)**
   - Prerequisites: None (parallel with Step 1)
   - Deliverables: BranchStatusPanel component, BackMergeDialog component, `useBranchStatus` and `useBackMerge` hooks
   - Files: `components/detail/BranchStatusPanel.tsx`, `components/detail/BackMergeDialog.tsx`, `hooks/useApi.ts`, `pages/RunDetail.tsx`

3. **Step 3: Merge strategy + clarification context + gate types (Gaps 4, 7, 8)**
   - Prerequisites: Step 2 (merge dialog exists)
   - Deliverables: Strategy picker in merge dialog, context rendering in ClarificationModal, GateTypeBadge component
   - Files: `components/detail/BackMergeDialog.tsx`, `components/detail/ClarificationModal.tsx`, `components/GateTypeBadge.tsx`, `components/dashboard/PendingActionsBadge.tsx`

4. **Step 4: Attempt cost + auto-verify output + step progress text (Gaps 5, 6, 9)**
   - Prerequisites: None
   - Deliverables: Per-attempt metrics in AttemptHistory, auto-verify output block in ActivityFeed, "Step X of Y" in RunCard
   - Files: `components/detail/AttemptHistory.tsx`, `components/detail/ActivityFeed.tsx`, `components/dashboard/RunCard.tsx`

5. **Step 5: History page + live guidance (Gaps 10, 11)**
   - Prerequisites: None
   - Deliverables: Functional History page, live guidance polling in AgentGuidancePanel
   - Files: `pages/History.tsx`, `components/guidance/AgentGuidancePanel.tsx`, `hooks/useApi.ts`

6. **Step 6: Routine detail + agents flow + revision viz (Gaps 12, 13, 14)**
   - Prerequisites: None
   - Deliverables: Rich routine detail rendering, agent pre-fill flow, attempt timeline visualization
   - Files: `pages/RoutineLibrary.tsx`, `pages/Agents.tsx`, `components/detail/AttemptHistory.tsx`, `context/CreateRunContext.tsx`

7. **Step 7: Grade threshold + blocked state + elapsed time (Gaps 15, 16, 17)**
   - Prerequisites: None
   - Deliverables: Threshold explanation panel, blocked-on-human badge, live timer
   - Files: `components/detail/ChecklistTable.tsx`, `components/StatusBadge.tsx`, `components/detail/MetricsBar.tsx`

8. **Step 8: Validation + env files + transitions + dashboard WS (Gaps 18, 19, 20, 21)**
   - Prerequisites: None
   - Deliverables: Validate button, env file config management + CreateRunModal env overrides, non-linear step viz, dashboard WebSocket aggregate channel
   - Files: `pages/RoutineLibrary.tsx`, `pages/Settings.tsx` (or config area), `components/EnvFileTemplates.tsx`, `components/run/CreateRunModal.tsx`, `components/dashboard/StepTimeline.tsx`, `pages/Dashboard.tsx`, `hooks/useApi.ts`
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
<<<<<<< HEAD
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
=======
| Milestone ordering | HIGH → MEDIUM → LOW | Unblock story journeys first, then improve them, then polish |
| Step-level vs task-level approval | Separate `StepApprovalModal` component (Q1→A) | Different API endpoint, different context; avoid overloading ApprovalModal. [HUMAN] |
| Branch status refresh strategy | Fetch on load + WebSocket event-driven (Q2→B) | Avoids unnecessary polling; refreshes when state actually changes. [HUMAN] |
| History page approach | Dedicated page (Q3→A) | Replace stub entirely; reuse existing RunCard for display. [HUMAN] |
| Dashboard real-time | Dashboard-level WebSocket/SSE aggregate channel (Q4→B) | Single connection for all runs; may need new backend endpoint. [HUMAN] |
| Env file UI | Config area with CreateRunModal overrides (Q5→custom) | Base templates in config, per-run overrides during creation. [HUMAN] |
| Auto-verify output | Collapsible code block in ActivityFeed (Q6→A) | Collapsed by default, expandable inline. [HUMAN] |
| Attempt timeline viz | Flat list with visual connectors (Q7→C) | Lowest effort, adds arrows/flow indicators between attempts. [HUMAN] |

## References

- `docs/stories/GAP-ANALYSIS-FRONTEND.md` — Full gap list with severity and context
- `docs/planner/templates/plan.md` — Plan template
- `docs/plan-runner/idea_to_plan_detailed.md` — Planning principles
- `ui/src/hooks/useApi.ts` — Existing API hooks
- `ui/src/pages/RunDetail.tsx` — Primary page for most changes
- `src/orchestrator/api/routers/` — Backend endpoint implementations
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5
