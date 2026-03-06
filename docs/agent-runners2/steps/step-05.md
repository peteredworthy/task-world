# Step 5: Agents Concept (Backend + DB)

Introduce the new "Agent" concept -- a prompt template paired with a model profile. Three default agents are seeded (Planner, Builder, Verifier) with factory default prompts that support reset.

## Intent Verification
**Original Intent**: M5 from `docs/agent-runners2/plan.md` -- create Agent concept with DB model, CRUD API, and seeded defaults.
**Functionality to Produce**:
- `AgentConfigModel` DB table with Alembic migration
- CRUD API endpoints at `/api/agents`
- Prompt reset endpoint `POST /api/agents/{id}/reset-prompt`
- 3 default agents seeded: Planner (ARCHITECT), Builder (CODER), Verifier (CODER)
- Factory default prompts stored separately for reset capability
**Final Verification Criteria**:
- `GET /api/agents` returns 3 default agents after seed
- Full CRUD lifecycle works via API
- Prompt reset restores factory default
- All existing tests continue to pass

---

## Task 1: Create AgentConfig DB Model and Migration

**Description**: Create the `AgentConfigModel` SQLAlchemy model and Alembic migration for the `agent_configs` table.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/agents/` directory (new, for agent concept -- not the old runners directory)
- [ ] Create `src/orchestrator/agents/__init__.py`
- [ ] Create `src/orchestrator/agents/models.py` with `AgentConfigModel`:
  - `id`: UUID primary key
  - `name`: string, unique
  - `system_prompt`: text (user-editable)
  - `default_prompt`: text (factory default, immutable after seed)
  - `model_profile`: enum (`ModelProfile`)
  - `created_at`: datetime
  - `updated_at`: datetime
- [ ] Create Alembic migration for `agent_configs` table

**Dependencies**
- [ ] Step 01 must be complete (AgentRunner naming frees "Agent" namespace)
- [ ] Step 03 must be complete (`ModelProfile` enum exists)

**References**
- `docs/agent-runners2/step-05-plan.md` -- Tasks 1, 2
- `docs/agent-runners2/architecture.md` -- `agent_configs` table schema

**Constraints**
- Use Alembic migration (no DB recreation)
- `name` must have unique constraint

**Functionality (Expected Outcomes)**
- [ ] `AgentConfigModel` is importable
- [ ] Migration creates the table

**Final Verification (Proof of Completion)**
- [ ] `alembic upgrade head` succeeds
- [ ] Table has all required columns

---

## Task 2: Create Schemas and CRUD Service

**Description**: Create Pydantic schemas and CRUD service for agents.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/agents/schemas.py` with:
  - `AgentSchema` (id, name, system_prompt, model_profile, created_at, updated_at)
  - `CreateAgentRequest` (name, system_prompt, model_profile)
  - `UpdateAgentRequest` (name?, system_prompt?, model_profile?)
- [ ] Create `src/orchestrator/agents/service.py` with CRUD logic:
  - `list_agents()` -- return all agents
  - `get_agent(id)` -- return single agent or raise 404
  - `create_agent(data)` -- create with duplicate name check (409)
  - `update_agent(id, data)` -- update fields
  - `delete_agent(id)` -- delete agent
  - `reset_prompt(id)` -- restore system_prompt from default_prompt (400 if no default)

**Dependencies**
- [ ] Task 1 must be complete (DB model exists)

**References**
- `docs/agent-runners2/step-05-plan.md` -- Tasks 3, 4
- `docs/agent-runners2/architecture.md` -- API schemas

**Constraints**
- Duplicate name on create -> 409 Conflict
- Reset prompt on custom agent with no default_prompt -> 400 Bad Request

**Functionality (Expected Outcomes)**
- [ ] Full CRUD operations work
- [ ] Prompt reset restores factory default

**Final Verification (Proof of Completion)**
- [ ] Service methods work with in-memory or test DB
- [ ] Error cases handled correctly

---

## Task 3: Create API Router and Seed Defaults

**Description**: Create the API router for agent CRUD endpoints and seed 3 default agents.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/api/routers/agents.py` with endpoints:
  - `GET /api/agents` -- list all agents
  - `POST /api/agents` -- create agent
  - `GET /api/agents/{id}` -- get agent detail
  - `PUT /api/agents/{id}` -- update agent
  - `DELETE /api/agents/{id}` -- delete agent
  - `POST /api/agents/{id}/reset-prompt` -- reset to factory default
- [ ] Register router in `app.py`
- [ ] Update seed script to create 3 default agents:
  - Planner: ARCHITECT profile, planning system prompt
  - Builder: CODER profile, building system prompt
  - Verifier: CODER profile, verification system prompt
- [ ] Store factory default prompts in `default_prompt` column

**Dependencies**
- [ ] Task 2 must be complete (service exists)

**References**
- `docs/agent-runners2/step-05-plan.md` -- Tasks 5, 6, 7
- `docs/agent-runners2/architecture.md` -- API endpoints table
- Clarification Q1: Planner is user-assignable only, no engine integration
- Clarification Q7: Store factory defaults and allow reset

**Constraints**
- Planner has no special engine integration -- it's just another agent
- Follow existing router patterns in the codebase

**Functionality (Expected Outcomes)**
- [ ] All 6 API endpoints work
- [ ] Seed script creates 3 default agents
- [ ] Factory default prompts stored for reset

**Final Verification (Proof of Completion)**
- [ ] `GET /api/agents` returns 3 agents after seed
- [ ] `POST /api/agents/{id}/reset-prompt` works for seeded agents

---

## Task 4: Write Tests for Agent CRUD

**Description**: Write unit and integration tests for agent CRUD service and API endpoints.

**Implementation Plan (Do These Steps)**
- [ ] Unit tests: create, read, update, delete agent via service
- [ ] Unit tests: prompt reset restores `default_prompt` to `system_prompt`
- [ ] Unit tests: duplicate name creation fails with appropriate error
- [ ] Integration tests: `GET /api/agents` returns default agents after seed
- [ ] Integration tests: full CRUD lifecycle via API
- [ ] Integration tests: `POST /api/agents/{id}/reset-prompt` works
- [ ] Verify all existing tests continue to pass

**Dependencies**
- [ ] Task 3 must be complete (API and seed exist)

**References**
- `docs/agent-runners2/step-05-plan.md` -- Tasks 8, 9

**Functionality (Expected Outcomes)**
- [ ] All new tests pass
- [ ] All existing tests continue to pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/` passes with no new failures
- [ ] New agent tests exist and pass
