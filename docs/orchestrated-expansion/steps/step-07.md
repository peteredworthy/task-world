# Step 7: Frontend Display (M4)

Render expansion state throughout the UI so users can see what was expanded, why, by whom, and the current budget usage. Adds expansion-aware TypeScript types, component updates for task cards, step timeline, activity feed, and run detail, plus frontend tests.

## Intent Verification
**Original Intent**: Update TypeScript types to match expansion API fields, add visual indicators (badges, dashed borders, "+") in existing components, render `task_expanded` activity events, and display expansion budget in run detail (see `docs/orchestrated-expansion/plan.md` Step 7).
**Functionality to Produce**:
- `ui/src/types/tasks.ts`: `expanded_from_task_id?`, `expansion_justification?`, `is_expansion?` fields
- `ui/src/types/runs.ts`: step type gains `is_expansion?`, `expanded_from_task_id?`; run type gains `expansion_count?`, `expansion_limits?`; `ExpansionLimits` interface
- `TaskDetailCard.tsx`: "Expanded" badge (cyan accent) when `is_expansion=true`; provenance section showing requesting task ID and justification
- Step view component: dashed border and "Added by T-{id}" label for peer expansion tasks (`is_expansion=true`, no `parent_task_id`)
- `StepTimeline.tsx`: "+" indicator for `is_expansion=true` steps
- `ActivityFeed.tsx`: renderer for `task_expanded` event type (expansion type, title, requesting task ID, justification, approval status)
- `RunDetail.tsx`: expansion budget display (`"{expansion_count}/{max_total_expansions} used"`); pending expansion approval Approve/Reject buttons
- Frontend tests for badge rendering, step indicator, and activity event display

**Final Verification Criteria**:
- `npx vitest run` — all frontend tests pass (including new tests)
- `npx tsc --noEmit` — no TypeScript type errors
- `npm run lint` — no ESLint errors

---

## Task 1: Add Expansion Fields to TypeScript Types

**Description**: Update `ui/src/types/tasks.ts` and `ui/src/types/runs.ts` with all expansion-related fields.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/types/tasks.ts`
- [ ] Add optional fields to the task type: `expanded_from_task_id?: string`, `expansion_justification?: string`, `is_expansion?: boolean`
- [ ] Open `ui/src/types/runs.ts`
- [ ] Add optional fields to the step type: `is_expansion?: boolean`, `expanded_from_task_id?: string`
- [ ] Add `ExpansionLimits` interface with: `max_subtasks_per_task: number`, `max_peer_tasks_per_step: number`, `max_inserted_steps: number`, `max_total_expansions: number`, `require_human_approval: boolean`
- [ ] Add optional fields to the run type: `expansion_count?: number`, `expansion_limits?: ExpansionLimits`

**Dependencies**
- [ ] Step 5 complete — API returns expansion fields; types must match API response shapes

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Tasks 1 and 2
- `docs/orchestrated-expansion/architecture.md` — frontend type additions

**Constraints**
- All new fields must be optional (`?`) — existing runs and old API responses will not include them; do not crash on missing fields
- `ExpansionLimits` interface field names must exactly match the API response keys (snake_case)

**Functionality (Expected Outcomes)**
- [ ] TypeScript accepts task objects with or without expansion fields
- [ ] TypeScript accepts run objects with or without `expansion_count` / `expansion_limits`

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors after adding the fields

---

## Task 2: Add "Expanded" Badge and Provenance to TaskDetailCard

**Description**: Update `ui/src/components/detail/TaskDetailCard.tsx` to show an "Expanded" badge and provenance section for expansion tasks.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/TaskDetailCard.tsx`
- [ ] After the task title, conditionally render an "Expanded" badge (cyan/teal accent color) when `task.is_expansion === true`
- [ ] Add a provenance section (conditionally rendered when `task.expanded_from_task_id` is set): show "Requested by Task {expanded_from_task_id}" and `task.expansion_justification` text
- [ ] Ensure the badge and provenance section are absent for normal (non-expansion) tasks

**Dependencies**
- [ ] Task 1 complete — TypeScript types updated

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 3
- Existing fan-out children rendering in `TaskDetailCard.tsx` — reference for similar conditional UI patterns

**Constraints**
- Use existing CSS utility classes or component patterns (do not introduce new CSS files)
- Provenance section must not render when `expanded_from_task_id` is undefined

**Functionality (Expected Outcomes)**
- [ ] "Expanded" badge renders next to task title when `is_expansion=true`
- [ ] Provenance section shows requesting task ID and justification text
- [ ] Neither renders for tasks without expansion fields

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 3: Add Peer Task Visual Indicator in Step View

**Description**: In the step view component that renders individual task lists, add a dashed border and "Added by T-{id}" label for peer expansion tasks.

**Implementation Plan (Do These Steps)**
- [ ] Identify the correct step/task-list component (search for where tasks within a step are rendered; may be `StepDetail.tsx`, `StepCard.tsx`, or similar)
- [ ] For tasks where `task.is_expansion === true` AND `task.parent_task_id` is undefined (peer tasks, not subtasks): apply a dashed border style
- [ ] Render an "Added by T-{id}" label using `task.expanded_from_task_id` (show the short ID or raw ID)
- [ ] Regular tasks and subtasks (`parent_task_id` set) are unaffected

**Dependencies**
- [ ] Task 1 complete — TypeScript types updated
- [ ] Task 2 complete — confirms the badge pattern for reference

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 4

**Constraints**
- Only apply the dashed-border style to peer tasks (is_expansion AND no parent_task_id), not to blocking subtasks
- "Added by T-{id}" label must gracefully handle missing `expanded_from_task_id` (render nothing if undefined)

