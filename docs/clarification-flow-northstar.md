# Clarification Flow — North Star

This document describes the intended end-to-end behavior for the builder-asks-questions
workflow. All implementation work should be validated against it.

---

## Intended Behavior

### Step 1 — Initial Artifacts

**Task 1: The builder creates Plan, Intent, and Architecture documents.**

- No Design-Questions file is created at this stage.
- The builder gathers enough to know what it doesn't know, then moves on.

---

### Step 2 — Question Loop

**Task 1: The builder determines open questions and asks them via the orchestrator.**

1. The builder inspects the artifacts it just created (plan, intent, architecture) and identifies
   open questions that need human input before implementation can begin.

2. The builder calls `orchestrator_request_clarification` (via MCP) or the REST equivalent to
   submit those questions. Each question has a type (`single_select`, `multi_select`, `free_text`,
   or `number`), context, and optional options.

3. The run **stays ACTIVE** — it is not paused or blocked at the step/task level. The run
   enters the "waiting for user" state purely because the builder posted questions.

4. **The builder agent exits cleanly** — no need for the subprocess to stay alive while the
   human thinks. The executor loop exits naturally after discovering no BUILDING tasks remain.

5. **UI shows the waiting state** — a banner appears saying the run needs input, with a button
   to open the clarification dialogue.

6. The user answers the questions using the modal (supports all question types, "one at a time"
   or "all at once" modes, skip with reason).

7. **On response**: answers are written to the clarifications artifact file in the worktree.
   The task transitions back to BUILDING. **The executor is re-spawned automatically.**

8. The builder re-runs with the clarification file included in its context prompt. It reads
   the answers and decides:
   - If satisfied: marks the "all questions resolved" requirement as DONE, submits for
     verification.
   - If more clarification is needed: calls `orchestrator_request_clarification` again with
     a new set of questions. The loop repeats from step 3.

9. Once the builder submits, auto-verification runs followed by the LLM verifier.

---

## Key Constraints

| Property | Value |
|----------|-------|
| Run status during clarification | ACTIVE |
| Task status during clarification | PENDING_USER_ACTION |
| Step/task gate | NOT set to blocking/human_approval |
| Executor state while waiting | Exited cleanly; re-spawned on user response |
| Clarification answers location | `docs/{{feature}}/clarifications.md` (configurable) |
| Question types | single_select, multi_select, free_text, number |

---

## Identified Gaps (bugs + missing wiring)

### Backend

| # | File | Issue |
|---|------|-------|
| B1 | `src/orchestrator/mcp/tools.py` | `_request_clarification` does not forward `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` to `ClarificationQuestion`. Only `id`, `question`, `context`, `options` are passed. |
| B2 | `src/orchestrator/api/routers/clarifications.py` | `respond_to_clarification` does not re-spawn the executor after the user answers. Task goes back to BUILDING but no agent picks it up. |
| B3 | `src/orchestrator/agents/executor.py` | `_execute_task` does not pass `clarifications_path` to `generate_builder_prompt`. The re-spawned agent's prompt does not mention the clarification file. |

### Routine

| # | File | Issue |
|---|------|-------|
| R1 | `routines/idea-to-plan/routine.yaml` | S-01/T-01 creates `design-questions.md` — should only create plan, intent, architecture. |
| R2 | `routines/idea-to-plan/routine.yaml` | S-02 uses a `human_approval` gate ("Await Human Feedback") — should be replaced with a builder task that uses `orchestrator_request_clarification`. |
| R3 | `routines/idea-to-plan/routine.yaml` | Missing top-level `clarifications:` config (needed for `artifact_path`). Without it, `respond_to_clarification` cannot write answers to a file in the worktree. |

### UI

The UI is **already fully implemented** for clarifications:
- `ClarificationModal.tsx` — all question types, one-at-a-time / all-at-once modes, skip support
- `QuestionCard.tsx` — type-aware rendering
- `usePendingActions` — polls every 10 s, returns PENDING_USER_ACTION tasks
- `RunDetail.tsx` — shows banner + auto-opens modal for clarification actions
- `useRespondToClarification` — submits answers and invalidates queries

No UI changes are needed beyond what is already in place.

---

## Implementation Order

1. Fix B1 — MCP tool handler (small, isolated fix)
2. Fix B2 — `respond_to_clarification` re-spawns executor (requires adding executor dep to router)
3. Fix B3 — executor passes `clarifications_path` to prompt builder
4. Fix R1/R2/R3 — update `routines/idea-to-plan/routine.yaml`

---

## Validation Checklist

- [ ] Agent can call `orchestrator_request_clarification` with `question_type: "free_text"` (no options) — no validation error
- [ ] Agent can call with `question_type: "multi_select"` and multiple options
- [ ] After calling request_clarification, the task status is `PENDING_USER_ACTION`
- [ ] The run status stays `ACTIVE` (not paused)
- [ ] UI shows "Action required" banner
- [ ] Clicking "Review" opens the ClarificationModal with the correct questions
- [ ] User answers and submits
- [ ] Task transitions back to `BUILDING`
- [ ] Executor is re-spawned automatically (no manual resume required)
- [ ] Re-spawned builder prompt includes mention of the clarifications file
- [ ] Clarifications file exists in worktree with the Q&A content
- [ ] Builder reads answers, marks requirement DONE, submits — task proceeds to VERIFYING
- [ ] Multi-round: builder can call request_clarification a second time; above loop repeats
- [ ] idea-to-plan S-01 no longer creates design-questions.md
- [ ] idea-to-plan S-02 builder asks questions via MCP, not via human_approval gate
