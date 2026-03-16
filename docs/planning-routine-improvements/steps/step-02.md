# Step 2: Verification Optimization (M2)

Remove LLM verification from mechanical tasks (S-07/T-01 Human Approval, S-08/T-01 Generate Summary) and add structural auto-verify where needed. This eliminates unnecessary LLM verifier agent spawns, saving ~$3-5 per run.

## Intent Verification
**Original Intent**: R5 (drop LLM verification on mechanical tasks) from intent.md
**Functionality to Produce**:
- S-07/T-01 has no `verifier.rubric` (auto-verify only)
- S-08/T-01 has no `verifier.rubric`, replaced with structural auto-verify for file existence and section headers
**Final Verification Criteria**:
- Routine YAML passes schema validation
- S-07/T-01 and S-08/T-01 have no `verifier` block
- S-08/T-01 has structural auto-verify checks

---

## Task 1: Remove Verifier Rubrics and Add Structural Auto-Verify

**Description**: Remove `verifier.rubric` from S-07/T-01 and S-08/T-01 in the optimized routine, and add structural auto-verify to S-08/T-01 to replace the LLM verification with file existence and section header checks.

**Implementation Plan (Do These Steps)**

These are targeted removals and additions in the optimized routine YAML. Removing the `verifier` block causes the executor to skip LLM verifier spawning for those tasks.

- [ ] In `routines/idea-to-plan-optimized/routine.yaml`, remove the entire `verifier:` block from S-07/T-01 (Human Final Approval)
- [ ] In S-08/T-01 (Generate Summary), remove the entire `verifier:` block
- [ ] Add structural auto-verify to S-08/T-01 (if not already present with sufficient checks):
  ```yaml
  auto_verify:
    items:
      - id: "summary_exists"
        cmd: "test -f docs/{{feature}}/plan-summary.md"
        must: true
      - id: "has_sections"
        cmd: "grep -q 'Intent' docs/{{feature}}/plan-summary.md && grep -q 'Risks' docs/{{feature}}/plan-summary.md"
        must: true
  ```
- [ ] Add a comment in the routine YAML near the top noting that `verifier_model` should be set to `claude-sonnet-4-6` at run creation for remaining tasks that still have verifiers

**Dependencies**
- [ ] Step 01 completed — optimized routine exists at `routines/idea-to-plan-optimized/routine.yaml`

**References**
- Step plan: `docs/planning-routine-improvements/step-02-plan.md`
- Intent: `docs/planning-routine-improvements/intent.md` — R5
- Plan: `docs/planning-routine-improvements/plan.md` — M2 section
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 4 (auto-verify-only tasks)

**Constraints**
- S-07/T-01 must retain any existing `auto_verify` (if present) — only the `verifier` block is removed
- S-08/T-01 must have at least `auto_verify` after `verifier` removal — a task with neither has no verification at all

**Functionality (Expected Outcomes)**
- [ ] S-07/T-01 has no `verifier` key anywhere in its task definition
- [ ] S-08/T-01 has no `verifier` key anywhere in its task definition
- [ ] S-08/T-01 has `auto_verify.items` with `summary_exists` and `has_sections` checks
- [ ] All other tasks' verifier blocks remain unchanged

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] Search the YAML for `verifier:` under S-07/T-01 — must not be present
- [ ] Search the YAML for `verifier:` under S-08/T-01 — must not be present
- [ ] Search the YAML for `auto_verify:` under S-08/T-01 — must be present with `summary_exists` and `has_sections` items
- [ ] All other tasks (S-01/T-01, S-02/T-01, S-03/T-01, S-05/T-01, S-06/T-01, S-08/T-02) still have their `verifier` blocks
