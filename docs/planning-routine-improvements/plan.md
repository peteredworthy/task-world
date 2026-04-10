# Plan: Idea-to-Plan Routine Optimization

## Overview

Apply seven recommendations from token usage analysis to reduce the `idea-to-plan` routine cost by 60-70% and wall-clock time by 65%. Changes produce a new optimized variant (`routines/idea-to-plan-optimized/routine.yaml`); the original routine is preserved for A/B comparison. Two small engine fixes are required: two-pass template resolution in `templates.py` (for per-item context in fan-out prompts) and passing run variables to `shared_context` resolution in `executor.py`. All other changes use existing orchestrator mechanisms.

## Milestones

Each milestone produces a valid, runnable routine YAML. Milestones build on each other but can be tested independently.

### M1: Context Injection (R1 + R6 + R7)

Add `context_from` declarations and prompt improvements. This is the highest-impact change (~40% cost reduction) with zero risk -- it only adds information that agents already discover manually.

**Changes:**
1. Add `context_from` to S-04/T-01 (Create Step Files): plan, architecture, clarifications. *(Note: M4 later converts this to fan_out, replacing `context_from` with `shared_context`)*
2. Add `context_from` to S-05/T-01 (Simulate Execution): intent, plan, architecture, clarifications. *(Note: M4 later converts this to fan_out, replacing `context_from` with `shared_context`)*
3. Add `context_from` to S-06/T-01 (Cross-Check): architecture, clarifications (already has intent, plan, dry_run).
4. Add `context_from` to S-08/T-01 (Generate Summary): intent, plan, dry_run, verification_report.
5. Add `context_from` to S-08/T-02 (Create Routine YAML): intent, plan, architecture.
6. Add reference doc injection to S-01/T-01: `idea_to_plan_stripped.md`, `idea_to_plan_detailed.md`.
7. Add reference doc injection to S-04/T-01: `step-files.md` format guide. *(Note: M4 moves this to `shared_context`)*
8. Add source code suppression directive to S-01/T-01 task_context.

**Verification:** Routine YAML validates. Run on a small test idea and confirm:
- Agents do not read files that are injected via `context_from`
- S-01 agent does not read source code files
- Total tool calls decrease by 30%+

### M2: Verification Optimization (R5)

Remove LLM verification from mechanical tasks and configure lighter verifier model.

**Changes:**
1. Remove `verifier.rubric` from S-07/T-01 (Human Final Approval). Keep auto-verify only.
2. Remove `verifier.rubric` from S-08/T-01 (Generate Summary). Add structural auto-verify: file exists + has expected sections (Intent, Risks).
3. Document that `verifier_model` should be set to `claude-sonnet-4-6` at run creation for remaining tasks.

**Verification:** Routine YAML validates. Tasks without rubrics auto-complete verification. Verifier model override works via run config.

### M3: Profile-Based Model Routing (R4)

Add `profile` fields to route tasks to appropriate model tiers.

**Changes:**
1. Add `profile: "architect"` to S-01/T-01, S-02/T-01, S-03/T-01, S-05/T-01.
2. Add `profile: "coder"` to S-04/T-01, S-06/T-01, S-08/T-02.
3. Add `profile: "summarizer"` to S-07/T-01, S-08/T-01.
4. Configure profile-to-model mappings on the CLI_SUBPROCESS agent runner:
   - `architect` -> `claude-opus-4-6`
   - `coder` -> `claude-sonnet-4-6`
   - `summarizer` -> `claude-haiku-4-5`

**Verification:** Routine YAML validates. Profile fields are accepted by schema. When run with configured profile mappings, tasks use the expected models (visible in agent metadata).

### M4: Fan-Out Parallelism (R2 + R3)

Convert sequential tasks to parallel fan-out. This is the most complex change, affecting task structure and verification flow. S-05 is restructured from `dry_run` step type to standard step with fan-out. Requires a small engine enhancement for per-item context.

**Changes:**

0a. **Engine: Two-pass template resolution** -- Modify `src/orchestrator/workflow/templates.py` `resolve_template()`:
   - Pass 1: Resolve plain `{{variable}}` placeholders (e.g., `{{feature}}`, `{{item_stem}}`)
   - Pass 2: Resolve `{{file:...}}` placeholders (now with variables already substituted in the path)
   - This enables `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` in `per_item_prompt`
   - Add unit tests for: nested resolution, missing files, edge cases
   - ~10 lines of code change

0b. **Engine: Pass run variables to shared_context resolution** -- Modify `src/orchestrator/runners/executor.py` (line ~1206):
   - Currently `shared_context` entries are resolved via `resolve_template(ctx_entry, worktree_path=worktree_path)` without variables
   - Fix: pass run config variables so `{{feature}}` in shared_context paths resolves correctly
   - One-line fix: add `variables=variables` parameter

