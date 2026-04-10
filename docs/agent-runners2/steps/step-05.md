# Step 5: Agents Concept (Backend + DB)

Introduce the new "Agent" concept -- a prompt template paired with a model profile. Agents define *what* cognitive work to do (via prompt) and *how hard to think* (via profile). Three default agents are seeded: Planner, Builder, Verifier. Factory default prompts are stored separately so users can reset edits.

## Intent Verification
**Original Intent**: Create the Agent concept as a prompt+profile pairing, with 3 defaults and full CRUD (see `docs/agent-runners2/intent.md` -- "Agents" section).
**Functionality to Produce**:
- `AgentConfigModel` DB table: id, name, system_prompt, default_prompt, model_profile, timestamps
- API CRUD: list, create, get, update, delete agents + prompt reset
- 3 seeded default agents: Planner (ARCHITECT), Builder (CODER), Verifier (CODER)
- Factory default prompt storage and reset capability

**Final Verification Criteria**:
- `GET /api/agents` returns 3 default agents after seed
- Full CRUD lifecycle works via API
- `POST /api/agents/{id}/reset-prompt` restores factory default
- All existing tests continue to pass

---

## Task 1: Create AgentConfig DB Model and Migration

**Description**: Create the `AgentConfigModel` SQLAlchemy model and Alembic migration for the `agent_configs` table.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/agents/` directory (new, for the Agent concept)
- [ ] Create `src/orchestrator/agents/__init__.py`
- [ ] Create `src/orchestrator/agents/models.py` with `AgentConfigModel`:
  - `id`: UUID primary key
  - `name`: str, unique
  - `system_prompt`: text (user-editable)
  - `default_prompt`: text (factory default, set at seed time)
  - `model_profile`: ModelProfile enum
  - `created_at`: datetime
  - `updated_at`: datetime
- [ ] Generate Alembic migration: `uv run alembic revision --autogenerate -m "Add agent_configs table"`
- [ ] Verify migration: `uv run alembic upgrade head`

**Dependencies**
- [ ] Step 1 must be complete (AgentRunner naming in place, freeing "Agent" namespace)
- [ ] Step 3 must be complete (`ModelProfile` enum exists)

**References**
- `docs/agent-runners2/architecture.md` -- `agent_configs` table schema
- `docs/agent-runners2/plan.md` -- M5 steps 1-2
- Clarification Q7: Store factory defaults and allow reset

**Constraints**
- `name` must have a unique constraint
- `default_prompt` is immutable after seed (not enforced in DB, enforced in application logic)

**Functionality (Expected Outcomes)**
- [ ] `AgentConfigModel` is importable from `orchestrator.agents.models`
- [ ] `agent_configs` table created via migration
- [ ] Unique constraint on `name` column works

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` succeeds
- [ ] `uv run python -c "from orchestrator.agents.models import AgentConfigModel; print('OK')"` succeeds

---

## Task 2: Create Pydantic Schemas and CRUD Service

**Description**: Define Pydantic schemas for the Agent API and implement the CRUD service layer.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/agents/schemas.py` with:
  - `AgentSchema`: id, name, system_prompt, default_prompt, model_profile, created_at, updated_at
  - `CreateAgentRequest`: name, system_prompt, model_profile
  - `UpdateAgentRequest`: name (optional), system_prompt (optional), model_profile (optional)
- [ ] Create `src/orchestrator/agents/service.py` with CRUD functions:
  - `list_agents(db) -> list[AgentConfigModel]`
  - `get_agent(db, agent_id) -> AgentConfigModel | None`
  - `create_agent(db, data) -> AgentConfigModel` (409 on duplicate name)
  - `update_agent(db, agent_id, data) -> AgentConfigModel` (404 if not found)
  - `delete_agent(db, agent_id) -> None` (404 if not found)
  - `reset_prompt(db, agent_id) -> AgentConfigModel` (400 if no default_prompt)

**Dependencies**
- [ ] Task 1 must be complete (DB model exists)

**References**
- `docs/agent-runners2/architecture.md` -- API schemas section
- `docs/agent-runners2/plan.md` -- M5 steps 3-4

**Constraints**
- Follow existing service patterns in the codebase
- Prompt reset copies `default_prompt` to `system_prompt`; returns 400 if `default_prompt` is None

**Functionality (Expected Outcomes)**
- [ ] All CRUD operations work correctly
- [ ] Duplicate name creation returns appropriate error
- [ ] Prompt reset restores factory default

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.agents.service import list_agents; print('OK')"` succeeds
- [ ] `uv run python -c "from orchestrator.agents.schemas import AgentSchema; print('OK')"` succeeds

