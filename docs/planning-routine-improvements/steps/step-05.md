# Step 5: Fan-Out Parallelism (M4b)

Convert S-04 (Create Step Files) and S-05 (Simulate Execution) from sequential to parallel fan-out execution in the optimized routine YAML. S-05 is restructured from `dry_run` step type to a standard step with fan-out task + merge task. This achieves ~65% wall-clock time savings for the two most expensive steps.

## Intent Verification
**Original Intent**: R2 (fan-out step files), R3 (fan-out simulation) from intent.md
**Functionality to Produce**:
- S-04/T-01 converted to fan_out over step-plan files with shared_context and per-item auto-verify
- S-05 restructured from `dry_run` type to standard step with fan_out T-01 + merge T-02
- Fan-out tasks use `shared_context` (not `context_from`) for common artifacts
- Per-item context via `{{item_content}}` and two-pass `{{file:...}}` templates
**Final Verification Criteria**:
- Routine YAML passes schema validation
- S-04/T-01 has fan_out configuration
- S-05 has no `type: dry_run` or `dry_run:` config
- S-05/T-01 has fan_out configuration, S-05/T-02 is merge task
- No `context_from` on fan_out tasks

---

## Task 1: Convert S-04/T-01 to Fan-Out

**Description**: Convert S-04/T-01 (Create Step Files) from a sequential task to fan-out over step-plan files. Replace `context_from` with `shared_context` and add per-item auto-verify.

**Implementation Plan (Do These Steps)**

Fan-out tasks use `shared_context` for common files and `per_item_prompt` for per-item instructions. The `context_from` field is ignored at runtime during fan_out child execution.

- [ ] In `routines/idea-to-plan-optimized/routine.yaml`, add `fan_out` block to S-04/T-01:

  **⚠️ CRITICAL: fan_out and task_context are mutually exclusive** (enforced by TaskConfig validator in models.py:215-220). You MUST remove the `task_context:` field entirely from S-04/T-01 when adding `fan_out:`. Setting task_context to empty string ("") also works but removing it is cleaner. Keeping task_context will cause schema validation to fail with: `"Task 'T-01': 'fan_out' and 'task_context' are mutually exclusive."`

  **⚠️ NAMING NOTE**: Input files from S-03 are named `step-01-plan.md`, `step-02-plan.md`, etc. The `{{item_stem}}` for `step-01-plan.md` is `step-01-plan` (the filename without extension). So `output_pattern: "docs/{{feature}}/steps/{{item_stem}}.md"` produces files named `steps/step-01-plan.md`, `steps/step-02-plan.md`, etc. This naming is fine — S-05's input_glob `steps/step-*.md` will match them — but downstream references must account for the `-plan` suffix in the stem.

  ```yaml
  fan_out:
    input_glob: "docs/{{feature}}/step-*-plan.md"
    output_pattern: "docs/{{feature}}/steps/{{item_stem}}.md"
    per_item_prompt: |
      Convert the following step plan into a step file following the step-files format guide.

      STEP PLAN:
      {{item_content}}

      Create the output file at {{output_path}}.

      Each task must be:
      - Atomic (<5 files, <500 LOC)
      - Independently verifiable
      - Runnable in sequence
      - Linked to relevant context

      Follow the step-files format guide provided in shared context.
    shared_context:
      - "{{file:docs/{{feature}}/plan.md}}"
      - "{{file:docs/{{feature}}/architecture.md}}"
      - "{{file:docs/{{feature}}/clarifications.md}}"
      - "{{file:docs/plan-runner/step-files.md}}"
    max_concurrent: 4
    auto_verify:
      items:
        - id: "step_file_exists"
          cmd: "test -f {{output_path}}"
          must: true
  ```
- [ ] **REMOVE** `task_context:` from S-04/T-01 entirely (do NOT just empty it — remove the key)
- [ ] Remove `context_from` from S-04/T-01 (replaced by `shared_context` in fan_out)
- [ ] Update S-04/T-01 `title` to reflect fan-out behavior (e.g., "Create Step Files (Fan-Out)")

**Dependencies**
- [ ] Step 01 completed — optimized routine has `context_from` on S-04/T-01
- [ ] Step 04 completed — two-pass template resolution and shared_context variable fix deployed

