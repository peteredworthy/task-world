# Step Plan: Claude SDK Tool Filtering + MCP Wiring

## Purpose

Enable the Claude SDK agent to respect step-level `available_tools` by additively filtering its tool list, and to wire external MCP servers via the MCP Connector beta API. This is **Priority 1** alongside CLI.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model and `StepConfig` extension exist.
- **Step 2** complete: `ExecutionContext` carries `available_tools` and `mcp_servers`.

## Functional Contract

### Inputs

- `ExecutionContext.available_tools: list[str] | None` — step-level tools to add to phase tools
- `ExecutionContext.mcp_servers: list[MCPServerConfig] | None` — external MCP servers for this step

### Outputs

- **Tool filtering (additive):** When `available_tools` is set, step-level tools are added to the phase-determined tool list before passing to the Messages API. Phase tools (submit, grade, update_checklist, etc.) are always determined by role. When `available_tools` is `None`, all standard tools are included (backward compatible).
- **MCP wiring:** When `mcp_servers` is set, the agent uses `client.beta.messages.create()` with:
  - `mcp_servers` parameter containing server configs
  - `mcp_toolset` in tools list
  - Beta header `mcp-client-2025-11-20`
  - Only remote HTTPS servers supported via this path
- When both fields are `None`, behavior is unchanged (backward compatible)

### Error Cases

- Unknown tool name in `available_tools` → log warning, skip that tool, continue with known tools
- MCP connection failure → deferred to Anthropic API / agent error handling (no orchestrator-level handling)
- `MCPServerConfig` with `command` (STDIO) transport → not supported by MCP Connector beta; log warning and skip
- Empty `available_tools` list (`[]`) → only phase tools included (no step additions)

## Tasks

1. Update Claude SDK agent tool construction in `src/orchestrator/agents/claude_sdk.py` to accept `context.available_tools` and add step-level tools additively to phase tools
2. Add unknown tool name detection: log warning for tools not in the known tool registry
3. Implement MCP Connector beta wiring: convert `MCPServerConfig` list to the format expected by `client.beta.messages.create()`
4. Add beta header `mcp-client-2025-11-20` when MCP servers are configured
5. Filter out STDIO-transport MCP configs (only HTTPS URLs supported) with a warning
6. Write unit tests for tool filtering (additive semantics) and MCP passthrough

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_claude_sdk_tool_filtering.py`:
  - `available_tools=None` → all standard phase tools included (backward compat)
  - `available_tools=["terminal"]` → terminal added to phase tools
  - Phase filtering works: builders don't get `grade`, verifiers get `grade`
  - `available_tools=["nonexistent"]` → warning logged, tool skipped
  - `mcp_servers` with HTTPS URL → config passed to beta API call
  - `mcp_servers` with STDIO `command` → warning logged, server skipped
  - `mcp_servers=None` → no beta API parameters added
- All existing Claude SDK agent tests pass

### Manual Verification

- Verify MCP Connector beta API format matches current Anthropic SDK documentation
- Confirm beta header is correctly applied only when MCP servers are present
- Review that step tools are truly additive (don't replace phase tools)

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — Claude SDK agent row in agent table
- Current Claude SDK agent: `src/orchestrator/agents/claude_sdk.py`
- Key decision: MCP Connector beta with `mcp-client-2025-11-20` header, remote HTTPS only
- Key decision: Step tools are additive to phase tools, never restrictive
- Clarification Q2: Discovering Claude API MCP support is part of implementation
- Clarification Q4: MCP failures deferred to agents
- Clarification Q6: Claude SDK is Priority 1
