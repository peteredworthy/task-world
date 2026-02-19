# Step 2: Rewrite Human Gate Task Prompts (AGENT-DEATH-HUMAN-GATE — Routine)

This step replaces no-op wait instructions in `idea-to-plan.yaml` human gate tasks (S-02 and S-08)
with actionable prompts that direct the CLI agent to verify human feedback annotations in artifact
files, mark the checklist requirement done or blocked, and submit. This is the second half of the
AGENT-DEATH-HUMAN-GATE fix; once human feedback exists in the artifact files, the agent can
self-resolve the gate without manual intervention.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "Rewrite no-op human gate task prompts in `idea-to-plan.yaml` (S-02, S-08) to be actionable"
**Functionality to Produce**:
- S-02 T-01 prompt instructs the agent to check artifact files for `[HUMAN]` annotations and mark R1 done if present or blocked if absent
- S-08 task prompt is updated with the same pattern
- YAML remains syntactically valid after the changes

**Final Verification Criteria**:
- `python -c "import yaml; yaml.safe_load(open('routines/idea-to-plan.yaml'))"` exits 0
- S-02 T-01 prompt contains actionable "mark" and "done" instructions
- S-08 prompt contains the same pattern

---

## Task 1: Update S-02 T-01 human gate prompt in idea-to-plan.yaml
**Description**:
Replace the current no-op "Await Human Feedback" task context in S-02 T-01 with an actionable
verification prompt. The new prompt must instruct the agent to check the relevant artifact files
for `[HUMAN]` annotations, mark R1 as `done` if confirmed, or mark R1 as `blocked` with an
explanatory note if no artifacts exist, then submit.

**Implementation Plan (Do These Steps)**
The current S-02 T-01 prompt tells the agent to wait — it has nothing actionable to do and exits
cleanly. We need to replace it with instructions that produce a concrete MCP call.

- [ ] Open `routines/idea-to-plan.yaml` and locate the S-02 T-01 task definition
- [ ] Replace the `task_context` (or equivalent prompt field) with the following pattern:
```yaml
task_context: |
  Check the following artifact files for [HUMAN] annotations indicating that a human
  has reviewed and approved the plan:
    - docs/{{feature}}/intent.md
    - docs/{{feature}}/plan.md
    - docs/{{feature}}/design-questions.md
    - docs/{{feature}}/architecture.md

  If any of these files contain [HUMAN] annotations or if it is evident that the human
  has approved the plan (e.g., the files exist and are complete), mark R1 as done and submit.

  If the artifact files do not exist or contain no [HUMAN] annotations, mark R1 as blocked
  with the note "Awaiting human review — no [HUMAN] annotations found in artifact files" and submit.
```
- [ ] Preserve the rest of the task definition (task ID, step reference, requirements list, etc.) unchanged

**References**
- `docs/bug-removal/step-02-plan.md` — Task 1 description
- `docs/bugs/AGENT-DEATH-HUMAN-GATE.md` — Issue 2 (no-op prompt) and Proposed Fix 2
- `docs/bug-removal/architecture.md` — "Modified Components: routines/idea-to-plan.yaml"

**Constraints**
- [ ] Only the `task_context`/prompt field of S-02 T-01 should change; do not alter task IDs, step structure, or requirement IDs
- [ ] The `{{feature}}` template variable must be preserved as-is (it is substituted at runtime)

**Functionality (Expected Outcomes)**
- [ ] S-02 T-01 prompt contains explicit file paths with the `{{feature}}` template variable
- [ ] S-02 T-01 prompt contains instructions to mark R1 `done` or `blocked`
- [ ] S-02 T-01 prompt contains a `submit` instruction

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `python -c "import yaml; yaml.safe_load(open('routines/idea-to-plan.yaml'))"` exits 0
- [ ] `grep -A 20 "S-02" routines/idea-to-plan.yaml | grep -c "done"` returns at least 1
- [ ] `grep -A 20 "S-02" routines/idea-to-plan.yaml | grep -c "blocked"` returns at least 1

---

## Task 2: Update S-08 human gate prompt in idea-to-plan.yaml
**Description**:
Apply the same actionable prompt pattern to the S-08 final review gate task. S-08 is the final
plan review human gate; its prompt should follow the same structure: check artifacts, mark done or
blocked, submit.

**Implementation Plan (Do These Steps)**
- [ ] In `routines/idea-to-plan.yaml`, locate the S-08 task definition
- [ ] Replace the S-08 task prompt with the same actionable verification pattern as S-02 T-01:
```yaml
task_context: |
  Check the following artifact files for [HUMAN] annotations indicating that the final
  plan review has been completed:
    - docs/{{feature}}/intent.md
    - docs/{{feature}}/plan.md
    - docs/{{feature}}/architecture.md

  If [HUMAN] annotations are present or the human has clearly approved the final plan,
  mark R1 as done and submit.

  If no [HUMAN] annotations are found, mark R1 as blocked with the note
  "Awaiting final human review — no [HUMAN] annotations found" and submit.
```
- [ ] Preserve the rest of the S-08 task definition unchanged

**References**
- `docs/bug-removal/step-02-plan.md` — Task 2 description
- `docs/bugs/AGENT-DEATH-HUMAN-GATE.md` — S-08 gate task

**Constraints**
- [ ] Only the S-08 task prompt should change; no other tasks or steps should be modified

**Functionality (Expected Outcomes)**
- [ ] S-08 task prompt contains explicit instructions to check artifact files for `[HUMAN]` annotations
- [ ] S-08 task prompt includes mark-done and mark-blocked branches

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `python -c "import yaml; yaml.safe_load(open('routines/idea-to-plan.yaml'))"` exits 0
- [ ] `grep -A 20 "S-08" routines/idea-to-plan.yaml | grep -c "done"` returns at least 1
- [ ] `grep -A 20 "S-08" routines/idea-to-plan.yaml | grep -c "blocked"` returns at least 1
