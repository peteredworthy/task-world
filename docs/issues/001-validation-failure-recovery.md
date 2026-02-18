# Issue 001: Validation Test Failure Recovery

## Problem

When an auto-verify command fails and a task exhausts its `max_attempts`, the task is marked as `failed` and the run continues to the next task. There is no mechanism for human intervention, diagnosis, or guided repair. The user sees a failed task with cryptic auto-verify output and no actionable path forward except manually inspecting logs.

### Observed behavior

In run `6107f41e`, S-01/T-01 failed on attempts 1 and 2 because the auto-verify command used an incomplete constructor call (`ClarificationQuestion(question_type='single_select', options=['a'])` missing required `id`, `question`, `context` fields). The actual code changes were correct but the validation harness was broken. The run continued past the failed task, which is confusing — the task showed as failed while subsequent tasks that depended on it proceeded.

After manual intervention (bumping `max_attempts` to 10 and retrying), the task eventually passed on attempt 4, but only because the agent figured out the workaround, not because the system helped.

## Proposed Solution: Three-Level Recovery

### Level 1: Pause and Escalate

When auto-verify fails and `max_attempts` is exhausted, instead of marking the task as `failed` and moving on:

1. Transition the task to a new state: `VALIDATION_BLOCKED` (or reuse `PENDING_USER_ACTION` with `pending_action_type: "validation_failure"`).
2. Pause the run automatically.
3. Surface the failure to the user via the pending-actions system:
   - Show which auto-verify item(s) failed.
   - Show the command, exit code, and output.
   - Offer options: **Retry** (re-run the builder), **Skip** (mark task as passed despite failure), **Cancel** (fail the run).

**Backend changes:**
- `workflow/transitions.py`: Add `validation_failure` as a `pending_action_type`.
- `workflow/engine.py` or `workflow/service.py`: When auto-verify fails on final attempt, transition to blocked state instead of failed.
- `api/routers/clarifications.py` (or new router): Add endpoint to handle validation failure responses (retry/skip/cancel).
- `api/schemas`: Add `ValidationFailureAction` schema.

**Frontend changes:**
- `PendingActionsBadge`: Include validation failures in the count.
- New modal or extension of existing modals: Show auto-verify failure details with retry/skip/cancel buttons.

### Level 2: Diagnostic Agent

Before escalating to the user, run a lightweight diagnostic agent that analyzes the failure:

1. After auto-verify fails, spawn a diagnostic sub-agent (e.g., Haiku for speed/cost).
2. Provide it with:
   - The auto-verify command and its output.
   - The task context and requirements.
   - The files that were modified during the attempt.
3. The diagnostic agent produces a structured analysis:
   - **Root cause**: Why the validation failed (e.g., "test command uses incomplete constructor", "import path changed", "syntax error in generated code").
   - **Is this a code issue or a test issue?**: Distinguish between the agent's work being wrong vs. the validation harness being wrong.
   - **Suggested fix**: Concrete steps or code changes to resolve the failure.
4. Present this analysis to the user alongside the raw failure output.

**Backend changes:**
- New module: `workflow/diagnostics.py` — orchestrates the diagnostic agent call.
- `agents/interface.py`: Diagnostic agent adapter (lightweight, prompt-only, no tool use).
- `workflow/service.py`: After auto-verify failure, optionally run diagnostics before escalating.
- Config: `GlobalConfig` or routine-level setting to enable/disable diagnostic agent and choose model.

**Frontend changes:**
- Validation failure modal: Show the diagnostic analysis in a structured format (root cause, assessment, suggested fix) above the raw output.

### Level 3: Diagnostic-Suggested Fix with Human Approval

Extend Level 2 so the diagnostic agent can propose a concrete fix:

1. Diagnostic agent returns a structured fix proposal:
   - Files to modify with diffs.
   - Commands to run (if any).
   - Confidence level (high/medium/low).
2. Present the fix to the user for approval:
   - Show the proposed diffs inline.
   - "Apply fix and retry" / "Edit fix before applying" / "Skip" / "Cancel" buttons.
3. If approved, apply the fix to the worktree and re-run the validation cycle.
4. If validation fails again, repeat the diagnostic → propose → approve loop.
5. The human remains in the loop at every iteration, so they can choose to end it at any point.

**Backend changes:**
- `workflow/diagnostics.py`: Extend to return `FixProposal` (list of file diffs, commands, confidence).
- New endpoint: `POST /api/runs/{id}/tasks/{task_id}/apply-fix` — applies a proposed fix and retriggers validation.
- `workflow/service.py`: Implement the fix-apply-revalidate loop with human gating.

**Frontend changes:**
- Fix proposal modal: Render diffs (consider a simple diff viewer component), show confidence, approve/edit/reject buttons.
- Activity timeline: Show diagnostic rounds as events (collapsed by default).

## Implementation Order

1. **Level 1 first** — highest value, lowest effort. Stops the run from silently proceeding past broken tasks.
2. **Level 2 next** — adds diagnostic intelligence so users get actionable information, not just raw stderr.
3. **Level 3 last** — full self-healing loop, highest effort but enables autonomous recovery with human oversight.

## Related

- Existing clarification system (`pending_action_type: "clarification"`) provides the pattern for pausing and escalating.
- Step-level approval gates provide the pattern for human-gated progression.
- The `max_attempts` retry mechanism could be extended to include diagnostic attempts as a distinct attempt type.
