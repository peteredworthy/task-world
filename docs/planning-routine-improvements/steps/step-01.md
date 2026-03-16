# Step 1: Context Injection (M1)

Create the optimized routine variant by copying the original and adding `context_from` declarations, reference doc injection, and source code suppression. This is the highest-impact change (~40% cost reduction) with zero risk — it only adds information that agents already discover manually via tool calls.

## Intent Verification
**Original Intent**: R1 (context_from on all artifact-consuming tasks), R6 (embed reference docs), R7 (suppress source code exploration) from intent.md
**Functionality to Produce**:
- New routine file at `routines/idea-to-plan-optimized/routine.yaml` copied from original
- `context_from` entries on 5 tasks (S-04/T-01, S-05/T-01, S-06/T-01, S-08/T-01, S-08/T-02)
- Reference doc injection on S-01/T-01 and S-04/T-01
- Source code suppression directive on S-01/T-01
**Final Verification Criteria**:
- Routine YAML passes schema validation
- All 5 target tasks have `context_from` entries
- S-01/T-01 has reference doc entries and source code suppression in `task_context`
- Original routine at `routines/idea-to-plan/routine.yaml` is unchanged

---

## Task 1: Copy Original Routine and Add context_from to S-04, S-05, S-06, S-08

**Description**: Create the optimized routine variant by copying the original routine and adding `context_from` declarations to 5 tasks that currently lack them, plus reference doc injection and source code suppression directive.

**Implementation Plan (Do These Steps)**

This is a single-file change (new file creation) that adds context injection to the routine YAML. All changes are additive — no existing behavior is modified.

**⚠️ CRITICAL — `as:` values MUST include `context.` prefix (GAP-17)**

The prompt generator (`prompts.py:84-85`) does simple `{{key}} → value` replacement from `run_config`. The `context_builder.build_context()` returns keys matching the `as:` value directly. If `as: "intent"`, only `{{intent}}` resolves — NOT `{{context.intent}}`.

**FIX**: Every `as:` value in the YAML snippets below must be prefixed with `context.`:
- `as: "intent"` → `as: "context.intent"` (matches `{{context.intent}}`)
- `as: "plan"` → `as: "context.plan"` (matches `{{context.plan}}`)
- `as: "architecture"` → `as: "context.architecture"`
- `as: "clarifications"` → `as: "context.clarifications"`
- `as: "dry_run"` → `as: "context.dry_run"`
- `as: "verification_report"` → `as: "context.verification_report"`
- `as: "process_checklist"` → `as: "context.process_checklist"`
- `as: "process_detailed"` → `as: "context.process_detailed"`
- `as: "step_files_format"` → `as: "context.step_files_format"`

Apply this prefix to ALL `context_from` entries added by this step, AND fix the existing entries in S-02/T-01 and S-06/T-01 when copying to the optimized variant. Also applies to Step 05's merge task (S-05/T-02).

- [ ] Create directory `routines/idea-to-plan-optimized/`
- [ ] Copy `routines/idea-to-plan/routine.yaml` to `routines/idea-to-plan-optimized/routine.yaml`
- [ ] Update the routine `id` to `"idea-to-plan-optimized"` and `name` to include "Optimized"
- [ ] Add `context_from` to S-04/T-01 (Create Step Files):

  **⚠️ CRITICAL: `as:` values MUST include `context.` prefix** to match `{{context.X}}` template references in `task_context`. The prompt generator does simple `{{key}} → value` replacement. If `as: "plan"`, only `{{plan}}` resolves — NOT `{{context.plan}}`. Use `as: "context.plan"` so `{{context.plan}}` resolves correctly.

  ```yaml
  context_from:
    - artifact: "docs/{{feature}}/plan.md"
      as: "context.plan"
      required: true
    - artifact: "docs/{{feature}}/architecture.md"
      as: "context.architecture"
      required: true
    - artifact: "docs/{{feature}}/clarifications.md"
      as: "context.clarifications"
      required: false
  ```
- [ ] Add `context_from` to S-05/T-01 (Simulate Execution):
  ```yaml
  context_from:
    - artifact: "docs/{{feature}}/intent.md"
      as: "context.intent"
      required: true
    - artifact: "docs/{{feature}}/plan.md"
      as: "context.plan"
      required: true
    - artifact: "docs/{{feature}}/architecture.md"
      as: "context.architecture"
      required: true
    - artifact: "docs/{{feature}}/clarifications.md"
      as: "context.clarifications"
      required: false
  ```
- [ ] Add `context_from` to S-06/T-01 (Cross-Check) — already has intent, plan, dry_run; add:

  **Note**: Existing `as:` values in S-06/T-01 must also be prefixed with `context.` (e.g., `as: "context.intent"`) if not already. Apply same prefix to new entries:

  ```yaml
    - artifact: "docs/{{feature}}/architecture.md"
      as: "context.architecture"
      required: true
    - artifact: "docs/{{feature}}/clarifications.md"
      as: "context.clarifications"
      required: false
  ```
- [ ] Add `context_from` to S-08/T-01 (Generate Summary):
  ```yaml
  context_from:
    - artifact: "docs/{{feature}}/intent.md"
      as: "context.intent"
      required: true
    - artifact: "docs/{{feature}}/plan.md"
      as: "context.plan"
      required: true
    - artifact: "docs/{{feature}}/dry-run-notes.md"
      as: "context.dry_run"
      required: false
    - artifact: "docs/{{feature}}/verification-report.md"
      as: "context.verification_report"
      required: false
  ```
