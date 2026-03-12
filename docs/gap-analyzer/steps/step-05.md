# Step 5: Frontend Display

Render step verification state and gap reports in the UI. Users should see when a step is being verified, how many iterations have run, what the verifier assessed, and what actions were taken — including fix-up tasks spawned by the verifier.

## Intent Verification
**Original Intent**: Make gap-analyzer results visible to users in the dashboard (see `docs/gap-analyzer/intent.md`).
**Functionality to Produce**:
- `GapAction` and `GapReport` TypeScript interfaces in `ui/src/types/runs.ts`
- `StepSummary` extended with `verifying`, `verifier_iterations`, `gap_reports` (TypeScript)
- `TaskSummary` extended with `spawned_by_gap_report: boolean`
- Pulsing purple "Verifying N/M" badge on verifying steps in `StepTimeline`
- Gap report card(s) showing assessment, verdict badge, action list, iteration counter, collapsible history
- Fix-up tasks with dashed border and "Fix-up" badge
- Activity feed handles `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` events

**Final Verification Criteria**:
- `npx vitest run` — all frontend tests pass (including new ones)
- `npx tsc --noEmit` — no TypeScript errors
- `npx eslint ui/src/` — no lint errors
- Visual: verifying badge pulses; gap report card shows correct verdict color; fix-up tasks visually distinct

---

## Task 1: Update TypeScript Types

**Description**: Add `GapAction` and `GapReport` interfaces to `ui/src/types/runs.ts` and extend `StepSummary` and `TaskSummary` with new fields.

**Implementation Plan (Do These Steps)**
- [ ] Add to `ui/src/types/runs.ts`:
  ```typescript
  export interface GapAction {
    type: string;
    task_id?: string;
    feedback?: string;
    title?: string;
    context?: string;
    requirements?: Record<string, unknown>[];
  }
  export interface GapReport {
    id: string;
    iteration: number;
    assessment: string;
    verdict: 'pass' | 'retry' | 'fix' | 'fail';
    actions: GapAction[];
    timestamp: string;
  }
  ```
- [ ] Add to `StepSummary` interface: `verifying: boolean`, `verifier_iterations: number`, `gap_reports: GapReport[]`
- [ ] Add to `TaskSummary` interface: `spawned_by_gap_report: boolean`
- [ ] Run `npx tsc --noEmit` to confirm no type errors

**Dependencies**
- [ ] Step 4 complete: API returns `verifying`, `verifier_iterations`, `gap_reports`, `spawned_by_gap_report`.

**References**
- `docs/gap-analyzer/architecture.md` — frontend components section
- `docs/gap-analyzer/step-05-plan.md` — full functional contract

**Constraints**
- `spawned_by_gap_report` must be optional (or have `false` default) — older API responses omitting it must still type-check.
- All new fields on `StepSummary` must have defaults matching `StepSummary` usage across existing components.

**Functionality (Expected Outcomes)**
- [ ] `GapAction`, `GapReport` interfaces exported from `ui/src/types/runs.ts`
- [ ] `StepSummary.gap_reports` typed as `GapReport[]`
- [ ] `TaskSummary.spawned_by_gap_report` typed as `boolean`

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` passes
- [ ] `grep -n "gap_reports\|spawned_by_gap_report" ui/src/types/runs.ts` shows new fields

---

## Task 2: Add Verifying State to StepTimeline

**Description**: Update `ui/src/lib/stepTimelineUtils.ts` to return `'verifying'` state and update `ui/src/components/dashboard/StepTimeline.tsx` to render a pulsing purple badge with iteration counter.

**Implementation Plan (Do These Steps)**
- [ ] In `ui/src/lib/stepTimelineUtils.ts`:
  - Add `'verifying'` to the step state union type
  - Update `getStepState()` to return `'verifying'` when `step.verifying === true`
  - Add `'verifying'` entry to `stepBadgeClasses`: pulsing purple badge class (e.g., `animate-pulse bg-purple-500`)
- [ ] In `ui/src/components/dashboard/StepTimeline.tsx`:
  - Render verifying steps with pulsing purple badge
  - Show iteration counter: `"Verifying {verifier_iterations}/{max_iterations}"` (use `step.verifier_iterations`; max from step config if available, else omit denominator)

**Dependencies**
- [ ] Task 1 must be complete (TypeScript types include `verifying`, `verifier_iterations`)

**References**
- `docs/gap-analyzer/architecture.md` — step badge spec (pulsing purple, iteration counter)
- Existing pattern: task verifying badge in the same file

**Constraints**
- Follow existing badge class pattern in `stepBadgeClasses` (do not inline ad-hoc styles).
- `max_iterations` may not be available in `StepSummary`; show `"Verifying N"` if denominator unavailable.

**Functionality (Expected Outcomes)**
- [ ] `getStepState()` returns `'verifying'` for steps where `verifying === true`
- [ ] Verifying steps render with pulsing purple badge and iteration text

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vitest run` — `StepTimeline` test: verifying step renders pulsing purple badge with iteration counter

