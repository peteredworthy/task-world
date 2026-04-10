# Step 3: Pre-run test health check (A5)

## Milestone
M1: Gate Fixes & Safety

## Purpose
Before the first task attempt in a run, execute the project's test suite. If tests fail before any builder work begins, any subsequent failures are pre-existing — not regressions. This replaces complex baseline comparison with a simple pass/fail gate.

## Prerequisites / Dependencies
- None directly, though this pairs well with Step 9 (test count regression guard) from M3.

## Functional Contract

### Inputs
- Project working directory
- Test command from project-level config file (`.task-world/config.yaml` field `test_command`) or convention default (`uv run pytest --tb=no -q`)

### Outputs
- **Tests pass (exit 0):** Task execution proceeds normally
- **Tests fail (non-zero exit):** Task start is blocked with descriptive error including test output
- **No config, no tests:** Convention default runs; if no pytest found, the failure blocks (project should opt out explicitly)
- **Explicit opt-out (`test_command: null`):** Health check is skipped entirely

### Errors
- Task start blocked with error message containing: test command used, exit code, and truncated test output (last N lines)

### Configuration
- `.task-world/config.yaml`:
  ```yaml
  test_command: "uv run pytest --tb=no -q"  # or null to skip
  ```
- Convention fallback: `uv run pytest --tb=no -q`

## Files Modified
- `src/orchestrator/agents/executor.py` — add health check before first task attempt

## Verification Strategy
- **Integration test:** Executor with a project that has failing tests -> task start blocked with descriptive error.
- **Integration test:** Executor with passing tests -> task starts normally.
- **Integration test:** Project with `test_command: null` -> health check skipped, task starts.
- **Edge case test:** Project with no `.task-world/config.yaml` -> convention default used.
- **Regression:** Existing executor tests continue to pass.
