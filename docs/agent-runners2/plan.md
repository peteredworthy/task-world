# Plan: Agent-Runners, Model Profiles, and Agents Refactor

## Milestones

Each milestone ends with a working system where routines can be run.

### M1: Rename "Agents" to "Agent Runners" (Backend)

Programmatic rename of all backend Python references using `rope` for Python files + manual find-replace for non-Python files (YAML, docs, SQL).

**Naming convention**: Use prefixed names -- `AgentRunnerType`, `AgentRunner` protocol, `AgentRunnerExecutor`, `AgentRunnerInfo`, etc. -- to avoid confusion with the new Agent concept.

**Steps:**
1. Use rope to rename `AgentType` -> `AgentRunnerType`, `Agent` protocol -> `AgentRunner`, `AgentInfo` -> `AgentRunnerInfo`, `AgentExecutor` -> `AgentRunnerExecutor`, etc. across `src/orchestrator/agents/` (rename directory to `runners/`).
2. Rename API router file `routers/agents.py` -> `routers/runners.py`, update endpoint paths `/api/agents` -> `/api/agent-runners`.
3. Rename schemas: `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, etc.
4. Rename DB model columns: `RunModel.agent_type` -> `runner_type`, `RunModel.agent_config` -> `runner_config`. Create Alembic migration.
5. Rename enums in `config/enums.py`.
6. Update all imports and references in `executor.py`, `engine.py`, `service.py`, `deps.py`, `app.py`.
7. Update routine config models (`config/models.py`) -- field names referencing agents.
8. Use manual find-replace for non-Python files (YAML, templates, docs). Grep-verify after each pass.
9. Run full test suite, fix failures.

**Verification:** All backend tests pass. `GET /api/agent-runners` returns runner list. A run can be created and started.

### M2: Rename "Agents" to "Agent Runners" (Frontend)

**Steps:**
1. Rename `ui/src/pages/Agents.tsx` -> `AgentRunners.tsx`, update route to `/agent-runners` in router.
2. Rename `ui/src/types/agents.ts` -> `agentRunners.ts`, update all type names (`AgentOption` -> `AgentRunnerOption`, etc.).
3. Rename components: `AgentCard` -> `AgentRunnerCard`, `AgentConfigForm` -> `AgentRunnerConfigForm`, `AgentIcon` -> `AgentRunnerIcon`, `AgentQuotaBadge` -> `AgentRunnerQuotaBadge`, `AgentGuidancePanel` -> `AgentRunnerGuidancePanel`.
4. Update `agentConfigUtils.ts` -> `agentRunnerConfigUtils.ts`, rename functions.
5. Update API call URLs from `/api/agents` to `/api/agent-runners`.
6. Update all UI labels: "Agents" -> "Agent Runners" in nav, headings, tooltips.
7. Update `CreateRunModal` and run-related components that reference agent type/config.
8. Run frontend tests, fix failures. TypeScript type-check clean.

**Verification:** Frontend builds, tests pass, UI displays "Agent Runners" everywhere. Can create a run via UI.

### M3: Model Profiles (Backend + DB)

**Steps:**
1. Define `ModelProfile` enum: `ARCHITECT`, `DESIGNER`, `CODER`, `SUMMARIZER`.
2. Create DB model `AgentRunnerModelProfileDefaultModel` (or JSON column on runner config) mapping profile -> model string per runner type.
3. Create API endpoints: `GET /api/model-profiles` (list profiles), `GET /api/agent-runners/{type}/model-profile-defaults` (get Agent Runner Model Defaults), `PUT /api/agent-runners/{type}/model-profile-defaults` (set defaults).
4. Add Alembic migration for new table/columns.
5. Wire Agent Runner Model Defaults into execution context -- when a runner starts, it receives the resolved model for the relevant profile.
6. Tests for profile CRUD and resolution.

**Verification:** API returns profiles, defaults can be set and retrieved. Runner execution uses profile-resolved model.

### M4: Model Profiles (Frontend)

**Steps:**
1. Add "Model Profiles" section to each Runner card -- 4 fields (Architect, Designer, Coder, Summarizer) each with model selector (combobox with allow_custom).
2. Wire save/load to new API endpoints (replace or supplement localStorage approach).
3. Display current profile-to-model mappings on runner cards.
4. Tests for profile UI components.

**Verification:** UI shows profile configuration on each runner. Saving profiles persists to backend. Frontend tests pass.

### M5: Agents Concept (Backend + DB)

**Steps:**
1. Create `AgentConfig` model: `id`, `name`, `system_prompt` (text), `default_prompt` (text, factory default), `model_profile` (FK to ModelProfile enum), `created_at`, `updated_at`.
2. Seed three default agents: Planner (ARCHITECT profile), Builder (CODER profile), Verifier (CODER profile). Store factory default prompts in `default_prompt` column.
3. Create API endpoints: `GET /api/agents` (list), `POST /api/agents` (create), `GET /api/agents/{id}` (detail), `PUT /api/agents/{id}` (update), `DELETE /api/agents/{id}` (delete), `POST /api/agents/{id}/reset-prompt` (reset to factory default).
4. Planner agent has no special engine integration and is not a routine role.
5. Add Alembic migration.
6. Tests for agent CRUD including prompt reset.

**Verification:** API CRUD for agents works. Default agents seeded.

### M6: Routine Schema Update

**Steps:**
1. Add optional fields to `RoutineConfig`: `builder_agent`, `verifier_agent` (agent name or ID).
2. Add same optional fields to `StepConfig` and `TaskConfig`.
3. Implement cascading resolution: task -> step -> routine -> system default.
4. Update prompt generation to use the resolved agent's system prompt.
5. Update routine validation (warn if referenced agent doesn't exist, don't block).
6. Tests for cascading resolution logic.

**Verification:** Routine with agent overrides at different levels resolves correctly. Routines without agent fields still work with defaults.

### M7: Agents UI

**Steps:**
1. Create new "Agents" page/section in UI with list of agents (Planner, Builder, Verifier + custom).
2. Agent card: name, model profile selector, system prompt editor (textarea or code editor).
3. CRUD operations wired to API.
4. Add agent selection to routine creation/editing (if applicable in UI).
5. Navigation update: sidebar shows both "Agent Runners" and "Agents".
6. Frontend tests.

**Verification:** UI allows creating, editing, deleting agents. Prompt editing works. Model profile association displayed. Frontend tests pass.

### M8: Integration Testing and Polish

**Steps:**
1. End-to-end test: create a routine with agent overrides, run it, verify correct prompts and models used.
2. Browser-based UI verification using Playwright MCP (run on non-default ports 8001/5174).
3. Fix any visual/UX issues found.
4. Verify all existing routines still run without modification.
5. Update documentation (AGENTS.md, architecture docs).

**Verification:** Full routine lifecycle works. UI is polished. All tests green. Docs updated.

## Implementation Order

```
M1 (backend rename) -> M2 (frontend rename) -> M3 (profiles backend) -> M4 (profiles UI)
                                                                              |
                                                                              v
                                                          M5 (agents backend) -> M6 (routine schema) -> M7 (agents UI) -> M8 (integration)
