# Step 2: Data Model Extensions

Extend all data models (config, state, DB, events) to represent conditional steps. After this step, the system can store and serialize step conditions, skip state, and skip events -- even before the engine acts on them. All model changes are grouped into one step to avoid multiple migrations.

## Intent Verification
**Original Intent**: Add the data layer for conditional steps so the system can represent conditions and skip state at every level: config (routine YAML), runtime state, database persistence, and event tracking (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- `StepCondition` Pydantic model with `when` and `repeat_for` fields
- `condition` field on `StepConfig` (optional, backward compatible)
- `skipped` and `skip_reason` fields on `StepState`
- `skipped` and `skip_reason` columns on `StepModel` via Alembic migration
- `StepSkipped` event type
- Routine YAML files with `condition` blocks parse correctly

**Final Verification Criteria**:
- `uv run pytest tests/unit/ -v` -- all existing + new tests pass
- `uv run pyright` -- no type errors
- Alembic migration applies cleanly: `uv run alembic -c alembic.ini upgrade head`
- Existing routines parse without errors (no regression)

---

## Task 1: Add StepCondition and StepConfig.condition

**Description**: Add the `StepCondition` Pydantic model to config models and the optional `condition` field to `StepConfig`.

**Implementation Plan (Do These Steps)**
- [ ] Add `StepCondition(BaseModel)` to `src/orchestrator/config/models.py` with fields: `when: str | None = None`, `repeat_for: str | None = None`
- [ ] Add `condition: StepCondition | None = None` to `StepConfig`
- [ ] Verify existing routines without `condition` still parse identically

**Dependencies**
- [ ] Step 1 complete (evaluator exists so type annotations can reference `ConditionEvalError`)

**References**
- `docs/conditional-steps/architecture.md` -- `StepCondition` definition
- `docs/conditional-steps/step-02-plan.md` -- tasks 1-2
- `src/orchestrator/config/models.py` -- current `StepConfig`

**Constraints**
- `StepCondition` with neither `when` nor `repeat_for` is valid (no-op)
- Backward compatible: steps without `condition` continue to work

**Functionality (Expected Outcomes)**
- [ ] `StepCondition(when="always")` creates valid model
- [ ] `StepConfig(...)` without `condition` works unchanged
- [ ] `StepConfig(condition=StepCondition(when="{{x}} == 'y'"))` works

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.models import StepCondition, StepConfig; print('OK')"` succeeds
- [ ] Existing routine YAML files parse without errors

---

## Task 2: Add Skip Fields to StepState and StepModel

**Description**: Add `skipped` and `skip_reason` fields to the runtime state model and database model, with an Alembic migration for the DB columns.

**Implementation Plan (Do These Steps)**
- [ ] Add `skipped: bool = False` and `skip_reason: str | None = None` to `StepState` in `src/orchestrator/state/models.py`
- [ ] Add `skipped = Column(Boolean, default=False, nullable=False)` and `skip_reason = Column(String, nullable=True)` to `StepModel` in `src/orchestrator/db/models.py`
- [ ] Create Alembic migration: `uv run alembic -c alembic.ini revision -m "add step skipped and skip_reason columns"`
- [ ] Edit migration to set safe defaults (`skipped=False`, `skip_reason=None` for existing rows)

**Dependencies**
- [ ] Task 1 must be complete (StepCondition exists)

**References**
- `docs/conditional-steps/architecture.md` -- `StepState` and `StepModel` modifications
- `docs/conditional-steps/step-02-plan.md` -- tasks 3-5
- `src/orchestrator/state/models.py` -- current `StepState`
- `src/orchestrator/db/models.py` -- current `StepModel`

**Constraints**
- Migration must be safe for existing data (defaults ensure no null violations)
- No data loss on existing rows

**Functionality (Expected Outcomes)**
- [ ] `StepState(skipped=True, skip_reason="condition false")` creates valid model
- [ ] `StepModel` table has `skipped` and `skip_reason` columns after migration
- [ ] Existing `StepState` instances default to `skipped=False`

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic -c alembic.ini upgrade head` completes without error
- [ ] `uv run pyright src/orchestrator/state/models.py src/orchestrator/db/models.py` -- no errors

---

## Task 3: Add StepSkipped Event and Update Factory

**Description**: Add the `StepSkipped` event type and ensure `create_run_from_routine()` preserves condition fields on steps.

**Implementation Plan (Do These Steps)**
- [ ] Add `StepSkipped` event class to `src/orchestrator/workflow/events.py` with fields: `step_index: int`, `step_id: str`, `condition: str`, `reason: str`
- [ ] Verify `create_run_from_routine()` in `src/orchestrator/state/factory.py` preserves the `condition` field on steps (no expansion at creation time)
- [ ] Write unit tests: `StepCondition` parsing, `StepConfig` with/without condition, `StepState` skip fields, `StepSkipped` event serialization

**Dependencies**
- [ ] Tasks 1-2 must be complete (models exist)

**References**
- `docs/conditional-steps/architecture.md` -- `StepSkipped` event definition
- `docs/conditional-steps/step-02-plan.md` -- tasks 6-8
- `src/orchestrator/workflow/events.py` -- existing event types
- `src/orchestrator/state/factory.py` -- `create_run_from_routine()`

**Constraints**
- `repeat_for` expansion does NOT happen at creation time (deferred to runtime per Clarification Q4)
- Event must be serializable for activity feed

**Functionality (Expected Outcomes)**
- [ ] `StepSkipped` event can be created and serialized
- [ ] `create_run_from_routine()` with conditional steps preserves `condition` as-is
- [ ] Unit tests verify all new model behavior

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/ -v` -- all tests pass (existing + new)
- [ ] `uv run pyright` -- no type errors
