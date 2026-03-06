# Intent: Agent-Runners, Model Profiles, and Agents Refactor

## Goal

Rename the current "agents" concept to "agent-runners" throughout the backend and UI, then introduce two new concepts: [S-01/T-01/R1, S-02/T-01/R1]

1. **Model Profiles** (Architect, Designer, Coder, Summarizer) -- per-runner configuration that maps each profile to a specific model, enabling different model strengths for different cognitive tasks. [S-03/T-01/R1, S-03/T-03/R1, S-04/T-02/R1]
2. **Agents** (Planner, Builder, Verifier) -- a prompt paired with a model profile. Agents are assigned to routine roles (planner, builder, verifier) at the routine, step, or task level with cascading defaults. [S-05/T-03/R2, S-06/T-02/R1]

## Scope

### In Scope

- **Rename "agents" to "agent-runners"** across backend (enums, models, schemas, routers, endpoints, DB columns/tables), frontend (pages, components, types, routes, labels), and documentation. Use `rope` for Python renames + manual find-replace for non-Python files (YAML, templates, docs). [S-01/T-01/R1, S-01/T-02/R1, S-01/T-03/R1, S-01/T-05/R1, S-02/T-01/R1, S-02/T-02/R1, S-02/T-03/R1]
- **Python naming convention**: Use prefixed names throughout -- `AgentRunner`, `AgentRunnerType`, `AgentRunnerExecutor` -- to avoid confusion with the new Agent concept. [S-01/T-01/R1, S-01/T-01/R2]
- **Model Profiles** -- new backend model and API. Four initial profiles: Architect, Designer, Coder, Summarizer. Each agent-runner stores a default model for each profile. UI page for configuring profile-to-model mappings per runner. [S-03/T-01/R1, S-03/T-02/R1, S-03/T-03/R1, S-03/T-03/R2, S-04/T-01/R1, S-04/T-02/R1, S-04/T-02/R2]
- **Agents** -- new backend model and API. Three initial agents: Planner, Builder, Verifier. Each agent has a name, editable system prompt, and an associated model profile. Factory default prompts are stored separately so users can reset edited prompts to defaults. New UI section for managing agents (CRUD, prompt editing, profile selection, reset to defaults). [S-05/T-01/R1, S-05/T-02/R1, S-05/T-02/R3, S-05/T-03/R1, S-05/T-03/R2, S-07/T-02/R1, S-07/T-02/R2, S-07/T-02/R3]
- **Planner agent** -- the Planner is a user-assignable agent with no special engine integration. There is no planning phase in the workflow engine; users can reference the Planner agent in routines but it has no automatic behavior. [S-05/T-03/R3]
- **Routine schema update** -- add optional `planner_agent`, `builder_agent`, `verifier_agent` fields at routine, step, and task levels. Task-level overrides step-level, step-level overrides routine-level. [S-06/T-01/R1, S-06/T-02/R1, S-06/T-02/R2]
- **Per-run model-profile overrides** -- when creating a run, users can override the model for each profile used in the routine (not just a single model override). This allows fine-grained control per run. [S-03/T-04/R1]
- **UI updates** -- rename all "Agents" labels to "Agent Runners", add new "Agents" section for prompt/profile management, add model profile configuration on each runner card. Frontend routes: `/agent-runners` for runners, `/agents` for the new agents concept. [S-02/T-03/R1, S-02/T-03/R3, S-07/T-03/R1, S-07/T-03/R2, S-04/T-02/R1]
- **Non-breaking execution** -- at every milestone, running a routine must still work end-to-end. The system must remain functional after each incremental change. [S-01/T-06/R1, S-01/T-06/R2, S-08/T-03/R1, S-08/T-03/R2]
- **Database migrations** -- use Alembic migrations exclusively (production-grade). No DB recreation fallback. [S-01/T-04/R1, S-01/T-04/R2, S-03/T-02/R1, S-05/T-01/R2]

