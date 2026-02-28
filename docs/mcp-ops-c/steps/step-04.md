# Step 4: Claude SDK Tool Filtering + MCP Wiring

Enable the Claude SDK agent to respect step-level `available_tools` by additively filtering its tool list, and wire external MCP servers via the MCP Connector beta API. This is **Priority 1** alongside CLI. The Claude SDK agent passes tools directly to the Anthropic Messages API, so filtering happens on the tool list before each API call.

## Intent Verification
**Original Intent**: Claude SDK agent filters tools based on `context.available_tools` and passes `mcp_servers` via beta MCP Connector (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullet 5).
**Functionality to Produce**:
- Additive tool filtering: step-level tools are added to phase tools before API call
- Phase tools (submit, grade, etc.) always determined by role
- MCP Connector beta wiring with `mcp_servers` parameter and `mcp-client-2025-11-20` header
- STDIO-transport MCPs filtered out with warning (only HTTPS supported)
- Unknown tool names produce a warning but don't fail
- Backward compatible when both fields are `None`

**Final Verification Criteria**:
- Unit tests for additive tool filtering pass
- Unit tests for MCP passthrough pass
- Phase filtering still works correctly
- All existing Claude SDK tests pass

---

## Task 1: Implement Additive Tool Filtering in Claude SDK Agent
**Description**:
Update the Claude SDK agent's tool construction to accept `context.available_tools` and add step-level tools additively to the phase-determined tool list. Phase tools (`_BUILDER_TOOLS`, `_VERIFIER_TOOLS`) remain the baseline; step tools expand the available set.

**Implementation Plan (Do These Steps)**
The current implementation (line ~563-584 in `claude_sdk.py`) selects tools based on `is_verifier`:
```python
tools = _VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS
```

- [ ] Create a helper function that builds the final tool list from phase tools + step tools:
```python
def _build_tool_list(
    is_verifier: bool,
    available_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build tool list: phase tools + additive step tools.

    Step-level available_tools adds to (never restricts) phase tools.
    Unknown tool names are logged as warnings and skipped.
    """
    base_tools = list(_VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS)

    if not available_tools:
        return base_tools

    # Collect names already in base tools
    existing_names = {t["name"] for t in base_tools}

    # Known additional tools that can be added via available_tools
    # (This registry can be expanded as new tools are supported)
    known_additional_tools: dict[str, dict[str, Any]] = {}

    for tool_name in available_tools:
        if tool_name in existing_names:
            continue  # Already in phase tools
        if tool_name in known_additional_tools:
            base_tools.append(known_additional_tools[tool_name])
        else:
            logger.warning(
                "Unknown tool '%s' in available_tools — skipping (not in Claude SDK tool registry)",
                tool_name,
            )

    return base_tools
```
- [ ] Update the tool selection in the execute method to use this helper:
```python
tools = _build_tool_list(is_verifier, context.available_tools)
```

**Dependencies**
- [ ] Step 2 complete: `ExecutionContext` carries `available_tools`

**References**
- Current Claude SDK agent: `src/orchestrator/agents/claude_sdk.py` (lines 172-292 for tool defs, lines 563-584 for tool selection)
- Key decision: Step tools are additive to phase tools, never restrictive
- Architecture: `docs/mcp-ops-c/architecture.md` — Claude SDK row

**Constraints**
- Do not modify `_BUILDER_TOOLS` or `_VERIFIER_TOOLS` constants
- Phase tools must always be included regardless of `available_tools`
- Unknown tool names → log warning, skip, continue

**Functionality (Expected Outcomes)**
- [ ] `available_tools=None` → all standard phase tools included (backward compat)
- [ ] `available_tools=["terminal"]` → terminal tool added to phase tools (if registered)
- [ ] `available_tools=["nonexistent"]` → warning logged, tool skipped, no error
- [ ] Phase filtering still works: builders don't get `grade`, verifiers get `grade`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "claude_sdk" -v` — all Claude SDK tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 2: Implement MCP Connector Beta Wiring
**Description**:
When `context.mcp_servers` is set, convert `MCPServerConfig` list to the format expected by the MCP Connector beta API (`client.beta.messages.create()` with `mcp_servers` parameter). STDIO-transport servers are filtered out with a warning (only remote HTTPS URLs supported).

