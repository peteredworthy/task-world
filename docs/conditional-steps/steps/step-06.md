# Step 6: Frontend Display

Render conditional step state in the UI so users can see which steps were skipped, why, what conditions pending steps have, and interact with manual gates. This is the final step, making the feature visible to end users.

## Intent Verification
**Original Intent**: Make the conditional steps feature visible and interactive in the frontend, showing skip state, condition expressions, and providing manual gate controls (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- Skipped steps rendered with dashed border, dimmed opacity, and "Skipped" badge
- Tooltip on skipped steps shows `skip_reason`
- Pending conditional steps show condition expression text
- `repeat_for` iterations render as sub-items under parent step
- `StepSkipped` events in activity feed
- Manual gate UI with "Execute Step" and "Skip Step" buttons
- Updated TypeScript types for `StepSummary`

**Final Verification Criteria**:
- `cd ui && npx vitest run` -- all frontend tests pass
- `cd ui && npx tsc --noEmit` -- TypeScript type check clean
- `cd ui && npx eslint src/` -- ESLint clean

---

## Task 1: Update TypeScript Types and Step State Utils

**Description**: Add conditional step fields to TypeScript types and update step state classification to handle skipped steps.

**Implementation Plan (Do These Steps)**
- [ ] Update `ui/src/types/runs.ts`: add `skipped: boolean`, `skip_reason: string | null`, `condition: { when: string | null; repeat_for: string | null } | null` to `StepSummary` type
- [ ] Update `ui/src/lib/stepTimelineUtils.ts`:
  - `getStepState()` returns `'skipped'` when `step.skipped` is true
  - Add `stepBadgeClasses` entry for `'skipped'` state (dashed border, dimmed opacity)

**Dependencies**
- [ ] Step 5 (API surface) must be complete -- API returns the fields we're consuming

**References**
- `docs/conditional-steps/architecture.md` -- frontend component changes
- `docs/conditional-steps/step-06-plan.md` -- tasks 1-2
- `ui/src/types/runs.ts` -- current types
- `ui/src/lib/stepTimelineUtils.ts` -- current step state logic

**Constraints**
- Missing `condition` field (older runs) must not break rendering
- Missing `skip_reason` shows "Skipped" badge without tooltip detail

**Functionality (Expected Outcomes)**
- [ ] `StepSummary` type includes all conditional step fields
- [ ] `getStepState()` correctly identifies skipped steps
- [ ] Skipped steps get distinct visual classes

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` -- no type errors

---

## Task 2: Update StepTimeline and ActivityFeed Components

**Description**: Render skipped steps with visual indicators, show condition text on pending steps, handle repeat-for sub-items, and display StepSkipped events in the activity feed.

**Implementation Plan (Do These Steps)**
- [ ] Update `ui/src/components/dashboard/StepTimeline.tsx`:
  - Render skipped steps with skipped badge classes (dashed border, dimmed)
  - Show "Skipped" badge text on skipped steps
  - Add tooltip with `skip_reason` on skipped steps
  - Show condition expression text on pending conditional steps (e.g., "Runs if complexity = high")
  - Render `repeat_for` iterations as sub-items under parent step badge
- [ ] Update `ui/src/components/dashboard/ActivityFeed.tsx`:
  - Handle `StepSkipped` event type with skip icon and reason text

**Dependencies**
- [ ] Task 1 must be complete (types and utils updated)

**References**
- `docs/conditional-steps/step-06-plan.md` -- tasks 3-4
- `ui/src/components/dashboard/StepTimeline.tsx` -- current timeline
- `ui/src/components/dashboard/ActivityFeed.tsx` -- current activity feed

**Constraints**
- No inline confirm/cancel in tight spaces (per AGENTS.md UI constraints)
- Graceful fallback when `condition` or `skip_reason` is null

**Functionality (Expected Outcomes)**
- [ ] Skipped steps are visually distinct (dashed border, dimmed opacity, "Skipped" badge)
- [ ] Hovering a skipped step shows the skip reason
- [ ] Pending conditional steps show their condition expression
- [ ] `StepSkipped` events appear in activity feed with reason

**Final Verification (Proof of Completion)**
- [ ] Components render without errors for all step states

---

## Task 3: Add Manual Gate UI

**Description**: When a run is paused at a manual gate, show "Execute Step" and "Skip Step" buttons so the user can choose.

**Implementation Plan (Do These Steps)**
- [ ] Add manual gate UI in `RunDetail.tsx` (or appropriate component):
  - Detect `pause_reason === "manual_gate"` on the run
  - Show "Execute Step" button that calls existing `POST /runs/{id}/resume`
  - Show "Skip Step" button that calls `POST /runs/{id}/steps/{step_id}/skip`
  - Handle API errors with error toast
- [ ] Style buttons appropriately (Execute = primary, Skip = secondary/outline)

**Dependencies**
- [ ] Task 2 must be complete (timeline renders skipped state)
- [ ] Step 5 Task 2 (skip-step endpoint) must be complete

**References**
- `docs/conditional-steps/step-06-plan.md` -- task 5
- Clarification Q1: Add skip option so users can choose to skip OR execute
- AGENTS.md UI constraints: modals for destructive actions, no inline confirm/cancel

**Constraints**
- "Skip Step" is not destructive per se (step can be re-run), so inline buttons are acceptable here
- Error on API call shows toast, doesn't change UI state

**Functionality (Expected Outcomes)**
- [ ] Manual gate paused runs show both action buttons
- [ ] "Execute Step" resumes the run
- [ ] "Skip Step" skips the gated step and advances

**Final Verification (Proof of Completion)**
- [ ] Manual gate UI renders when `pause_reason === "manual_gate"`
- [ ] Both buttons call the correct API endpoints

---

## Task 4: Write Frontend Tests

**Description**: Add frontend tests for all new conditional step rendering.

**Implementation Plan (Do These Steps)**
- [ ] Add tests:
  - Skipped step renders with dashed border class
  - Skipped step shows skip reason in tooltip
  - Pending conditional step shows condition text
  - `repeat_for` iterations render as sub-items
  - Manual gate shows execute and skip buttons

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/conditional-steps/architecture.md` -- frontend testing strategy
- `docs/conditional-steps/step-06-plan.md` -- task 6

**Constraints**
- Tests should use real component rendering (Vitest + Testing Library)

**Functionality (Expected Outcomes)**
- [ ] All new UI elements have test coverage

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx vitest run` -- all tests pass
- [ ] `cd ui && npx tsc --noEmit` -- clean
- [ ] `cd ui && npx eslint src/` -- clean
