# Step 1: Fix auto_verify timing (A1)

**Milestone:** M1 — Gate Fixes & Safety
**Plan:** [step-01-plan.md](../step-01-plan.md)
**Architecture:** [architecture.md](../architecture.md) §1 (Workflow Engine, A1)
**Intent:** [intent.md](../intent.md) — Completion Criteria #1

## Tasks

### Task 1.1: Reorder auto_verify execution in submit_for_verification

Move auto_verify command execution before the checklist gate evaluation in
`engine.py:submit_for_verification()`. If any `must: true` auto_verify item
fails, raise `GateBlockedError` with failing item details. Task remains in
BUILDING state.

**Files:** `src/orchestrator/workflow/engine.py`
**LOC estimate:** ~50
**Verify:** Unit test — failing `must: true` auto_verify blocks transition
even when all checklist items self-report done. Passing auto_verify proceeds
normally. Existing gate tests still pass.

### Task 1.2: Integration test for auto_verify gate via API

Add integration test exercising the full submit flow through the API with
auto_verify configured. Verify 409 response when `must: true` item fails.

**Files:** `tests/integration/test_api_full_lifecycle.py` (or new test file)
**LOC estimate:** ~40
**Verify:** Test passes; exercises real submit endpoint with auto_verify config.
