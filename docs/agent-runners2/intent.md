# Intent: Agent-Runners, Model Profiles, and Agents Refactor

## Goal

Rename the current "agents" concept to "agent-runners" throughout the backend and UI, then introduce two new concepts:

1. **Model Profiles** (Architect, Designer, Coder, Summarizer) -- per-runner configuration that maps each profile to a specific model, enabling different model strengths for different cognitive tasks.
2. **Agents** (Planner, Builder, Verifier) -- a prompt paired with a model profile. Agents are assigned to routine roles (planner, builder, verifier) at the routine, step, or task level with cascading defaults.

## Scope

### In Scope

- **Rename "agents" to "agent-runners"** across backend (enums, models, schemas, routers, endpoints, DB columns/tables), frontend (pages, components, types, routes, labels), and documentation. Use `rope` for Python renames + manual find-replace for non-Python files (YAML, templates, docs).
- **Python naming convention**: Use prefixed names throughout -- `AgentRunner`, `AgentRunnerType`, `AgentRunnerExecutor` -- to avoid confusion with the new Agent concept.
- **Model Profiles** -- new backend model and API. Four initial profiles: Architect, Designer, Coder, Summarizer. Each agent-runner stores a default model for each profile. UI page for configuring profile-to-model mappings per runner.
- **Agents** -- new backend model and API. Three initial agents: Planner, Builder, Verifier. Each agent has a name, editable system prompt, and an associated model profile. Factory default prompts are stored separately so users can reset edited prompts to defaults. New UI section for managing agents (CRUD, prompt editing, profile selection, reset to defaults).
- **Planner agent** -- the Planner is a user-assignable agent with no special engine integration. There is no planning phase in the workflow engine; users can reference the Planner agent in routines but it has no automatic behavior.
- **Routine schema update** -- add optional `planner_agent`, `builder_agent`, `verifier_agent` fields at routine, step, and task levels. Task-level overrides step-level, step-level overrides routine-level.
- **Per-run model-profile overrides** -- when creating a run, users can override the model for each profile used in the routine (not just a single model override). This allows fine-grained control per run.
- **UI updates** -- rename all "Agents" labels to "Agent Runners", add new "Agents" section for prompt/profile management, add model profile configuration on each runner card. Frontend routes: `/agent-runners` for runners, `/agents` for the new agents concept.
- **Non-breaking execution** -- at every milestone, running a routine must still work end-to-end. The system must remain functional after each incremental change.
- **Database migrations** -- use Alembic migrations exclusively (production-grade). No DB recreation fallback.

### Out of Scope

- Automatic agent selection based on task content (future).
- Model profile cost optimization or routing logic.
- Migration of existing routine YAML files (they continue to work with defaults).
- Changes to the Agent Protocol interface or execution flow beyond renaming.

## Completion Criteria

1. All backend references to "agent" (in the runner sense) are renamed to "agent-runner" using prefixed names (`AgentRunnerType`, `AgentRunnerExecutor`, etc.) -- API endpoints, enums, DB schema, config models, variable names.
2. All frontend references updated -- page titles, routes (`/agent-runners`), component names, labels, types.
3. Model profiles exist as a first-class concept: API CRUD, DB storage, per-runner defaults configurable via UI. All 4 profiles included: Architect, Designer, Coder, Summarizer.
4. Agents (Planner, Builder, Verifier) exist as a first-class concept: API CRUD, DB storage, prompt editing, model profile association, and factory-default prompt reset via UI.
5. Planner agent is user-assignable only -- no special workflow engine integration.
6. Routine YAML schema accepts `planner_agent`, `builder_agent`, `verifier_agent` at routine/step/task level with proper cascading.
7. Per-run model-profile overrides allow users to customize models for each profile when creating a run.
8. All existing tests pass (with updated references).
9. A routine can be created, started, and run to completion at every milestone.
10. No orphaned references to the old "agent" naming in the runner context.
11. All schema changes use Alembic migrations.

## Key Unknowns and Risks

| Unknown | Risk | Mitigation |
|---------|------|------------|
| `rope` may not handle all renames (templates, YAML, SQL) | Incomplete rename leaves broken references | Use rope for Python, manual find-replace for non-Python files, grep-verify after each pass |
| DB migration for column/table renames | Data loss or migration failures on existing DBs | Use Alembic migrations exclusively |
| Frontend route changes break bookmarks/links | Users hit 404s | Add redirects from old routes during transition |
| Agent-runner vs Agent naming confusion | Developers/users conflate the two concepts | Clear naming convention: "runner" = execution environment, "agent" = prompt + profile |
| Routine schema backward compatibility | Existing routines break after schema change | New fields are optional with sensible defaults; old routines work unchanged |
| Running on non-default ports for testing | Port conflicts with production orchestrator | Explicitly configure alternative ports (e.g., 8001/5174) in dev scripts |
