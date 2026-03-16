# Step Plan: M4c — Validation and Live Test

## Purpose

Validate the complete optimized routine end-to-end: schema validation, unit test suite, and a live test run using Claude CLI. Confirm cost and time savings against the baseline ($18.28, 70 min, 703 tool calls). Ensure the original routine is unchanged.

## Prerequisites

- **Steps 01-05** must be complete: all M1-M4 changes applied to `routines/idea-to-plan-optimized/routine.yaml`
- **Step 04** engine enhancements deployed and tested
- Claude CLI configured and available (no API key setup needed — already configured per clarification Q5)
- Profile-to-model mappings configured on CLI_SUBPROCESS agent runner:
  - `architect` → `claude-opus-4-6`
  - `coder` → `claude-sonnet-4-6`
  - `summarizer` → `claude-haiku-4-5`

## Functional Contract

### Inputs

- Completed optimized routine at `routines/idea-to-plan-optimized/routine.yaml`
- Original routine at `routines/idea-to-plan/routine.yaml` (must be unchanged)
- Engine enhancements in `templates.py` and `executor.py`
- Unit tests in `tests/unit/test_templates.py`
- A small test idea for the live run

### Outputs

- Schema validation passes: `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml`
- Original routine unchanged: `git diff HEAD -- routines/idea-to-plan/routine.yaml` shows no changes
- All unit tests pass (existing + new template resolution tests)
- Live test run completes successfully, producing all expected artifacts:
  - `docs/{feature}/intent.md`
  - `docs/{feature}/plan.md`
  - `docs/{feature}/architecture.md`
  - `docs/{feature}/clarifications.md`
  - `docs/{feature}/step-*-plan.md` (step plans)
  - `docs/{feature}/steps/step-*.md` (step files, from fan-out)
  - `docs/{feature}/dry-run/*-notes.md` (per-step notes, from fan-out)
  - `docs/{feature}/dry-run-notes.md` (merged)
  - `docs/{feature}/verification-report.md`
  - `docs/{feature}/plan-summary.md`
  - Routine YAML output
- Cost measurably lower than baseline ($18.28)

### Error Cases

- Schema validation fails → fix YAML syntax or structure issues in the routine
- Unit tests fail → fix engine enhancement code or update test expectations
- Live test: fan-out fails due to glob matching zero files → check `input_glob` paths and upstream step output locations
- Live test: two-pass template resolution doesn't resolve nested variables → debug `resolve_template()` with actual variable values
- Live test: profile mappings not configured → tasks fall back to default model, cost savings not achieved but run still completes
- Live test: S-05 restructure produces different artifacts than original → verify merge task (S-05/T-02) consolidates correctly
- Original routine accidentally modified → restore from git

## Tasks

1. Run schema validation: `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml`
2. Verify original routine unchanged: `git diff HEAD -- routines/idea-to-plan/routine.yaml`
3. Run unit test suite: `uv run pytest tests/unit/` (all tests including new template tests)
4. Run integration test suite: `uv run pytest tests/integration/` (confirm no regressions)
5. Execute live test run of optimized routine using Claude CLI on a small test idea
6. Collect metrics from live run: cost, wall-clock time, tool calls
7. Compare metrics to baseline and document results
8. If any issues found, fix and re-run affected validation steps

## Verification Approach

### Auto-Verify

- `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- `git diff HEAD -- routines/idea-to-plan/routine.yaml` shows no output
- `uv run pytest tests/unit/` all pass
- `uv run pytest tests/integration/` all pass (excluding known failures)

### Manual Verification

- Live test run completes all 8 steps
- All expected artifact files exist in the output directory
- Fan-out steps (S-04, S-05) execute sub-agents concurrently
- No LLM verifier spawns for S-07/T-01 or S-08/T-01
- Agent metadata shows correct models per profile
- Cost is measurably lower than $18.28 baseline
- Wall-clock time is measurably lower than 70 min baseline

### Metrics Comparison

| Metric | Baseline | Target | Actual |
|--------|----------|--------|--------|
| Cost | $18.28 | $5-7 | (measured) |
| Wall-clock | 70 min | 20-25 min | (measured) |
| Tool calls | 703 | 250-300 | (measured) |
| Duplicate reads | 103 (41%) | 10-15 (5%) | (measured) |

## Context & References

- Plan: `docs/planning-routine-improvements/plan.md` — testing strategy, live test
- Architecture: `docs/planning-routine-improvements/architecture.md` — testing strategy (full section)
- Intent: `docs/planning-routine-improvements/intent.md` — completion criteria #8, #10, #13
- Clarification Q5: Live test using Claude CLI (already configured)
- Baseline analysis: run b46dbe62 metrics
