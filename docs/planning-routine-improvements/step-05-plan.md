# Step Plan: M4b — Fan-Out Parallelism (R2 + R3)

## Purpose

Convert S-04 (Create Step Files) and S-05 (Simulate Execution) from sequential to parallel fan-out execution in the optimized routine YAML. S-05 is restructured from `dry_run` step type to a standard step with fan-out task + merge task. This achieves ~65% wall-clock time savings for the two most expensive steps.

## Prerequisites

- **Step 04 (M4a)** must be complete: two-pass template resolution and shared_context variable fix are required for per-item context in fan-out prompts
- **Steps 01-03** must be complete: optimized routine has context_from, verification, and profile changes applied
- Understanding of fan-out mechanics: `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context`, `max_concurrent`
- Fan-out variables available to sub-agents: `{{item_content}}`, `{{item_stem}}`, `{{output_path}}`

## Functional Contract

### Inputs

- Optimized routine from steps 01-03 with:
  - S-04/T-01 using `context_from` (to be replaced by `shared_context`)
  - S-05/T-01 using `context_from` and `dry_run` step type (to be restructured)
  - All tasks have `profile` fields
- Engine enhancements from step 04 (two-pass templates, shared_context variables)

### Outputs

**S-04/T-01 converted to fan_out:**
- `input_glob: "docs/{{feature}}/step-*-plan.md"`
- `output_pattern: "docs/{{feature}}/steps/{{item_stem}}.md"`
- `per_item_prompt` with step-plan content and format instructions; uses `{{item_content}}` for the step-plan file content
- `shared_context` with plan, architecture, clarifications, step-files format guide (replaces `context_from`)
- `max_concurrent: 4`
- Per-item auto-verify: `test -f {{output_path}}`
- `context_from` removed (ignored during fan_out execution)

**S-05 restructured from `dry_run` to standard step:**
- `type: dry_run` and `dry_run:` config block removed
- S-05/T-01 converted to fan_out:
  - `input_glob: "docs/{{feature}}/steps/step-*.md"`
  - `output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"`
  - `per_item_prompt` with simulation instructions; `{{item_content}}` provides step file content; `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` provides corresponding step-plan via two-pass templates
  - `shared_context` with intent, plan, architecture (replaces `context_from`)
  - `max_concurrent: 4`
  - Per-item auto-verify: `test -f {{output_path}}`
  - `profile: "architect"` retained
- S-05/T-02 added (Merge Dry Run Notes):
  - `profile: "summarizer"`
  - `context_from` with intent, plan (non-fan_out task, context_from works normally)
  - Merges per-step notes from `docs/{{feature}}/dry-run/` into `docs/{{feature}}/dry-run-notes.md`
  - Auto-verify: `test -f docs/{{feature}}/dry-run-notes.md`

**S-06 context_from updated:**
- References `docs/{{feature}}/dry-run-notes.md` (merged file from S-05/T-02, same path as before)

**Routine YAML passes schema validation.**

### Error Cases

- Fan-out `output_pattern` naming mismatch: `step-03-plan.md` stem is `step-03-plan`, producing `steps/step-03-plan.md` instead of `steps/step-03.md` → accept longer name or adjust `per_item_prompt` to specify exact output filename
- `input_glob` matches zero files → fan-out produces no sub-tasks; step completes vacuously. Guard with auto-verify on parent task or ensure upstream steps produce files.
- `shared_context` file path with unresolved `{{feature}}` → fixed by step 04 engine enhancement; if engine fix not applied, `{{feature}}` left as literal string and file not found
- S-05/T-02 merge task runs before fan-out completes → orchestrator runs tasks within a step sequentially by task order; T-02 runs after T-01 fan-out completes
- `context_from` accidentally left on fan-out task → syntactically valid but ignored at runtime; remove to avoid confusion

## Tasks

1. Convert S-04/T-01 to fan_out configuration:
   - Add `fan_out` block with `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context`, `max_concurrent`
   - Remove `context_from` (replaced by `shared_context`)
   - Add per-item auto-verify
   - Update task description to reflect fan-out behavior
2. Remove `type: dry_run` and `dry_run:` config from S-05
3. Convert S-05/T-01 to fan_out configuration:
   - Add `fan_out` block with `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context`, `max_concurrent`
   - Use `{{item_content}}` for step file content in per_item_prompt
   - Use `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` for corresponding step-plan (two-pass resolution)
   - Remove `context_from` (replaced by `shared_context`)
   - Add per-item auto-verify
4. Add S-05/T-02 (Merge Dry Run Notes):
   - `profile: "summarizer"`, `context_from` with intent and plan
   - Task prompt instructs merging all dry-run notes into single file
   - Auto-verify: merged file exists
5. Verify S-06/T-01 `context_from` still references correct dry-run output path
6. Validate routine YAML: `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml`

## Verification Approach

### Auto-Verify

- Routine YAML passes schema validation
- S-04/T-01 has `fan_out` block with required fields
- S-05 has no `type: dry_run` or `dry_run:` config
- S-05/T-01 has `fan_out` block with required fields
- S-05/T-02 exists with `profile: "summarizer"` and merge task prompt
- No `context_from` on fan_out tasks (S-04/T-01, S-05/T-01)

### Manual Verification

- Run on a small test idea (2-3 step plan) and verify:
  - S-04 fan-out spawns concurrent sub-agents (one per step-plan file)
  - Each sub-agent produces a step file at the expected output path
  - S-05 fan-out spawns concurrent sub-agents (one per step file)
  - Each sub-agent produces dry-run notes at the expected output path
  - S-05/T-02 merge task produces consolidated dry-run-notes.md
  - S-06 cross-check references the merged dry-run notes correctly
- Wall-clock for S-04 + S-05 should drop from ~25 min to ~7 min

## Context & References

- Plan: `docs/planning-routine-improvements/plan.md` — M4 steps 1-4
- Architecture: `docs/planning-routine-improvements/architecture.md` — fan-out configuration (section 2), context injection for fan-out (section 2 subsection)
- Intent: `docs/planning-routine-improvements/intent.md` — R2 (fan-out step files), R3 (fan-out simulation)
- Step 04 plan: `docs/planning-routine-improvements/step-04-plan.md` — engine prerequisites
- Clarification Q6: Restructure S-05 for fan-out with per-item context
