# Step Plan: Codex Server Phase Filtering + Context Filtering + MCP Wiring

## Purpose

Fix Codex Server's phase filtering (builders currently see the `grade` tool) and add step-level tool filtering and external MCP wiring. Codex Server uses `dynamicTools` for both orchestrator callback tools and external MCP configuration, providing per-thread control. This is **Priority 2**.

## Prerequisites

- **Step 1** complete: `MCPServerConfig` model and `StepConfig` extension exist.
- **Step 2** complete: `ExecutionContext` carries `available_tools` and `mcp_servers`.

## Functional Contract

### Inputs

- `ExecutionContext.available_tools: list[str] | None` — step-level tools to add
- `ExecutionContext.mcp_servers: list[MCPServerConfig] | None` — external MCP servers
- `is_verifier: bool` — phase role indicator for `build_dynamic_tool_specs()`

### Outputs

- **Phase filtering fix:** `build_dynamic_tool_specs()` accepts `is_verifier` parameter. Builders do not see `grade`/`set_grade` tool; verifiers get all tools including `grade`.
- **Step-level tool filtering (additive):** `build_dynamic_tool_specs()` accepts `context` parameter. When `available_tools` is set, step-level tools are added to the phase-filtered tool set.
- **MCP wiring:** External MCP server configs are included in `dynamicTools` during thread creation (`thread/start`). No `config.toml` changes.
- When `available_tools` and `mcp_servers` are `None`, behavior matches current (all phase-appropriate tools).

### Error Cases

- Unknown tool name in `available_tools` → log warning, skip, continue
- MCP server connection failure → deferred to Codex Server's error handling
- Empty `available_tools` list (`[]`) → only phase tools included

## Tasks

1. Add `is_verifier` parameter to `build_dynamic_tool_specs()` in `src/orchestrator/agents/codex_server_common.py`
2. Update `build_dynamic_tool_specs()` to exclude `grade`/`set_grade` from builder tool specs
3. Extend `build_dynamic_tool_specs()` to accept `context` and add step-level tools from `available_tools`
4. Wire `mcp_servers` config into `dynamicTools` payload during thread creation in `src/orchestrator/agents/codex_server.py`
5. Write unit tests for phase filtering and step-level additive filtering

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_codex_server_tool_filtering.py`:
  - `is_verifier=False` → `grade` tool NOT in tool specs (phase fix)
  - `is_verifier=True` → `grade` tool IS in tool specs
  - `available_tools=None` → all standard phase tools (backward compat)
  - `available_tools=["terminal"]` → terminal added to phase tools
  - `available_tools=["nonexistent"]` → warning logged, tool skipped
  - MCP config appears in `dynamicTools` payload
  - `mcp_servers=None` → no MCP entries in `dynamicTools`
- All existing Codex Server tests pass

### Manual Verification

- Verify `dynamicTools` JSON format matches Codex Server API expectations
- Confirm thread creation payload includes both orchestrator tools and MCP configs
- Test that `grade` tool is correctly excluded for builder threads

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — Codex Server row in agent table
- Current Codex Server: `src/orchestrator/agents/codex_server_common.py`, `src/orchestrator/agents/codex_server.py`
- Current issue: `build_dynamic_tool_specs()` returns all 5 tools unconditionally (no phase filtering)
- Key decision: `dynamicTools` only for MCP (no config.toml) — per-thread control
- Clarification Q7: dynamicTools only confirmed
