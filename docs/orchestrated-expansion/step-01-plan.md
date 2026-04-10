# Step Plan: Data Models (M1 Core)

## Purpose

Extend all data models to represent expansion state and limits. This step defines the complete data shape for the orchestrated expansion feature — config models, runtime state fields, DB columns, API schemas, and the `TaskExpanded` event type. No logic is implemented yet; the goal is to establish a stable foundation that all subsequent steps can build upon.

## Prerequisites

- None — this is the first step with no dependencies.

## Functional Contract

### Inputs

No runtime inputs. This step produces model definitions and schema changes only.

### Outputs

- `ExpansionLimits` Pydantic model in `src/orchestrator/config/models.py`:
  - `max_subtasks_per_task: int = 5`
  - `max_peer_tasks_per_step: int = 3`
  - `max_inserted_steps: int = 2`
  - `max_total_expansions: int = 10`
  - `require_human_approval: bool = False`
- `RoutineConfig.expansion_limits: ExpansionLimits` field (optional, `default_factory=ExpansionLimits`)
- `TaskState` new fields:
  - `expansions_requested: int = 0`
  - `expanded_from_task_id: str | None = None`
  - `expansion_justification: str | None = None`
- `Run` new field: `total_expansions: int = 0`
- `TaskModel` new DB columns: `expanded_from_task_id` (FK, nullable), `expansion_justification` (String, nullable), `is_expansion` (Boolean, default False)
- `StepModel` new DB columns: `is_expansion` (Boolean, default False), `expanded_from_task_id` (FK, nullable)
- `RunModel` new DB column: `expansion_count` (Integer, default 0)
- `ExpansionTaskSpec`, `ExpansionRequest`, `ExpansionResponse` schemas in `src/orchestrator/api/schemas/tasks.py`
- `TaskExpanded` event in `src/orchestrator/workflow/events.py`

### Error Cases

- No new runtime error cases in this step (data model only).
- Schema validation: `ExpansionRequest.type` must be one of `"add_subtask"`, `"add_peer_task"`, `"add_next_step"`.
- Schema validation: `add_next_step` requires `tasks` array with at least one entry; validated at request time.

## Tasks

1. **`src/orchestrator/config/models.py`**: Add `ExpansionLimits` class. Add `expansion_limits` field to `RoutineConfig`.

2. **`src/orchestrator/state/models.py`**: Add `expansions_requested`, `expanded_from_task_id`, `expansion_justification` to `TaskState`. Add `total_expansions` to `Run`.

3. **`src/orchestrator/db/models.py`**: Add columns to `TaskModel`, `StepModel`, `RunModel` as described above. Use `Column(Boolean, default=False, nullable=False)` for `is_expansion`, `Column(String, nullable=True)` for text fields, `Column(Integer, default=0, nullable=False)` for `expansion_count`.

4. **`src/orchestrator/api/schemas/tasks.py`**: Add:
   - `ExpansionTaskSpec` with `title`, `context`, `requirements`, `agent_profile`
   - `ExpansionRequest` with `type` (Literal), `title`, `context`, `justification`, `requirements`, `blocking`, `agent_profile`, `tasks`
   - `ExpansionResponse` with `status`, `expansion_type`, `created_task_id`, `created_step_id`, `created_task_ids`, `total_expansions_used`, `budget_remaining`

5. **`src/orchestrator/workflow/events.py`**: Add `TaskExpanded` event with `requesting_task_id`, `expansion_type`, `created_task_id`, `created_step_id`, `justification`, `blocking`, `approved`.

6. **`tests/unit/test_expansion_models.py`**: Unit tests for:
   - `ExpansionLimits` default values
   - `ExpansionLimits` serialization round-trip
   - `ExpansionRequest` schema validation (valid types, invalid type rejected)
   - `add_next_step` with empty `tasks` list raises validation error

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_expansion_models.py -v` — all tests pass
- `uv run pyright src/orchestrator/` — no type errors
- `uv run pytest tests/unit/ -v` — no existing tests broken

### Manual Verification

- Confirm `ExpansionLimits` default values match the spec (5, 3, 2, 10, False)
- Confirm all new DB columns have correct defaults so existing rows remain valid without data migration

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 1 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — full schema definitions
- Clarification Q1: `StepModel` also gets `is_expansion` and `expanded_from_task_id` columns
- Clarification Q2: `add_next_step` supports multiple tasks via `tasks: list[ExpansionTaskSpec]`
