# Step Plan: OpenHands Tool Filtering + MCP Wiring

## Purpose

Enable the OpenHands agent to respect step-level `available_tools` for built-in tool selection and wire external MCP servers via OpenHands' native `mcp_config` parameter. OpenHands supports stdio, SSE, and Streamable HTTP transports via FastMCP. This is **Priority 3**.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model and `StepConfig` extension exist.
- **Step 2** complete: `ExecutionContext` carries `available_tools` and `mcp_servers`.
- Research into OpenHands SDK MCP support (clarification Q3: "I expect you to research this").

## Functional Contract

### Inputs

- `ExecutionContext.available_tools: list[str] | None` — step-level tools to add at `Agent()` construction
- `ExecutionContext.mcp_servers: list[MCPServerConfig] | None` — external MCP servers

### Outputs

- **Tool filtering (additive):** When `available_tools` is set, step-level tools are added to the default tools (`terminal`, `file_editor`) at `Agent()` construction. Phase role tools (orchestrator callbacks) are always included.
- **MCP wiring:** `MCPServerConfig` list converted to OpenHands `mcp_config` dict format:
  ```json
  {"mcpServers": {"server_name": {"url": "...", "command": "...", "args": [...]}}}
  ```
  Passed to `Agent()` constructor. Supports stdio, SSE, and Streamable HTTP transports natively via FastMCP.
- When both fields are `None`, behavior is unchanged (backward compatible with default tools).

### Error Cases

- Unknown tool name in `available_tools` → log warning, skip, continue with known tools
- MCP connection failure → deferred to OpenHands agent / FastMCP error handling
- `mcp_config` parameter not supported by installed OpenHands version → log error, skip MCP wiring
- Empty `available_tools` list (`[]`) → only default tools included

## Tasks

1. Research OpenHands SDK `Agent()` constructor for `mcp_config` parameter support (per clarification Q3)
2. Update `src/orchestrator/agents/openhands.py` to add step-level tools from `context.available_tools` at `Agent()` construction
3. Implement `MCPServerConfig` → OpenHands `mcp_config` dict conversion
4. Pass converted `mcp_config` to `Agent()` constructor when `mcp_servers` is set
5. Add graceful fallback if `mcp_config` parameter is not supported
6. Write unit tests for tool filtering and MCP config passthrough

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_openhands_tool_filtering.py`:
  - `available_tools=None` → default tools (`terminal`, `file_editor`) used (backward compat)
  - `available_tools=["browser"]` → `browser` added to default tools
  - `available_tools=["nonexistent"]` → warning logged, tool skipped
  - `mcp_servers` → `mcp_config` dict correctly formatted for OpenHands
  - `mcp_servers=None` → no `mcp_config` passed
  - STDIO transport (`command`) → correct format in `mcp_config`
  - HTTP transport (`url`) → correct format in `mcp_config`
- All existing OpenHands tests pass

### Manual Verification

- Verify `mcp_config` dict format matches OpenHands SDK expectations (research-dependent)
- Confirm FastMCP transport detection works for both URL and command-based configs
- Review graceful degradation when OpenHands version doesn't support `mcp_config`

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — OpenHands row in agent table
- Current OpenHands agent: `src/orchestrator/agents/openhands.py`
- Current tools: `DEFAULT_OPENHANDS_TOOLS = ["terminal", "file_editor"]`
- Current issue: `_register_sdk_tools()` has boolean guard preventing re-registration
- Key decision: Native `mcp_config` parameter on `Agent()` constructor
- Clarification Q3: Research OpenHands MCP support is implementer's responsibility
- Clarification Q4: MCP failures deferred to agents
