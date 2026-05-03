# Step Plan: Agents Concept (Backend + DB)

## Purpose

Introduce the new "Agent" concept -- a prompt template paired with a model profile. Agents define *what* cognitive work to do (via prompt) and *how hard to think* (via profile). Three default agents are seeded: Planner, Builder, Verifier. Factory default prompts are stored separately so users can reset edits.

## Prerequisites

- **Step 01 (M1)** must be complete: "AgentRunner" naming in place, freeing "Agent" namespace
- **Step 03 (M3)** must be complete: `ModelProfile` enum exists

## Functional Contract

### Inputs

- Agent creation: `name` (unique string), `system_prompt` (text), `model_profile` (ModelProfile enum value)
- Seed data: Planner (ARCHITECT), Builder (CODER), Verifier (CODER) with factory default prompts
- Agent update: modified `system_prompt`, `model_profile`, or `name`
- Prompt reset: restores `system_prompt` to `default_prompt` value

### Outputs

- `AgentConfigModel` DB table: `id` (UUID), `name` (unique), `system_prompt`, `default_prompt`, `model_profile`, `created_at`, `updated_at`
- Alembic migration creating the table
- Seed script creating 3 default agents with factory prompts
- API endpoints:
  - `GET /api/agents` -- list all agents
  - `POST /api/agents` -- create agent
  - `GET /api/agents/{id}` -- get agent detail
  - `PUT /api/agents/{id}` -- update agent
  - `DELETE /api/agents/{id}` -- delete agent
  - `POST /api/agents/{id}/reset-prompt` -- reset system prompt to factory default
- Pydantic schemas: `AgentSchema`, `CreateAgentRequest`, `UpdateAgentRequest`
- Agent CRUD service in `src/orchestrator/agents/service.py`

### Error Cases

- `POST /api/agents` with duplicate name -> 409 Conflict
- `GET /api/agents/{id}` with unknown ID -> 404 Not Found
- `DELETE /api/agents/{id}` for a default agent referenced by active runs -> 409 Conflict (or soft-delete)
- `POST /api/agents/{id}/reset-prompt` when `default_prompt` is None (custom agent) -> 400 Bad Request
- Invalid `model_profile` value -> 422 Validation Error

## Tasks

1. Create `AgentConfigModel` SQLAlchemy model in new `src/orchestrator/agents/models.py`
2. Create Alembic migration for `agent_configs` table
3. Create Pydantic schemas in `src/orchestrator/agents/schemas.py`
4. Implement CRUD service in `src/orchestrator/agents/service.py`
5. Create API router `src/orchestrator/api/routers/agents.py` with all endpoints
6. Seed 3 default agents (Planner, Builder, Verifier) with factory prompts
7. Planner agent has no special engine integration -- standalone only
8. Write unit tests for agent CRUD service
9. Write integration tests for API endpoints including prompt reset

## Verification Approach

### Auto-Verify

- Unit tests: create, read, update, delete agent
- Unit tests: prompt reset restores `default_prompt` to `system_prompt`
- Unit tests: duplicate name creation fails
- Integration tests: `GET /api/agents` returns 3 default agents after seed
- Integration tests: full CRUD lifecycle via API
- Integration tests: `POST /api/agents/{id}/reset-prompt` works for seeded agents
- All existing tests continue to pass

### Manual Verification

- `GET /api/agents` returns Planner, Builder, Verifier with correct profiles
- Update Builder's prompt, then reset -- prompt returns to factory default
- Create a custom agent "Security Reviewer" with ARCHITECT profile -- appears in list

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M5 specification
- Architecture: `docs/agent-runners2/architecture.md` -- `agent_configs` table schema, API endpoints
- Clarification Q1: Planner is standalone only, no engine integration
- Clarification Q7: Store factory defaults and allow reset
- File structure: `src/orchestrator/agents/` (new directory for agent concept)
