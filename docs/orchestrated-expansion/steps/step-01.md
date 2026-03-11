# Step 1: Data Models (M1 Core)

Extend all data models to represent expansion state and limits. Defines the complete data shape for orchestrated expansion — config models, runtime state fields, DB columns, API schemas, and the `TaskExpanded` event type. No logic is implemented yet; the goal is a stable foundation that all subsequent steps build upon.

## Intent Verification
**Original Intent**: Establish all model definitions and schema changes required by the orchestrated expansion feature before any logic is built (see `docs/orchestrated-expansion/plan.md` Step 1).
**Functionality to Produce**:
- `ExpansionLimits` Pydantic model in `src/orchestrator/config/models.py` with defaults (5, 3, 2, 10, False)
- `RoutineConfig.expansion_limits` optional field with `default_factory=ExpansionLimits`
- `TaskState` gains `expansions_requested`, `expanded_from_task_id`, `expansion_justification`
- `Run` gains `total_expansions: int = 0`
- `TaskModel` gains `expanded_from_task_id` (FK, nullable), `expansion_justification` (String, nullable), `is_expansion` (Boolean, default False)
- `StepModel` gains `is_expansion` (Boolean, default False), `expanded_from_task_id` (FK, nullable)
- `RunModel` gains `expansion_count` (Integer, default 0)
- `ExpansionTaskSpec`, `ExpansionRequest`, `ExpansionResponse` schemas in `src/orchestrator/api/schemas/tasks.py`
- `TaskExpanded` event in `src/orchestrator/workflow/events.py`

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_expansion_models.py -v` — all tests pass
- `uv run pyright src/orchestrator/` — no type errors
- `uv run pytest tests/unit/ -v` — no regressions

---

## Task 1: Add ExpansionLimits to Config Models

**Description**: Add `ExpansionLimits` Pydantic model and wire it into `RoutineConfig` as an optional field.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/config/models.py`
- [ ] Add `ExpansionLimits` class with fields: `max_subtasks_per_task: int = 5`, `max_peer_tasks_per_step: int = 3`, `max_inserted_steps: int = 2`, `max_total_expansions: int = 10`, `require_human_approval: bool = False`
- [ ] Add `expansion_limits: ExpansionLimits = Field(default_factory=ExpansionLimits)` to `RoutineConfig`

**Dependencies**
- None — first task in the step

**References**
- `docs/orchestrated-expansion/plan.md` — Step 1, M1 Core
- `docs/orchestrated-expansion/architecture.md` — `ExpansionLimits` definition
- `docs/orchestrated-expansion/clarifications.md` — Q4: `require_human_approval` is required

**Constraints**
- No logic changes; data model definitions only
- Field defaults must match the spec exactly (5, 3, 2, 10, False)

**Functionality (Expected Outcomes)**
- [ ] `ExpansionLimits()` instantiates with correct defaults
- [ ] `RoutineConfig` parses YAML that omits `expansion_limits` (defaults to `ExpansionLimits()`)
- [ ] `RoutineConfig` parses YAML that includes `expansion_limits` overrides

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.models import ExpansionLimits; print(ExpansionLimits())"` shows all five fields with correct defaults
- [ ] `uv run pyright src/orchestrator/config/models.py` — no type errors

---

## Task 2: Add Expansion Fields to State Models

**Description**: Add expansion tracking fields to `TaskState` and `Run` in the runtime state models.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/state/models.py`
- [ ] Add to `TaskState`: `expansions_requested: int = 0`, `expanded_from_task_id: str | None = None`, `expansion_justification: str | None = None`
- [ ] Add to `Run`: `total_expansions: int = 0`

**Dependencies**
- [ ] Task 1 must be complete (config model defined)

**References**
- `docs/orchestrated-expansion/architecture.md` — `TaskState` and `Run` fields section

**Constraints**
- All new fields must have defaults so existing `TaskState`/`Run` construction still works without passing these fields

**Functionality (Expected Outcomes)**
- [ ] `TaskState(...)` constructs without error when expansion fields are omitted
- [ ] `Run(...)` constructs with `total_expansions=0` by default

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.state.models import TaskState, Run; t=TaskState(id='x',title='y'); print(t.expansions_requested, t.expanded_from_task_id)"` prints `0 None`

---

## Task 3: Add DB Columns to TaskModel, StepModel, RunModel

**Description**: Add new SQLAlchemy ORM columns to the three existing DB models. No migration yet — that's Step 2.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/db/models.py`
- [ ] Add to `TaskModel`: `expanded_from_task_id = Column(String, ForeignKey('tasks.id', use_alter=True), nullable=True)`, `expansion_justification = Column(String, nullable=True)`, `is_expansion = Column(Boolean, default=False, nullable=False)`
- [ ] Add to `StepModel`: `is_expansion = Column(Boolean, default=False, nullable=False)`, `expanded_from_task_id = Column(String, ForeignKey('tasks.id', use_alter=True), nullable=True)`
- [ ] Add to `RunModel`: `expansion_count = Column(Integer, default=0, nullable=False)`

**Dependencies**
- [ ] Task 2 must be complete (state fields align with DB columns)

