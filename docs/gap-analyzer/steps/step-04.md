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

## Task 1: Add GapReportSchema and Extend StepSummary

**Description**: Add `GapActionSchema` and `GapReportSchema` Pydantic models to `src/orchestrator/api/schemas/runs.py`, and add `verifying`, `verifier_iterations`, `gap_reports` to `StepSummary`.

**Implementation Plan (Do These Steps)**
- [ ] Add to `src/orchestrator/api/schemas/runs.py`:
  ```python
  class GapActionSchema(BaseModel):
      type: str
      task_id: str | None = None
      feedback: str | None = None
      title: str | None = None
      context: str | None = None
      requirements: list[dict] | None = None

  class GapReportSchema(BaseModel):
      id: str
      iteration: int
      assessment: str
      verdict: str
      actions: list[GapActionSchema] = []
      timestamp: datetime
  ```
- [ ] Add to `StepSummary`:
  ```python
  verifying: bool = False
  verifier_iterations: int = 0
  gap_reports: list[GapReportSchema] = Field(default_factory=list)
  ```

**Dependencies**
- [ ] Step 1 complete: `GapReport` state model exists; Step 3 complete: executor writes gap reports.

**References**
- `docs/gap-analyzer/architecture.md` — `GapReportSchema` definition, `StepSummary` additions
- `docs/gap-analyzer/step-04-plan.md` — full functional contract

**Constraints**
- `GapReportSchema.verdict` is `str` (not enum) for forward compatibility.
- Pre-migration rows with `gap_reports=None` in DB must serialize as `[]` — handle in serialization, not schema.

**Functionality (Expected Outcomes)**
- [ ] `GapActionSchema` and `GapReportSchema` importable from `src/orchestrator/api/schemas/runs.py`
- [ ] `StepSummary` has `verifying`, `verifier_iterations`, `gap_reports` fields with correct defaults

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/runs.py` — no type errors
- [ ] `uv run python -c "from orchestrator.api.schemas.runs import GapReportSchema, StepSummary; print('OK')"` succeeds

---

## Task 2: Update Serialization to Populate New StepSummary Fields

**Description**: Update `_run_to_response()` (or equivalent serialization path) in the runs router to populate `verifying`, `verifier_iterations`, `gap_reports` from `StepModel` when building `StepSummary`.

**Implementation Plan (Do These Steps)**
- [ ] Locate the `StepSummary` construction in the serialization path (likely `_run_to_response()` or `_step_to_summary()`)
- [ ] Populate `verifying` from `StepModel.verifying` (coerce to bool if Integer)
- [ ] Populate `verifier_iterations` from `StepModel.verifier_iterations`
- [ ] Populate `gap_reports`: load JSON from `StepModel.gap_reports`; deserialize each dict as `GapReportSchema`; handle `None` → `[]`; handle malformed JSON → log warning, return `[]`

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

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_gap_analyzer.py`
- [ ] Scenario 1: Full lifecycle — all tasks complete → step verifier runs → `pass` → step advances to next step
- [ ] Scenario 2: `retry_task` — task re-runs with feedback → verifier runs again → `pass` → step completes
- [ ] Scenario 3: `spawn_fix` — new task created and run → verifier runs again → `pass` → step completes
- [ ] Scenario 4: `fail` verdict → run paused with `step_verifier_failed` pause reason
- [ ] Scenario 5: `max_iterations` reached → run paused with `step_verifier_max_iterations` pause reason
- [ ] Scenario 6: Verifier output is invalid JSON → run paused (fail verdict, parse error message in assessment)
- [ ] Scenario 7: `GET /api/runs/{id}` includes `verifying`, `verifier_iterations`, `gap_reports` on `StepSummary`
- [ ] Scenario 8: Regression — step without `step_verifier` advances normally (no new code path triggered)

**Dependencies**
- [ ] Tasks 1-2 must be complete (API surface ready)
- [ ] Step 3 complete (executor wired) — tests exercise the full stack

**References**
- `docs/gap-analyzer/plan.md` — M3 integration test list
- `docs/gap-analyzer/step-04-plan.md` — scenario descriptions

**Constraints**
- Tests must use in-memory DB (`create_all` path) — no Alembic migrations in tests.
- Mock or stub the verifier agent output (return controlled JSON strings) to exercise all verdict paths.

**Functionality (Expected Outcomes)**
- [ ] All 8 integration test scenarios pass
- [ ] `GapReport` round-trip verified: `GapReport` → DB JSON → `GapReportSchema` → JSON response

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_gap_analyzer.py -v` — all 8 tests pass
- [ ] `uv run pytest tests/integration/ -v` — no existing tests broken
