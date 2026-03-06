# Step 3: Model Profiles (Backend + DB)

Introduce Model Profiles as a first-class backend concept: an enum of cognitive work classes (ARCHITECT, DESIGNER, CODER, SUMMARIZER) with per-runner default model mappings stored in the database.

## Intent Verification
**Original Intent**: M3 from `docs/agent-runners2/plan.md` -- create Model Profiles with per-runner default mappings, API endpoints, and DB storage.
**Functionality to Produce**:
- `ModelProfile` enum with 4 values
- `RunnerProfileDefaultModel` DB table with Alembic migration
- API endpoints for listing profiles and managing per-runner defaults
- Profile resolution wired into execution context
**Final Verification Criteria**:
- `GET /api/model-profiles` returns 4 profiles
- `PUT` then `GET` profile defaults round-trips correctly
- All existing tests continue to pass
- New unit and integration tests pass

---

## Task 1: Define ModelProfile Enum and DB Model

**Description**: Add the `ModelProfile` enum to `config/enums.py` and create the `RunnerProfileDefaultModel` SQLAlchemy model in `db/models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add `ModelProfile` enum to `config/enums.py` with values: `ARCHITECT`, `DESIGNER`, `CODER`, `SUMMARIZER`
- [ ] Create `RunnerProfileDefaultModel` in `db/models.py`:
  - `id`: UUID primary key
  - `runner_type`: enum (`AgentRunnerType`)
  - `profile`: enum (`ModelProfile`)
  - `model`: string
  - `UNIQUE(runner_type, profile)` constraint
- [ ] Create Alembic migration for the new table

**Dependencies**
- [ ] Step 01 must be complete (`AgentRunnerType` enum exists)

**References**
- `docs/agent-runners2/step-03-plan.md` -- Tasks 1, 2, 3
- `docs/agent-runners2/architecture.md` -- `runner_profile_defaults` table schema
- Clarification Q8: Include all 4 profiles from the start

**Constraints**
- Use Alembic migration (no DB recreation)
- Enum values must match architecture spec exactly

**Functionality (Expected Outcomes)**
- [ ] `ModelProfile` enum is importable from `config/enums.py`
- [ ] `RunnerProfileDefaultModel` table is created by migration
- [ ] Unique constraint prevents duplicate (runner_type, profile) pairs

**Final Verification (Proof of Completion)**
- [ ] `alembic upgrade head` succeeds
- [ ] `ModelProfile` has exactly 4 members

---

## Task 2: Create Schemas and API Endpoints

**Description**: Create Pydantic schemas for model profiles and API endpoints for listing profiles and managing per-runner defaults.

**Implementation Plan (Do These Steps)**
- [ ] Create Pydantic schemas: `ModelProfileSchema` (name, description), `RunnerProfileDefaultsSchema` (runner_type, profiles dict)
- [ ] Create API router `routers/model_profiles.py` with `GET /api/model-profiles` endpoint
- [ ] Add profile endpoints to runners router:
  - `GET /api/agent-runners/{type}/profiles` -- get runner's profile-to-model defaults
  - `PUT /api/agent-runners/{type}/profiles` -- set runner's profile-to-model defaults
- [ ] Register new router in `app.py`
- [ ] Handle error cases: invalid runner type (422), invalid profile (422), no defaults (return empty dict)

**Dependencies**
- [ ] Task 1 must be complete (enum and DB model exist)

**References**
- `docs/agent-runners2/step-03-plan.md` -- Tasks 4, 5, 6
- `docs/agent-runners2/architecture.md` -- API schemas, new endpoints table

**Constraints**
- `GET /api/agent-runners/{type}/profiles` for runner with no defaults returns empty mapping, not 404
- Follow existing router patterns in the codebase

**Functionality (Expected Outcomes)**
- [ ] `GET /api/model-profiles` returns list of 4 profiles with descriptions
- [ ] Profile defaults can be saved and retrieved per runner type
- [ ] Validation errors returned for invalid input

**Final Verification (Proof of Completion)**
- [ ] `GET /api/model-profiles` returns 200 with 4 items
- [ ] Round-trip: PUT then GET returns saved defaults

---

## Task 3: Wire Profiles into Execution and Write Tests

**Description**: Wire profile defaults into the execution context so runners receive the resolved model, and write unit/integration tests.

**Implementation Plan (Do These Steps)**
- [ ] Update execution context to include profile-resolved model when a runner starts
- [ ] Resolution order: per-run profile overrides (future) -> runner's profile defaults -> runner's built-in default model
- [ ] Write unit tests for `ModelProfile` enum membership
- [ ] Write unit tests for profile-to-model resolution logic (default fallback, explicit override)
- [ ] Write integration tests for all 3 API endpoints
- [ ] Verify all existing tests continue to pass

**Dependencies**
- [ ] Task 2 must be complete (API endpoints exist)

**References**
- `docs/agent-runners2/step-03-plan.md` -- Tasks 7, 8, 9
- Clarification Q5: Per-run profile overrides (wired in later via run creation)

**Constraints**
- Per-run overrides are wired in a later step -- just establish the resolution chain here
- Don't break existing execution flow

**Functionality (Expected Outcomes)**
- [ ] Runner execution uses profile-resolved model when defaults are set
- [ ] Falls back to built-in default when no profile default configured
- [ ] All new tests pass
- [ ] All existing tests continue to pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/` passes with no new failures
- [ ] New profile tests exist and pass
