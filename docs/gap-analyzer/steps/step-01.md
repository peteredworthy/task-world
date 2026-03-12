# Step 1: Data Models + Schema

Define all new types — enums, Pydantic models, DB columns, and event types — so the rest of the system can reference them without touching the engine or executor. This is the foundation step: everything else depends on these types existing.

## Intent Verification
**Original Intent**: Introduce the `StepVerifierConfig`, `GapReport`, `GapAction`, and related types needed for gap-analyzer, plus DB columns and events (see `docs/gap-analyzer/intent.md`).
**Functionality to Produce**:
- `StepVerdict` enum (`PASS`, `RETRY`, `FIX`, `FAIL`) in `src/orchestrator/config/enums.py`
- `StepVerifierConfig` and `GapAction`/`GapReport` Pydantic models defined and importable
- `StepConfig.step_verifier` optional field (backward compatible — existing routines unaffected)
- `StepState` gains `verifying`, `verifier_iterations`, `gap_reports` fields
- `StepModel` DB columns `verifying` and `gap_reports` added via Alembic migration
- `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` event types defined

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_gap_analyzer_models.py -v` — all new tests pass
- `uv run pytest tests/unit/ -v` — no existing tests broken
- `uv run alembic upgrade head` — migration applies cleanly

---

## Task 1: Add Enums and Config Models

**Description**: Add `StepVerdict` enum to `src/orchestrator/config/enums.py` and add `StepVerifierConfig` Pydantic model plus `step_verifier` field to `StepConfig` in `src/orchestrator/config/models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add `StepVerdict` enum to `src/orchestrator/config/enums.py` with members: `PASS = "pass"`, `RETRY = "retry"`, `FIX = "fix"`, `FAIL = "fail"`
- [ ] Add `StepVerifierConfig` to `src/orchestrator/config/models.py` with fields: `prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`
- [ ] Add `step_verifier: StepVerifierConfig | None = None` field to `StepConfig` (after existing fields)
- [ ] Verify `StepVerifierConfig` with `max_iterations < 1` raises Pydantic validation error

**Dependencies**
- None — this is the first task in the first step.

**References**
- `docs/gap-analyzer/plan.md` — M1 specification
- `docs/gap-analyzer/architecture.md` — `StepVerifierConfig` definition
- `docs/gap-analyzer/step-01-plan.md` — full step contract

**Constraints**
- `step_verifier` must be optional with `None` default — no existing routines must break.
- Do not add state or DB models in this task.

**Functionality (Expected Outcomes)**
- [ ] `StepVerdict` importable from `src/orchestrator/config/enums.py`
- [ ] `StepVerifierConfig` importable from `src/orchestrator/config/models.py`
- [ ] `StepConfig.step_verifier` defaults to `None`

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.enums import StepVerdict; print(list(StepVerdict))"` succeeds
- [ ] `uv run python -c "from orchestrator.config.models import StepVerifierConfig; print(StepVerifierConfig(prompt='test'))"` succeeds
- [ ] Existing routine YAML files load without error

---

## Task 2: Add GapAction, GapReport, and StepState Fields

**Description**: Add `GapAction` and `GapReport` Pydantic models to `src/orchestrator/state/models.py` and add `verifying`, `verifier_iterations`, `gap_reports` fields to `StepState`.

**Implementation Plan (Do These Steps)**
- [ ] Add `GapAction` to `src/orchestrator/state/models.py` with fields: `type: str`, `task_id: str | None = None`, `feedback: str | None = None`, `title: str | None = None`, `context: str | None = None`, `requirements: list[dict] | None = None`
- [ ] Add `GapReport` to `src/orchestrator/state/models.py` with fields: `id: str`, `iteration: int`, `assessment: str`, `verdict: StepVerdict`, `actions: list[GapAction] = []`, `timestamp: datetime`
- [ ] Add `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = Field(default_factory=list)` to `StepState`

**Dependencies**
- [ ] Task 1 must be complete (`StepVerdict` enum must exist)

