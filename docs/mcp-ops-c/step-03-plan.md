# Step Plan: CLI Agent Tool Hints + MCP Info in Prompt

## Purpose

Enable the CLI agent to communicate step-level tool availability and external MCP server information to its subprocess. Since CLI agents operate as opaque subprocesses (e.g., Claude Code), tool control is text-based — the agent includes tool hints and MCP configuration in the enriched prompt. This is **Priority 1** alongside Claude SDK.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model and `StepConfig` extension exist.
- **Step 2** complete: `ExecutionContext` carries `available_tools` and `mcp_servers`.

## Functional Contract

### Inputs

- `ExecutionContext.available_tools: list[str] | None` — tool names to include as hints
- `ExecutionContext.mcp_servers: list[MCPServerConfig] | None` — external MCP servers

### Outputs

- Enriched prompt text includes a "Step Tools" section listing available tool names when `available_tools` is set
- Enriched prompt text includes MCP server connection info (names, URLs/commands) when `mcp_servers` is set
- Alternatively/additionally: `.mcp.json` file written to subprocess working directory for auto-discovery by Claude Code
- When both fields are `None`, prompt is unchanged (backward compatible)

### Error Cases

- `available_tools` contains unknown tool names → include them in the prompt as-is (CLI subprocess handles its own tools; log warning in orchestrator)
- `mcp_servers` with auth tokens → `auth_token_env` name included in `.mcp.json` or env vars passed to subprocess, never in prompt text
- Empty `available_tools` list (`[]`) → no tool hints section added

## Tasks

1. Update `CLIAgent.build_prompt()` in `src/orchestrator/agents/cli.py` to include step-level tool hints when `context.available_tools` is set
2. Update prompt builder to include MCP server info (URLs, names) when `context.mcp_servers` is set
3. Implement `.mcp.json` file generation in working directory for CLI subprocesses that support auto-discovery
4. Ensure auth tokens are passed via environment variables to subprocess, never in prompt text
5. Write unit tests for prompt content with and without tool hints and MCP info

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_cli_tool_hints.py`:
  - `available_tools=["terminal", "file_editor"]` → prompt contains tool names
  - `available_tools=None` → prompt unchanged from current behavior
  - `mcp_servers=[MCPServerConfig(name="ctx7", url="https://...")]` → prompt or `.mcp.json` includes MCP info
  - `mcp_servers=None` → no MCP section in prompt
  - Auth token env var names are NOT embedded in prompt text
  - Unknown tool name in `available_tools` → warning logged, name still in prompt
- All existing CLI agent tests pass

### Manual Verification

- Review prompt output format for readability when tools and MCPs are present
- Confirm `.mcp.json` format is valid for Claude Code auto-discovery (if applicable)

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — CLI agent row in agent table
- Current CLI agent: `src/orchestrator/agents/cli.py` (line 136 — phase-specific prompts)
- Key decision: CLI tool control is text hints in prompt (not enforced), since subprocess is opaque boundary
- Key decision: Auth tokens via env vars to subprocess, never in prompt
- Clarification Q6: CLI is Priority 1 alongside Claude SDK
