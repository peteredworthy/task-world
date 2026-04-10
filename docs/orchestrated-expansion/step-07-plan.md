# Step Plan: Frontend Display (M4)

## Purpose

Render expansion state throughout the UI so users can see what was expanded, why, by whom, and the current budget usage. This step adds expansion-aware types, component updates, and frontend tests. It depends only on the API contract being stable (Step 5), not on the executor or prompt changes (Step 6).

## Prerequisites

- **Step 5 complete** — API returns expansion fields in task, step, and run responses.
- TypeScript types must match the API response shapes.

## Functional Contract

### Inputs

Updated API responses (after Steps 1–5):
- `TaskResponse`: now includes `expanded_from_task_id`, `expansion_justification`, `is_expansion`
- `StepResponse`: now includes `is_expansion`, `expanded_from_task_id`
- `RunResponse`: now includes `expansion_count`, `expansion_limits` (object with all limit fields)
- `ActivityEvent` of type `task_expanded`: includes `expansion_type`, `requesting_task_id`, `justification`, `blocking`, `approved`

### Outputs

Updated TypeScript types:
- `ui/src/types/tasks.ts`: `expanded_from_task_id?: string`, `expansion_justification?: string`, `is_expansion?: boolean` added to task type
- `ui/src/types/runs.ts`: step type gains `is_expansion?`, `expanded_from_task_id?`; run type gains `expansion_count?`, `expansion_limits?` (typed object)

UI components:

**`TaskDetailCard.tsx`**:
- If `task.is_expansion`: render "Expanded" badge (cyan/teal accent) next to task title
- Provenance section: show "Requested by Task {expanded_from_task_id}" and justification text when `expanded_from_task_id` set
- Expanded children section: tasks with `parent_task_id` matching this task's ID (already fetched as children) rendered with cyan accent

**Step view (step component)**:
- Peer task expansions with dashed border (tasks where `is_expansion=true` and no `parent_task_id`)
- "Added by T-{id}" label using `expanded_from_task_id`

**`StepTimeline.tsx`**:
- Steps with `is_expansion=true` render a "+" indicator (e.g., `+` prefix on step label or a small badge)
- Regular steps unaffected

**`ActivityFeed.tsx`**:
- `task_expanded` event type renders prominently:
  - Expansion type (`add_subtask` / `add_peer_task` / `add_next_step`)
  - New task or step title
  - Requesting task ID
  - Justification text
  - Approval status if `require_human_approval` was true

**`RunDetail.tsx`**:
- Expansion budget display in run metadata area: `"Expansions: {expansion_count}/{max_total_expansions} used"`
- If `expansion_count` is 0 or `expansion_limits` absent: section not shown (or shown as `0/{limit}`)
- Pending expansion approvals: when `require_human_approval=true` and there are pending expansion approval actions, show them in the pending actions area with Approve/Reject buttons

### Error Cases

- If `expansion_limits` is undefined in run data (old runs or runs without limits configured): render budget section with defaults or hide it — do not crash
- If `expanded_from_task_id` references an unknown task ID: render the raw ID string; do not fetch additional data

## Tasks

1. **`ui/src/types/tasks.ts`**: Add `expanded_from_task_id?`, `expansion_justification?`, `is_expansion?` fields.

2. **`ui/src/types/runs.ts`**: Add expansion fields to step type and run type. Add `ExpansionLimits` interface.

3. **`ui/src/components/detail/TaskDetailCard.tsx`**: Add "Expanded" badge and provenance section.

4. **Step view component** (identify the correct component rendering individual step task lists): Add dashed border and "Added by T-XX" label for peer expansion tasks.

5. **`ui/src/components/dashboard/StepTimeline.tsx`**: Add "+" indicator for `is_expansion` steps.

6. **`ui/src/components/detail/ActivityFeed.tsx`**: Add handler for `task_expanded` event type.

7. **`ui/src/components/detail/RunDetail.tsx`**: Add expansion budget display and pending approval actions.

8. **Frontend tests**:
   - `TaskDetailCard`: "Expanded" badge renders when `is_expansion=true`; provenance section shows requesting task and justification; badge absent for normal tasks
   - `StepTimeline`: "+" indicator renders for `is_expansion=true` steps; absent for regular steps
   - `ActivityFeed`: `task_expanded` event renders with correct expansion type, title, requesting task ID, and justification

## Verification Approach

### Auto-Verify

- `npx vitest run` — all frontend tests pass (including new tests)
- `npx tsc --noEmit` — no TypeScript type errors
- `npm run lint` — no ESLint errors

### Manual Verification (Visual)

- Create a run with a routine that includes `expansion_limits`; inspect run detail page for budget display
- Check that expanded tasks show the "Expanded" badge in `TaskDetailCard`
- Check that inserted steps show the "+" in `StepTimeline`
- Verify `task_expanded` activity events render legibly in the activity feed with all required fields

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 7 (M4) specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — frontend type additions, component descriptions
- Existing fan-out children rendering in `TaskDetailCard.tsx` — reference for similar UI patterns
- Existing activity event types in `ActivityFeed.tsx` — reference for adding new event renderers
