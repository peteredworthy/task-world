# Step 2: State, DB, and Factory (M2)

Thread phase state through runtime models and persistence. `TaskState` gains `current_phase_index`, `phase_outputs`, and `phases_config`; the DB gets new columns via Alembic; the factory synthesizes `phases_config` from legacy task fields.

## Intent Verification
**Original Intent**: Make `TaskState` carry phase progression fields, add DB columns to persist them, and synthesize a `phases_config` list from legacy task config so the engine can drive progression without knowing whether phases were explicit or synthesized.
**Functionality to Produce**:
- `TaskState` with `current_phase_index: int = 0`, `phase_outputs: dict[int, str] = {}`, `phases_config: list[PhaseConfig] | None`
- `current_phase_type` property on `TaskState`
- Alembic migration adding `current_phase_index` and `phase_outputs` columns to `tasks` table
- `PhaseStarted` and `PhaseCompleted` event types in `workflow/events.py`
- `_synthesize_phases` in `state/factory.py` covering all 5 synthesis cases

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_phase_synthesis.py -v` — all synthesis cases pass
- `uv run pytest tests/unit/ -v` — no regressions
- `alembic upgrade head` applies cleanly; `alembic downgrade -1` reverses without data loss

---

## Task 1: Extend TaskState with Phase Fields

**Description**: Add three new fields and a property to `TaskState` in `src/orchestrator/state/models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/state/models.py`
- [ ] Import `PhaseConfig` from `orchestrator.config.models`
- [ ] Add to `TaskState`:
  - `current_phase_index: int = 0`
  - `phase_outputs: dict[int, str] = Field(default_factory=dict)`
  - `phases_config: list[PhaseConfig] | None = None`
- [ ] Add `current_phase_type` property: returns `phases_config[current_phase_index].type.value` if `phases_config` is not None and index is in bounds, else `None`

**Dependencies**
- Step 1 complete: `PhaseConfig` importable

**References**
- `docs/phase-pipelines/step-02-plan.md` — Task 1
- `docs/phase-pipelines/architecture.md` — TaskState fields
- `docs/phase-pipelines/clarifications.md` — Q5: dict[int, str] JSON serialization

**Constraints**
- `phases_config` is not persisted to DB (derived at creation time); only `current_phase_index` and `phase_outputs` are DB-backed

**Functionality (Expected Outcomes)**
- [ ] `TaskState()` initializes with `current_phase_index=0`, `phase_outputs={}`, `phases_config=None`
- [ ] `current_phase_type` returns correct value or `None`

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.state.models import TaskState; ts = TaskState(id='t', config_id='task1'); print(ts.current_phase_index, ts.phase_outputs, ts.phases_config)"` succeeds

> **DRY-RUN FIX**: `TaskState` has no `task_id` or `run_id` fields. Correct constructor uses `id=` and `config_id=`.

---

## Task 2: Add Phase Events

**Description**: Add `PhaseStarted` and `PhaseCompleted` event dataclasses to `src/orchestrator/workflow/events.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/events.py`
- [ ] Add `@dataclass class PhaseStarted` with fields: `run_id: str`, `task_id: str`, `phase_index: int`, `phase_type: str`
- [ ] Add `@dataclass class PhaseCompleted` with fields: `run_id: str`, `task_id: str`, `phase_index: int`, `phase_type: str`, `output: str`
- [ ] Export both from the module

**Dependencies**
- None (independent of other tasks in this step)

**References**
- `docs/phase-pipelines/step-02-plan.md` — Task 3
- `docs/phase-pipelines/architecture.md` — event type definitions

**Constraints**
- Follow the existing event dataclass pattern in the file
- ⚠️ HARDENING NOTE (Gap 5): Use `output: str` on `PhaseCompleted` (NOT `output_length: int` as written in plan.md). The full output string is needed for prior-phase prompt injection in the executor. The plan.md field name is incorrect — `output: str` is the canonical definition.