**References**
- Step plan: `docs/planning-routine-improvements/step-05-plan.md`
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 2 (fan-out configuration), context injection for fan-out
- Intent: `docs/planning-routine-improvements/intent.md` — R2
- Clarification Q6: Restructure for fan-out with per-item context

**Constraints**
- `context_from` must be removed from fan_out tasks — it is syntactically valid but ignored at runtime, creating confusion
- `output_pattern` naming: `step-03-plan.md` stem is `step-03-plan`, producing `steps/step-03-plan.md` — accept this naming or adjust `per_item_prompt` to specify exact output filename
- `input_glob` must match files produced by S-03 (step-plan files)

**Functionality (Expected Outcomes)**
- [ ] S-04/T-01 has a `fan_out` block with `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context`, `max_concurrent`
- [ ] S-04/T-01 has no `context_from` entries
- [ ] S-04/T-01 `fan_out.auto_verify` checks output file existence per item (MUST be inside fan_out block, not at task level)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] S-04/T-01 has `fan_out:` block in the YAML
- [ ] S-04/T-01 has no `context_from:` in its task definition
- [ ] `shared_context` references plan.md, architecture.md, clarifications.md, step-files.md

---

## Task 2: Restructure S-05 from dry_run to Fan-Out + Merge

**Description**: Remove the `dry_run` step type from S-05, convert S-05/T-01 to fan-out over step files, and add S-05/T-02 as a merge task that consolidates per-step dry-run notes into a single file.

**Implementation Plan (Do These Steps)**

S-05 currently uses `type: dry_run` with `target_steps`, `context_limit`, and `report_path`. Fan-out provides better parallelism while the merge task replaces the consolidated report.

- [ ] Remove `type: dry_run` from S-05's step definition
- [ ] Remove the entire `dry_run:` config block (target_steps, context_limit, report_path)
- [ ] Convert S-05/T-01 to fan_out:

  **⚠️ CRITICAL: fan_out and task_context are mutually exclusive.** You MUST remove the `task_context:` field entirely from S-05/T-01 when adding `fan_out:`. Same as S-04/T-01.

  **⚠️ CRITICAL: auto_verify for per-item checks MUST go INSIDE the fan_out block**, not at the task level. The executor checks `fan_out.auto_verify` for per-item verification (executor.py line 1285). Task-level `auto_verify` is for the parent task completion check, not per-child checks.

  **⚠️ STEM NAMING**: S-04 produces step files named `steps/step-01-plan.md` (stem = `step-01-plan`). The `per_item_prompt` file reference must use `{{file:docs/{{feature}}/{{item_stem}}.md}}` (NOT `{{item_stem}}-plan.md`) because the stem already contains `-plan`. Using `{{item_stem}}-plan.md` would produce `step-01-plan-plan.md` — a non-existent file.

  ```yaml
  fan_out:
    input_glob: "docs/{{feature}}/steps/step-*.md"
    output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"
    per_item_prompt: |
      Simulate execution of the following step file. For each task in the step:

      1. Walk through the tasks and capture:
         - Assumptions being made
         - Expected outputs
         - Blockers and mitigation

      2. Identify failure modes:
         - Are file references correct?
         - Are model/class names correct against actual source?
         - Does "create" vs "update" match file existence?
         - Are format-dependent interfaces specified explicitly?
         - Will existing tests break?
         - Are async/infrastructure dependencies resolved?
         - Persistence layer complete? (DB column, repo write, repo read for new fields)
         - Integration test assertions specified?

      3. For each failure mode, propose a hardening action.

      4. Apply fixes directly to the step file being analyzed.

      STEP FILE:
      {{item_content}}

      CORRESPONDING STEP PLAN:
      {{file:docs/{{feature}}/{{item_stem}}.md}}

      Save notes to {{output_path}}.
    shared_context:
      - "{{file:docs/{{feature}}/intent.md}}"
      - "{{file:docs/{{feature}}/plan.md}}"
      - "{{file:docs/{{feature}}/architecture.md}}"
    max_concurrent: 4
    auto_verify:
      items:
        - id: "dry_run_notes_exist"
          cmd: "test -f {{output_path}}"
          must: true
  ```
