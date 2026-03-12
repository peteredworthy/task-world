# Step Plan: Executor + Prompts

## Purpose

Connect the executor to the engine lifecycle so verifier agents are actually spawned. This step implements the step verifier prompt generator and wires the executor to detect when step verification should run, spawn the verifier agent, parse its JSON output, and call the engine lifecycle methods.

## Prerequisites

- Step 1 complete: `StepVerifierConfig`, `GapReport`, `GapAction`, `StepVerdict`, event types all defined.
- Step 2 complete: `start_step_verification` and `complete_step_verification` on `WorkflowEngine` working and tested.

## Functional Contract

### Inputs

**Prompt builder (`build_step_verifier_prompt`):**
- `step_config: StepConfig` — contains `step_verifier.prompt`, `step_verifier.auto_verify`
- `step_state: StepState` — contains task list with statuses, last attempt grades, `auto_verify_results`
- `auto_verify_results: list[AutoVerifyResult]` — results from step-level auto-verify (if configured)

**Executor integration:**
- After inner task execution loop: all tasks in step reach terminal state
- `step_config.step_verifier` is not None

### Outputs

**`build_step_verifier_prompt` returns `str`:**
```
{step_verifier.prompt}

## Step Context
...

## Task Outcomes
### {task.config_id}: {task.title}
Status: ...
Last attempt outcome: ...
Grades: ...
Auto-verify results: ...

## Step Auto-Verify Results
...

## Required Output
You MUST respond with a JSON object matching this schema:
{"assessment": "...", "verdict": "pass"|"retry"|"fix"|"fail", "actions": [...]}
Respond with JSON only. No markdown fences, no preamble.
```

**Executor step verifier flow:**
1. Detects all tasks terminal and `step_verifier` configured
2. Calls `service.start_step_verification(run_id, step.id)`
3. Runs `step_verifier.auto_verify` items via existing `LocalAutoVerifyRunner` (if configured)
4. Builds prompt via `build_step_verifier_prompt`
5. Spawns verifier agent with prompt (same agent runner as tasks in the step)
6. Parses JSON from agent output using `json.loads`
7. Validates parsed dict against `GapReport` schema
8. On parse/validation error: constructs `GapReport(verdict=FAIL, assessment="Parse error: {details}")`
9. Calls `service.complete_step_verification(run_id, step.id, gap_report)`
10. If `retry_task` or `spawn_fix` actions were dispatched, the existing task execution loop picks up newly-PENDING tasks automatically and re-enters verification after they complete

### Error Cases

- Agent output is not valid JSON → `fail` verdict, log raw output for debugging
- Agent output is valid JSON but fails `GapReport` validation → `fail` verdict
- Agent spawning fails → propagate existing agent error handling (executor error path)
- Fan-out parent steps — the new `step_verifier` condition must not interfere with the fan-out parent verification path (separate code path, check before entering verifier branch)

## Tasks

1. Add `build_step_verifier_prompt(step_config, step_state, auto_verify_results)` to `src/orchestrator/workflow/prompts.py`
2. Modify `src/orchestrator/runners/executor.py`:
   - After all tasks in a step reach terminal state, check `step_config.step_verifier`
   - If configured (and not a fan-out parent step): run auto-verify, build prompt, spawn agent, parse output, call engine methods
   - Wrap JSON parsing in try/except; construct fail-verdict `GapReport` on error
   - Ensure this check is inside the step execution loop so task loop naturally re-runs for newly-PENDING tasks

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/ -v` — no regressions from executor changes
- Manual integration test (or stub): verifier prompt contains all required sections (task outcomes, required output schema)

### Manual Verification

- Confirm fan-out parent step path is not modified (read the relevant executor code section)
- Confirm JSON parse error path produces a `fail`-verdict `GapReport` with descriptive `assessment`
- Confirm raw agent output is logged when parse fails

## Context & References

- Plan: `docs/gap-analyzer/plan.md` — M3 core specification
- Architecture: `docs/gap-analyzer/architecture.md` — prompt template, executor pseudocode, interaction diagram
- Clarification: JSON parsing failure → `fail` verdict; verifier uses same agent runner as tasks in the step
- Step 1 plan: `docs/gap-analyzer/step-01-plan.md` — types used in this step
- Step 2 plan: `docs/gap-analyzer/step-02-plan.md` — engine methods called by executor