**Functionality (Expected Outcomes)**
- [ ] `PhaseStarted` and `PhaseCompleted` importable from `orchestrator.workflow.events`

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.events import PhaseStarted, PhaseCompleted; print('OK')"` succeeds

---

## Task 3: Extend TaskModel and Create Alembic Migration

**Description**: Add `current_phase_index` (Integer, default 0) and `phase_outputs` (JSON, default `{}`) to `TaskModel` in `src/orchestrator/db/models.py`, then generate an Alembic migration.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/db/models.py`
- [ ] Add to `TaskModel`:
  - `current_phase_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")`
  - `phase_outputs: Mapped[dict] = mapped_column(JSON, default=dict)` — do NOT add `server_default` for the JSON column; existing JSON columns in `TaskModel` (e.g. `checklist`) use only Python-level `default=list`, and SQLite JSON server_default is unreliable
- [ ] Generate migration: `uv run alembic revision -m "add phase pipeline columns to tasks"`
- [ ] Implement `upgrade()`:
  - `op.add_column("tasks", sa.Column("current_phase_index", sa.Integer(), nullable=False, server_default="0"))`
  - `op.add_column("tasks", sa.Column("phase_outputs", sa.JSON(), nullable=True))` — use nullable=True to avoid issues with existing rows; the Python model treats None as {}
- [ ] Implement `downgrade()`: `op.drop_column("tasks", "current_phase_index")` and `op.drop_column("tasks", "phase_outputs")`
- [ ] ALSO update `src/orchestrator/db/repositories.py` — the ACTUAL persistence mapping:
  - In `_to_domain()` (read path, around line 167): when constructing `TaskState`, add `current_phase_index=task_model.current_phase_index` and `phase_outputs={int(k): v for k, v in (task_model.phase_outputs or {}).items()}` — **int key conversion is required**: JSON serializes `dict[int, str]` keys as strings, so they must be converted back to int on read; otherwise `task.phase_outputs[0]` raises `KeyError` at runtime
  - In `_to_model()` (write path, around line 310): when constructing `TaskModel`, add `current_phase_index=task.current_phase_index` and `phase_outputs=task.phase_outputs`
- [ ] Test: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`

**Dependencies**
- [ ] Task 1 must be complete (TaskState fields defined for reference)

**References**
- `docs/phase-pipelines/step-02-plan.md` — Tasks 4–5
- Architecture: existing Alembic migration patterns in `alembic/versions/`

**Constraints**
- Migration must be reversible
- Existing rows must default gracefully (no null violations)

**Functionality (Expected Outcomes)**
- [ ] `tasks` table has `current_phase_index` and `phase_outputs` columns after migration
- [ ] Migration applies and reverses cleanly

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` completes without error
- [ ] `uv run alembic downgrade -1` completes without error

---

## Task 4: Implement Phase Synthesis in Factory

