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
- [ ] Add `@field_validator("max_iterations")` to `StepVerifierConfig` that raises `ValueError("max_iterations must be >= 1")` if value < 1. Example pattern (from existing validators in models.py):
  ```python
  @field_validator("max_iterations")
  @classmethod
  def _validate_max_iterations(cls, v: int) -> int:
      if v < 1:
          raise ValueError("max_iterations must be >= 1")
      return v
  ```
- [ ] Add `step_verifier: StepVerifierConfig | None = None` field to `StepConfig` (after `condition` field at end of existing fields)
- [ ] Note: `_validate_file_exclusivity` in `StepConfig` does NOT need updating — the validator only errors on non-None values; `step_verifier=None` is safe

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

**Description**: Add `GapAction` and `GapReport` Pydantic models to `src/orchestrator/state/models.py`, add `verifying`, `verifier_iterations`, `gap_reports` fields to `StepState`, and add `spawned_by_gap_report` and `gap_report_feedback` fields to `TaskState`.

**Implementation Plan (Do These Steps)**
- [ ] Add `GapAction` to `src/orchestrator/state/models.py` with fields: `type: Literal["retry_task", "spawn_fix", "pass", "fail"]`, `task_id: str | None = None`, `feedback: str | None = None`, `title: str | None = None`, `context: str | None = None`, `requirements: list[dict] | None = None`
  - Note: Use `from typing import Literal` — `type` field must use `Literal` not bare `str` so unknown action types fail validation immediately
- [ ] Add `GapReport` to `src/orchestrator/state/models.py` with fields: `id: str = Field(default_factory=generate_id)`, `iteration: int`, `assessment: str`, `verdict: StepVerdict`, `actions: list[GapAction] = Field(default_factory=list)`, `timestamp: datetime = Field(default_factory=_utc_now)`
  - Use `Field(default_factory=list)` not `= []` for mutable defaults (Pydantic v2 requirement)
- [ ] Add `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = Field(default_factory=list)` to `StepState`
- [ ] Add `spawned_by_gap_report: bool = False` to `TaskState` (after `fan_out_output` field)
  - This field must be `False` by default so existing task creation code is unaffected
- [ ] Add `gap_report_feedback: str | None = None` to `TaskState` (after `spawned_by_gap_report` field)
  - This field stores feedback from a `retry_task` gap action, injected into the next builder prompt
  - Must be cleared after each builder invocation (set back to `None`) once the feedback is used

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

**Description**: Add `verifying`, `verifier_iterations`, and `gap_reports` columns to `StepModel`, and `spawned_by_gap_report` and `gap_report_feedback` columns to `TaskModel` in `src/orchestrator/db/models.py`. Create a single Alembic migration for all five new columns.

**Implementation Plan (Do These Steps)**
- [ ] Add to `StepModel` in `src/orchestrator/db/models.py`:
  - `verifying: Mapped[bool] = mapped_column(Integer, default=0)`
  - `verifier_iterations: Mapped[int] = mapped_column(Integer, default=0)`
  - `gap_reports: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)`
- [ ] Add to `TaskModel` in `src/orchestrator/db/models.py`:
  - `spawned_by_gap_report: Mapped[bool] = mapped_column(Integer, default=0)`
  - `gap_report_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)`
- [ ] Generate migration: `uv run alembic revision --autogenerate -m "add step_verifier columns"`
- [ ] Inspect the generated migration file — confirm it adds all 5 columns with correct defaults
- [ ] Test migration: `uv run alembic upgrade head`

**Dependencies**
- [ ] Task 2 must be complete (state models defined before DB models are updated)

**References**
- `docs/gap-analyzer/plan.md` — M1 DB column spec
- Architecture note (MEMORY.md): never run `rm orchestrator.db`; Alembic migrations only
- Pattern: `StepModel.completed` uses `mapped_column(Integer, default=0)` — follow same pattern for boolean columns

**Constraints**
- Migration must be safe and additive — no data loss; existing rows default to `verifying=0`, `verifier_iterations=0`, `gap_reports=[]`, `spawned_by_gap_report=0`, `gap_report_feedback=NULL`.
- Do not drop or rename any existing column.

**Functionality (Expected Outcomes)**
- [ ] `StepModel` has `verifying`, `verifier_iterations`, `gap_reports` attributes
- [ ] `TaskModel` has `spawned_by_gap_report`, `gap_report_feedback` attributes
- [ ] Alembic migration file exists in `alembic/versions/`
- [ ] Migration applies cleanly on existing DB

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` completes without error
- [ ] `uv run python -c "from orchestrator.db.models import StepModel, TaskModel; print(StepModel.verifying, TaskModel.spawned_by_gap_report)"` succeeds

---

## Task 4: Add Event Types and Unit Tests

**Description**: Add `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` event types to `src/orchestrator/workflow/events.py` and write unit tests in `tests/unit/test_gap_analyzer_models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add to `src/orchestrator/workflow/events.py`, following the `@dataclass` pattern of existing events:
  ```python
  @dataclass
  class StepVerificationStarted(WorkflowEvent):
      """Emitted when step verification begins."""
      step_id: str = ""
      iteration: int = 0
      max_iterations: int = 0
      # event_type value: "step_verification_started"

  @dataclass
  class GapReportGenerated(WorkflowEvent):
      """Emitted when a gap report is produced by the verifier."""
      step_id: str = ""
      iteration: int = 0
      assessment: str = ""
      verdict: str = ""
      action_count: int = 0
      # event_type value: "gap_report_generated"

  @dataclass
  class StepVerificationCompleted(WorkflowEvent):
      """Emitted when step verification concludes (pass or fail)."""
      step_id: str = ""
      total_iterations: int = 0
      final_verdict: str = ""
      # event_type value: "step_verification_completed"
  ```
  - Note: `event_type` is set at instantiation time (e.g. `event_type="step_verification_started"`). These exact snake_case strings are what the frontend must match in the activity feed.
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
