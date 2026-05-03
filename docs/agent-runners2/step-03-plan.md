# Step Plan: Model Profiles (Backend + DB)

## Purpose

Introduce Model Profiles as a first-class concept: an enum of cognitive work classes (ARCHITECT, DESIGNER, CODER, SUMMARIZER) with per-runner default model mappings. This enables different model strengths for different phases of work.

## Prerequisites

- **Step 01 (M1)** must be complete: backend uses `AgentRunnerType` naming
- **Step 02 (M2)** should be complete (frontend rename) but is not a hard dependency for backend work

## Functional Contract

### Inputs

- `ModelProfile` enum values: `ARCHITECT`, `DESIGNER`, `CODER`, `SUMMARIZER`
- Per-runner profile-to-model mapping: `{ agent_runner_type, profile, model_string }`
- API requests to set/get Agent Runner Model Defaults per runner type

### Outputs

- `ModelProfile` enum in `config/enums.py`
- `AgentRunnerModelProfileDefaultModel` DB table: `id`, `runner_type`, `profile`, `model` with `UNIQUE(runner_type, profile)` constraint
- API endpoints:
  - `GET /api/model-profiles` -- list all profiles with descriptions
  - `GET /api/agent-runners/{type}/model-profile-defaults` -- get Agent Runner Model Defaults
  - `PUT /api/agent-runners/{type}/model-profile-defaults` -- set Agent Runner Model Defaults
- Alembic migration creating the new table
- Agent Runner Model Defaults wired into execution context -- runner receives resolved model for the relevant profile
- Pydantic schemas: `ModelProfileSchema`, `AgentRunnerModelProfileDefaultsSchema`

### Error Cases

- `PUT /api/agent-runners/{type}/model-profile-defaults` with invalid runner type -> 422 validation error
- `PUT /api/agent-runners/{type}/model-profile-defaults` with invalid profile name -> 422 validation error
- `GET /api/agent-runners/{type}/model-profile-defaults` for runner with no defaults set -> return empty mapping (not 404)
- Profile resolution when no default set -> fall back to runner's built-in default model

## Tasks

1. Define `ModelProfile` enum in `config/enums.py`: `ARCHITECT`, `DESIGNER`, `CODER`, `SUMMARIZER`
2. Create `AgentRunnerModelProfileDefaultModel` SQLAlchemy model in `db/models.py`
3. Create Alembic migration for the new table
4. Create Pydantic schemas: `ModelProfileSchema`, `AgentRunnerModelProfileDefaultsSchema`
5. Create API router `routers/model_profiles.py` with `GET /api/model-profiles`
6. Add model default endpoints to runners router: `GET/PUT /api/agent-runners/{type}/model-profile-defaults`
7. Wire Agent Runner Model Defaults into execution context -- when a runner starts, resolve model from profile
8. Write unit tests for profile CRUD and resolution logic
9. Write integration tests for API endpoints

## Verification Approach

### Auto-Verify

- Unit tests for `ModelProfile` enum membership
- Unit tests for profile-to-model resolution (default fallback, explicit override)
- Integration tests: `GET /api/model-profiles` returns 4 profiles
- Integration tests: `PUT` then `GET` Agent Runner Model Defaults round-trips correctly
- Integration tests: runner execution uses profile-resolved model
- All existing tests continue to pass

### Manual Verification

- `GET /api/model-profiles` returns `[{name: "ARCHITECT", description: "..."}, ...]`
- `PUT /api/agent-runners/CLI_SUBPROCESS/model-profile-defaults` with `{CODER: "claude-sonnet-4-6"}` persists
- `GET /api/agent-runners/CLI_SUBPROCESS/model-profile-defaults` returns the saved mapping

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M3 specification
- Architecture: `docs/agent-runners2/architecture.md` -- data model, API schemas
- Clarification Q5: Per-run profile overrides possible (implemented in later step via run creation)
- Clarification Q8: Include all 4 profiles from the start
- Profile descriptions: ARCHITECT (planning/design), DESIGNER (UI/UX), CODER (implementation), SUMMARIZER (docs/context)
