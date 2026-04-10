# Step Plan: Frontend (M5)

## Purpose

Render phase progress and phase-type context in the UI. After this step, users can see the full
phase pipeline for a task (which phases exist, which is active, which are complete), read prior
phase outputs in the task detail view, see mini phase dots in the step timeline tooltip, and
observe `PhaseStarted`/`PhaseCompleted` events in the activity feed.

## Prerequisites

- Step 4 complete: API returns `current_phase_index`, `current_phase_type`, `phase_count`,
  `phase_outputs` on `TaskDetailResponse`; `PromptResponse` includes `phase_type`.

## Functional Contract

### Inputs

- `TaskDetailResponse` with new phase fields: `current_phase_index`, `phase_count`,
  `current_phase_type`, `phase_outputs`
- `ActivityEvent` union extended with `PhaseStarted` and `PhaseCompleted` event shapes
- Component props derived from the above

### Outputs

- `ui/src/types/tasks.ts` updated with new fields on `TaskDetailResponse` and a `PhaseType`
  string literal union type
- New `PhaseIndicator` component (or inline in `TaskDetailCard.tsx`): horizontal chain of phase
  badges showing completed (solid + checkmark), active (pulsing + colored), and pending
  (dimmed + outline) states with per-type colors
- `TaskDetailCard.tsx`:
  - Phase indicator rendered at the top of the task detail when `phase_count > 1`
  - Collapsible "Phase Outputs" section listing each prior phase's output text
- `StepTimeline.tsx`: mini phase dots rendered below active task badges in the step tooltip,
  colored by phase type, with current phase pulsing
- `ActivityFeed.tsx`: renders `PhaseStarted` and `PhaseCompleted` events with human-readable
  labels

### Error Cases

- `phase_count` is 0 or 1 → phase indicator not rendered (no visual clutter for simple tasks)
- `phase_outputs` has no entries → "Phase Outputs" section not rendered
- Unknown `phase_type` value → render with gray/neutral styling (forward compatibility)
- `PhaseStarted`/`PhaseCompleted` events with unrecognized fields → fall back to generic event
  renderer

## Tasks

1. Update `ui/src/types/tasks.ts`:
   - Add `current_phase_index: number`, `phase_count: number`,
     `current_phase_type: string | null`, `phase_outputs: Record<number, string>` to
     `TaskDetailResponse`.
   - Add `PhaseType` string literal union: `'build' | 'verify' | 'plan' | 'summarize' |
     'gap_check' | 'script' | 'auto_verify' | 'human_review'`.
2. Create `ui/src/components/detail/PhaseIndicator.tsx`:
   - Props: `phases_config` shape (type, label), `current_phase_index`, total count.
   - Renders a horizontal badge chain; colors by type (see architecture); pulsing animation for
     active phase; checkmark for completed; outline for pending.
   - Utility types/helpers in a separate `.ts` file (`phaseIndicatorUtils.ts`) to satisfy Fast
     Refresh requirements.
3. Update `ui/src/components/detail/TaskDetailCard.tsx`:
   - Render `<PhaseIndicator>` at top of card when `phase_count > 1`.
   - Add collapsible "Phase Outputs" section when `phase_outputs` has entries.
4. Update `ui/src/components/dashboard/StepTimeline.tsx`:
   - In the step tooltip for active tasks, render mini phase dots below the task badge.
   - Dots colored by phase type; current phase dot pulses.
5. Update `ui/src/components/detail/ActivityFeed.tsx` (or equivalent):
   - Add cases for `PhaseStarted`: render "Phase {index} started: {type}".
   - Add cases for `PhaseCompleted`: render "Phase {index} completed: {type} → Phase {index+1}".
6. Create `ui/src/__tests__/PhaseIndicator.test.tsx`:
   - All phases render in correct order.
   - Completed phases have checkmark and solid background class.
   - Active phase has pulsing class and correct color for its type.
   - Pending phases have dimmed/outline class.
   - `phase_count <= 1` → component renders nothing.
7. Add tests to existing `TaskDetailCard` test file:
   - Phase indicator appears when `phase_count > 1`.
   - Phase outputs section renders collapsible prior output text.
8. Add tests to existing `ActivityFeed` test file:
   - `PhaseStarted` event renders with type and index.
   - `PhaseCompleted` event renders with `→ Phase N+1`.

## Verification Approach

### Auto-Verify

- `npx vitest run` — all new and existing frontend tests pass.
- `npx tsc --noEmit` — TypeScript clean.
- `npx eslint src/` — ESLint clean.

### Manual Verification

- Open a task with a three-phase pipeline (`[plan, build, verify]`) in the task detail view;
  confirm the phase indicator shows three badges with correct state and color.
- Advance the task to the second phase; confirm the first badge shows a checkmark and the second
  pulses.
- Confirm prior plan output appears in the collapsible "Phase Outputs" section.
- Open the step timeline tooltip; confirm mini phase dots appear for active tasks.
- Check the activity feed; confirm `PhaseStarted` and `PhaseCompleted` entries are human-readable.

## Context & References

- Plan: `docs/phase-pipelines/plan.md` — M5 and Step 5 specification.
- Architecture: `docs/phase-pipelines/architecture.md` — phase badge colors, frontend phase
  indicator design, `TaskDetailResponse` additions.
- Memory note: utility exports must live in separate `.ts` files (React Fast Refresh requirement).
- Memory note: wrap context functions with optional params in arrow functions for `onClick`.