**Implementation Plan (Do These Steps)**
- [ ] Create a helper function to convert `MCPServerConfig` to beta API format:
```python
def _build_mcp_params(
    mcp_servers: list[MCPServerConfig] | None,
) -> dict[str, Any]:
    """Convert MCPServerConfig list to MCP Connector beta parameters.

    Only HTTPS URL-based servers are supported. STDIO servers are skipped with a warning.
    Returns empty dict if no servers or all filtered out.
    """
    if not mcp_servers:
        return {}

    api_servers = []
    for mcp in mcp_servers:
        if mcp.command:
            logger.warning(
                "MCP server '%s' uses STDIO transport (command='%s') — "
                "not supported by Claude MCP Connector beta, skipping",
                mcp.name, mcp.command,
            )
            continue

        server_config: dict[str, Any] = {
            "type": "url",
            "url": mcp.url,
            "name": mcp.name,
        }
        if mcp.auth_token_env:
            import os
            token = os.environ.get(mcp.auth_token_env)
            if token:
                server_config["authorization_token"] = token
            else:
                logger.warning(
                    "Auth token env var '%s' for MCP server '%s' not set",
                    mcp.auth_token_env, mcp.name,
                )
        api_servers.append(server_config)

    if not api_servers:
        return {}

    return {"mcp_servers": api_servers}
```
- [ ] Update the API call in the execute method to include MCP parameters when available:
```python
mcp_params = _build_mcp_params(context.mcp_servers)
if mcp_params:
    # Use beta API with MCP Connector
    response = await asyncio.to_thread(
        client.beta.messages.create,
        model=self._model,
        max_tokens=self._max_tokens,
        tools=tools,
        messages=messages,
        betas=["mcp-client-2025-11-20"],
        **mcp_params,
    )
else:
    response = await asyncio.to_thread(
        client.messages.create,
        model=self._model,
        max_tokens=self._max_tokens,
        tools=tools,
        messages=messages,
    )
```

**Dependencies**
- [ ] Task 1 complete: Tool filtering is in place

**References**
- Key decision: MCP Connector beta with `mcp-client-2025-11-20` header, remote HTTPS only
- Clarification Q2: Discovering Claude API MCP support is part of implementation
- Clarification Q4: MCP failures deferred to agents

**Constraints**
- Only HTTPS URL-based MCP servers are passed to the beta API
- STDIO-transport servers must be skipped with a warning, not cause an error
- Auth tokens resolved from env vars at runtime, never hardcoded

**Side Effects**
- Requires the Anthropic SDK version to support `client.beta.messages.create()` with `mcp_servers` parameter

**Functionality (Expected Outcomes)**
- [ ] `mcp_servers` with HTTPS URL → config passed to beta API call with `mcp-client-2025-11-20` header
- [ ] `mcp_servers` with STDIO `command` → warning logged, server skipped
- [ ] `mcp_servers=None` → standard (non-beta) API call used (backward compat)
- [ ] Auth token resolved from `auth_token_env` at runtime

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "claude_sdk" -v` — all Claude SDK tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 3: Write Unit Tests for Claude SDK Tool Filtering and MCP Wiring
**Description**:
Create unit tests verifying additive tool filtering and MCP Connector beta parameter construction.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_claude_sdk_tool_filtering.py`:
```python
"""Tests for Claude SDK agent tool filtering and MCP wiring."""
import logging
from unittest.mock import patch

from orchestrator.agents.claude_sdk import _build_tool_list, _build_mcp_params
from orchestrator.config.models import MCPServerConfig


class TestClaudeSDKToolFiltering:
    def test_builder_tools_when_none(self):
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert "grade" not in names  # Builder doesn't get grade

    def test_verifier_tools_when_none(self):
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" in names
        assert "submit" in names

    def test_unknown_tool_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent_tool"])
        assert "nonexistent_tool" in caplog.text
        # Should still have all base tools
        names = {t["name"] for t in tools}
        assert "submit" in names

    def test_phase_tools_always_included(self):
        """Step tools never remove phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=["terminal"])
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names


class TestClaudeSDKMCPParams:
    def test_https_server_included(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        params = _build_mcp_params([mcp])
        assert "mcp_servers" in params
        assert params["mcp_servers"][0]["url"] == "https://ctx7.example.com"

    def test_stdio_server_skipped(self, caplog):
        mcp = MCPServerConfig(name="local", command="context7-mcp")
        with caplog.at_level(logging.WARNING):
            params = _build_mcp_params([mcp])
        assert params == {}
        assert "STDIO" in caplog.text

    def test_none_returns_empty(self):
        params = _build_mcp_params(None)
        assert params == {}

    def test_auth_token_from_env(self):
        mcp = MCPServerConfig(
            name="auth", url="https://auth.example.com",
            auth_token_env="MY_TOKEN",
        )
        with patch.dict("os.environ", {"MY_TOKEN": "secret123"}):
            params = _build_mcp_params([mcp])
        assert params["mcp_servers"][0].get("authorization_token") == "secret123"
```

**Functionality (Expected Outcomes)**
- [ ] All tool filtering tests pass
- [ ] All MCP parameter tests pass
- [ ] Phase filtering verified (builder vs verifier)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_claude_sdk_tool_filtering.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
