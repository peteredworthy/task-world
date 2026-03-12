# Step Plan: API Surface + Integration Tests

## Purpose

Expose step verification state and gap reports through the REST API, and write end-to-end integration tests that exercise the full verification loop from routine creation through agent spawning, gap report generation, and step completion.

## Prerequisites

- Step 1 complete: all new types defined.
- Step 2 complete: engine lifecycle methods working.
- Step 3 complete: executor spawns verifier agents and calls engine methods.

## Functional Contract

### Inputs

**Schema changes:**
- `StepSummary` in `src/orchestrator/api/schemas/runs.py` — extended with new fields
- `_run_to_response()` serialization — reads new fields from `StepModel`

**API consumer:**
- `GET /api/runs/{run_id}` — returns run with step summaries including gap report data

### Outputs

**`GapReportSchema` (new):**
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

**`StepSummary` additions:**
```python
verifying: bool = False
verifier_iterations: int = 0
gap_reports: list[GapReportSchema] = Field(default_factory=list)
```

**Integration test scenarios (`tests/integration/test_gap_analyzer.py`):**
1. Full lifecycle: all tasks complete → step verifier runs → `pass` → step advances to next step
2. `retry_task`: task re-runs with feedback → verifier runs again → `pass` → step completes
3. `spawn_fix`: new task created and run → verifier runs again → `pass` → step completes
4. `fail` verdict → run paused with `step_verifier_failed` pause reason
5. `max_iterations` reached → run paused with `step_verifier_max_iterations` pause reason
6. Verifier output is invalid JSON → run paused (fail verdict, parse error message in assessment)
7. GET run response includes `verifying`, `verifier_iterations`, `gap_reports` on `StepSummary`
8. Regression: step without `step_verifier` advances normally (no new code path triggered)

### Error Cases

- `StepModel` with `gap_reports=None` in DB (pre-migration rows) — serialize as `[]`
- `gap_reports` JSON in DB is malformed — log warning, return `[]` (don't crash GET)

## Tasks

1. Add `GapActionSchema` and `GapReportSchema` to `src/orchestrator/api/schemas/runs.py`
2. Add `verifying`, `verifier_iterations`, `gap_reports` fields to `StepSummary`
3. Update `_run_to_response()` (or equivalent serialization path) to populate new `StepSummary` fields from `StepModel`
4. Create `tests/integration/test_gap_analyzer.py` with all 8 scenarios listed above

## Verification Approach

### Auto-Verify

- `uv run pytest tests/integration/test_gap_analyzer.py -v` — all 8 scenarios pass
- `uv run pytest tests/integration/ -v` — no existing integration tests broken
- `uv run pyright src/orchestrator/api/schemas/runs.py` — no type errors
- `GET /api/runs/{run_id}` response JSON contains `verifying`, `verifier_iterations`, `gap_reports` on each step

### Manual Verification

- Confirm `GapReportSchema` round-trips correctly: `GapReport` → DB JSON → `GapReportSchema` → JSON response
- Confirm pre-migration rows (null `gap_reports`) are handled gracefully

## Context & References

- Plan: `docs/gap-analyzer/plan.md` — M3 remaining specification and integration test list
- Architecture: `docs/gap-analyzer/architecture.md` — `StepSummary` additions, `GapReportSchema` definition
- Step 3 plan: `docs/gap-analyzer/step-03-plan.md` — executor integration this step tests end-to-end
