# Bug: Agent Death on Human Approval Gate Tasks

## Summary

When a `human_approval` gate step contains a task with checklist requirements, the CLI agent exits successfully (code 0) but the automatic `on_submit()` call fails because the checklist gate is not satisfied. The `GateBlockedError` is not handled explicitly, so it's wrapped as `AgentExecutionError` and the run is paused with `agent_execution_error`. This requires manual intervention to resume, defeating the purpose of autonomous operation.

## Reproduction

1. Run the `idea-to-plan` routine with a CLI agent (claude or codex)
2. Complete Step 1 (Initial Plan)
3. Approve Step 2's human approval gate via `POST /api/runs/{id}/steps/{step_id}/approve`
4. The agent spawns for S2's task "Await Human Feedback"
5. The agent reads the prompt ("Wait for human feedback. Do not generate [HUMAN] notes. Continue only after approval."), finds nothing actionable, and exits cleanly
6. `on_submit()` fires, checklist gate evaluates R1 as `open`, raises `GateBlockedError`
7. Run pauses with `agent_execution_error`

Observed in run `70577a15-5a02-4235-9a42-0c27ef966bc5` — happened 3 consecutive times on the same task.

## Root Cause

Two separate issues combine to cause this:

### Issue 1: `GateBlockedError` not handled in CLI agent

**File:** `src/orchestrator/agents/cli.py`, lines 438-457

The `execute()` method has explicit re-raises for `AgentCancelledError`, `AgentExecutionError`, and `AgentNotAvailableError`. But `GateBlockedError` (raised by `on_submit()` → `service.submit_for_verification()` → `engine.submit_for_verification()`) falls through to the generic `except Exception` handler, which wraps it as an `AgentExecutionError` and triggers `on_agent_died`.

```python
# Current code (cli.py:438-457)
except AgentCancelledError:
    raise
except AgentExecutionError:
    raise
except AgentNotAvailableError:
    raise
except Exception as exc:
    # GateBlockedError lands here — treated as a crash
    ...
    raise AgentExecutionError("cli_subprocess", str(exc)) from exc
```

### Issue 2: Human gate task prompt doesn't instruct the agent to verify and mark requirements

**File:** `routines/idea-to-plan.yaml`, S-02 task T-01

The task prompt says:

> "Wait for human feedback. Do not generate [HUMAN] notes. Continue only after approval."

This is a no-op instruction for a CLI agent. The agent reads it, has nothing to do, and exits. It never marks R1 ("Human feedback is present and gate is approved") as `done` because the prompt doesn't tell it to check for approval status or mark the checklist.

## Proposed Fix

### Fix 1: Handle `GateBlockedError` as a revision trigger, not a crash

When `on_submit()` raises `GateBlockedError`, the agent should not die. Instead, the executor should treat it the same as a failed checklist gate during normal operation — loop back to the builder phase so the agent gets another chance with feedback about what requirements are still open.

**Changes to `src/orchestrator/agents/cli.py`:**

Add `GateBlockedError` to the import and handle it in the execute method. Rather than adding it to the re-raise list (which would still crash the agent loop in the executor), catch it before `on_submit` or let the executor handle it:

```python
# Option A: Catch GateBlockedError in cli.py execute(), don't call on_submit if gate would fail
# This requires access to the gate check, which cli.py doesn't have.

# Option B (preferred): Add GateBlockedError to the explicit re-raise list in cli.py,
# then handle it in the executor's _execute_task method as a revision signal.
except GateBlockedError:
    raise  # Let executor handle this as a revision, not a crash
```

**Changes to `src/orchestrator/agents/executor.py`:**

In `_execute_task`, catch `GateBlockedError` from the agent execution and treat it as "requirements not met — retry the builder phase":

```python
try:
    result = await agent.execute(...)
except GateBlockedError as e:
    logger.warning(f"Task {task_state.id}: checklist gate blocked on submit: {e}")
    # Don't kill the agent or pause the run.
    # The task stays in BUILDING state. The executor loop will re-enter
    # _execute_task, spawning a new agent with feedback about what's still open.
    return
```

This means: if the agent exits successfully but the checklist gate blocks submission, the task stays in `building` and the executor loop picks it up again on the next iteration. The new agent instance gets a prompt that includes feedback about which requirements are still open, giving it a chance to mark them.

### Fix 2: Rewrite human gate task prompts to be actionable

The S-02 task prompt should instruct the agent to:
1. Check that the human approval gate has been satisfied
2. Verify the [HUMAN] feedback annotations exist in the artifact files
3. Mark R1 as `done` once confirmed
4. Submit