1. Convert S-04/T-01 (Create Step Files) to `fan_out`:
   - `input_glob: "docs/{{feature}}/step-*-plan.md"`
   - `output_pattern: "docs/{{feature}}/steps/{{item_stem}}.md"` (or adjust naming)
   - `per_item_prompt` with step-plan content and format instructions
   - `shared_context` with plan, architecture, clarifications, step-files format guide
   - `max_concurrent: 4`
   - Per-item auto-verify: `test -f {{output_path}}`
   - Update outer task requirements to reflect fan-out structure

2. Restructure S-05 from `dry_run` type to standard step:
   - Remove `type: dry_run` and `dry_run:` config block (`target_steps`, `context_limit`, `report_path`)
   - Convert S-05/T-01 (Simulate Execution) to `fan_out`:
     - `input_glob: "docs/{{feature}}/steps/step-*.md"`
     - `output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"`
     - `per_item_prompt` with simulation instructions — each sub-agent receives the step file content via `{{item_content}}`
     - `shared_context` with intent, plan, architecture (identical for all sub-agents)
     - `max_concurrent: 4`
     - Per-item auto-verify: `test -f {{output_path}}`
   - **Per-item context via two-pass templates:** Fan-out's `shared_context` is the same for all items. To inject item-specific artifacts (e.g., the step-plan corresponding to each step file), use `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` in `per_item_prompt`. This requires the two-pass template resolution enhancement (M4 prerequisite) -- currently `resolve_template()` is single-pass and fails on nested `{{}}` patterns.
   - **Important:** `context_from` is syntactically valid alongside `fan_out` but is **ignored at runtime** during fan_out child execution. All context for fan_out tasks must use `shared_context` (common files) and `per_item_prompt` (per-item content). Non-fan_out tasks in the same step (e.g., S-05/T-02 merge task) can use `context_from` normally.

3. Add S-05/T-02 (Merge Dry Run Notes):
   - `profile: "summarizer"`
   - `context_from` with intent, plan
   - Task merges per-step dry-run notes from `docs/{{feature}}/dry-run/` into `docs/{{feature}}/dry-run-notes.md`
   - Auto-verify: merged file exists

4. Update S-06 cross-check `context_from` to reference `docs/{{feature}}/dry-run-notes.md` (unchanged path).

**Verification:** Routine YAML validates. Fan-out tasks spawn sub-agents correctly. S-04 produces step files in parallel. S-05 produces per-step notes + merged summary. Total wall-clock for S-04+S-05 drops from ~25 min to ~7 min.

## Implementation Order

```
M1 (context injection)  -->  M2 (verification)  -->  M3 (profiles)  -->  M4 (fan-out)
    ~40% cost savings         ~$3-5 savings          ~$5-7 savings       ~65% time savings
    30 min effort             30 min effort           1 hr effort         2-3 hr effort
```

Each milestone is independently valuable and all four are in scope. M1 alone justifies the effort; M4 adds significant wall-clock savings.

## Testing Strategy

| Milestone | Test Approach |
|-----------|--------------|
| M1 | Validate YAML. Run on small idea. Compare tool call count to baseline (703). Target: <500. |
| M2 | Validate YAML. Verify tasks without rubric auto-complete. Check no LLM verifier spawns for S-07, S-08/T-01. |
| M3 | Validate YAML. Run with profile mappings configured. Check agent metadata shows correct models per task. |
| M4 | Validate YAML. Run with 2-step plan. Verify fan-out spawns concurrent sub-agents. Check merged dry-run notes. Compare wall-clock to sequential baseline. |

**Live test:** After all milestones, run the optimized routine end-to-end using Claude CLI (already configured, no API key setup needed). Compare cost, time, and tool calls to the baseline.

**Regression check:** After each milestone, run the full routine on the same test idea used for the baseline analysis. Compare cost, time, and tool calls.

## Dependencies

- **M1-M3**: No code dependencies. Only routine YAML changes.
- **M4**: Requires two engine fixes: two-pass template resolution in `templates.py` (step 0a) and shared_context variable passing in `executor.py` (step 0b). Also depends on `fan_out` working correctly with `shared_context` and `per_item_prompt` -- verify with the engine fixes before full integration. S-05 restructure removes `dry_run` step type -- the `fan_out` mechanism replaces it.
- **Profile mappings (M3)**: Requires agent runner to have profile-to-model defaults configured. This is set via the Agents UI page or API. If not configured, profile fields are ignored and all tasks use the run's default model.
