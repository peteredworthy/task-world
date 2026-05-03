# Step Plan: Routine Schema Update

## Purpose

Add optional agent assignment fields to the routine schema at routine, step, and task levels. Implement cascading resolution so task-level overrides step-level, step-level overrides routine-level, and routine-level overrides system defaults. Update prompt generation to use the resolved agent's system prompt.

## Prerequisites

- **Step 05 (M5)** must be complete: Agent concept exists with CRUD API and seeded defaults

## Functional Contract

### Inputs

- Routine YAML with optional fields: `builder_agent`, `verifier_agent` at routine, step, and task levels
- Agent name strings referencing agents in the `agent_configs` table
- Current phase (build/verify) to determine which agent role to resolve

### Outputs

- `RoutineConfig`, `StepConfig`, `TaskConfig` models extended with optional `builder_agent`, `verifier_agent` string fields
- `resolve_agent(phase, task_config, step_config, routine_config)` pure function implementing cascading resolution: task -> step -> routine -> system default
- Prompt generation updated: resolved agent's `system_prompt` concatenated with separator before task-specific prompt
- Routine validation: warn (log) if referenced agent name doesn't exist, but don't block routine loading

### Error Cases

- Agent name in YAML doesn't match any agent in DB -> warning logged, fall back to system default
- Routine with no agent fields -> uses system default agents (backward compatible)
- Phase has no matching agent role (e.g., "planning" phase doesn't exist) -> no-op for Planner in engine

## Tasks

1. Add optional `builder_agent`, `verifier_agent` fields to `RoutineConfig`, `StepConfig`, `TaskConfig` in `config/models.py`
2. Implement `resolve_agent()` pure function with cascading resolution logic
3. Update prompt generation in task prompt endpoint to prepend resolved agent's system prompt
4. Prompt composition: agent system prompt + `"\n\n---\n\n"` separator + task prompt
5. Add routine validation: warn if referenced agent doesn't exist
6. Write unit tests for cascading resolution (all override levels, fallback to default)
7. Write integration tests for prompt endpoint returning agent-prefixed prompts

## Verification Approach

### Auto-Verify

- Unit tests: `resolve_agent("build", task_with_override, step, routine)` returns task-level agent
- Unit tests: `resolve_agent("build", task_no_override, step_with_override, routine)` returns step-level agent
- Unit tests: `resolve_agent("build", task_no_override, step_no_override, routine_with_override)` returns routine-level agent
- Unit tests: `resolve_agent("build", no_overrides, no_overrides, no_overrides)` returns system default "Builder"
- Unit tests: `resolve_agent("verify", ...)` resolves `verifier_agent` field
- Integration tests: `GET /api/tasks/{id}/prompt` includes agent system prompt prefix
- Existing routines without agent fields still parse and run correctly
- All existing tests continue to pass

### Manual Verification

- Create a routine with `builder_agent: "Security-Aware Builder"` at step level
- Run the routine -- verify the prompt includes the custom agent's system prompt
- Run an old routine without agent fields -- verify default Builder prompt is used

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M6 specification
- Architecture: `docs/agent-runners2/architecture.md` -- routine YAML schema, resolution order
- Clarification Q6: Simple concatenation (agent prompt + separator + task prompt)
- Current config models: `src/orchestrator/config/models.py`
- Current prompt endpoint: `src/orchestrator/api/routers/tasks.py`
