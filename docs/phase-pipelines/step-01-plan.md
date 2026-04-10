# Step Plan: Config Models + Enums (M1)

## Purpose

Define all new types (`PhaseType` enum, `PhaseConfig` model, `phases` field on `TaskConfig`) so
the rest of the system can reference them without touching the engine, executor, or DB. This step
has no runtime effect — it is purely additive type/model work that unblocks every subsequent step.

## Prerequisites

- None — this is the first step with no dependencies.

## Functional Contract

### Inputs

- `PhaseType` — string enum consumed by `PhaseConfig`, executor dispatch, and prompts
- `PhaseConfig` — Pydantic model consumed by `TaskConfig.phases`, `TaskState.phases_config`,
  engine methods, and executor
- `TaskConfig.phases: list[PhaseConfig] | None` — optional explicit pipeline defined in routine YAML

### Outputs

- `PhaseType` enum with 8 values: `build`, `verify`, `plan`, `summarize`, `gap_check`, `script`,
  `auto_verify`, `human_review`
- `PhaseConfig` Pydantic model with fields:
  - `type: PhaseType`
  - `prompt: str | None = None`
  - `profile: ModelProfile | None = None`
  - `condition: str | None = None`
  - `cmd: str | None = None`
  - `retry_target: int | None = None`
- `TaskConfig` extended with `phases: list[PhaseConfig] | None = None`
- Validator on `TaskConfig` rejecting `phases` + `fan_out` co-existence
- Unit tests covering all validation rules

### Error Cases

- `TaskConfig` with both `phases` and `fan_out` set → `ValidationError`
- `retry_target` validated at `TaskConfig` level (needs phase list): must be < index of the verify
  phase that owns it → `ValidationError`
- `PhaseConfig.cmd` is required when `type == script` — validated at `TaskConfig` level once full
  phase list is available (or flagged in unit tests as user responsibility)

## Tasks

1. Add `PhaseType(str, Enum)` to `src/orchestrator/config/enums.py` with 8 values.
2. Add `PhaseConfig(BaseModel)` to `src/orchestrator/config/models.py` with all fields listed above.
3. Add `phases: list[PhaseConfig] | None = None` to `TaskConfig` in the same file.
4. Add `@model_validator(mode="after")` on `TaskConfig`:
   - Reject `phases` + `fan_out` co-existence.
   - Validate each verify-type phase's `retry_target` is `< phase_index` of that phase.
5. Create `tests/unit/test_phase_config.py`:
   - `PhaseConfig` accepts all 8 `PhaseType` values.
   - `PhaseConfig` round-trips through JSON serialization (all fields).
   - `TaskConfig.phases` co-exists with `task_context`, `verifier`, `auto_verify`.
   - `TaskConfig.phases` + `fan_out` raises `ValidationError`.
   - `retry_target` pointing to an invalid index raises `ValidationError`.
   - `retry_target` pointing to a valid earlier index is accepted.

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_phase_config.py -v` — all new tests pass.
- `uv run pytest tests/unit/ -v` — no existing tests broken.
- `uv run pyright src/orchestrator/config/` — no type errors.

### Manual Verification

- Confirm `PhaseType` is importable from `src/orchestrator/config/enums.py`.
- Confirm `PhaseConfig` and updated `TaskConfig` are importable from
  `src/orchestrator/config/models.py`.

## Context & References

- Plan: `docs/phase-pipelines/plan.md` — M1 and Step 1 specification.
- Architecture: `docs/phase-pipelines/architecture.md` — `PhaseType`, `PhaseConfig`, `TaskConfig`
  addition.
- Clarification Q3: `phases` is mutually exclusive with `fan_out`; fan-out subtask phase support
  is deferred.
- Clarification Q4: `retry_target` validation belongs at `TaskConfig` level (not `PhaseConfig`
  level) because full phase list context is required.
