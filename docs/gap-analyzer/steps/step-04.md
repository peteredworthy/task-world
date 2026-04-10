# Step 4: API Surface + Integration Tests

Expose step verification state and gap reports through the REST API, and write end-to-end integration tests that exercise the full verification loop from routine creation through agent spawning, gap report generation, and step completion.

## Intent Verification
**Original Intent**: Make gap-analyzer state visible to API consumers and prove the full loop works end-to-end (see `docs/gap-analyzer/intent.md`).
**Functionality to Produce**:
- `GapActionSchema` and `GapReportSchema` Pydantic schemas in `src/orchestrator/api/schemas/runs.py`
- `StepSummary` extended with `verifying`, `verifier_iterations`, `gap_reports` fields
- `GET /api/runs/{run_id}` response includes new step fields
- `tests/integration/test_gap_analyzer.py` with 8 end-to-end scenarios covering all verdict paths

**Final Verification Criteria**:
- `uv run pytest tests/integration/test_gap_analyzer.py -v` — all 8 scenarios pass
- `uv run pytest tests/integration/ -v` — no existing integration tests broken
- `uv run pyright src/orchestrator/api/schemas/runs.py` — no type errors
- `GET /api/runs/{run_id}` response JSON contains `verifying`, `verifier_iterations`, `gap_reports` on each step

---

## Task 1: Add GapReportSchema, Extend StepSummary, and Extend TaskSummary

**Description**: Add `GapActionSchema` and `GapReportSchema` Pydantic models to `src/orchestrator/api/schemas/runs.py`, add `verifying`, `verifier_iterations`, `gap_reports` to `StepSummary`, and add `spawned_by_gap_report` to `TaskSummary`.

**Implementation Plan (Do These Steps)**
- [ ] Add to `src/orchestrator/api/schemas/runs.py` (before `StepSummary` class):
  ```python
  class GapActionSchema(ApiModel):
      type: str
      task_id: str | None = None
      feedback: str | None = None
      title: str | None = None
      context: str | None = None
      requirements: list[dict] | None = None

  class GapReportSchema(ApiModel):
      id: str
      iteration: int
      assessment: str
      verdict: str
      actions: list[GapActionSchema] = []
      timestamp: datetime
  ```
  Note: use `ApiModel` base (matches existing `TaskSummary`, `StepSummary` etc.), not `BaseModel`.
- [ ] Add to `StepSummary`:
  ```python
  verifying: bool = False
  verifier_iterations: int = 0
  gap_reports: list[GapReportSchema] = Field(default_factory=list)
  ```
- [ ] Add to `TaskSummary` (after `parent_task_id` field):
  ```python
  spawned_by_gap_report: bool = False
  ```
  This field must default to `False` so existing code building `TaskSummary` objects is unaffected.

**Dependencies**
- [ ] Step 1 complete: `GapReport` state model exists; Step 3 complete: executor writes gap reports.

**References**
- `docs/gap-analyzer/architecture.md` — `GapReportSchema` definition, `StepSummary` additions
- `docs/gap-analyzer/step-04-plan.md` — full functional contract

**Constraints**
- `GapReportSchema.verdict` is `str` (not enum) for forward compatibility.
- Pre-migration rows with `gap_reports=None` in DB must serialize as `[]` — handle in serialization, not schema.
- `spawned_by_gap_report` on `TaskSummary` must default to `False` — existing task creation paths that don't set it will work correctly.

