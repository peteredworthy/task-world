# Step 3: Model Profiles (Backend + DB)

Introduce Model Profiles as a first-class concept: an enum of cognitive work classes (ARCHITECT, DESIGNER, CODER, SUMMARIZER) with per-runner default model mappings. This enables different model strengths for different phases of work.

## Intent Verification
**Original Intent**: Create the Model Profiles concept so each agent-runner can map cognitive profiles to specific models (see `docs/agent-runners2/intent.md` -- "Model Profiles" section).
**Functionality to Produce**:
- `ModelProfile` enum: ARCHITECT, DESIGNER, CODER, SUMMARIZER
- `AgentRunnerModelProfileDefaultModel` DB table with per-runner profile-to-model mappings
- API endpoints for listing profiles and managing per-runner defaults
- Agent Runner Model Defaults wired into execution context

**Final Verification Criteria**:
- `GET /api/model-profiles` returns 4 profiles
- `PUT/GET /api/agent-runners/{type}/model-profile-defaults` round-trips correctly
- Alembic migration applies cleanly
- All existing tests continue to pass

---

## Task 1: Define ModelProfile Enum and DB Model

**Description**: Add the `ModelProfile` enum to `config/enums.py` and create the `AgentRunnerModelProfileDefaultModel` SQLAlchemy model in `db/models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add `ModelProfile` enum to `src/orchestrator/config/enums.py`:
  ```python
  class ModelProfile(str, Enum):
      ARCHITECT = "ARCHITECT"
      DESIGNER = "DESIGNER"
      CODER = "CODER"
      SUMMARIZER = "SUMMARIZER"
  ```
- [ ] Add `AgentRunnerModelProfileDefaultModel` to `src/orchestrator/db/models.py`:
  - Columns: `id` (UUID PK), `runner_type` (enum), `profile` (enum), `model` (str)
  - Unique constraint on `(runner_type, profile)`
- [ ] Verify the model can be imported without errors

**Dependencies**
- [ ] Step 1 must be complete (`AgentRunnerType` enum exists)

**References**
- `docs/agent-runners2/architecture.md` -- data model section, `agent_runner_model_profile_defaults` table
- `docs/agent-runners2/plan.md` -- M3 steps 1-2
- Clarification Q8: Include all 4 profiles from the start

**Constraints**
- `ModelProfile` is an enum, not user-extensible (initially)
- Do not modify existing models or enums

**Functionality (Expected Outcomes)**
- [ ] `ModelProfile.ARCHITECT`, `.DESIGNER`, `.CODER`, `.SUMMARIZER` are valid enum values
- [ ] `AgentRunnerModelProfileDefaultModel` is importable and has correct columns
- [ ] Unique constraint prevents duplicate `(runner_type, profile)` entries

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.enums import ModelProfile; print(list(ModelProfile))"` prints 4 profiles
- [ ] `uv run python -c "from orchestrator.db.models import AgentRunnerModelProfileDefaultModel; print('OK')"` succeeds

---

## Task 2: Create Alembic Migration and Pydantic Schemas

**Description**: Create the Alembic migration for `agent_runner_model_profile_defaults` table and define Pydantic schemas for the API layer.

**Implementation Plan (Do These Steps)**
- [ ] Generate migration: `uv run alembic revision --autogenerate -m "Add agent_runner_model_profile_defaults table"`
- [ ] Verify the migration creates the table with correct columns and unique constraint
- [ ] Test migration: `uv run alembic upgrade head`
- [ ] Create Pydantic schemas:
  ```python
  class ModelProfileSchema(BaseModel):
      name: str           # e.g. "ARCHITECT"
      description: str

  class AgentRunnerModelProfileDefaultsSchema(BaseModel):
      agent_runner_type: str
      model_profile_defaults: dict[str, str]  # {profile_name: model_string}
  ```
- [ ] Place schemas in appropriate schema file (e.g., `schemas/runners.py` or new `schemas/profiles.py`)