**Proposed prompt for `routines/idea-to-plan.yaml` S-02 T-01:**

```yaml
task_context: |
  The human review gate for this step has been approved.
  Your job is to confirm that human feedback is present in the planning artifacts.

  Check these files for [HUMAN] annotations or other feedback:
  - docs/{{feature}}/intent.md
  - docs/{{feature}}/plan.md
  - docs/{{feature}}/design-questions.md
  - docs/{{feature}}/architecture.md

  If feedback is present (or the human approved without inline notes, which is
  also valid), mark requirement R1 as done and submit.

  If no artifacts exist yet, mark R1 as blocked with a note explaining why.
```

This gives the agent something concrete to do: read the files, confirm feedback exists, mark the checklist, and submit. If it fails to mark R1, the GateBlockedError handling from Fix 1 will loop it back to try again with feedback about the open requirement.

### Fix 3 (optional): Handle the same pattern in S-08

S-08 "Final Plan Review" has the same structure — a `human_approval` gate with a stub task. Apply the same prompt fix there to prevent the identical failure at the end of the routine.

## Observed Occurrences

### Run `70577a15-5a02-4235-9a42-0c27ef966bc5`

**S-02 (Human Review):** Agent died 3 consecutive times on the same task. Each time:
1. Step approved via `POST /api/runs/{id}/steps/{step_id}/approve`
2. Agent spawned for T-01 "Await Human Feedback"
3. Agent read the no-op prompt, found nothing actionable, exited cleanly (code 0)
4. `on_submit()` fired, checklist gate evaluated R1 as `open`, raised `GateBlockedError`
5. Run paused with `agent_execution_error`

**Manual workaround:** Resume run → PATCH R1 checklist item to `done` → POST submit. Task moved to verifying → completed.

**S-08 (Final Plan Review):** Same structure — `human_approval` gate with stub task. The run paused with `agent_health_check_failed` before the agent even started the S8 task (likely a timing issue with the gate check). After resume and step approval, the agent happened to succeed on this attempt — but the underlying bug remains: the prompt is still a no-op, and success depends on the agent coincidentally marking the requirement. The same 3-failure pattern from S-02 could easily recur.

**Additional observation:** Between S-02 and S-08, the run also paused with `agent_health_check_failed` during S-07 (Final Check) while in `verifying` state — a separate but related reliability issue with agent health monitoring triggering false positives during normal verification.

### Impact on This Run

The combination of agent death on human gates + missing frontend capabilities meant:
- The user could not see the generated plan/summary to review it — **the UI has no ability to display particular files or agent output** from the worktree, so there is no way to inspect what the agent produced before approving
- The user could not approve the step through the UI — no step-level approval UI exists (Gap 1)
- The user could not mark checklist requirements through the UI
- The user could not see or answer design questions through the UI — **the UI has no mechanism for displaying structured questions generated by the agent** (e.g., the design-questions.md from S-01), nor for capturing user answers and feeding them back to the orchestrator. Questions had to be answered by manually editing files in the worktree.
- Every human gate required manual API intervention via `curl`
- The run paused 5+ times requiring manual intervention to progress

### Missing UI Capabilities (Contributing Factors)

These are not bugs in the agent/executor but are missing frontend features that compound the human gate problem:

1. **No file/output viewer:** The UI cannot display files from the run's worktree (e.g., the generated `plan.md`, `architecture.md`, `verification-report.md`). At human review gates, the user needs to see what was produced before approving. Without this, the user must browse the filesystem or use `curl`/`cat` to read artifacts.

2. **No question/answer UI:** The UI cannot present structured questions to the user or capture answers. When the idea-to-plan routine generates `design-questions.md` (S-01), the user must manually edit the file in the worktree to provide answers with `[HUMAN]` annotations. There is no mechanism for the agent to define questions in a structured format that the frontend can render as an interactive form. (This was identified as Gap 22 during the run and tracked in the generated plan.)

## Severity

**High** — This bug breaks autonomous operation of any routine with `human_approval` gates. The run cannot progress past the gate without manual API intervention (marking the checklist item and calling submit). This defeats the purpose of the orchestrator managing the workflow automatically.

## Affected Routines

- `idea-to-plan.yaml` — Steps S-02 and S-08
- Any future routine using `human_approval` gates with checklist requirements

## Related Gap

This is directly related to Gap 1 in `docs/stories/GAP-ANALYSIS-FRONTEND.md` ("No step-level approval UI"). Even after the frontend gap is closed, the backend/agent interaction described here would still cause failures if the prompt and error handling aren't fixed.