**Functionality (Expected Outcomes)**
- [ ] `GapActionSchema` and `GapReportSchema` importable from `src/orchestrator/api/schemas/runs.py`
- [ ] `StepSummary` has `verifying`, `verifier_iterations`, `gap_reports` fields with correct defaults

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/runs.py` — no type errors
- [ ] `uv run python -c "from orchestrator.api.schemas.runs import GapReportSchema, StepSummary; print('OK')"` succeeds

---

## Task 2: Update Serialization to Populate New StepSummary and TaskSummary Fields

**Description**: Update `_run_to_response()` (or equivalent serialization path) in the runs router to populate `verifying`, `verifier_iterations`, `gap_reports` from step data and `spawned_by_gap_report` from task data when building summaries.

**Implementation Plan (Do These Steps)**
- [ ] Locate the `StepSummary` construction in the serialization path (likely `_run_to_response()` or `_step_to_summary()` in `src/orchestrator/api/routers/runs.py`)
- [ ] Populate `verifying` from step data (coerce Integer `0/1` to `bool`)
- [ ] Populate `verifier_iterations` from step data (default `0` if None)
- [ ] Populate `gap_reports`: deserialize from step's `gap_reports` JSON list; use `GapReportSchema(**d)` for each dict; handle `None` → `[]`; wrap in try/except for malformed JSON → log warning, return `[]`
- [ ] In the `TaskSummary` construction within the same serialization path, populate:
  - `spawned_by_gap_report=bool(task_data.get("spawned_by_gap_report", False))` (or from the ORM model attribute if available)

**Dependencies**
- [ ] Task 1 must be complete (`GapReportSchema` and `StepSummary` fields exist)

**References**
- `docs/gap-analyzer/step-04-plan.md` — error cases (null gap_reports, malformed JSON)
- Architecture note (MEMORY.md): `_run_to_response()` serialization pattern

**Constraints**
- Malformed `gap_reports` JSON in DB: log warning and return `[]`; do not crash `GET /api/runs/{id}`.
- `StepModel.verifying` is stored as Integer (0/1); coerce to `bool` in serialization.

**Functionality (Expected Outcomes)**
- [ ] `GET /api/runs/{run_id}` response includes `verifying`, `verifier_iterations`, `gap_reports` on each step
- [ ] Pre-migration rows (null `gap_reports`) return `gap_reports: []` without error

**Final Verification (Proof of Completion)**
- [ ] Start server; create a run; `GET /api/runs/{id}` includes `verifying: false`, `verifier_iterations: 0`, `gap_reports: []` on steps
- [ ] `uv run pytest tests/integration/ -v` — no existing tests broken by serialization change

---

## Task 3: Write Integration Tests

**Description**: Create `tests/integration/test_gap_analyzer.py` covering all 8 end-to-end scenarios for the gap-analyzer feature.

**Test Strategy (READ THIS BEFORE WRITING TESTS)**

Use a **two-track approach**:
- **Track A (engine/service direct calls)**: For scenarios 1–6, 8 — call `WorkflowService` methods directly (no executor, no agent spawning). Use in-memory DB. This tests DB persistence, engine dispatch, and action routing without needing to mock agents.
- **Track B (API response)**: For scenario 7 — create a run via the test client, call service methods to set state, then hit `GET /api/runs/{id}` to verify the serialized response.

**Pattern reference**: See `tests/integration/test_mock_agent_workflow.py` for the fixture pattern (in-memory DB, `WorkflowService`).

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_gap_analyzer.py`
- [ ] Add fixtures:
  ```python
  @pytest.fixture
  async def session():
      engine = create_engine(":memory:")
      await init_db(engine)
      factory = create_session_factory(engine)
      async with factory() as s:
          yield s

  @pytest.fixture
  def service(session):
      return WorkflowService(session)
  ```
- [ ] **Scenario 1: Full lifecycle → pass → step advances**
  - Create run with 2-step routine (step 1 has `step_verifier`, step 2 is normal); start run; complete task to COMPLETED; call `service.start_step_verification(run_id, step_id)`; call `service.complete_step_verification(run_id, step_id, GapReport(verdict=PASS, ...))`
  - Assert:
    ```python
    run = await service._repo.get(run_id)
    step = run.steps[0]
    assert step.verifying == False
    assert step.completed == True
    assert step.verifier_iterations == 1
    assert len(step.gap_reports) == 1
    assert step.gap_reports[0].verdict == StepVerdict.PASS
    assert run.current_step_index == 1
    ```

