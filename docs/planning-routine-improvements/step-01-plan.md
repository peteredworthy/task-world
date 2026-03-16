# Step 01: Context Injection (M1)

## Purpose

Add `context_from` declarations and prompt improvements to the optimized routine YAML so agents receive previously-generated artifacts in their prompts instead of rediscovering them via tool calls. This is the highest-impact change (~40% cost reduction) with zero risk.

## Prerequisites

- Original routine at `routines/idea-to-plan/routine.yaml` exists and is understood
- Reference docs exist: `docs/plan-runner/idea_to_plan_stripped.md`, `docs/plan-runner/idea_to_plan_detailed.md`, `docs/plan-runner/step-files.md`

## Dependencies

- **None.** This is the first step and has no dependencies on other steps.
- Step 05 (fan-out) will later supersede `context_from` entries on S-04/T-01 and S-05/T-01 with `shared_context` when those tasks are converted to fan-out.

## Functional Contract

### Inputs

- `routines/idea-to-plan/routine.yaml` (source to copy and modify)
- Reference doc file paths for injection

### Outputs

- `routines/idea-to-plan-optimized/routine.yaml` (new file) with these changes:
  1. `context_from` added to S-04/T-01: plan, architecture, clarifications
  2. `context_from` added to S-05/T-01: intent, plan, architecture, clarifications
  3. `context_from` added to S-06/T-01: architecture, clarifications (already has intent, plan, dry_run)
  4. `context_from` added to S-08/T-01: intent, plan, dry_run, verification_report
  5. `context_from` added to S-08/T-02: intent, plan, architecture
  6. Reference doc injection on S-01/T-01: `idea_to_plan_stripped.md`, `idea_to_plan_detailed.md`
  7. Reference doc injection on S-04/T-01: `step-files.md` format guide
  8. Source code suppression directive added to S-01/T-01 `task_context`

### Errors

- If a `context_from` path references a file that doesn't exist at runtime, behavior depends on the `required` field (defaults to true). Non-required entries resolve to empty string.
- If reference doc paths are wrong, agents will get empty context and fall back to reading files manually (no crash, just lost optimization).

## Changes

| File | Change |
|------|--------|
| `routines/idea-to-plan-optimized/routine.yaml` | New file, copied from original with `context_from` entries added to 5 tasks, reference doc injection on 2 tasks, source code suppression directive on S-01/T-01 |

## Verification Strategy

1. **Schema validation:** `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` passes
2. **Structural check:** All 5 target tasks have `context_from` entries; S-01/T-01 has reference doc entries and source code suppression in `task_context`
3. **Behavioral (deferred to Step 06):** Run on test idea and confirm agents don't read files that are injected via `context_from`; S-01 agent does not read source code; total tool calls decrease by 30%+