**References**
- `docs/gap-analyzer/architecture.md` — `GapAction`, `GapReport` field definitions
- `docs/gap-analyzer/clarifications.md` — `retry_task` eligibility, `fail` on JSON parse error

**Constraints**
- `GapReport` with unknown verdict string must raise Pydantic validation error (enum mismatch).
- `GapAction` with `type="retry_task"` and no `task_id` is a valid model — engine enforces semantics.

**Functionality (Expected Outcomes)**
- [ ] `GapAction` and `GapReport` importable from `src/orchestrator/state/models.py`
- [ ] `StepState` has `verifying`, `verifier_iterations`, `gap_reports` with correct defaults

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.state.models import GapReport, GapAction; print('OK')"` succeeds
- [ ] `uv run python -c "from orchestrator.state.models import StepState; s = StepState.__new__(StepState); print('OK')"` succeeds

---

## Task 3: Add DB Columns and Alembic Migration

**Description**: Add `verifying` (Integer/bool, default 0) and `gap_reports` (JSON, default list) columns to `StepModel` in `src/orchestrator/db/models.py`, and create a corresponding Alembic migration.

**Implementation Plan (Do These Steps)**
- [ ] Add `verifying = Column(Integer, default=0)` to `StepModel` in `src/orchestrator/db/models.py`
- [ ] Add `gap_reports = Column(JSON, default=list)` to `StepModel`
- [ ] Generate migration: `uv run alembic revision --autogenerate -m "add step_verifier columns"`
- [ ] Inspect and confirm migration SQL uses `DEFAULT 0` and `DEFAULT '[]'` (or equivalent)
- [ ] Test migration: `uv run alembic upgrade head`

**Dependencies**
- [ ] Task 2 must be complete (state models defined before DB models are updated)

**References**
- `docs/gap-analyzer/plan.md` — M1 DB column spec
- Architecture note (MEMORY.md): never run `rm orchestrator.db`; Alembic migrations only

**Constraints**
- Migration must be safe and additive — no data loss, existing rows default to `verifying=0`, `gap_reports=[]`.
- Do not drop or rename any existing column.

**Functionality (Expected Outcomes)**
- [ ] `StepModel` has `verifying` and `gap_reports` attributes
- [ ] Alembic migration file exists in `alembic/versions/`
- [ ] Migration applies cleanly on existing DB

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` completes without error
- [ ] `uv run python -c "from orchestrator.db.models import StepModel; print(StepModel.verifying)"` succeeds

---

## Task 4: Add Event Types and Unit Tests

**Description**: Add `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` event types to `src/orchestrator/workflow/events.py` and write unit tests in `tests/unit/test_gap_analyzer_models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` dataclasses/classes to `src/orchestrator/workflow/events.py` with appropriate fields (e.g., `step_id`, `iteration`, `max_iterations`, `gap_report`, `verdict`)
- [ ] Create `tests/unit/test_gap_analyzer_models.py` with tests covering:
  - `GapReport` validation: valid data constructs; missing required fields raise errors
  - `GapAction` with all four types (`retry_task`, `spawn_fix`, `pass`, `fail`)
  - `StepVerifierConfig` defaults: `max_iterations=3`, `auto_verify=None`
  - `StepVerdict` values: all four members present with correct string values
  - `StepState` default values: `verifying=False`, `verifier_iterations=0`, `gap_reports=[]`
  - Event type construction: all three new event types instantiate correctly

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/gap-analyzer/architecture.md` — event type definitions and fields
- `docs/gap-analyzer/step-01-plan.md` — full task list and verification approach

**Constraints**
- Event classes should follow the existing event pattern in `events.py` (check existing style).
- Tests must cover both happy-path and validation-error cases.

**Functionality (Expected Outcomes)**
- [ ] All three new event types importable from `src/orchestrator/workflow/events.py`
- [ ] `tests/unit/test_gap_analyzer_models.py` exists and all tests pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_gap_analyzer_models.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ -v` — no existing tests broken
- [ ] `uv run pyright src/orchestrator/` — no new type errors