**Dependencies**
- [ ] Task 1 must be complete (enum and model exist)

**References**
- `docs/agent-runners2/architecture.md` -- schema definitions
- Clarification Q3: Alembic migrations only

**Constraints**
- Migration must be reversible
- Schemas should follow existing Pydantic patterns in the codebase

**Functionality (Expected Outcomes)**
- [ ] Alembic migration creates `agent_runner_model_profile_defaults` table
- [ ] Migration applies and reverses cleanly
- [ ] Pydantic schemas validate correctly

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` succeeds
- [ ] `uv run alembic downgrade -1` succeeds

---

## Task 3: Create API Endpoints for Profiles

**Description**: Create the API router for model profiles and add per-runner profile endpoints.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/api/routers/model_profiles.py` with:
  - `GET /api/model-profiles` -- returns list of `ModelProfileSchema` with name and description
- [ ] Add model default endpoints to runners router (`routers/runners.py`):
  - `GET /api/agent-runners/{type}/model-profile-defaults` -- get Agent Runner Model Defaults
  - `PUT /api/agent-runners/{type}/model-profile-defaults` -- set Agent Runner Model Defaults
- [ ] Register the new router in `app.py`
- [ ] Implement DB CRUD logic for reading/writing `AgentRunnerModelProfileDefaultModel` records

**Dependencies**
- [ ] Task 2 must be complete (migration applied, schemas defined)

**References**
- `docs/agent-runners2/architecture.md` -- API endpoints table
- `docs/agent-runners2/plan.md` -- M3 steps 5-6
- Profile descriptions: ARCHITECT (planning/design), DESIGNER (UI/UX), CODER (implementation), SUMMARIZER (docs/context)

**Constraints**
- `GET` for runner with no defaults returns empty mapping, not 404
- Invalid runner type or profile name returns 422

**Functionality (Expected Outcomes)**
- [ ] `GET /api/model-profiles` returns 4 profiles with descriptions
- [ ] `PUT /api/agent-runners/{type}/model-profile-defaults` persists mapping
- [ ] `GET /api/agent-runners/{type}/model-profile-defaults` returns saved mapping

**Final Verification (Proof of Completion)**
- [ ] `curl localhost:8000/api/model-profiles` returns JSON array with 4 items
- [ ] PUT then GET Agent Runner Model Defaults round-trips correctly

---

## Task 4: Wire Profiles into Execution and Write Tests

**Description**: Wire Agent Runner Model Defaults into the execution context so runners receive the resolved model, and write unit + integration tests.

**Implementation Plan (Do These Steps)**
- [ ] Update execution context: when a runner starts, resolve the model from the profile mapping
- [ ] Resolution order: per-run model overrides (future) -> Agent Runner Model Defaults -> runner's built-in default model
- [ ] Write unit tests for `ModelProfile` enum membership
- [ ] Write unit tests for profile-to-model resolution logic (default fallback, explicit override)
- [ ] Write integration tests: `GET /api/model-profiles` returns 4 profiles
- [ ] Write integration tests: `PUT` then `GET` Agent Runner Model Defaults round-trips correctly
- [ ] Verify all existing tests still pass

**Dependencies**
- [ ] Task 3 must be complete (API endpoints exist)

**References**
- `docs/agent-runners2/architecture.md` -- execution flow section
- `docs/agent-runners2/plan.md` -- M3 steps 7-9
- Clarification Q5: Per-run profile overrides possible (implemented later via run creation)

**Constraints**
- Per-run profile overrides are not implemented yet -- just ensure the resolution chain supports them
- Fallback to runner's built-in default if no profile default is set

**Functionality (Expected Outcomes)**
- [ ] Runner execution uses profile-resolved model when Agent Runner Model Defaults are set
- [ ] Falls back to built-in default when no profile default exists
- [ ] All new tests pass
- [ ] All existing tests still pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -x --timeout=120` -- all tests pass
- [ ] New profile tests are included in the test count