```

Each milestone is independently deployable and leaves the system in a working state.

## Testing Strategy Per Milestone

| Milestone | Backend Tests | Frontend Tests | Manual/Browser |
|-----------|--------------|----------------|----------------|
| M1 | All existing tests pass with renames | N/A | API smoke test |
| M2 | N/A | All frontend tests pass | Visual check |
| M3 | Profile CRUD + resolution unit/integration | N/A | API smoke test |
| M4 | N/A | Profile UI component tests | Visual check |
| M5 | Agent CRUD unit/integration | N/A | API smoke test |
| M6 | Cascading resolution unit tests | N/A | Routine run test |
| M7 | N/A | Agent UI component tests | Visual check |
| M8 | E2E lifecycle test | Full suite | Playwright MCP verification |

## Port Configuration for Testing

To avoid conflicting with the production orchestrator:
- Backend: `uvicorn scripts.serve:app --port 8001 --reload --reload-dir src --reload-dir scripts`
- Frontend: `VITE_API_PORT=8001 npx vite --port 5174` (update vite proxy target)
- Browser testing: Playwright MCP navigates to `http://localhost:5174`

## Risk Mitigations

- **Incremental commits**: Each milestone is committed separately. If a later milestone breaks, earlier ones are safe.
- **Rope limitations**: After rope renames, run `grep -r` to catch references in strings, comments, YAML, and templates that rope misses.
- **DB migration**: Use Alembic migrations exclusively (production-grade).
- **Backward compatibility**: All new routine fields are optional. Existing routines run unchanged.
