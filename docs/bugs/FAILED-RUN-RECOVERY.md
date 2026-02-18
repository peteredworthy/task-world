# Feature: Recover Failed Runs with Step/Task Rollback

## Summary

There is no supported way to recover a run from `FAILED` status. The only valid transitions from FAILED are none — it's a terminal state. When a run fails (e.g., max attempts exhausted on a task, or a cascading failure from a cosmetic error like the double `complete_verification` bug), the only recovery option is direct SQL manipulation of the database.

We need a first-class recovery mechanism that lets the user select a step/task to roll back to and continue from, using the git commit history to restore the worktree to the correct state.

## Current State

- `FAILED` is a terminal run status with no outbound transitions
- The only way to recover is manual SQL: update run status, task status, step completed flag, and bump max_attempts
- Each attempt records `end_commit` — the git commit at the end of the builder phase — which can be used to restore the worktree
- There is no UI or API for recovery

## Observed Need

Run `6107f41e-66db-499b-8518-a77f467c045b` failed because the verifier called `complete-verification` via REST, then the executor's `on_complete` callback tried to call it again after the run had already transitioned to FAILED. The task grades were R22=B, R23=A, R24=A — a legitimate grade failure, but recovery required manual DB surgery:

```sql
UPDATE runs SET status = 'paused', completed_at = NULL, pause_reason = 'recovered_from_failed' WHERE id = '...';
UPDATE tasks SET status = 'building', max_attempts = max_attempts + 1 WHERE id = '...';
UPDATE steps SET completed = 0 WHERE id = '...';
```

## Proposed Design

### API: `POST /api/runs/{run_id}/recover`

```json
{
  "target_step_id": "S-02",
  "target_task_id": "T-09",
  "additional_attempts": 1,
  "agent_type": "cli_subprocess",
  "agent_config": {}
}
```

Only `target_task_id` is required. `target_step_id` can be inferred from the task. `additional_attempts` defaults to 1.

### Recovery Logic

1. **Validate** the run is in `FAILED` (or `COMPLETED` — allow re-opening completed runs too for re-verification scenarios).

2. **Identify the target task** and all tasks that come after it in execution order (same step after it, plus all subsequent steps).

3. **Reset the target task:**
   - Status → `BUILDING`
   - Bump `max_attempts` by `additional_attempts`
   - Clear grades on checklist items (keep status as-is so prior builder work isn't lost)
   - Create a new attempt record

4. **Reset downstream tasks** (tasks after the target in execution order):
   - Status → `PENDING`
   - Reset `current_attempt` to 0
   - Clear all checklist grades
   - Optionally clear checklist status back to `open` (configurable — sometimes prior builder self-reports are still valid)

5. **Reset steps:**
   - Un-complete the target task's step and all subsequent steps
   - Preserve human approval gates that were already approved

6. **Restore the worktree** using git:
   - Find the `end_commit` from the target task's last successful attempt (or the prior task's end_commit if rolling back to re-build)
   - `git checkout {end_commit}` in the worktree directory
   - This ensures the worktree matches the state at the point we're rolling back to

7. **Transition the run:**
   - `FAILED` → `PAUSED` (with `pause_reason = "recovered"`)
   - Clear `completed_at`
   - Update `current_step_index` to the target step's index

8. The user can then call `POST /api/runs/{run_id}/resume` to restart the agent loop.

### Git Commit Integration

Each attempt already stores `end_commit` on the attempt record. The recovery flow uses this to:

- **Roll back to a step boundary:** checkout the `end_commit` of the last completed task in the prior step
- **Roll back to a task boundary:** checkout the `end_commit` of the prior task in the same step
- **Retry the same task:** checkout the `end_commit` of the target task's last attempt (so the builder's code is present but verification is re-run)

If no `end_commit` is available (e.g., the task never completed a build), fall back to the run's `source_branch` HEAD.

### UI

Add a recovery action to the run detail page when the run is in FAILED status:

- Show a timeline of steps/tasks with their status and git commits
- Let the user click on a step/task to select the rollback point
- Show a confirmation dialog with what will be reset
- Optionally allow changing the agent type/config on recovery (same as resume)

### Edge Cases

- **No worktree:** If `worktree_path` is gone (cleaned up), recovery should re-create it from the repo and checkout the appropriate commit
- **Merge conflicts:** If the source branch has diverged significantly, the checkout may fail. Surface this to the user.
- **Multiple failed tasks:** If more than one task failed, resetting to the earliest one automatically resets all subsequent ones
- **Human approval gates:** Preserve existing approvals — don't force the user to re-approve steps they already approved

## Severity

**High** — Failed runs currently require manual SQL intervention to recover. This is not viable for non-technical users or production deployments. Every failed run is effectively dead without DB access.

## Related

- `MCP-TOOLS-NO-PHASE-FILTERING.md` — the `set_grade` during BUILDING error that can cause spurious failures
- `AGENT-DEATH-HUMAN-GATE.md` — another source of runs getting stuck/failing
- Double `complete_verification` bug (fixed in `executor.py`) — the specific bug that caused the run referenced here to fail
