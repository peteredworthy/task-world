# Step 5: Frontend (M5)

Render phase progress and phase-type context in the UI. Users can see the full phase pipeline for a task (which phases exist, which is active, which are complete), read prior phase outputs, see mini phase dots in the step timeline tooltip, and observe `PhaseStarted`/`PhaseCompleted` events in the activity feed.

## Intent Verification
**Original Intent**: Add `PhaseIndicator` component, update `TaskDetailCard` with phase outputs section, add mini phase dots to `StepTimeline`, render phase events in `ActivityFeed`, and update TypeScript types.
**Functionality to Produce**:
- `ui/src/types/tasks.ts` updated with phase fields and `PhaseType` union
- New `PhaseIndicator` component: horizontal badge chain showing completed/active/pending state with per-type colors
- `TaskDetailCard.tsx` with phase indicator at top and collapsible "Phase Outputs" section
- `StepTimeline.tsx` with mini phase dots for active tasks
- `ActivityFeed.tsx` rendering `PhaseStarted` and `PhaseCompleted` events
- Tests for all new/updated components

**Final Verification Criteria**:
- `npx vitest run` — all new and existing frontend tests pass
- `npx tsc --noEmit` — TypeScript clean
- `npx eslint src/` — ESLint clean

---

## Task 1: Update TypeScript Types

**Description**: Update `ui/src/types/tasks.ts` with new phase fields on `TaskDetailResponse` and a `PhaseType` string literal union.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/types/tasks.ts`
- [ ] Add `PhaseType` string literal union: `'build' | 'verify' | 'plan' | 'summarize' | 'gap_check' | 'script' | 'auto_verify' | 'human_review'`
- [ ] Add to `TaskDetailResponse` — all new fields MUST be optional (`?`) to avoid breaking consumers of older API responses that don't include these fields:
  - `current_phase_index?: number`
  - `phase_count?: number`
  - `current_phase_type?: string | null`
  - `phase_outputs?: Record<number, string>`

**Dependencies**
- Step 4 complete: API returns these fields

**References**
- `docs/phase-pipelines/step-05-plan.md` — Task 1
- `docs/phase-pipelines/clarifications.md` — Q5: JSON string keys, TypeScript `Record<number, string>`

**Constraints**
- All 4 new fields MUST be optional (`?`) — use `current_phase_index?: number`, `phase_count?: number`, `current_phase_type?: string | null`, `phase_outputs?: Record<number, string>`. Older API responses will not include these fields; non-optional types will cause TypeScript errors at all call sites that use legacy task data.

**Functionality (Expected Outcomes)**
- [ ] `PhaseType` exported from `ui/src/types/tasks.ts`
- [ ] `TaskDetailResponse` has all 4 new phase fields
- [ ] `npx tsc --noEmit` remains clean

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` — no type errors

---

## Task 2: Create PhaseIndicator Component

**Description**: Create `ui/src/components/detail/PhaseIndicator.tsx` with utility types in `ui/src/components/detail/phaseIndicatorUtils.ts`.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/phaseIndicatorUtils.ts`:
  - Phase type color map (build→blue, verify→purple, plan→indigo, summarize→teal, gap_check→amber, script→gray, auto_verify→green, human_review→orange)
  - `getPhaseLabel(type: PhaseType): string` helper
  - `PhaseStatus` type: `'completed' | 'active' | 'pending'`
- [ ] Create `ui/src/components/detail/PhaseIndicator.tsx`:
  - Props: `phaseTypes: PhaseType[]`, `currentPhaseIndex: number`
  - Renders horizontal badge chain
  - Completed phases: solid background + checkmark icon
  - Active phase: pulsing animation + colored border
  - Pending phases: dimmed + outline only
  - Returns `null` when `phaseTypes.length <= 1`

**Dependencies**
- [ ] Task 1 must be complete (PhaseType defined)

**References**
- `docs/phase-pipelines/step-05-plan.md` — Task 2
- `docs/phase-pipelines/architecture.md` — phase badge colors
- Memory: utility exports must live in separate `.ts` files (React Fast Refresh requirement)

**Constraints**
- Utilities MUST be in `phaseIndicatorUtils.ts` (not inline in the component) — Fast Refresh requirement
- Unknown `PhaseType` values → render with gray/neutral styling (forward compatibility)

**Functionality (Expected Outcomes)**
- [ ] `PhaseIndicator` renders correct badge count for given `phaseTypes`
- [ ] Active phase has pulsing class
- [ ] Returns null when `phaseTypes.length <= 1`

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run ui/src/components/detail/__tests__/PhaseIndicator.test.tsx` — all pass

> **DRY-RUN FIX**: `ui/src/__tests__/` does not exist. Test file goes in `ui/src/components/detail/__tests__/PhaseIndicator.test.tsx`.

---

## Task 3: Update TaskDetailCard