- [ ] **Scenario 2: retry_task → re-run → pass → completes**
  - Complete task → first verifier call with `GapReport(verdict=RETRY, actions=[GapAction(type="retry_task", task_id=task.id, feedback="try harder")])`
  - Assert after first call:
    ```python
    assert step.verifying == True
    assert step.verifier_iterations == 1
    assert task.status == TaskStatus.PENDING
    assert task.gap_report_feedback == "try harder"
    ```
  - Simulate task completing again → second verifier call with `verdict=PASS`
  - Assert: `step.completed == True`, `step.verifier_iterations == 2`

- [ ] **Scenario 3: spawn_fix → new task runs → pass → completes**
  - First verifier: `GapReport(verdict=FIX, actions=[GapAction(type="spawn_fix", title="Fix X", requirements=[{"id": "R1", "desc": "test", "priority": "critical"}])])`
  - Assert: `len(step.tasks) == 2`, `step.tasks[1].spawned_by_gap_report == True`
  - Complete new task → second verifier: `verdict=PASS`
  - Assert: `step.completed == True`

- [ ] **Scenario 4: fail verdict → run paused**
  - Call `service.complete_step_verification(run_id, step_id, GapReport(verdict=FAIL, ...))`
  - Assert:
    ```python
    assert run.status == RunStatus.PAUSED
    assert run.pause_reason == "step_verifier_failed"
    assert step.verifying == False
    ```

- [ ] **Scenario 5: max_iterations reached → run paused**
  - Set `step_verifier.max_iterations=1`; call `start_step_verification` (now `verifier_iterations=1 >= max_iterations=1`); call `complete_step_verification` with any verdict
  - Assert: `run.status == RunStatus.PAUSED`, `run.pause_reason == "step_verifier_max_iterations"`

- [ ] **Scenario 6: invalid JSON from verifier → fail verdict in gap report**
  - Simulate JSON parse error path: construct a `GapReport(verdict=FAIL, assessment="Parse error: ...")` and call `complete_step_verification`
  - Assert: `run.status == RunStatus.PAUSED`, `step.gap_reports[-1].verdict == StepVerdict.FAIL`, `"Parse error" in step.gap_reports[-1].assessment`

- [ ] **Scenario 7: GET response includes new step fields**
  - Use test client (`AsyncClient`); create run, set verifying state via service; call `GET /api/runs/{run_id}`
  - Assert:
    ```python
    step_data = response.json()["steps"][0]
    assert step_data["verifying"] == True
    assert step_data["verifier_iterations"] == 1
    assert isinstance(step_data["gap_reports"], list)
    assert step_data["gap_reports"][0]["verdict"] == "retry"
    # Check TaskSummary has spawned_by_gap_report
    # (after spawn_fix, second task should have spawned_by_gap_report=true)
    ```

- [ ] **Scenario 8: Regression — step without step_verifier advances normally**
  - Create run with normal step (no `step_verifier`); complete task to COMPLETED; call service's task completion path
  - Assert: `step.completed == True`, `run.status == RunStatus.COMPLETED` (if 1-step routine), `step.verifier_iterations == 0`, `step.gap_reports == []`
  - Confirm `start_step_verification` was never needed

**Dependencies**
- [ ] Tasks 1-2 must be complete (API surface ready for scenario 7)
- [ ] Step 3 complete (executor wired) — steps 1-6 can use service directly; scenario 7 needs API

**References**
- `docs/gap-analyzer/plan.md` — M3 integration test list
- `docs/gap-analyzer/step-04-plan.md` — scenario descriptions
- `tests/integration/test_mock_agent_workflow.py` — fixture and service pattern reference

**Constraints**
- Tests must use in-memory DB (`create_all` path) — no Alembic migrations in tests.
- Use `WorkflowService` direct calls for scenarios 1–6 and 8 (no executor, no agent spawning needed).
- Scenario 7 uses the test HTTP client against the real API router.

**Functionality (Expected Outcomes)**
- [ ] All 8 integration test scenarios pass with concrete assertions
- [ ] `GapReport` round-trip verified: `GapReport` → DB JSON → `GapReportSchema` → JSON response

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_gap_analyzer.py -v` — all 8 tests pass
- [ ] `uv run pytest tests/integration/ -v` — no existing tests broken
