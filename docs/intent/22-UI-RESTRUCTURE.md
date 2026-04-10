# UI Restructure: Inspector on Dashboard, Rich Task Details

## Overview

Restructure the UI so the Dashboard is the primary interaction surface with an
inspector panel, and the Run Detail page ("logs view") shows rich, expandable
task information without the inspector.

---

## Requirement 1 — Inspector on Dashboard

When a user clicks a task inside an expanded RunCard on the Dashboard, open the
InspectorPanel on the right side of the Dashboard page.

### Acceptance criteria

- [x] Dashboard page renders an `InspectorPanel` when a task is selected.
- [x] Selecting a task in any expanded RunCard opens the inspector with that
      task's data (checklist, attempts, grades).
- [x] The inspector uses the existing `InspectorPanel` component (or its
      successor), fetching data via `useTask(runId, taskId)`.
- [x] Clicking a different task switches the inspector to the new task.
- [x] Clicking the same task again (or the close button) dismisses the
      inspector.
- [x] The inspector slides in from the right and the main content area narrows
      to accommodate it (same pattern used on RunDetail today).

---

## Requirement 2 — Remove Inspector from Run Detail Page

The Run Detail page ("logs view") no longer needs the inspector panel.

### Acceptance criteria

- [x] `InspectorPanel` is no longer rendered inside `RunDetail.tsx`.
- [x] `selectedTask` state and `handleSelectTaskById` / `handleCloseInspector`
      are removed from `RunDetailInner`.
- [x] `onSelectTask` / `selectedTaskId` props are removed from `ActivityFeed`
      and `UpcomingPlan` on this page.
- [x] Task cards in the activity feed are no longer clickable/selectable on the
      detail page (they become informational only).

---

## Requirement 3 — Remove Link from Run Name in Dashboard RunCard Bar

Currently the run name in the collapsed RunCard row is a `<Link>` that navigates
to `/runs/:id`. Replace it so clicking the name expands/collapses the card, same
as clicking anywhere else on the bar.

### Acceptance criteria

- [x] The run name in both `CollapsedRow` and `ExpandedView` header is a
      `<span>` (not a `<Link>`), styled the same.
- [x] Clicking the name triggers `onToggle` (expand/collapse), not navigation.
- [x] There is still a way to navigate to the detail/logs view (e.g. "View
      Logs" link in the expanded card footer, or an icon button).
- [x] Existing tests that reference `<Link>` in the RunCard are updated.

---

## Requirement 4 — Rich Task Detail in Run Detail ("Logs View")

Each task in the activity feed on the Run Detail page becomes an expandable card
with comprehensive information.

### 4a — Collapsed state (default)

Show a compact single-line bar containing:

- Status icon (dot/check/x)
- Task title
- Compact grade summary (colored letter badges for each requirement)
- Attempt count if > 1 (e.g. "x3")
- Status badge (COMPLETED / FAILED / BUILDING / etc.)

### 4b — Expanded state (on click)

Clicking the bar toggles open a detail panel showing all available information
grouped into sections:

#### Grades & Requirements

- Full checklist table: requirement description, priority, status, grade letter,
  grade reason.
- Grouped by priority (Critical / Expected / Optional).

#### Attempt History

- Each attempt as a collapsible sub-section.
- Attempt number, outcome badge (Passed/Revision/Failed), duration, token
  counts.
- Grade snapshot per attempt (showing how grades changed across attempts).

#### Builder Prompt

- The system + user prompt given to the builder agent.
- Fetched via `GET /api/runs/{runId}/tasks/{taskId}/prompt`.
- Rendered in a scrollable monospace block with copy button.

#### Verifier Feedback

- Verifier comment for each attempt (what the verifier said).
- Requires backend change: expose `verifier_comment` on `AttemptSchema`.

#### Event Timeline

- The existing event timeline (status transitions, gate evaluations, grade
  evaluations) for this task, extracted from the activity events.

### Acceptance criteria

- [x] Task cards default to collapsed state showing grades in bar.
- [x] Clicking a task card toggles it between collapsed and expanded.
- [x] Expanded view shows: grades/requirements table, attempt history with
      metrics, builder prompt, verifier comments, and event timeline.
- [x] Builder prompt is fetched lazily (only when expanded and that section is
      opened).
- [x] Verifier comments are visible per attempt.
- [x] Multiple tasks can be expanded simultaneously.

---

## Requirement 5 — Backend: Expose Attempt Prompts and Verifier Comments

The `Attempt` model already stores `builder_prompt`, `verifier_prompt`, and
`verifier_comment` but the API doesn't return them.

### Acceptance criteria

- [x] `AttemptSchema` gains optional fields: `builder_prompt`, `verifier_prompt`,
      `verifier_comment`.
- [x] `GET /api/runs/{runId}/tasks/{taskId}` returns these fields on each attempt.
- [x] Frontend `AttemptSchema` type is updated to include these fields.
- [x] Existing backend tests still pass.

---

## Issues Found During Implementation

1. **Shared components extraction**: `ChecklistGrades` and `AttemptTimeline` were
   inlined in `InspectorPanel.tsx`. Extracted to `ui/src/components/detail/shared.tsx`
   so both `InspectorPanel` (Dashboard) and `TaskDetailCard` (Run Detail) can
   reuse them.

2. **TaskCard event propagation**: Added `stopPropagation()` to `TaskCard` click
   handler in `RunCard.tsx` to prevent clicks from bubbling up to the card
   header's collapse/expand handler.

---

## Files Expected to Change

### Backend
- `src/orchestrator/api/schemas/tasks.py` — add fields to AttemptSchema
- `src/orchestrator/api/routers/tasks.py` — pass new fields in response

### Frontend — Components
- `ui/src/pages/Dashboard.tsx` — add inspector state + panel
- `ui/src/pages/RunDetail.tsx` — remove inspector, make tasks non-selectable
- `ui/src/components/dashboard/RunCard.tsx` — remove Link from name, add task
  click handler
- `ui/src/components/detail/ActivityFeed.tsx` — make task cards expandable with
  rich detail
- `ui/src/components/detail/TaskDetailCard.tsx` — NEW: expandable task card with
  all sections

### Frontend — Types
- `ui/src/types/tasks.ts` — add new fields to AttemptSchema

### Frontend — Tests
- `ui/tests/components/RunCard.test.tsx` — update Link → span expectations
- `ui/src/lib/activity.test.ts` — update if grouping logic changes
- New tests for the expandable TaskDetailCard component

### Docs
- `docs/intent/22-UI-RESTRUCTURE.md` — this file