**Description**: Update `ui/src/components/detail/TaskDetailCard.tsx` to render `PhaseIndicator` and a collapsible "Phase Outputs" section.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/TaskDetailCard.tsx`
- [ ] Import `PhaseIndicator` from `./PhaseIndicator`
- [ ] Render `<PhaseIndicator>` at top of card when `phase_count > 1`
- [ ] Add collapsible "Phase Outputs" section:
  - Only render when `phase_outputs` has at least one entry
  - Show each prior phase's output text with phase type label
  - Use a `<details>` or expandable component pattern consistent with existing UI

**Dependencies**
- [ ] Task 2 must be complete (PhaseIndicator exists)

**References**
- `docs/phase-pipelines/step-05-plan.md` — Task 3
- Memory: `onClick` handlers for context functions with optional params must use arrow functions

**Constraints**
- Do not re-export utilities from this file (Fast Refresh)
- `phase_count = 0` or `1` → PhaseIndicator not rendered (no visual clutter for simple tasks)

**Functionality (Expected Outcomes)**
- [ ] Phase indicator appears when `phase_count > 1`
- [ ] Phase outputs section renders collapsible prior output text
- [ ] Existing card functionality unchanged

**Final Verification (Proof of Completion)**
- [ ] Updated `TaskDetailCard` tests pass (see Task 6)

---

## Task 4: Update StepTimeline with Mini Phase Dots

**Description**: Update `ui/src/components/dashboard/StepTimeline.tsx` to render mini phase dots for active tasks in the step tooltip.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/dashboard/StepTimeline.tsx`
- [ ] In the step tooltip for active tasks, render mini phase dots below the task badge:
  - One dot per phase in `phase_count`
  - Dots colored by `current_phase_type` (active dot) vs neutral (other dots)
  - Active phase dot pulses
- [ ] Only render dots when `phase_count > 1`

**Dependencies**
- [ ] Task 1 must be complete (types updated)

**References**
- `docs/phase-pipelines/step-05-plan.md` — Task 4

**Constraints**
- Mini dots must not significantly increase tooltip height for tasks with many phases
- Reuse color utilities from `phaseIndicatorUtils.ts` rather than duplicating. Import with relative path `'../detail/phaseIndicatorUtils'` — `StepTimeline.tsx` is in `dashboard/` and `phaseIndicatorUtils.ts` is in `detail/`.

**Functionality (Expected Outcomes)**
- [ ] Mini phase dots appear in tooltip for active tasks with `phase_count > 1`
- [ ] Current phase dot pulses; others are neutral

**Final Verification (Proof of Completion)**
- [ ] No TypeScript errors, ESLint clean

---

## Task 5: Update ActivityFeed with Phase Events

**Description**: Update `ui/src/components/detail/ActivityFeed.tsx` (or equivalent) to render `PhaseStarted` and `PhaseCompleted` events.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/ActivityFeed.tsx` — this is the full activity feed with task/run context. There is also `ui/src/components/dashboard/ActivityFeed.tsx` (simpler) — update the DETAIL one, not the dashboard one.
- [ ] Add case for `PhaseStarted` event: render "Phase {index + 1} started: {type}"
- [ ] Add case for `PhaseCompleted` event: render "Phase {index + 1} completed: {type} → Phase {index + 2}"
- [ ] Unknown event types fall back to existing generic event renderer

**Dependencies**
- Step 2 complete: `PhaseStarted`/`PhaseCompleted` event types defined

**References**
- `docs/phase-pipelines/step-05-plan.md` — Task 5

**Constraints**
- Unknown event fields → fall back to generic renderer (forward compat)
- Use 1-based phase numbering in display ("Phase 1", "Phase 2") even though the index is 0-based internally

**Functionality (Expected Outcomes)**
- [ ] `PhaseStarted` events render with human-readable label
- [ ] `PhaseCompleted` events render with arrow to next phase

**Final Verification (Proof of Completion)**
- [ ] ActivityFeed tests pass (see Task 6)

---

## Task 6: Write Frontend Tests

**Description**: Write tests for `PhaseIndicator`, `TaskDetailCard` phase sections, and `ActivityFeed` phase events.

**Implementation Plan (Do These Steps)**
- [ ] ⚠️ HARDENING NOTE (Gap 9): Use `ui/src/components/detail/__tests__/` for all test files — this follows project convention (e.g. `RecoveryPanel.test.tsx` lives there). `ui/src/__tests__/` does NOT exist. `TaskDetailCard` and `ActivityFeed` test files also do not exist yet — CREATE them, do not "add to existing".
- [ ] Create `ui/src/components/detail/__tests__/PhaseIndicator.test.tsx`:
  - `test_all_phases_render`: all phases render in correct order
  - `test_completed_phases_have_checkmark`: completed phases have solid background + checkmark class
  - `test_active_phase_pulses`: active phase has pulsing class and correct color
  - `test_pending_phases_are_dimmed`: pending phases have outline class
  - `test_single_phase_renders_nothing`: `phaseTypes.length <= 1` → renders nothing
- [ ] Create `ui/src/components/detail/__tests__/TaskDetailCard.test.tsx` (new file, does not yet exist):
  - Phase indicator appears when `phase_count > 1`
  - Phase outputs section renders collapsible prior output text
- [ ] Create `ui/src/components/detail/__tests__/ActivityFeed.test.tsx` (new file, does not yet exist):
  - `PhaseStarted` event renders with type and index
  - `PhaseCompleted` event renders with `→ Phase N+1`
- [ ] Run: `npx vitest run`

**Dependencies**
- [ ] Tasks 2–5 must be complete

**References**
- `docs/phase-pipelines/step-05-plan.md` — Tasks 6–8

**Constraints**
- Use existing test patterns (render + queries) from sibling test files

**Functionality (Expected Outcomes)**
- [ ] All new tests pass

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` — all new and existing frontend tests pass
- [ ] `npx tsc --noEmit` — TypeScript clean
- [ ] `npx eslint src/` — ESLint clean

---
