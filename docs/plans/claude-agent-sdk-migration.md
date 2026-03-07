# Plan: Migrate Claude SDK Runner to Claude Agent SDK

## Goal

Replace the hand-rolled agentic loop in `src/orchestrator/runners/claude_sdk.py` (which uses the raw `anthropic` Messages API) with the **Claude Agent SDK** (`claude-agent-sdk` package). This gives the runner access to built-in tools (Read, Write, Edit, Bash, Glob, Grep, WebSearch, etc.) while keeping the orchestrator callback tools (update_checklist, grade, submit, request_clarification) as custom MCP tools via `create_sdk_mcp_server`.

## Current State

- `claude_sdk.py` (~860 lines) implements its own agentic loop using `client.messages.create()` with tool_use
- Tool schemas are raw dicts (`_BUILDER_TOOLS`, `_VERIFIER_TOOLS`)
- Tool dispatch is manual via `_dispatch_tool()`
- MCP servers are wired via the beta `mcp-client-2025-11-20` API
- 84 tests pass across 3 test files

## Architecture After Migration

```
ClaudeSDKAgent.execute()
    ↓
claude_agent_sdk.query(prompt, options=ClaudeAgentOptions(
    model=...,
    allowed_tools=[...],        # Built-in tools: Read, Edit, Bash, etc.
    mcp_servers={
        "orchestrator": sdk_mcp_server,  # Custom callback tools
        "ctx7": {url: "..."},            # External MCP servers from config
    },
    permission_mode="bypassPermissions",
))
    ↓
async for message in query(...):
    - StreamEvent → on_output callback
    - AssistantMessage → collect output lines
    - ResultMessage → extract metrics (total_cost_usd, usage, num_turns)
```

### Key Design Decisions

1. **Custom tools via in-process MCP server**: Use `@tool` decorator + `create_sdk_mcp_server` to define orchestrator callbacks (update_checklist, grade, submit, request_clarification). These become `mcp__orchestrator__update_checklist` etc.
2. **Built-in tools enabled by default**: The Agent SDK provides Read, Write, Edit, Bash, Glob, Grep out of the box. These give the agent real coding capabilities.
3. **Permission mode**: Use `bypassPermissions` since the orchestrator is the trusted caller.
4. **Cancellation**: Use the `interrupt()` method on the query object.
5. **Token metrics**: Extract from `ResultMessage.usage` and `ResultMessage.total_cost_usd`.
6. **MCP servers from config**: External MCP servers (from `context.mcp_servers`) are passed as stdio/URL entries in `ClaudeAgentOptions.mcp_servers`.
7. **Fake client injection**: Replace `_client` injection with a `_query_fn` injection that replaces the `query()` call for testing.

## Tasks

### Task 1: Install claude-agent-sdk package
- `uv add claude-agent-sdk`
- Verify import works

### Task 2: Rewrite `claude_sdk.py` core
- Replace the manual agentic loop with `query()` from claude_agent_sdk
- Define orchestrator callback tools using `@tool` + `create_sdk_mcp_server`
- Keep the same public API: `ClaudeSDKAgent` class with `execute()`, `cancel()`, `get_quota()`, `info`
- Keep credential resolution logic (API key, auth token, keychain)
- Keep `build_claude_sdk_prompt()` (used by prompt endpoint)
- Keep `fetch_claude_models()` (used by detector)
- Keep `_build_mcp_params()` adapted for Agent SDK format
- Replace `_client` test injection with `_query_fn` callable injection
- Remove: `_BUILDER_TOOLS`, `_VERIFIER_TOOLS` raw dicts, `_dispatch_tool()`, `_build_tool_list()`, manual loop

### Task 3: Update detector.py
- Update `_detect_claude_sdk()` to check for `claude_agent_sdk` import instead of (or in addition to) `anthropic`
- Update description text
- Update install hint

### Task 4: Update executor.py
- Update the `CLAUDE_SDK` branch in `_create_agent()` if constructor args changed
- Verify `max_tokens` and `max_iterations` are still passed through

### Task 5: Rewrite unit tests (`test_claude_sdk_agent.py`)
- Replace fake Anthropic client stubs with `_query_fn` injection stubs
- Fake `query()` returns async iterables of the SDK message types
- Test the same behaviors: builder flow, verifier flow, cancellation, error mapping, credential resolution, prompt building
- Remove tests for deleted internals (`_dispatch_tool`, `_BUILDER_TOOLS`, `_VERIFIER_TOOLS`, `_build_tool_list`)

### Task 6: Rewrite tool filtering tests (`test_claude_sdk_tool_filtering.py`)
- Remove `from unittest.mock import patch` (violates project rules)
- MCP params tests: adapt for new MCP server format (Agent SDK uses dict config, not beta API params)
- Tool filtering tests may be removed if `_build_tool_list` is removed, or adapted to test `allowed_tools` construction

### Task 7: Rewrite integration tests (`test_claude_sdk_agent.py`)
- Replace fake Anthropic client stubs with `_query_fn` injection
- Keep the same test scenarios: builder→VERIFYING, verifier→COMPLETED, full lifecycle, token metrics, auto-submit

### Task 8: Fix pre-existing issues
- Remove `from unittest.mock import patch` in `test_claude_sdk_tool_filtering.py` and `test_clarification_workflow.py`
- Fix any ruff/pyright/eslint issues

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `claude-agent-sdk` dependency |
| `src/orchestrator/runners/claude_sdk.py` | Major rewrite |
| `src/orchestrator/runners/detector.py` | Update SDK detection |
| `src/orchestrator/runners/executor.py` | Minor constructor arg updates |
| `tests/unit/test_claude_sdk_agent.py` | Full rewrite of stubs |
| `tests/unit/test_claude_sdk_tool_filtering.py` | Adapt or replace |
| `tests/integration/test_claude_sdk_agent.py` | Full rewrite of stubs |

## Risks

1. **Agent SDK not yet in uv lockfile**: Need to install and verify compatibility
2. **Test injection pattern change**: Moving from `_client` to `_query_fn` changes how tests stub behavior
3. **Tool naming**: Agent SDK names custom MCP tools as `mcp__<server>__<tool>`. The prompt must reference these names.
4. **Backward compatibility**: `ClaudeSdkAgent` alias must be preserved
5. **`_SDK_AVAILABLE` guard**: Must check for `claude_agent_sdk` not just `anthropic`
