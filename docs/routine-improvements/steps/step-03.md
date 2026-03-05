# Step 3: Pre-run test health check (A5)

**Milestone:** M1 — Gate Fixes & Safety
**Plan:** [step-03-plan.md](../step-03-plan.md)
**Architecture:** [architecture.md](../architecture.md) §6 (Executor, A5)
**Intent:** [intent.md](../intent.md) — Completion Criteria #3
**Clarification:** Q1 in [clarifications.md](../clarifications.md) — project-level config with convention fallback

## Tasks

### Task 3.1: Add test health check to executor

Before the first task attempt in a run, execute the project's test command.
Read from `.task-world/config.yaml` `test_command` field, falling back to
`uv run pytest --tb=no -q`. If exit non-zero, block task start with error
including command, exit code, and truncated output. If `test_command: null`,
skip the check.

**Files:** `src/orchestrator/agents/executor.py`
**LOC estimate:** ~60
**Verify:** Integration tests — failing tests block task start; passing tests
proceed; `test_command: null` skips check; no config file uses convention default.

### Task 3.2: Tests for pre-run health check

Write integration tests covering: failing test suite blocks start, passing
suite proceeds, explicit opt-out skips check, missing config uses default.

**Files:** `tests/integration/` (new or existing test file)
**LOC estimate:** ~80
**Verify:** All test scenarios pass. Existing executor tests unaffected.
