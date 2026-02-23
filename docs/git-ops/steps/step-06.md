# Step 6: Backend Test Execution Endpoint

Provide backend support for executing the routine's `auto_verify` commands against the run worktree from the Review & Merge workbench. This allows users to validate that the run's changes (including after pruning) still pass tests before merging.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Test execution can be triggered from the workbench; results show pass/fail, summary counts, and collapsible log output.

**Functionality to Produce**:
- `POST /api/runs/{id}/review/test` endpoint that starts async test execution
- `GET /api/runs/{id}/review/test/{test_run_id}` endpoint that retrieves test results
- Test execution runs the routine's `auto_verify` commands in the worktree directory
- `TEST_RUN_STARTED` and `TEST_RUN_COMPLETED` events logged
- In-memory test run tracking for active and completed test runs

**Final Verification Criteria**:
- `POST /review/test` starts a test run and returns a test_run_id immediately
- `GET /review/test/{id}` returns running/passed/failed status with summary
- Log output contains actual stdout/stderr from test commands
- Test commands are sourced from the routine's auto_verify configuration
- Events are logged for test start and completion

---

## Task 1: Create Test Runner Module

**Description**: Create the test runner module that executes auto_verify commands in a worktree subprocess and captures output.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/review/test_runner.py`:

```python
class TestRunner:
    """Executes auto_verify commands in a worktree and tracks results."""

    async def start_test_run(self, worktree_path: str, commands: list[str]) -> str:
        """Start async test execution. Returns test_run_id."""

    async def get_test_result(self, test_run_id: str) -> TestRunResult:
        """Get status/results for a test run."""

    async def _execute_commands(self, test_run_id: str, worktree_path: str, commands: list[str]) -> None:
        """Execute commands in sequence, capture output, compute summary."""
```

- [ ] Use `asyncio.create_subprocess_exec` to run commands in the worktree directory
- [ ] Capture stdout/stderr for log display
- [ ] Parse test output to compute summary (total/passed/failed/skipped) where possible
- [ ] Track test runs in-memory with status transitions: running → passed/failed/error

**References**
- Existing auto-verify infrastructure in the codebase
- `src/orchestrator/git/branch_ops.py` — subprocess execution pattern
- `docs/git-ops/step-06-plan.md` — Task 1
- `docs/git-ops/clarifications.md` — Q2: test commands from routine's auto_verify

**Functionality (Expected Outcomes)**
- [ ] Test runner executes commands in the correct worktree directory
- [ ] Output is captured and stored
- [ ] Status transitions correctly from running to passed/failed/error

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/review/test_runner.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/review/test_runner.py` — no lint errors

---

## Task 2: Add Test Schemas and Event Types

**Description**: Create API schemas for test run requests/responses and add test event types.

**Implementation Plan (Do These Steps)**

- [ ] Add test schemas to `src/orchestrator/api/schemas/review.py`:

```python
class TestRunRequest(BaseModel):
    profile: str | None = None  # Reserved for future use

class TestRunResponse(BaseModel):
    test_run_id: str
    status: str  # "running"

class TestSummary(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int

class TestRunResult(BaseModel):
    test_run_id: str
    status: str  # "running" | "passed" | "failed" | "error"
    summary: TestSummary | None = None
    log_output: str
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
```

- [ ] Add `TEST_RUN_STARTED` and `TEST_RUN_COMPLETED` event types to `src/orchestrator/workflow/events.py`

**References**
- `docs/git-ops/step-06-plan.md` — Tasks 2, 3, 4

**Functionality (Expected Outcomes)**
- [ ] Test schemas validate correctly
- [ ] Event types are defined and usable

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/review.py` — no type errors

---

## Task 3: Add Test Execution API Endpoints

**Description**: Add the test execution endpoints to the review router.

**Implementation Plan (Do These Steps)**

- [ ] Add endpoints to `src/orchestrator/api/routers/review.py`:

```python
# POST /api/runs/{run_id}/review/test
#   Body: TestRunRequest
#   Returns: TestRunResponse { test_run_id, status: "running" }
#   Starts async test execution using routine's auto_verify commands

# GET /api/runs/{run_id}/review/test/{test_run_id}
#   Returns: TestRunResult with status, summary, log_output, duration
```

- [ ] Validate that the run has an active worktree (409 if not)
- [ ] Validate that the routine has auto_verify commands configured (422 if not)
- [ ] Prevent concurrent test runs for the same run (409 if already running)
- [ ] Log `TEST_RUN_STARTED` event when test starts
- [ ] Log `TEST_RUN_COMPLETED` event when test finishes

**Dependencies**
- [ ] Tasks 1-2 must be complete

**References**
- `docs/git-ops/step-06-plan.md` — Tasks 5, 6

**Functionality (Expected Outcomes)**
- [ ] POST endpoint starts test and returns immediately with test_run_id
- [ ] GET endpoint returns current status and results
- [ ] Events are logged for test lifecycle

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/review.py` — no type errors

---

## Task 4: Write Integration Tests for Test Execution

**Description**: Write integration tests that execute test commands in a real worktree and verify results.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/integration/test_review_test_runner.py`:
  - `test_start_test_run_returns_id` — POST starts test and returns ID
  - `test_test_run_completes_with_results` — GET returns results after completion
  - `test_test_run_captures_output` — log_output contains actual command output
  - `test_test_run_reports_failure` — failing commands produce "failed" status
  - `test_no_auto_verify_returns_422` — 422 when no commands configured
  - `test_concurrent_test_run_returns_409` — 409 when test already running

- [ ] Create a real worktree with a simple test file for execution
- [ ] Use `AsyncClient` with the real FastAPI app

**Dependencies**
- [ ] Task 3 must be complete (endpoints exist)

**References**
- `docs/git-ops/step-06-plan.md` — Task 7
- `tests/integration/test_branch_ops.py` — integration test patterns

**Functionality (Expected Outcomes)**
- [ ] Integration tests verify end-to-end test execution
- [ ] Both passing and failing test commands are covered

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_review_test_runner.py -v` — all tests pass (verify test count > 0)
