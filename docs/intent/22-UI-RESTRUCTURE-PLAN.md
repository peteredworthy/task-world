# Implementation Plan: UI Restructure

Reference: `docs/intent/22-UI-RESTRUCTURE.md`

---

## Phase 1 — Backend: Expose Attempt Details (Req 5)

**Goal:** Make builder_prompt, verifier_prompt, and verifier_comment available
via the task detail API.

### Step 1.1 — Update AttemptSchema

File: `src/orchestrator/api/schemas/tasks.py`

Add three optional string fields to `AttemptSchema`:

```python
builder_prompt: str | None = None
verifier_prompt: str | None = None
verifier_comment: str | None = None
```

### Step 1.2 — Pass fields in router

File: `src/orchestrator/api/routers/tasks.py`

In `get_task()`, the `AttemptSchema(...)` construction already maps from the
`Attempt` model. Add the three new fields:

```python
builder_prompt=att.builder_prompt,
verifier_prompt=att.verifier_prompt,
verifier_comment=att.verifier_comment,
```

### Step 1.3 — Update frontend types

File: `ui/src/types/tasks.ts`

Add to `AttemptSchema`:

```typescript
builder_prompt: string | null;
verifier_prompt: string | null;
verifier_comment: string | null;
```

### Step 1.4 — Verify

- Run `uv run pytest tests/ -x -q` — all backend tests pass.
- Run `cd ui && npx vitest run` — all frontend tests pass.
- `curl` the task detail endpoint and confirm the new fields appear.

---

## Phase 2 — Remove Inspector from Run Detail (Req 2)

**Goal:** Strip the inspector panel and task-selection logic from RunDetail.

### Step 2.1 — Simplify RunDetailInner

File: `ui/src/pages/RunDetail.tsx`

- Remove `selectedTask` state, `handleSelectTaskById`, `handleCloseInspector`.
- Remove `InspectorPanel` import and render.
- Remove `onSelectTask` and `selectedTaskId` props from `<ActivityFeed>` and
  `<UpcomingPlan>`.
- Remove conditional `pr-0` class based on `selectedTask`.
- Remove the `useEffect` that syncs `selectedTask` with run data.

### Step 2.2 — Make ActivityFeed non-interactive on detail page

File: `ui/src/components/detail/ActivityFeed.tsx`

The `ActivityFeed` component currently accepts optional `onSelectTask` and
`selectedTaskId` props. When these are not provided, task cards should not
render as buttons. Change `TaskGroupCard` and `ActiveTaskCard`:

- When `onSelect` is undefined, render as `<div>` instead of `<button>`.
- Remove `aria-pressed`, click handler, and hover styles when not selectable.

### Step 2.3 — Verify

- Navigate to any run detail page — no inspector panel, tasks are not
  clickable/selectable.
- No console errors.

---

## Phase 3 — Remove Link from RunCard Name (Req 3)

**Goal:** Clicking the run name expands/collapses the card instead of navigating.

### Step 3.1 — Replace Link with span in CollapsedRow and ExpandedView

File: `ui/src/components/dashboard/RunCard.tsx`

In `CollapsedRow`: change the `<Link to={'/runs/' + run.id}>` wrapping the run
name to a `<span>`. Keep the same CSS classes minus the `hover:text-accent-purple`
(or keep it for consistency). Remove `onClick={e => e.stopPropagation()}`.

In `ExpandedView`: same change for the header run name.

The "View Logs" link in the expanded footer already provides navigation.

### Step 3.2 — Update RunCard tests

File: `ui/tests/components/RunCard.test.tsx`

Update any tests that expect a `<Link>` for the run name. They should now expect
a `<span>` or look for the text without expecting a link role.

### Step 3.3 — Verify

- Dashboard: clicking run name expands/collapses.
- "View Logs" link in expanded footer still navigates to detail page.

---

## Phase 4 — Rich Expandable Task Cards on Run Detail (Req 4)

**Goal:** Replace the current task cards in the activity feed with expandable
cards that show comprehensive detail.

### Step 4.1 — Create TaskDetailCard component

File: `ui/src/components/detail/TaskDetailCard.tsx` (NEW)

A self-contained expandable card component:

**Props:**
```typescript
interface TaskDetailCardProps {
  taskId: string;
  taskTitle: string;
  stepTitle: string;
  status: string;
  events: ActivityEvent[];        // events for this task
  gradeSummary: GradeSummaryItem[]; // from RunResponse task summary
  attemptsSummary: AttemptOutcome[];
  runId: string;
  defaultExpanded?: boolean;
}
```

**Collapsed bar:** (single row, ~40px height)
- Status icon (dot/check/x based on status)
- Task title (bold)
- Step title (muted, small)
- Compact grade badges (colored letters: A, B, C, etc.)
- Attempt badge if > 1 ("x3")
- Status badge (COMPLETED / BUILDING / etc.)
- Chevron indicator (rotates on expand)

**Expanded detail:** (appears below the bar on click)

Uses `useTask(runId, taskId)` to fetch full detail (lazy, only when expanded).
Uses `useTaskPrompt(runId, taskId)` to fetch prompt (lazy, only when prompt
section is opened).

Sections (each with a header):

1. **Grades & Requirements** — `ChecklistGrades` component (reuse from
   InspectorPanel, move to shared location).
2. **Attempt History** — For each attempt: number, outcome, duration, tokens,
   grade snapshot. If `verifier_comment` is present, show it.
3. **Builder Prompt** — Collapsible section. System prompt + user prompt in
   monospace blocks with copy buttons. Loaded lazily.
4. **Event Timeline** — The existing event list for this task (status changes,
   gate evaluations, grade evaluations) with timestamps.

