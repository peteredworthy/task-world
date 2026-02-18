# Step 7 Plan: Grade Threshold + Blocked State + Elapsed Time (Gaps 15, 16, 17)

## Purpose

Show grade threshold explanations when verification fails, add a visual blocked-on-human state, and display live elapsed time for active runs. These LOW-severity gaps improve user understanding of verification outcomes, run states, and execution duration.

## Prerequisites

- None (independent of Steps 1–6)

## Functional Contract

### Inputs

- Checklist/grade data: per-requirement scores, threshold value, critical item statuses — from run detail checklist API response
- Verification outcome: `pass`/`fail` status with grade details — triggers threshold explainer visibility
- Run pending actions: presence of human-requiring actions (approval, clarification) while run status is `ACTIVE` — triggers blocked-on-human state
- Run timing data: `started_at` timestamp (ISO 8601) from run detail — used to calculate elapsed time
- Run status: `ACTIVE` — elapsed timer only ticks for active runs

### Outputs

- `GradeThresholdExplainer` component at `components/detail/GradeThresholdExplainer.tsx` — shows average score vs threshold, lists critical item failures, explains why verification failed
- `ChecklistTable` updated to render GradeThresholdExplainer when verification outcome is `fail`
- `StatusBadge` updated with a `blocked-on-human` variant — distinct color/icon when run is ACTIVE but has pending human actions
- `ElapsedTimer` component at `components/detail/ElapsedTimer.tsx` — live counter showing `HH:MM:SS` since run started
- `MetricsBar` updated to include ElapsedTimer for active runs

### Errors

- Grade data incomplete (missing scores or threshold) → show "Grade details unavailable" placeholder instead of explainer
- No pending human actions → standard StatusBadge behavior (no blocked variant)
- `started_at` is null → omit ElapsedTimer entirely
- Run completes while timer is active → timer stops and shows final elapsed time

## Tasks

1. Create `components/detail/GradeThresholdExplainer.tsx` showing threshold calculation: average score, threshold value, critical failures list
2. Update `components/detail/ChecklistTable.tsx` to render GradeThresholdExplainer below the table when verification fails
3. Update `components/StatusBadge.tsx` to add `blocked-on-human` variant with distinct styling (amber color, hand/pause icon)
4. Update `pages/RunDetail.tsx` to pass blocked-on-human state to StatusBadge when applicable
5. Create `components/detail/ElapsedTimer.tsx` using `useEffect` + `setInterval(1000)` for live HH:MM:SS display
6. Update `components/detail/MetricsBar.tsx` to render ElapsedTimer for active runs

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `GradeThresholdExplainer.tsx` exists at `ui/src/components/detail/GradeThresholdExplainer.tsx`
- [ ] `ElapsedTimer.tsx` exists at `ui/src/components/detail/ElapsedTimer.tsx`
- [ ] `StatusBadge.tsx` handles a `blocked-on-human` variant

### Manual Verify

- [ ] ChecklistTable shows threshold explanation when verification fails
- [ ] Threshold explainer correctly shows average score vs threshold and critical failures
- [ ] StatusBadge displays blocked-on-human variant when run is ACTIVE with pending human actions
- [ ] ElapsedTimer ticks every second for active runs
- [ ] Timer stops when run completes and shows final elapsed time
- [ ] Timer is absent for runs without `started_at` data

## Context & References

- Gap analysis: Gaps 15 (grade threshold), 16 (blocked state), 17 (elapsed time) — all LOW
- Architecture: ElapsedTimer uses `useEffect` + `setInterval` (simple client-side, no server dependency)
- Performance: 1s interval timer has negligible CPU impact
- StatusBadge: extends existing badge component with one new variant
