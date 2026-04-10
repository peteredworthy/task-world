# Step Plan: State, DB, and Factory (M2)

## Purpose

Thread phase state through the runtime models and persistence layer. By the end of this step,
`TaskState` carries `current_phase_index`, `phase_outputs`, and `phases_config`; the DB has the
required columns; and the factory synthesizes a `phases_config` list from legacy task fields so
the engine can drive progression without knowing whether phases were explicit or synthesized.

## Prerequisites

- Step 1 complete: `PhaseType` and `PhaseConfig` defined and importable.

## Functional Contract

### Inputs

- `TaskConfig` (any combination of `task_context`, `verifier`, `auto_verify`, `script`, or
  explicit `phases`)
- Existing `TaskModel` rows in the DB (must survive migration without data loss)

### Outputs

- `TaskState` with three new fields:
  - `current_phase_index: int = 0`
  - `phase_outputs: dict[int, str] = {}` (empty at creation)
  - `phases_config: list[PhaseConfig] | None` — populated by factory
- `current_phase_type` property on `TaskState`: returns
  `phases_config[current_phase_index].type.value` if set, else `None`
- Alembic migration that adds `current_phase_index` (Integer, default 0) and `phase_outputs`
  (JSON, default `{}`) to the `tasks` table; existing rows default gracefully
- `PhaseStarted` and `PhaseCompleted` event types in `src/orchestrator/workflow/events.py`
- Factory synthesis in `src/orchestrator/state/factory.py`:
  - `task_context` + verifier rubric → `[build, verify]`
  - `task_context` + auto_verify items, no rubric → `[build, auto_verify]`
  - `task_context` + no verification → `[build]`
  - `script` set → `[script(cmd=task.script)]`
  - explicit `phases` on config → copy as-is
  - fan-out tasks → `phases_config` left as `None` (synthesis skipped)

### Error Cases

- DB migration failure (e.g. column already exists) — Alembic should handle idempotently via
  `op.add_column` with `if_exists` handling or by checking schema before adding.
- `_synthesize_phases` called on a fan-out task — must not set `phases_config` (return `None`).

## Tasks

1. Add `current_phase_index`, `phase_outputs`, and `phases_config` fields to `TaskState` in
   `src/orchestrator/state/models.py`.
2. Add `current_phase_type` property to `TaskState`.
3. Add `PhaseStarted` and `PhaseCompleted` event dataclasses to
   `src/orchestrator/workflow/events.py`.
4. Add `current_phase_index` (Integer, default 0) and `phase_outputs` (JSON, default `{}`) to
   `TaskModel` in `src/orchestrator/db/models.py`.
5. Generate Alembic migration: `alembic revision -m "add phase pipeline columns to tasks"` and
   implement `upgrade()`/`downgrade()`.
6. Implement `_synthesize_phases(task_config: TaskConfig) -> list[PhaseConfig]` in
   `src/orchestrator/state/factory.py`.
7. Call synthesis (or copy explicit phases) when creating `TaskState` from `TaskConfig` in the
   factory; skip synthesis for fan-out tasks.
8. Create `tests/unit/test_phase_synthesis.py`:
   - Each synthesis case produces the correct phase list.
   - Explicit `phases` are passed through unchanged.
   - Fan-out tasks have `phases_config = None`.
   - `TaskState` fields default correctly at creation.
9. Add DB migration test (in-memory SQLite): apply migration, verify new columns exist with
   defaults.

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_phase_synthesis.py -v` — all synthesis cases pass.
- `uv run pytest tests/unit/ -v` — no regressions.
- `alembic upgrade head` applies cleanly to the dev DB.
- `alembic downgrade -1` followed by `alembic upgrade head` round-trips without data loss.
- `uv run pyright src/orchestrator/state/ src/orchestrator/db/ src/orchestrator/workflow/events.py`
  — no type errors.

### Manual Verification

- Confirm that creating a `TaskState` from a legacy task config (no `phases` field) results in a
  non-None `phases_config` with the correct synthesized phases.
- Confirm `current_phase_type` returns the correct string for index 0 of a synthesized pipeline.

## Context & References

- Plan: `docs/phase-pipelines/plan.md` — M2 and Step 2 specification.
- Architecture: `docs/phase-pipelines/architecture.md` — `TaskState` fields, `TaskModel`
  migration, synthesis logic, event types.
- Clarification Q2: `task_context` with no verifier and no `auto_verify` synthesizes `[build]`
  (no verification step).
- Clarification Q3: Fan-out tasks skip synthesis entirely (`phases_config` left `None`).
- Clarification Q5: `phase_outputs` uses `dict[int, str]`; Pydantic serializes int keys as
  JSON string keys and deserializes back — no manual handling needed.