---

## Task 3: Create API Router and Seed Default Agents

**Description**: Create the API router with all CRUD endpoints and seed the 3 default agents.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/api/routers/agents.py` with endpoints:
  - `GET /api/agents` -- list all agents
  - `POST /api/agents` -- create agent (409 on duplicate name)
  - `GET /api/agents/{id}` -- get agent detail (404 if not found)
  - `PUT /api/agents/{id}` -- update agent (404 if not found)
  - `DELETE /api/agents/{id}` -- delete agent (404 if not found)
  - `POST /api/agents/{id}/reset-prompt` -- reset to factory default (400 if no default)
- [ ] Register the router in `app.py`
- [ ] Create or update seed script to seed 3 default agents:
  - Planner: profile=ARCHITECT, prompt for breaking down work into steps/tasks
  - Builder: profile=CODER, prompt for implementing requirements
  - Verifier: profile=CODER, prompt for grading work against requirements
- [ ] Each seeded agent has both `system_prompt` and `default_prompt` set to the same initial value

**Dependencies**
- [ ] Task 2 must be complete (service and schemas exist)

**References**
- `docs/agent-runners2/architecture.md` -- API endpoints table
- `docs/agent-runners2/plan.md` -- M5 steps 5-7
- Clarification Q1: Planner is user-assignable only, no engine integration

**Constraints**
- Note: `GET /api/agents` now returns the new Agent concept, not runners (runners are at `/api/agent-runners`)
- Planner has no special engine integration -- it's just data

**Functionality (Expected Outcomes)**
- [ ] All 6 API endpoints respond correctly
- [ ] After seed, `GET /api/agents` returns Planner, Builder, Verifier
- [ ] Full CRUD lifecycle works via API

**Final Verification (Proof of Completion)**
- [ ] `curl localhost:8000/api/agents` returns JSON array with 3 agents
- [ ] POST + GET + PUT + DELETE lifecycle works

---

## Task 4: Write Unit and Integration Tests

**Description**: Write tests for the Agent CRUD service and API endpoints, including prompt reset.

**Implementation Plan (Do These Steps)**
- [ ] Write unit tests for agent CRUD service:
  - Create, read, update, delete operations
  - Duplicate name creation fails
  - Prompt reset restores `default_prompt` to `system_prompt`
  - Prompt reset on agent without `default_prompt` returns error
- [ ] Write integration tests for API endpoints:
  - `GET /api/agents` returns seeded agents
  - Full CRUD lifecycle via HTTP
  - `POST /api/agents/{id}/reset-prompt` works for seeded agents
  - Error cases: 404 for unknown ID, 409 for duplicate name, 400 for reset without default
- [ ] Verify all existing tests still pass

**Dependencies**
- [ ] Task 3 must be complete (API and seed exist)

**References**
- `docs/agent-runners2/plan.md` -- M5 steps 8-9
- Existing test patterns in `tests/unit/` and `tests/integration/`

**Constraints**
- Follow existing test patterns in the codebase
- All existing tests must still pass

**Functionality (Expected Outcomes)**
- [ ] Agent CRUD unit tests cover all operations and error cases
- [ ] Agent API integration tests cover full lifecycle
- [ ] All tests pass (new + existing)

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -x --timeout=120` -- all tests pass
- [ ] New agent tests are in the test output