**References**
- `docs/orchestrated-expansion/architecture.md` — DB model section
- `docs/orchestrated-expansion/clarifications.md` — Q1: `StepModel` also gets `is_expansion` and `expanded_from_task_id`

**Constraints**
- Use `use_alter=True` on `tasks.expanded_from_task_id` self-referencing FK to avoid circular FK creation issues
- Do not delete existing columns or change existing column types
- Column defaults must ensure existing rows remain valid without data migration

**Functionality (Expected Outcomes)**
- [ ] All three model classes import without error
- [ ] `create_all()` on a fresh DB produces tables with the new columns

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.db.models import TaskModel, StepModel, RunModel; print('OK')"` succeeds
- [ ] `uv run pyright src/orchestrator/db/models.py` — no type errors

---

## Task 4: Add Expansion Schemas to tasks.py

**Description**: Add `ExpansionTaskSpec`, `ExpansionRequest`, and `ExpansionResponse` Pydantic schemas.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/schemas/tasks.py`
- [ ] Add `ExpansionTaskSpec` with: `title: str`, `context: str`, `requirements: list[str] | None = None`, `agent_profile: str | None = None`
- [ ] Add `ExpansionRequest` with: `type: Literal["add_subtask", "add_peer_task", "add_next_step"]`, `title: str`, `context: str`, `justification: str`, `requirements: list[str] | None = None`, `blocking: bool = False`, `agent_profile: str | None = None`, `tasks: list[ExpansionTaskSpec] | None = None`
- [ ] Add `ExpansionResponse` with: `status: str`, `expansion_type: str`, `created_task_id: str | None = None`, `created_step_id: str | None = None`, `created_task_ids: list[str] | None = None`, `total_expansions_used: int`, `budget_remaining: dict[str, int]`
- [ ] Add validator on `ExpansionRequest`: if `type == "add_next_step"`, `tasks` must be non-empty

**Dependencies**
- [ ] Task 3 must be complete (DB columns defined before schemas reference them)

**References**
- `docs/orchestrated-expansion/architecture.md` — schema definitions
- `docs/orchestrated-expansion/clarifications.md` — Q2: `add_next_step` supports multiple tasks via `tasks` array

**Constraints**
- `ExpansionRequest.type` must be a `Literal` — invalid type values rejected by Pydantic
- Validator for empty `tasks` in `add_next_step` should raise `ValueError` with clear message

**Functionality (Expected Outcomes)**
- [ ] `ExpansionRequest(type="add_subtask", title="t", context="c", justification="j")` parses successfully
- [ ] `ExpansionRequest(type="add_next_step", title="t", context="c", justification="j", tasks=[])` raises `ValidationError`
- [ ] `ExpansionRequest(type="invalid", ...)` raises `ValidationError`

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.api.schemas.tasks import ExpansionRequest, ExpansionResponse; print('OK')"` succeeds
- [ ] `uv run pyright src/orchestrator/api/schemas/tasks.py` — no type errors

---

## Task 5: Add TaskExpanded Event

**Description**: Add the `TaskExpanded` event class to the workflow events module.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/events.py`
- [ ] Add `TaskExpanded` dataclass/Pydantic model with: `requesting_task_id: str`, `expansion_type: str`, `created_task_id: str | None = None`, `created_step_id: str | None = None`, `justification: str`, `blocking: bool = False`, `approved: bool = True`
- [ ] Follow the existing event registration pattern (if events are registered in a registry, register `TaskExpanded`)

**Dependencies**
- [ ] Task 4 complete (schema established before event mirrors its shape)

**References**
- `docs/orchestrated-expansion/architecture.md` — `TaskExpanded` event definition
- Existing events: `src/orchestrator/workflow/events.py`

**Constraints**
- Match existing event definition patterns in the file (dataclass vs Pydantic, inheritance, etc.)

**Functionality (Expected Outcomes)**
- [ ] `TaskExpanded` is importable from `orchestrator.workflow.events`
- [ ] Event has all required fields with correct types and defaults

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.events import TaskExpanded; print(TaskExpanded.__annotations__)"` shows all fields

---

## Task 6: Write Unit Tests for Expansion Models

**Description**: Create `tests/unit/test_expansion_models.py` with unit tests covering model defaults, round-trip serialization, and schema validation.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_models.py`
- [ ] Test `ExpansionLimits` default values (5, 3, 2, 10, False)
- [ ] Test `ExpansionLimits` serialization round-trip (model_dump → model_validate)
- [ ] Test `ExpansionRequest` with valid types (`add_subtask`, `add_peer_task`, `add_next_step`)
- [ ] Test `ExpansionRequest` with invalid type raises `ValidationError`
- [ ] Test `ExpansionRequest` with `type="add_next_step"` and empty `tasks` list raises `ValidationError`
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Tasks 1–5 complete (all models defined)

**References**
- `docs/orchestrated-expansion/step-01-plan.md` — Verification Approach

**Constraints**
- Tests must be self-contained (no DB or server required)

**Functionality (Expected Outcomes)**
- [ ] All tests pass
- [ ] No existing unit tests broken

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_models.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ -v` — no regressions