**Description**: Implement `_synthesize_phases` in `src/orchestrator/state/factory.py` and call it when creating `TaskState` from `TaskConfig`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/state/factory.py`
- [ ] Add `_synthesize_phases(task_config: TaskConfig) -> list[PhaseConfig] | None`:
  - Fan-out task (`task_config.fan_out` is not None) → return `None`
  - Explicit `phases` set (`task_config.phases is not None`) → return `list(task_config.phases)`
  - `task_config.script` set → return `[PhaseConfig(type=PhaseType.script, cmd=task_config.script)]`
  - IMPORTANT: Check `auto_verify.items` BEFORE checking `verifier.rubric`. The `_warn_if_no_verification` validator on `TaskConfig` auto-generates a rubric from `requirements` — so tasks with `task_context + requirements + auto_verify` will have a non-empty rubric after validation. To correctly produce `[build, auto_verify]` for such tasks, the auto_verify check must come first:
    - `task_config.task_context` + auto_verify items (`bool(task_config.auto_verify.items)`) → `[PhaseConfig(type=PhaseType.build), PhaseConfig(type=PhaseType.auto_verify)]`
    - `task_config.task_context` + verifier rubric (`bool(task_config.verifier.rubric)`) → `[PhaseConfig(type=PhaseType.build), PhaseConfig(type=PhaseType.verify)]`
    - `task_config.task_context` only → `[PhaseConfig(type=PhaseType.build)]`
- [ ] Call `_synthesize_phases` when constructing `TaskState` from config; set `phases_config` on the result

**Dependencies**
- [ ] Tasks 1 and 3 must be complete

**References**
- `docs/phase-pipelines/step-02-plan.md` — Tasks 6–7
- `docs/phase-pipelines/clarifications.md` — Q2: task_context-only → [build]; Q3: fan-out skips synthesis

**Constraints**
- Synthesis must not mutate the input `TaskConfig`
- Fan-out tasks must have `phases_config = None` (not an empty list)
- CRITICAL: `phases_config` is NOT persisted to DB. After any server restart, `TaskState.phases_config`
  loaded from DB will be `None`. To fix this, add a helper method
  `WorkflowService._with_phases(run: Run, task: TaskState) -> TaskState` in
  `src/orchestrator/workflow/service.py` that re-synthesizes `phases_config` by:
  1. Parsing the embedded routine from `run.routine_embedded` via `RoutineConfig.model_validate(...)`
  2. Finding the `TaskConfig` whose `id == task.config_id` across all steps
  3. Calling `_synthesize_phases(task_config)` and assigning the result to `task.phases_config`
  This helper must be called in `WorkflowService.get_task()` and before any engine dispatch.

**Functionality (Expected Outcomes)**
- [ ] Legacy task config (no `phases`) synthesizes correct phase list
- [ ] Fan-out tasks have `phases_config = None`
- [ ] Explicit `phases` passed through unchanged

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_phase_synthesis.py -v` — all synthesis cases pass

---

## Task 5: Write Synthesis Unit Tests

**Description**: Create `tests/unit/test_phase_synthesis.py` covering all factory synthesis cases.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_phase_synthesis.py`
- [ ] Write tests:
  - `test_synthesize_build_verify`: `task_context` + verifier rubric → `[build, verify]`
  - `test_synthesize_build_auto_verify`: `task_context` + `auto_verify` items, no rubric → `[build, auto_verify]`
  - `test_synthesize_build_only`: `task_context` only → `[build]` (clarification Q2)
  - `test_synthesize_script`: `script` set → `[script]` with correct `cmd`
  - `test_synthesize_explicit_phases`: explicit `phases` passed through unchanged
  - `test_fan_out_skips_synthesis`: fan-out task → `phases_config = None`
  - `test_task_state_defaults`: `TaskState` fields default correctly at creation
- [ ] Run: `uv run pytest tests/unit/test_phase_synthesis.py -v`

**Dependencies**
- [ ] Task 4 must be complete

**References**
- `docs/phase-pipelines/step-02-plan.md` — Task 8
- `docs/phase-pipelines/clarifications.md` — Q2, Q3

**Constraints**
- Use `TaskConfig` + factory function (call `create_task_state(task_config)` and inspect `task_state.phases_config`); do not call `_synthesize_phases` directly if it's private
- IMPORTANT for `test_synthesize_build_auto_verify`: construct the task with NO `requirements` field (empty list or omit). If `requirements` are present, `TaskConfig._warn_if_no_verification` auto-generates a rubric, making `verifier.rubric` non-empty and causing synthesis to produce `[build, verify]` instead of `[build, auto_verify]`. Use `requirements=[]` explicitly.

**Functionality (Expected Outcomes)**
- [ ] All 7 test cases pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_phase_synthesis.py -v` — all pass
- [ ] `uv run pytest tests/unit/ -v` — no regressions

---