**Functionality (Expected Outcomes)**
- [ ] Peer expansion tasks render with dashed border and "Added by T-{id}" label
- [ ] Blocking subtask tasks and regular tasks are unaffected by this change

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 4: Add "+" Indicator for Expanded Steps in StepTimeline

**Description**: Update `ui/src/components/dashboard/StepTimeline.tsx` to render a "+" indicator for steps with `is_expansion=true`.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/dashboard/StepTimeline.tsx`
- [ ] For each step in the timeline, conditionally render a "+" prefix or small badge next to the step label when `step.is_expansion === true`
- [ ] Regular (non-expansion) steps are unaffected

**Dependencies**
- [ ] Task 1 complete — TypeScript step type updated with `is_expansion?`

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 5

**Constraints**
- Use the existing step rendering pattern; do not restructure the component
- "+" indicator should be visually distinguishable but not disruptive (consistent with existing timeline style)

**Functionality (Expected Outcomes)**
- [ ] Steps with `is_expansion=true` show a "+" indicator in the timeline
- [ ] Steps without `is_expansion` (or with `is_expansion=false`) are unchanged

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 5: Add task_expanded Event Renderer to ActivityFeed

**Description**: Update `ui/src/components/detail/ActivityFeed.tsx` to render `task_expanded` activity events with all required fields.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/ActivityFeed.tsx`
- [ ] Add a handler for `event.type === "task_expanded"` (or the snake_case key used in the API)
- [ ] Render the following from the event payload:
  - Expansion type (`add_subtask` / `add_peer_task` / `add_next_step`) — human-readable label
  - New task or step title (if available in event payload)
  - Requesting task ID (`requesting_task_id`)
  - Justification text
  - Approval status (if `approved=false`, show "Pending approval"; if `approved=true`, show nothing or "Approved")
- [ ] Follow the existing event renderer pattern for visual consistency

**Dependencies**
- [ ] Task 1 complete — TypeScript types (activity event types should be extended if needed)

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 6
- Existing activity event types in `ActivityFeed.tsx` — reference for adding new renderers

**Constraints**
- Do not crash if optional event payload fields are missing — use optional chaining
- Follow the existing event renderer pattern (do not introduce new component abstractions)

**Functionality (Expected Outcomes)**
- [ ] `task_expanded` events render with expansion type, requesting task ID, and justification
- [ ] Approval status shown only when `approved=false`

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 6: Add Expansion Budget and Approval UI to RunDetail

**Description**: Update `ui/src/components/detail/RunDetail.tsx` to display expansion budget usage and pending expansion approval actions.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/RunDetail.tsx`
- [ ] In the run metadata area, conditionally render expansion budget when `run.expansion_count` or `run.expansion_limits` is present: `"Expansions: {expansion_count}/{max_total_expansions} used"`
- [ ] If `expansion_count === 0` and `expansion_limits` is absent: hide the budget section (do not show `0/undefined`)
- [ ] In the pending actions area: when there are pending actions of type `"expansion_approval"`, render each with task ID, expansion type (from payload), and Approve/Reject buttons
- [ ] Approve button: `POST .../expand/approve` with `action="approve"`; Reject button: `action="reject"`
- [ ] On approve/reject success, refresh the run data (or remove the pending action from local state)

**Dependencies**
- [ ] Task 1 complete — TypeScript run type updated with `expansion_count?`, `expansion_limits?`
- [ ] Step 5 complete — `POST .../expand/approve` endpoint exists

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 7
- Existing pending actions rendering in `RunDetail.tsx` for the Approve/Reject button pattern

**Constraints**
- Do not crash when `expansion_limits` is undefined (old runs) — use optional chaining
- Budget section only visible when meaningful data is present
- Approve/Reject buttons must correctly call the approval endpoint and handle errors gracefully

**Functionality (Expected Outcomes)**
- [ ] Budget display shows `"{count}/{max} used"` when expansion data is present
- [ ] Budget section hidden when no expansion data available
- [ ] Pending expansion approval actions show with Approve/Reject buttons
- [ ] Approve/Reject updates UI after successful API call

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 7: Write Frontend Tests

**Description**: Write frontend tests covering the "Expanded" badge in `TaskDetailCard`, the "+" indicator in `StepTimeline`, and the `task_expanded` event renderer in `ActivityFeed`.

**Implementation Plan (Do These Steps)**
- [ ] Add tests to the `TaskDetailCard` test file (or create one):
  - "Expanded" badge renders when `task.is_expansion=true`
  - Provenance section shows requesting task ID and justification text
  - Badge absent for normal (non-expansion) tasks
- [ ] Add tests to the `StepTimeline` test file (or create one):
  - "+" indicator renders for steps with `is_expansion=true`
  - Indicator absent for regular steps
- [ ] Add tests to the `ActivityFeed` test file (or create one):
  - `task_expanded` event renders with correct expansion type, requesting task ID, and justification
- [ ] Run `npx vitest run` to confirm all tests pass

**Dependencies**
- [ ] Tasks 2–5 complete — components updated before tests are written

**References**
- `docs/orchestrated-expansion/step-07-plan.md` — Task 8
- Existing frontend test files for component test patterns

**Constraints**
- Tests must use the existing test setup (vitest + testing-library); do not introduce new test frameworks
- Each test must be self-contained — mock API calls and props directly

**Functionality (Expected Outcomes)**
- [ ] All new frontend tests pass
- [ ] No existing frontend tests broken

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` — all tests pass (including new ones)
- [ ] `npx tsc --noEmit` — no TypeScript type errors
- [ ] `npm run lint` — no ESLint errors
