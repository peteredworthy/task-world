# Step 03: Profile-Based Model Routing (M3)

## Purpose

Add `profile` fields to each task in the optimized routine YAML to route tasks to appropriate model tiers. Architectural reasoning tasks use Opus, structured output tasks use Sonnet, and mechanical tasks use Haiku. This saves ~$5-7 per run by using cheaper models where full reasoning power is unnecessary.

## Prerequisites

- Step 01 completed (optimized routine YAML exists)
- Profile-to-model mappings must be configured on the CLI_SUBPROCESS agent runner (via Agents UI or API) before running the routine

## Dependencies

- **Depends on:** Step 01 (the optimized routine file must exist)
- **Independent of:** Steps 02, 04, 05 (can be done in any order after Step 01)
- **Runtime dependency:** Agent runner must have profile-to-model defaults configured. If not configured, profile fields are silently ignored and all tasks use the run's default model.

## Functional Contract

### Inputs

- `routines/idea-to-plan-optimized/routine.yaml` (from Step 01)
- Profile-to-model mapping specification:
  - `architect` -> `claude-opus-4-6`
  - `coder` -> `claude-sonnet-4-6`
  - `summarizer` -> `claude-haiku-4-5`

### Outputs

- Updated `routines/idea-to-plan-optimized/routine.yaml` with `profile` fields on every task:
  - `profile: "architect"`: S-01/T-01, S-02/T-01, S-03/T-01, S-05/T-01
  - `profile: "coder"`: S-04/T-01, S-06/T-01, S-08/T-02
  - `profile: "summarizer"`: S-07/T-01, S-08/T-01

### Errors

- If `profile` value is not a valid `ModelProfile` enum value, schema validation will reject it
- If agent runner has no mapping for a profile, the profile is ignored (no error, just no cost savings)

## Changes

| File | Change |
|------|--------|
| `routines/idea-to-plan-optimized/routine.yaml` | Add `profile` field to all 9 tasks (10 after S-05/T-02 is added in Step 05) |

## Verification Strategy

1. **Schema validation:** Routine YAML validates; `profile` fields are accepted by schema
2. **Structural check:** Every task has a `profile` field with one of: `architect`, `coder`, `summarizer`
3. **Behavioral (deferred to Step 06):** When run with configured profile mappings, agent metadata shows correct models per task (Opus for architect, Sonnet for coder, Haiku for summarizer)