### Out of Scope

- Automatic agent selection based on task content (future). [NO-REQ] Out of scope per intent.
- Model profile cost optimization or routing logic. [NO-REQ] Out of scope per intent.
- Migration of existing routine YAML files (they continue to work with defaults). [NO-REQ] Out of scope; backward compatibility covered by S-06/T-01/R2.
- Changes to the Agent Protocol interface or execution flow beyond renaming. [NO-REQ] Out of scope per intent.

## Completion Criteria

1. All backend references to "agent" (in the runner sense) are renamed to "agent-runner" using prefixed names (`AgentRunnerType`, `AgentRunnerExecutor`, etc.) -- API endpoints, enums, DB schema, config models, variable names. [S-01/T-01/R1, S-01/T-03/R1, S-01/T-04/R4, S-01/T-05/R1]
2. All frontend references updated -- page titles, routes (`/agent-runners`), component names, labels, types. [S-02/T-01/R1, S-02/T-02/R1, S-02/T-03/R1, S-02/T-03/R3]
3. Model profiles exist as a first-class concept: API CRUD, DB storage, per-runner defaults configurable via UI. All 4 profiles included: Architect, Designer, Coder, Summarizer. [S-03/T-01/R1, S-03/T-03/R1, S-03/T-03/R2, S-04/T-02/R1, S-04/T-02/R2]
4. Agents (Planner, Builder, Verifier) exist as a first-class concept: API CRUD, DB storage, prompt editing, model profile association, and factory-default prompt reset via UI. [S-05/T-02/R1, S-05/T-02/R3, S-05/T-03/R1, S-05/T-03/R2, S-07/T-02/R1, S-07/T-02/R2, S-07/T-02/R3]
5. Planner agent is user-assignable only -- no special workflow engine integration. [S-05/T-03/R3]
6. Routine YAML schema accepts `planner_agent`, `builder_agent`, `verifier_agent` at routine/step/task level with proper cascading. [S-06/T-01/R1, S-06/T-02/R1, S-06/T-02/R2]
7. Per-run model-profile overrides allow users to customize models for each profile when creating a run. [S-03/T-04/R1]
8. All existing tests pass (with updated references). [S-01/T-06/R1, S-01/T-06/R2, S-02/T-04/R1, S-08/T-03/R1, S-08/T-03/R2]
9. A routine can be created, started, and run to completion at every milestone. [S-08/T-01/R2, S-08/T-02/R3]
10. No orphaned references to the old "agent" naming in the runner context. [S-01/T-05/R1, S-01/T-06/R3, S-08/T-04/R2]
11. All schema changes use Alembic migrations. [S-01/T-04/R1, S-03/T-02/R1, S-05/T-01/R2]

## Key Unknowns and Risks

| Unknown | Risk | Mitigation |
|---------|------|------------|
| `rope` may not handle all renames (templates, YAML, SQL) | Incomplete rename leaves broken references | Use rope for Python, manual find-replace for non-Python files, grep-verify after each pass [S-01/T-01/R1, S-01/T-05/R1] |
| DB migration for column/table renames | Data loss or migration failures on existing DBs | Use Alembic migrations exclusively [S-01/T-04/R1, S-01/T-04/R3] |
| Frontend route changes break bookmarks/links | Users hit 404s | Add redirects from old routes during transition [S-02/T-03/R1] |
| Agent-runner vs Agent naming confusion | Developers/users conflate the two concepts | Clear naming convention: "runner" = execution environment, "agent" = prompt + profile [S-01/T-01/R1, S-05/T-01/R1] |
| Routine schema backward compatibility | Existing routines break after schema change | New fields are optional with sensible defaults; old routines work unchanged [S-06/T-01/R2, S-06/T-03/R2] |
| Running on non-default ports for testing | Port conflicts with production orchestrator | Explicitly configure alternative ports (e.g., 8001/5174) in dev scripts [S-08/T-02/R1] |
