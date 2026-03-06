# Intent: Agent-Runners, Model Profiles, and Agents Refactor

## Goal

Rename the current "agents" concept to "agent-runners" throughout the backend and UI, then introduce two new concepts:

1. **Model Profiles** (Architect, Designer, Coder, Summarizer) -- per-runner configuration that maps each profile to a specific model, enabling different model strengths for different cognitive tasks.
2. **Agents** (Planner, Builder, Verifier) -- a prompt paired with a model profile. Agents are assigned to routine roles (planner, builder, verifier) at the routine, step, or task level with cascading defaults.

## Scope

### In Scope

- **Rename "agents" to "agent-runners"** across backend (enums, models, schemas, routers, endpoints, DB columns/tables), frontend (pages, components, types, routes, labels), and documentation. Use `rope` or equivalent programmatic refactoring tools -- do NOT manually rewrite files.
- **Model Profiles** -- new backend model and API. Four initial profiles: Architect, Designer, Coder, Summarizer. Each agent-runner stores a default model for each profile. UI page for configuring profile-to-model mappings per runner.
- **Agents** -- new backend model and API. Three initial agents: Planner, Builder, Verifier. Each agent has a name, editable system prompt, and an associated model profile. New UI section for managing agents (CRUD, prompt editing, profile selection).
- **Routine schema update** -- add optional `planner_agent`, `builder_agent`, `verifier_agent` fields at routine, step, and task levels. Task-level overrides step-level, step-level overrides routine-level.
- **UI updates** -- rename all "Agents" labels to "Agent Runners", add new "Agents" section for prompt/profile management, add model profile configuration on each runner card.
- **Non-breaking execution** -- at every milestone, running a routine must still work end-to-end. The system must remain functional after each incremental change.

### Out of Scope

- Automatic agent selection based on task content (future).
- Model profile cost optimization or routing logic.
- Migration of existing routine YAML files (they continue to work with defaults).
- Changes to the Agent Protocol interface or execution flow beyond renaming.

## Completion Criteria

1. All backend references to "agent" (in the runner sense) are renamed to "agent-runner" -- API endpoints, enums, DB schema, config models, variable names.
2. All frontend references updated -- page titles, routes, component names, labels, types.
3. Model profiles exist as a first-class concept: API CRUD, DB storage, per-runner defaults configurable via UI.
4. Agents (Planner, Builder, Verifier) exist as a first-class concept: API CRUD, DB storage, prompt editing and model profile association via UI.
5. Routine YAML schema accepts `planner_agent`, `builder_agent`, `verifier_agent` at routine/step/task level with proper cascading.
6. All existing tests pass (with updated references).
7. A routine can be created, started, and run to completion at every milestone.
8. No orphaned references to the old "agent" naming in the runner context.

## Key Unknowns and Risks

| Unknown | Risk | Mitigation |
|---------|------|------------|
| `rope` may not handle all renames (templates, YAML, SQL) | Incomplete rename leaves broken references | Run rope for Python, use `sed`/`find-replace` for non-Python files, grep-verify after each pass |
| DB migration for column/table renames | Data loss or migration failures on existing DBs | Use Alembic migration; for dev, allow DB recreation |
| Frontend route changes break bookmarks/links | Users hit 404s | Add redirects from old routes during transition |
| Agent-runner vs Agent naming confusion | Developers/users conflate the two concepts | Clear naming convention: "runner" = execution environment, "agent" = prompt + profile |
| Routine schema backward compatibility | Existing routines break after schema change | New fields are optional with sensible defaults; old routines work unchanged |
| Running on non-default ports for testing | Port conflicts with production orchestrator | Explicitly configure alternative ports (e.g., 8001/5174) in dev scripts |