- [ ] **REMOVE** `task_context:` from S-05/T-01 entirely
- [ ] Remove `context_from` from S-05/T-01 (replaced by `shared_context`)
- [ ] Add S-05/T-02 (Merge Dry Run Notes):

  **⚠️ CRITICAL (GAP-17)**: The `as:` values below MUST use `context.` prefix to match `{{context.X}}` templates in task_context. Use `as: "context.intent"` and `as: "context.plan"` — see Step 01 for full explanation.

  ```yaml
  - id: "T-02"
    title: "Merge Dry Run Notes"
    profile: "summarizer"
    context_from:
      - artifact: "docs/{{feature}}/intent.md"
        as: "context.intent"
        required: true
      - artifact: "docs/{{feature}}/plan.md"
        as: "context.plan"
        required: true
    task_context: |
      Merge all per-step dry-run notes from docs/{{feature}}/dry-run/ into a single
      consolidated file at docs/{{feature}}/dry-run-notes.md.

      INTENT:
      {{context.intent}}

      PLAN:
      {{context.plan}}

      The merged file must include:
      - Per-step simulation results
      - Persistence mapping audit (table, or N/A if no new state fields)
      - Failure mode analysis (table: step, failure mode, likelihood, hardening action)
      - Cross-step risk synthesis (dependencies and risks that span multiple steps)
      - Plan changes recommended (with confirmation each is applied)
    requirements:
      - id: "R1"
        desc: "Merged dry-run-notes.md contains all per-step simulation results"
        priority: critical
    auto_verify:
      items:
        - id: "merged_notes_exist"
          cmd: "test -f docs/{{feature}}/dry-run-notes.md"
          must: true
  ```
- [ ] Verify S-06/T-01 `context_from` still references `docs/{{feature}}/dry-run-notes.md` (the merged file, same path as before)
- [ ] Update S-05/T-01 title to "Simulate Execution Per Step"
- [ ] Update S-05/T-01 requirements to reflect per-step simulation (not whole-routine)

**Dependencies**
- [ ] Step 01 completed — optimized routine exists
- [ ] Step 04 completed — two-pass template resolution enables `{{file:docs/{{feature}}/{{item_stem}}.md}}` in per_item_prompt and `{{file:...}}` format in shared_context

**References**
- Step plan: `docs/planning-routine-improvements/step-05-plan.md`
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 2 (fan-out), context injection for fan-out
- Intent: `docs/planning-routine-improvements/intent.md` — R3
- Clarification Q6: Restructure S-05 for fan-out with per-item context

**Constraints**
- S-05/T-02 runs after T-01 fan-out completes (orchestrator runs tasks within a step sequentially by task order)
- The merged output path `docs/{{feature}}/dry-run-notes.md` must match what S-06/T-01 references in `context_from`
- `context_from` is valid on S-05/T-02 because it is a non-fan_out task

**Side Effects**
- The `dry-run/` subdirectory will now contain per-step notes files instead of a single report
- S-06 cross-check references the merged file, which is the same path as before — no downstream impact

**Functionality (Expected Outcomes)**
- [ ] S-05 has no `type: dry_run` or `dry_run:` config block
- [ ] S-05/T-01 has a `fan_out` block with input_glob over step files, output_pattern for per-step notes, per_item_prompt with simulation instructions
- [ ] S-05/T-01 uses `{{file:docs/{{feature}}/{{item_stem}}.md}}` for per-item step-plan context (two-pass resolution — note: stem already includes `-plan` suffix from S-04 output naming)
- [ ] S-05/T-01 has no `context_from` entries
- [ ] S-05/T-02 exists as a merge task with `profile: "summarizer"` and `context_from` with intent and plan
- [ ] S-06/T-01 still references `docs/{{feature}}/dry-run-notes.md` in context_from

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] S-05 has no `type:` field (defaults to standard) and no `dry_run:` block
- [ ] S-05/T-01 has `fan_out:` block in the YAML
- [ ] S-05/T-02 exists with `profile: "summarizer"` and merge task instructions
- [ ] S-06/T-01 `context_from` includes `dry-run-notes.md` reference
- [ ] No `context_from` on either fan_out task (S-04/T-01, S-05/T-01)
