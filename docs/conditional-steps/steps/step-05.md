# Step 5: Manual Gate Skip Option + API Surface

Add the skip-step API endpoint for manual gates and expose all conditional step data through the API schema. After this step, external clients can see skip state, conditions, and skip reasons on steps, and users can choose to skip manually gated steps.

## Intent Verification
**Original Intent**: Complete the API surface for conditional steps so clients can see skip state and conditions, and users have the option to skip manually gated steps instead of being forced to execute them (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- `POST /runs/{id}/steps/{step_id}/skip` endpoint for skipping manual gates
- `StepConditionSchema` in API schemas
- `StepSummary` gains `skipped`, `skip_reason`, `condition` fields
- `RunResponse` serialization includes skip data
- Proper 409 responses for invalid skip attempts

**Final Verification Criteria**:
- `uv run pytest tests/integration/ -v` -- all integration tests pass
- `uv run pyright` -- no type errors in schemas or router
- API response schema matches expected fields

---

## Task 1: Add API Schemas for Conditional Steps

**Description**: Add `StepConditionSchema` and extend `StepSummary` with skip and condition fields.

**Implementation Plan (Do These Steps)**
- [ ] Add `StepConditionSchema(BaseModel)` to `src/orchestrator/api/schemas/runs.py` with `when: str | None = None` and `repeat_for: str | None = None`
- [ ] Add `skipped: bool = False`, `skip_reason: str | None = None`, `condition: StepConditionSchema | None = None` to `StepSummary`
- [ ] Update `RunResponse` serialization to populate skip data and condition from `StepModel`/`StepState`

**Dependencies**
- [ ] Step 2 (data models with `skipped`, `skip_reason`, `StepCondition`) must be complete

**References**
- `docs/conditional-steps/architecture.md` -- `StepSummary` schema changes
- `docs/conditional-steps/step-05-plan.md` -- tasks 1-3
- `src/orchestrator/api/schemas/runs.py` -- current `StepSummary`

**Constraints**
- Backward compatible: runs without conditions still serialize correctly

**Functionality (Expected Outcomes)**
- [ ] `GET /runs/{id}` response includes `skipped`, `skip_reason`, `condition` on each step
- [ ] Steps without conditions show `condition: null`
- [ ] Skipped steps show `skipped: true` with `skip_reason`

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/runs.py` -- no errors

---

## Task 2: Add Skip-Step API Endpoint

**Description**: Add the `POST /runs/{id}/steps/{step_id}/skip` endpoint that allows users to skip a manually gated step.

**Implementation Plan (Do These Steps)**
- [ ] Add `POST /runs/{id}/steps/{step_id}/skip` endpoint in `src/orchestrator/api/routers/runs.py`:
  - Validate run is paused at manual gate (`pause_reason="manual_gate"`)
  - Validate `step_id` matches the current gated step
  - Mark step as `skipped=True`, `skip_reason="manual_skip"`
  - Emit `StepSkipped` event
  - Advance to next step (evaluating its condition if present)
  - Resume the run
  - Return 200 with updated run state
- [ ] Return 409 for invalid skip attempts:
  - Run is not paused
  - Run is paused but not at a manual gate
  - `step_id` doesn't match the current gated step
- [ ] Return 404 for invalid step ID
- [ ] Add `skip_step()` method to `WorkflowService` if needed

**Dependencies**
- [ ] Task 1 must be complete (schemas exist)
- [ ] Step 3 (engine wiring with manual gate pause) must be complete

**References**
- `docs/conditional-steps/architecture.md` -- manual gate resume with skip option
- `docs/conditional-steps/step-05-plan.md` -- tasks 4-5
- Clarification Q1: Add skip option so users can choose to skip OR execute

**Constraints**
- Only works when paused at a manual gate -- not for arbitrary step skipping
- Must advance correctly (evaluating conditions on next step)

**Functionality (Expected Outcomes)**
- [ ] Skipping a manual gate marks the step as skipped and advances
- [ ] Invalid skip attempts return 409 with descriptive message
- [ ] `StepSkipped` event is emitted with `reason="manual_skip"`

**Final Verification (Proof of Completion)**
- [ ] Endpoint responds correctly for valid and invalid requests

---

## Task 3: Write Integration Tests

**Description**: Write integration tests covering the API surface for conditional steps and the skip-step endpoint.

**Implementation Plan (Do These Steps)**
- [ ] Add integration tests:
  - GET run response includes `skipped`, `skip_reason`, `condition` on steps
  - Skipped steps have `StepSkipped` event in activity
  - Skip-step endpoint works for manual gate paused runs (skip and advance)
  - Skip-step returns 409 when not at a manual gate
  - Skip-step returns 409 when step_id doesn't match current gated step

**Dependencies**
- [ ] Tasks 1-2 must be complete

**References**
- `docs/conditional-steps/architecture.md` -- testing strategy
- `docs/conditional-steps/step-05-plan.md` -- task 6

**Constraints**
- No mocking (per AGENTS.md)

**Functionality (Expected Outcomes)**
- [ ] All API scenarios have integration test coverage
- [ ] Error cases (409, 404) are tested

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/ -v` -- all tests pass
- [ ] `uv run pytest tests/ -v` -- existing tests unaffected
