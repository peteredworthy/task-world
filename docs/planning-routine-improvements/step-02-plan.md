# Step 02: Verification Optimization (M2)

## Purpose

Remove LLM verification from mechanical tasks and configure lighter verifier models. This eliminates unnecessary LLM verifier agent spawns on tasks where auto-verify commands fully validate output, saving ~$3-5 per run.

## Prerequisites

- Step 01 completed (optimized routine YAML exists at `routines/idea-to-plan-optimized/routine.yaml`)

## Dependencies

- **Depends on:** Step 01 (the optimized routine file must exist)
- **Independent of:** Steps 03, 04, 05 (can be done in any order after Step 01)
- **No downstream blockers**

## Functional Contract

### Inputs

- `routines/idea-to-plan-optimized/routine.yaml` (from Step 01)

### Outputs

- Updated `routines/idea-to-plan-optimized/routine.yaml` with:
  1. `verifier.rubric` removed from S-07/T-01 (Human Final Approval) -- auto-verify only
  2. `verifier.rubric` removed from S-08/T-01 (Generate Summary) -- replaced with structural auto-verify
  3. New structural auto-verify on S-08/T-01: file exists + has expected sections (Intent, Risks)
  4. Documentation note that `verifier_model` should be set to `claude-sonnet-4-6` at run creation for remaining tasks

### Errors

- If auto-verify commands have syntax errors, verification fails and the task blocks. Commands must be tested.
- If `verifier.rubric` is removed but `auto_verify` is also missing, the task will have no verification at all -- ensure at least auto-verify remains.

## Changes

| File | Change |
|------|--------|
| `routines/idea-to-plan-optimized/routine.yaml` | Remove `verifier.rubric` from S-07/T-01 and S-08/T-01; add structural auto-verify to S-08/T-01 |

## Verification Strategy

1. **Schema validation:** Routine YAML validates successfully
2. **Structural check:** S-07/T-01 and S-08/T-01 have no `verifier.rubric` key; S-08/T-01 has `auto_verify.items` with `summary_exists` and `has_sections` checks
3. **Behavioral (deferred to Step 06):** Tasks without rubrics auto-complete verification without spawning LLM verifier agents