---

## Task 3: Build Gap Report Display Component

**Description**: Create a gap report display (as a new component file or inline in the step detail section) showing assessment text, verdict badge, action list, iteration counter, and collapsible history.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/GapReportCard.tsx` (or inline in the step detail section of `RunDetail.tsx`)
- [ ] Props: `reports: GapReport[]`, `verifier_iterations: number`
- [ ] For each report: show assessment text, verdict badge (green=pass, amber=retry/fix, red=fail), action list (type + target task ID + feedback/context), iteration counter `"Iteration N of M"`
- [ ] Historical gap reports (all past iterations): collapsible — most recent expanded, prior collapsed
- [ ] Export from utility file if needed to satisfy React Fast Refresh (per MEMORY.md)

**Dependencies**
- [ ] Task 1 must be complete (TypeScript types for `GapReport`)

**References**
- `docs/gap-analyzer/architecture.md` — gap report card visual spec
- MEMORY.md — Fast Refresh constraint: utilities must be in separate files from components

**Constraints**
- Collapsible history: use an existing collapsible/accordion pattern in the codebase.
- Verdict badge colors: green for `pass`, amber for `retry`/`fix`, red for `fail`.
- Empty state (`gap_reports: []`): render nothing (no card).

**Functionality (Expected Outcomes)**
- [ ] Gap report card renders assessment text, verdict badge, and action list
- [ ] Historical reports accessible via collapsible
- [ ] Empty `gap_reports` renders nothing

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vitest run` — gap report card test: renders assessment, verdict badge, action list

---

## Task 4: Fix-up Task Display and Activity Feed Events

**Description**: Add visual distinction for fix-up tasks (dashed border, "Fix-up" badge) in the step task list, and update `ActivityFeed.tsx` to handle the three new event types.

**Implementation Plan (Do These Steps)**
- [ ] In the step task list component (locate in `RunDetail.tsx` or step detail component):
  - Add condition: `task.spawned_by_gap_report === true` → apply dashed border class and render "Fix-up" badge
- [ ] In `ui/src/components/detail/ActivityFeed.tsx`:
  - Add handler for `StepVerificationStarted`: magnifying glass icon, show iteration info
  - Add handler for `GapReportGenerated`: verdict badge inline, assessment snippet (truncated)
  - Add handler for `StepVerificationCompleted`: final verdict summary with icon
- [ ] Write frontend tests:
  - `StepTimeline` renders pulsing purple badge with iteration counter for `verifying=true` steps
  - Gap report card renders assessment text, verdict badge, action list
  - Fix-up task renders with "Fix-up" badge and dashed border

**Dependencies**
- [ ] Tasks 1-3 must be complete
- [ ] Step 1 complete: event type strings `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` defined in backend (matched by frontend string literals)

**References**
- `docs/gap-analyzer/architecture.md` — activity feed event descriptions
- Existing `ActivityFeed.tsx` for event handler pattern

**Constraints**
- Activity feed event type strings must match exactly what the backend emits (check `src/orchestrator/workflow/events.py`).
- Fix-up task dashed border: use Tailwind `border-dashed` class (or existing pattern).

**Functionality (Expected Outcomes)**
- [ ] Fix-up tasks show dashed border and "Fix-up" badge
- [ ] Activity feed renders all three new event types with appropriate icons/content

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` — all frontend tests pass (including new ones for this task)
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npx eslint ui/src/` — no lint errors
