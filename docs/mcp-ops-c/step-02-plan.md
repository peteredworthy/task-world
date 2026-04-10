# Step Plan: ExecutionContext Extension + Executor Wiring

## Purpose

Extend `ExecutionContext` to carry step-level tool and MCP information, and update the executor to populate these fields from `StepConfig`. This connects the schema layer (Step 1) to the agent layer (Steps 3–7), enabling all agents to receive step-specific configuration.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model exists, `StepConfig` has `available_tools` and `mcp_servers` fields.

## Functional Contract

### Inputs

- `StepConfig` with optional `available_tools` and `mcp_servers` (from Step 1)
- Current step index from the active run

### Outputs

- `ExecutionContext` extended with:
  - `step_id: str | None = None` — current step identifier
  - `available_tools: list[str] | None = None` — step-level tool list
  - `mcp_servers: list[MCPServerConfig] | None = None` — step-level MCP servers
- Executor (`executor.py ~line 650`) populates these fields from the step config when creating context

### Error Cases

- `StepConfig` without new fields (existing routines) → context fields remain `None` (backward compatible)
- Missing step config at step index → handled by existing executor flow (not a new error case)

## Tasks

1. Add `step_id`, `available_tools`, and `mcp_servers` fields to `ExecutionContext` in `src/orchestrator/agents/types.py`
2. Update executor in `src/orchestrator/agents/executor.py` (~line 650) to read step config and populate new context fields
3. Update any existing tests that construct `ExecutionContext` to accommodate new optional fields
4. Write unit tests confirming context is populated from step config
5. Write unit test confirming context fields are `None` when step config has no tool/MCP fields

## Verification Approach

### Auto-Verify

- Unit tests:
  - `ExecutionContext` with `available_tools=["terminal"]` → field accessible
  - `ExecutionContext` with `mcp_servers=[MCPServerConfig(...)]` → field accessible
  - `ExecutionContext` without new fields → all default to `None`
  - Executor creates context with correct `step_id`, `available_tools`, `mcp_servers` from step config
  - Executor creates context with `None` fields when step config has no tool/MCP data
- All existing tests pass (backward compatible changes only)

### Manual Verification

- Trace data flow: step config → executor → context to confirm wiring is correct
- Confirm no eager MCP connections are made (config passed as data only)

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — ExecutionContext extension, Executor wiring
- Current ExecutionContext: `src/orchestrator/agents/types.py:52`
- Current executor context creation: `src/orchestrator/agents/executor.py:650`
- Data flow: YAML → StepConfig → Executor → ExecutionContext → Agent
