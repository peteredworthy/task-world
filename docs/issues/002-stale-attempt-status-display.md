# Issue 002: Stale Attempt Status Display

## Problem

After run `6107f41e` S-01/T-01 was retried (max_attempts bumped from 2 to 10, eventually passing on attempt 4), the frontend displays incorrect state:

1. **Attempts #1 and #4 both show as "Building"** in the task detail view, even though attempt 1 failed auto-verify and attempt 4 completed successfully.
2. **The most recent attempt displays "building" in grey text** instead of the breathing green animation that indicates active work.

## Expected Behavior

- Attempt 1: Should show as failed (red) with the auto-verify failure details.
- Attempt 4: Should show as completed/passed (green).
- Only the currently active attempt (if any) should show the breathing green animation.
- Completed attempts should show their final outcome (passed/failed) with static styling.

## Reproduction Context

- **Run ID:** `6107f41e-66db-499b-8518-a77f467c045b`
- **Task ID:** `2fd86790-e15a-43d5-99ef-084c8e36345e` (S-01/T-01)
- **Scenario:** T-01's auto-verify command was broken (used `ClarificationQuestion(question_type='single_select', options=['a'])` missing required `id`, `question`, `context` fields). Task failed on attempts 1 and 2, then `max_attempts` was manually bumped from 2 to 10. The agent eventually passed on attempt 4.

### Actual attempt state from API (`GET /api/runs/{run_id}/tasks/{task_id}`):

```
Attempt 1: outcome=null,   completed_at=null                           (should be "failed")
Attempt 2: outcome="failed", completed_at="2026-02-17T22:59:09.949780Z"  (correct)
Attempt 3: outcome=null,   completed_at=null                           (should be "failed")
Attempt 4: outcome="passed", completed_at="2026-02-18T00:21:16.755445Z"  (correct)
```

Attempts 1 and 3 have `outcome: null` — they were never properly finalized. This causes the frontend to show them without any status indicator.

## Root Cause (Confirmed)

There are two distinct bugs: one backend, one frontend.

### Backend Bug: Auto-verify retry path does not set `outcome` on the failing attempt

When auto-verify fails and the task has retries remaining, the code path in `workflow/service.py` (around line 693-771) does the following:

1. **Line 693:** `if not all_must_passed:` — enters the auto-verify failure path.
2. **Lines 696-711:** Stores `verifier_comment` feedback on `task.attempts[-1]` (the current attempt).
3. **Line 717:** Checks `task.current_attempt >= task.max_attempts`.
4. **Line 720-721:** If max attempts exceeded, sets `task.attempts[-1].outcome = "failed"`. ✅ Correct.
5. **Line 741:** If retries remain, calls `transition_to_building(task, ...)` which creates a NEW attempt but **never sets `outcome` on the old attempt**. ❌ Bug.

The `transition_to_building` function (`workflow/transitions.py` line 52-72) appends a new `Attempt` and updates `task.current_attempt`, but has no logic to finalize the previous attempt's outcome or `completed_at`.

**Compare with the verifier grading path** (`transitions.py` line 272-275): `complete_verification` correctly sets `task.attempts[-1].completed_at = now` and `task.attempts[-1].outcome = "passed" if grade_result.passed else "revision_needed"` BEFORE creating any new attempt. The auto-verify failure path skips this entirely.

**Where outcome IS correctly set:**
- `transitions.py:190` — human approval accepted: `outcome = "passed"`
- `transitions.py:198` — human approval rejected: `outcome = "failed"`
- `transitions.py:275` — verifier grading: `outcome = "passed" | "revision_needed"`
- `transitions.py:287` — max attempts exceeded after grading: `outcome = "failed"`
- `service.py:721` — max attempts exceeded after auto-verify: `outcome = "failed"`

**Where outcome is NOT set (the bug):**
- `service.py:741` — auto-verify failure with retries remaining: **outcome stays `null`**

### Frontend Bug: `AttemptCard` does not render status for null-outcome attempts

In `ui/src/components/detail/TaskDetailCard.tsx`:

**Line 345-348** — `AttemptCard` only renders the outcome label when `att.outcome` is truthy:
```tsx
{att.outcome && (
  <span className={'text-xs font-medium uppercase ' + outcomeColor(att.outcome)}>
    {outcomeLabel(att.outcome)}
  </span>
)}
```

When `outcome` is `null`, no status indicator is rendered at all. The attempt shows as a bare "Attempt #N" with no color or label, which looks identical to a building-in-progress attempt.

**Line 53-59** — `StatusIcon` uses the task-level `status` prop for its pulse animation:
```tsx
function StatusIcon({ status }: { status: string }) {
  if (status === 'building' || status === 'verifying') {
    return (
      <span className={'inline-block h-2.5 w-2.5 rounded-full shrink-0 animate-pulse-dot ' +
        (status === 'building' ? 'bg-status-active' : 'bg-accent-purple')}
      />
    );
  }
```

This means the breathing green dot is keyed on the task's current status, not whether the specific attempt being viewed is the active one. If the task's overall status is `building`, the dot pulses regardless. If the task has completed (status is `completed`), the dot won't pulse — but stale attempts still show no outcome label.

## Fix Plan

### Backend Fix

In `workflow/service.py`, before calling `transition_to_building` on line 741, set the current attempt's outcome and completed_at:

```python
# Around line 740, BEFORE the retry:
if task.attempts:
    task.attempts[-1].outcome = "failed"
    task.attempts[-1].completed_at = self._clock.now()

rev_result = transition_to_building(task, self._clock.now())
```

This mirrors what the max-attempts path does at line 720-721 and what `complete_verification` does at line 272-275.

### Frontend Fix

In `ui/src/components/detail/TaskDetailCard.tsx`, the `AttemptCard` should handle null outcomes:

```tsx
// Instead of:
{att.outcome && (
  <span className={...}>{outcomeLabel(att.outcome)}</span>
)}

// Should be:
{att.outcome ? (
  <span className={...}>{outcomeLabel(att.outcome)}</span>
) : att.attempt_num < task.current_attempt ? (
  <span className="text-xs font-medium uppercase text-text-tertiary">interrupted</span>
) : task.status === 'building' ? (
  <span className="text-xs font-medium uppercase text-status-active">building</span>
) : null}
```

The breathing animation in `StatusIcon` should also only apply to the current active attempt, not the task-level status globally.

### Data Migration

For existing runs with null-outcome attempts, consider a one-time migration or API endpoint that retroactively sets `outcome = "failed"` on any attempt where `outcome` is null AND `attempt_num < task.current_attempt`.

## Severity

**Medium** — cosmetic/UX issue but causes confusion about the actual state of the run. Users cannot tell at a glance which attempts succeeded and which failed.