### Step 4.2 — Update ActivityFeed to use TaskDetailCard

File: `ui/src/components/detail/ActivityFeed.tsx`

Replace `TaskGroupCard` rendering with `TaskDetailCard` when on the detail page
(when `onSelectTask` is not provided). Pass the task's events, grade summary,
and run ID.

To get `gradeSummary` and `attemptsSummary` for each task, the `ActivityFeed`
needs access to the run data. Add an optional `run` prop:

```typescript
interface ActivityFeedProps {
  events: ActivityEvent[];
  activeTasks?: ActiveTask[];
  onSelectTask?: (taskId: string) => void;
  selectedTaskId?: string | null;
  run?: RunResponse;    // NEW — needed for grade summaries in expandable cards
}
```

When `run` is provided and `onSelectTask` is not, render `TaskDetailCard`.
Otherwise render the existing `TaskGroupCard` (for dashboard use).

### Step 4.3 — Move shared components

Move `ChecklistGrades` and `AttemptTimeline` from `InspectorPanel.tsx` to a
shared location (e.g. `ui/src/components/detail/shared.tsx`) so they can be
used by both InspectorPanel (on Dashboard) and TaskDetailCard (on Detail page).

### Step 4.4 — Wire up in RunDetail

File: `ui/src/pages/RunDetail.tsx`

Pass `run` to `<ActivityFeed>`:

```tsx
<ActivityFeed events={events} run={run} />
```

No `onSelectTask` or `selectedTaskId` — this triggers the expandable card mode.

### Step 4.5 — Verify

- Navigate to completed run detail — each task is collapsed with grade badges.
- Click a task — it expands showing requirements, attempts, prompt, events.
- Click again — it collapses.
- Prompt section loads lazily on first expand.
- Verifier comments show per attempt (if present in seed data).

---

## Phase 5 — Inspector on Dashboard (Req 1)

**Goal:** Add the inspector panel to the Dashboard page, triggered by task
selection in expanded RunCards.

### Step 5.1 — Add task selection state to Dashboard

File: `ui/src/pages/Dashboard.tsx`

Add state:

```typescript
const [inspectorTarget, setInspectorTarget] = useState<{
  runId: string;
  task: TaskSummary;
} | null>(null);
```

### Step 5.2 — Thread task click from RunCard

File: `ui/src/components/dashboard/RunCard.tsx`

Add an `onTaskClick` prop to `RunCard`:

```typescript
onTaskClick?: (runId: string, task: TaskSummary) => void;
```

In the expanded `StepColumn` → `TaskCard`, make each task card clickable. On
click, call `onTaskClick(run.id, task)`.

### Step 5.3 — Render InspectorPanel on Dashboard

File: `ui/src/pages/Dashboard.tsx`

Wrap the page content in a flex container. When `inspectorTarget` is set,
render `<InspectorPanel>` on the right side.

```tsx
<div className="flex h-full">
  <div className="flex-1 min-w-0 overflow-y-auto">
    {/* existing dashboard content */}
  </div>
  {inspectorTarget && (
    <InspectorPanel
      task={inspectorTarget.task}
      runId={inspectorTarget.runId}
      onClose={() => setInspectorTarget(null)}
    />
  )}
</div>
```

### Step 5.4 — Verify

- Dashboard: expand a run card, click a task — inspector opens on the right.
- Click another task — inspector switches.
- Click close — inspector dismisses.
- Click same task — inspector dismisses (toggle behavior).

---

## Phase 6 — Tests & Cleanup

### Step 6.1 — Update existing tests

- `ui/tests/components/RunCard.test.tsx` — Link → span, add onTaskClick tests.
- Any tests referencing InspectorPanel in RunDetail context.

### Step 6.2 — Add new tests

- `ui/src/components/detail/TaskDetailCard.test.tsx` — collapsed renders grade
  badges, expanded renders sections, lazy loading.
- `ui/src/lib/activity.test.ts` — add tests if grouping logic changed.

### Step 6.3 — Final verification

- `cd ui && npx vitest run` — all tests pass.
- `cd ui && npx tsc -b` — no type errors.
- `uv run pytest tests/ -x -q` — backend tests pass.
- Visual check: Dashboard, all run detail pages.

---

## Issues Found During Implementation

1. **Shared components extraction** (Phase 4): `ChecklistGrades` and
   `AttemptTimeline` were inlined in `InspectorPanel.tsx`. Created
   `ui/src/components/detail/shared.tsx` to share them between InspectorPanel
   (Dashboard) and TaskDetailCard (Run Detail).

2. **TaskCard event propagation** (Phase 5): Added `stopPropagation()` to
   `TaskCard` click handler in `RunCard.tsx` to prevent clicks from bubbling
   to the card header's collapse/expand handler.

3. **Additional file created**: `ui/src/components/CompactGradeRow.tsx` —
   reusable compact grade badge row component used by both `TaskDetailCard`
   (collapsed bar) and `RunCard` (expanded task cards).

---

## Execution Order

1. Phase 1 (backend) — independent, do first
2. Phase 2 (remove inspector from detail) — independent of Phase 1
3. Phase 3 (remove link from RunCard) — independent
4. Phase 4 (rich task cards) — depends on Phase 1 (needs verifier_comment),
   Phase 2 (detail page cleared for new cards)
5. Phase 5 (inspector on dashboard) — depends on Phase 3 (RunCard changes)
6. Phase 6 (tests) — after all phases

Phases 1, 2, 3 can run in parallel.
Phase 4 runs after 1+2.
Phase 5 runs after 3.
Phase 6 runs last.
