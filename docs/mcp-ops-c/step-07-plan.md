# Step Plan: User-Managed MCP All-Tools + MCP Info in Prompt Response

## Purpose

Update the User-Managed MCP server to register all tools (removing phase-based filtering), and extend the prompt response / `CallbackInstructions` to include MCP server information. External agents using the prompt endpoint will see available MCP servers they can optionally connect to. This is **Priority 3**.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model and `StepConfig` extension exist.
- **Step 2** complete: `ExecutionContext` carries `available_tools` and `mcp_servers`.

## Functional Contract

### Inputs

- `ExecutionContext.mcp_servers: list[MCPServerConfig] | None` — external MCP servers for this step
- Current phase hardcoded to "building" in `mcp/server.py`

### Outputs

- **All-tools registration:** MCP server in `src/orchestrator/mcp/server.py` registers both builder and verifier tools at startup. Phase filtering is removed from `_register_tools()`. Runtime validation still rejects phase-inappropriate tool calls with clear error messages.
- **MCP info in prompt response:** `CallbackInstructions` schema in `src/orchestrator/api/schemas/tasks.py` extended with `mcp_servers` field containing step-level MCP server information.
- Prompt response endpoint in `src/orchestrator/api/routers/tasks.py` populates `mcp_servers` from execution context.
- When `mcp_servers` is `None`, no MCP info in callback instructions (backward compatible).

### Error Cases

- Phase-inappropriate tool call (e.g., builder calling `grade`) → runtime validation error with clear message (existing behavior, now for all tools)
- `mcp_servers` info included in response but external agent can't connect → deferred to external agent (not orchestrator's concern)
- Empty `mcp_servers` list (`[]`) → empty list in callback instructions

## Tasks

1. Update `_register_tools()` in `src/orchestrator/mcp/server.py` to register all tools (remove phase filter)
2. Add `mcp_servers` field to `CallbackInstructions` in `src/orchestrator/api/schemas/tasks.py`
3. Update prompt response endpoint in `src/orchestrator/api/routers/tasks.py` to include `mcp_servers` from context
4. Ensure runtime validation still prevents phase-inappropriate tool calls
5. Write unit tests for all-tools registration and prompt response schema

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_mcp_server_all_tools.py`:
  - MCP server exposes both builder tools (`submit`, `update_checklist`) and verifier tools (`set_grade`)
  - Runtime validation still rejects inappropriate calls (builder can't `grade`)
- Schema tests:
  - `CallbackInstructions` includes `mcp_servers` field (optional list)
  - Prompt response includes MCP server info when context has `mcp_servers`
  - Prompt response has no MCP info when context has `mcp_servers=None`
- All existing MCP server and prompt endpoint tests pass

### Manual Verification

- Verify MCP server tool list is complete (all orchestrator tools registered)
- Confirm runtime validation error messages are clear for phase violations
- Review prompt response JSON to ensure MCP info is well-structured for external agents

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — User-Managed row in agent table
- Current MCP server: `src/orchestrator/mcp/server.py` — phase hardcoded to "building"
- Current schemas: `src/orchestrator/api/schemas/tasks.py` — `CallbackInstructions`
- Current prompt endpoint: `src/orchestrator/api/routers/tasks.py`
- Key decision: Register all tools, rely on runtime validation (simpler than per-connection scoping)
- Key decision: MCP info in `CallbackInstructions` — no new endpoints needed
