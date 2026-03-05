# Step 5: Trim prompt dead weight (A7)

**Milestone:** M2 — Prompt & Context Efficiency
**Plan:** [step-05-plan.md](../step-05-plan.md)
**Architecture:** [architecture.md](../architecture.md) §4 (Prompt Builder, A7)
**Intent:** [intent.md](../intent.md) — Completion Criteria #5
**Clarification:** Q6 in [clarifications.md](../clarifications.md) — remove identified sections only, percentage is informational

## Tasks

### Task 5.1: Remove dead-weight sections from system prompt

Remove the "Avoiding Loops" section (~512 chars) and other agent-behavioral
instructions identified in D4 as dead weight from `prompts.py`. Retain all
required sections (task context, requirements, callback instructions).

**Files:** `src/orchestrator/workflow/prompts.py`
**LOC estimate:** ~30 (deletions mostly)
**Verify:** Unit tests — generated prompt does not contain "Avoiding Loops"
or other removed sections; still contains required sections. Existing prompt
tests pass with updated expectations.
