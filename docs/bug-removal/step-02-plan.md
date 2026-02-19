# Step 2 Plan: Rewrite Human Gate Task Prompts (AGENT-DEATH-HUMAN-GATE — Routine)

## Purpose

Replace no-op wait instructions in `idea-to-plan.yaml` human gate tasks with actionable prompts that instruct the CLI agent to verify the existence of human feedback annotations in artifact files, mark the checklist requirement done, and submit. Without this fix, the agent reads the prompt, finds nothing to do, exits cleanly (code 0), and the executor must retry indefinitely until a human marks the requirement manually. This is the second half of the AGENT-DEATH-HUMAN-GATE fix; it makes the human gate self-resolving once the gate is approved and feedback exists.

## Prerequisites

- Step 1 (GateBlockedError handling) must be complete — the retry loop in `executor.py` must be in place so that if the agent still fails to mark R1, it gets another chance with feedback rather than crashing the run

## Functional Contract

### Inputs

- `routines/idea-to-plan.yaml` S-02 T-01 task definition (the "Await Human Feedback" gate task)
- `routines/idea-to-plan.yaml` S-08 task definition (the "Final Plan Review" gate task)
- Template variable `{{feature}}` — resolved to the feature directory name at runtime

### Outputs

- S-02 T-01 prompt updated to instruct the agent to:
  1. Check `docs/{{feature}}/intent.md`, `plan.md`, `design-questions.md`, `architecture.md` for `[HUMAN]` annotations
  2. Mark R1 as `done` if feedback is confirmed (or if the human approved without inline notes)
  3. Mark R1 as `blocked` with an explanatory note if no artifacts exist
  4. Submit
- S-08 task prompt updated with the same pattern (check for final review annotations → mark R1 done → submit)

### Errors

- If `{{feature}}` template variable is not substituted at runtime, the agent will look for literal `{{feature}}` paths — this is a runtime configuration issue, not a YAML defect
- If neither `done` nor `blocked` is submitted by the agent, the executor retry loop (from Step 1) will re-invoke the agent with open-requirement feedback

## Tasks

1. In `routines/idea-to-plan.yaml` S-02 T-01: replace the current `task_context` with the actionable verification prompt (check artifact files for `[HUMAN]` annotations, mark R1 done or blocked, submit)
2. In `routines/idea-to-plan.yaml` S-08: apply the same prompt pattern to the final review gate task
3. Manual inspection: verify the updated prompts contain explicit file paths and checklist action instructions with no ambiguity

## Verification

### Auto-Verify

- [ ] YAML is valid: `python -c "import yaml; yaml.safe_load(open('routines/idea-to-plan.yaml'))"` exits 0
- [ ] S-02 T-01 prompt contains the phrase "mark" and "done" (grep check confirms actionable instruction)
- [ ] S-08 task prompt contains the same pattern (grep check)

### Manual Verify

- [ ] Spin up a stub CLI agent with the new S-02 prompt; confirm the agent produces a `update_checklist` (R1 done) MCP call rather than exiting with no action
- [ ] End-to-end: run `idea-to-plan` through S-02 human gate approval; agent marks R1 done and submits without requiring manual checklist patch

## Context & References

- Bug report: `docs/bugs/AGENT-DEATH-HUMAN-GATE.md` — Issue 2 (no-op prompt) and Proposed Fix 2
- Source file: `routines/idea-to-plan.yaml` — S-02 and S-08 gate tasks
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: routines/idea-to-plan.yaml"
- Prerequisite: Step 1 (GateBlockedError executor handling)