- [ ] Add `context_from` to S-08/T-02 (Create Routine YAML):
  ```yaml
  context_from:
    - artifact: "docs/{{feature}}/intent.md"
      as: "context.intent"
      required: true
    - artifact: "docs/{{feature}}/plan.md"
      as: "context.plan"
      required: true
    - artifact: "docs/{{feature}}/architecture.md"
      as: "context.architecture"
      required: true
  ```
- [ ] Add reference doc injection to S-01/T-01 via `context_from`:
  ```yaml
  context_from:
    - artifact: "docs/plan-runner/idea_to_plan_stripped.md"
      as: "context.process_checklist"
      required: false
    - artifact: "docs/plan-runner/idea_to_plan_detailed.md"
      as: "context.process_detailed"
      required: false
  ```
- [ ] Add reference doc injection to S-04/T-01 via `context_from`:
  ```yaml
    - artifact: "docs/plan-runner/step-files.md"
      as: "context.step_files_format"
      required: false
  ```
- [ ] Add source code suppression directive to S-01/T-01 `task_context`:
  ```
  IMPORTANT: Do NOT read source code files. The codebase_context input and reference
  documents above provide sufficient context. Reading source files wastes tool calls
  and tokens without improving plan quality.
  ```
- [ ] Update S-01/T-01 `task_context` to reference injected context variables (`{{context.process_checklist}}`, `{{context.process_detailed}}`)
- [ ] Update S-04/T-01 `task_context` to reference `{{context.plan}}`, `{{context.architecture}}`, `{{context.clarifications}}`, `{{context.step_files_format}}`
- [ ] Update S-05/T-01 `task_context` to reference injected context variables
- [ ] Update S-08/T-01 `task_context` to reference injected context variables
- [ ] Update S-08/T-02 `task_context` to reference injected context variables

**Dependencies**
- [ ] Original routine exists at `routines/idea-to-plan/routine.yaml`
- [ ] Reference docs exist: `docs/plan-runner/idea_to_plan_stripped.md`, `docs/plan-runner/idea_to_plan_detailed.md`, `docs/plan-runner/step-files.md`

**⚠️ CRITICAL: Reference Doc Existence Check**
Before adding `context_from` entries for reference docs, verify these files actually exist in the worktree:
```bash
test -f docs/plan-runner/idea_to_plan_stripped.md && echo "EXISTS" || echo "MISSING"
test -f docs/plan-runner/idea_to_plan_detailed.md && echo "EXISTS" || echo "MISSING"
test -f docs/plan-runner/step-files.md && echo "EXISTS" || echo "MISSING"
```
If ANY reference doc is MISSING:
1. Check if it exists in the main project root: `ls /Users/peter/code/task-world/docs/plan-runner/`
2. If it exists in main but not worktree, copy it: `cp /Users/peter/code/task-world/docs/plan-runner/*.md docs/plan-runner/` (create dir first)
3. If it doesn't exist anywhere, **SKIP** the `context_from` entries for missing files — the optimization is useless without the actual content. Keep the existing inline references in `task_context` instead (the agent will read them via tool calls as before).
4. Do NOT add `context_from` with `required: false` for files that don't exist — this silently injects nothing, giving a false sense of optimization.

**References**
- Step plan: `docs/planning-routine-improvements/step-01-plan.md`
- Intent: `docs/planning-routine-improvements/intent.md` — R1, R6, R7
- Plan: `docs/planning-routine-improvements/plan.md` — M1 section
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 1 (context_from injection)
- Original routine: `routines/idea-to-plan/routine.yaml`

**Constraints**
- The original routine at `routines/idea-to-plan/routine.yaml` must NOT be modified
- `context_from` entries must use existing artifact paths that match what the routine produces
- Reference doc paths must be correct — wrong paths result in empty context (no crash, just lost optimization)
- Note: the original routine references `docs/planner/templates/*.md` in S-01/T-01 and S-03/T-01 task_context. This directory does not contain template files (only `failure-mode-analysis.md` and `mcp-server-guide.md` exist). This is a pre-existing issue — do not try to fix it in the optimized routine.

**Functionality (Expected Outcomes)**
- [ ] `routines/idea-to-plan-optimized/routine.yaml` exists as a complete routine
- [ ] S-04/T-01 has `context_from` with plan, architecture, clarifications, and step-files format guide
- [ ] S-05/T-01 has `context_from` with intent, plan, architecture, clarifications
- [ ] S-06/T-01 has `context_from` with intent, plan, dry_run, architecture, clarifications
- [ ] S-08/T-01 has `context_from` with intent, plan, dry_run, verification_report
- [ ] S-08/T-02 has `context_from` with intent, plan, architecture
- [ ] S-01/T-01 has reference doc `context_from` entries and source code suppression directive
- [ ] Original routine is byte-identical to its git HEAD version

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] `git diff HEAD -- routines/idea-to-plan/routine.yaml` shows no output (original unchanged)
- [ ] Verify S-04/T-01, S-05/T-01, S-06/T-01, S-08/T-01, S-08/T-02 each have `context_from` entries by searching the YAML
- [ ] Verify S-01/T-01 task_context contains "Do NOT read source code" directive
- [ ] Verify S-01/T-01 has context_from entries for `idea_to_plan_stripped.md` and `idea_to_plan_detailed.md`
