# Step 4 Plan: Attempt Cost + Auto-Verify Output + Step Progress Text (Gaps 5, 6, 9)

## Purpose

Surface per-attempt cost data, auto-verify command output, and textual step progress on the dashboard. These MEDIUM-severity improvements give users better visibility into execution costs, verification results, and run progress at a glance.

## Prerequisites

- None (independent of Steps 1–3)

## Functional Contract

### Inputs

- `attempts_summary` data from the run detail API — contains per-attempt `tokens_read`, `tokens_write`, `duration_ms` fields
- Auto-verify events in the activity feed — contain `stdout` and `stderr` fields in the event payload
- Run step data — `current_step` (number) and `total_steps` (number) from the run summary for dashboard cards

### Outputs

- `AttemptMetrics` component at `components/detail/AttemptMetrics.tsx` — shows token counts (read/write) and estimated cost per attempt
- `AttemptHistory` updated to render AttemptMetrics inline for each attempt
- `AutoVerifyOutput` component at `components/detail/AutoVerifyOutput.tsx` — collapsible `<pre>` block for stdout/stderr
- `ActivityFeed` updated to embed AutoVerifyOutput within auto-verify event entries
- `RunCard` updated to show "Step X of Y" text alongside the existing StepTimeline component

### Errors

- Attempt has zero/null token counts → show "No usage data" placeholder instead of metrics
- Auto-verify output is empty → show "No output captured" message in collapsed block
- Step count data missing → omit "Step X of Y" text (graceful degradation)

## Tasks

1. Create `components/detail/AttemptMetrics.tsx` displaying token read/write counts and estimated cost (tokens × rate)
2. Update `components/detail/AttemptHistory.tsx` to render AttemptMetrics for each attempt in the list
3. Create `components/detail/AutoVerifyOutput.tsx` as a collapsible code block (collapsed by default) with max-height and overflow scroll
4. Update `components/detail/ActivityFeed.tsx` to embed AutoVerifyOutput in auto-verify event entries
5. Update `components/dashboard/RunCard.tsx` to show "Step X of Y" text next to StepTimeline

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `AttemptMetrics.tsx` exists at `ui/src/components/detail/AttemptMetrics.tsx`
- [ ] `AutoVerifyOutput.tsx` exists at `ui/src/components/detail/AutoVerifyOutput.tsx`
- [ ] `RunCard.tsx` contains "Step" text rendering logic

### Manual Verify

- [ ] AttemptHistory shows token counts and cost per attempt
- [ ] Attempts with no usage data show appropriate placeholder
- [ ] Auto-verify output block is collapsed by default and expands on click
- [ ] Large auto-verify output scrolls within the container (no layout thrash)
- [ ] Dashboard RunCard shows "Step X of Y" text for runs with step data

## Context & References

- Gap analysis: Gaps 5 (attempt cost), 6 (auto-verify output), 9 (step progress text) — all MEDIUM
- Design decision Q6: Collapsible code block in ActivityFeed (collapsed by default)
- Architecture: `AutoVerifyOutput` uses `<pre>` with collapsible wrapper matching existing log viewer patterns
- Performance note: auto-verify output can be large — max-height + overflow scroll required
