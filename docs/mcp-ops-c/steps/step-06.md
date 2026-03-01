# Step 6: OpenHands Tool Filtering + MCP Wiring

Enable the OpenHands agent to respect step-level `available_tools` for built-in tool selection and wire external MCP servers via OpenHands' native `mcp_config` parameter. OpenHands supports stdio, SSE, and Streamable HTTP transports via FastMCP. This is **Priority 3**. Includes research into OpenHands SDK MCP support (per Clarification Q3).

## Intent Verification
**Original Intent**: OpenHands agent filters built-in tools based on `context.available_tools` and passes `mcp_config` to constructor (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullet 7).
**Functionality to Produce**:
- Built-in tool selection respects `context.available_tools` (additive to defaults)
- `MCPServerConfig` converted to OpenHands `mcp_config` dict format
- `mcp_config` passed to `Agent()` constructor when available
- Graceful fallback if `mcp_config` parameter not supported by installed version
- Backward compatible when fields are `None`

**Final Verification Criteria**:
- Unit tests confirm tool filtering works (default vs custom)
- Unit tests confirm MCP config conversion and passthrough
- Graceful degradation test passes
- All existing OpenHands tests pass

---

## Task 1: Research OpenHands SDK MCP Support
**Description**:
Investigate whether the installed OpenHands SDK version supports the `mcp_config` parameter on the `Agent()` constructor. Document findings and determine the correct wiring approach.

**Implementation Plan (Do These Steps)**
- [ ] Check the installed OpenHands SDK version: `uv run python -c "import openhands_ai; print(openhands_ai.__version__)"`
- [ ] Inspect the `Agent` class constructor signature: `uv run python -c "from openhands import Agent; import inspect; print(inspect.signature(Agent.__init__))"`
- [ ] Search for `mcp_config` or `mcp` in the OpenHands SDK source: `uv run python -c "import openhands; import os; print(os.path.dirname(openhands.__file__))"` then grep that directory
- [ ] Document findings: does `Agent()` accept `mcp_config`? What format? What transports?
- [ ] If `mcp_config` is NOT supported, plan the fallback approach (prompt-based MCP info, similar to CLI)

**References**
- Clarification Q3: "I expect you to research this" — implementer must discover MCP support
- Architecture assumes `Agent(mcp_config={...})` with `{"mcpServers": {...}}` format
- Current OpenHands agent: `src/orchestrator/agents/openhands.py:458-482`

**Functionality (Expected Outcomes)**
- [ ] Clear documentation of whether `mcp_config` is supported
- [ ] If supported: exact format and parameter name confirmed
- [ ] If not supported: fallback approach documented

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Research findings documented in code comments or a brief note
- [ ] Decision made on wiring approach (native `mcp_config` vs fallback)

---

## Task 2: Implement Step-Level Tool Filtering in OpenHands Agent
**Description**:
Update the OpenHands agent to add step-level tools from `context.available_tools` at `Agent()` construction time. Default tools (`terminal`, `file_editor`) are always included; step tools are additive.

**Implementation Plan (Do These Steps)**
The current implementation (lines 458-482 in `openhands.py`) builds tool list from `self._tools` or `DEFAULT_OPENHANDS_TOOLS`:
```python
tool_names = self._tools or DEFAULT_OPENHANDS_TOOLS
builtin_tools = [OHTool(name=name) for name in tool_names]
```

- [ ] Update tool list construction to include step-level tools:
```python
# Start with configured or default tools
tool_names = list(self._tools or DEFAULT_OPENHANDS_TOOLS)

# Add step-level tools (additive)
if context.available_tools:
    for tool_name in context.available_tools:
        if tool_name not in tool_names:
            tool_names.append(tool_name)

builtin_tools = [OHTool(name=name) for name in tool_names]
```
- [ ] Add unknown tool name detection — log warning for tools that don't exist in OpenHands registry:
```python
try:
    builtin_tools = [OHTool(name=name) for name in tool_names]
except Exception as e:
    logger.warning("Error creating tool '%s': %s — skipping", name, e)
```

**Dependencies**
- [ ] Step 2 complete: `ExecutionContext` carries `available_tools`
- [ ] Task 1 complete: Research confirms tool approach

**References**
- Current tool construction: `src/orchestrator/agents/openhands.py:458-482`
- `DEFAULT_OPENHANDS_TOOLS = ["terminal", "file_editor"]`

**Constraints**
- Default tools (`terminal`, `file_editor`) must always be included
- Orchestrator callback tools are always added regardless of `available_tools`
- Unknown tool names should warn but not crash

**Functionality (Expected Outcomes)**
- [ ] `available_tools=None` → default tools used (backward compat)
- [ ] `available_tools=["browser"]` → `browser` added to default tools
- [ ] `available_tools=["nonexistent"]` → warning logged, tool skipped or handled gracefully

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "openhands" -v` — all OpenHands tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 3: Implement MCP Config Passthrough to OpenHands Agent
**Description**:
Convert `MCPServerConfig` list to OpenHands `mcp_config` dict format and pass to `Agent()` constructor. Add graceful fallback if the parameter is not supported.

**Implementation Plan (Do These Steps)**
- [ ] Create a conversion function:
```python
def _build_openhands_mcp_config(
    mcp_servers: list[MCPServerConfig] | None,
) -> dict[str, Any] | None:
    """Convert MCPServerConfig list to OpenHands mcp_config format.

    Format: {"mcpServers": {"name": {"url": "...", "command": "...", ...}}}
    """
    if not mcp_servers:
        return None

    servers: dict[str, dict[str, Any]] = {}
    for mcp in mcp_servers:
        entry: dict[str, Any] = {}
        if mcp.url:
            entry["url"] = mcp.url
        elif mcp.command:
            entry["command"] = mcp.command
            if mcp.args:
                entry["args"] = mcp.args
        if mcp.env:
            entry["env"] = dict(mcp.env)
        if mcp.auth_token_env:
            import os
            token = os.environ.get(mcp.auth_token_env)
            if token:
                entry.setdefault("env", {})["AUTH_TOKEN"] = token
        servers[mcp.name] = entry

    return {"mcpServers": servers}
```
- [ ] Pass to `Agent()` constructor (with graceful fallback):
```python
mcp_config = _build_openhands_mcp_config(context.mcp_servers)
try:
    agent = OHAgent(
        llm=llm,
        tools=builtin_tools + orchestrator_tools,
        **({"mcp_config": mcp_config} if mcp_config else {}),
    )
except TypeError as e:
    if "mcp_config" in str(e):
        logger.warning(
            "OpenHands SDK does not support mcp_config parameter — "
            "MCP servers will not be available. Error: %s", e,
        )
        agent = OHAgent(llm=llm, tools=builtin_tools + orchestrator_tools)
    else:
        raise
```

**Dependencies**
- [ ] Task 1 complete: Research confirms approach
- [ ] Task 2 complete: Tool filtering in place

**References**
- Architecture: `docs/mcp-ops-c/architecture.md` — OpenHands `mcp_config` format
- Clarification Q4: MCP failures deferred to agents

**Constraints**
- Must handle `TypeError` gracefully if `mcp_config` is not a valid parameter
- Auth tokens resolved from env vars, never hardcoded

**Functionality (Expected Outcomes)**
- [ ] `mcp_servers` with URL → correct `mcp_config` dict passed
- [ ] `mcp_servers` with command → correct stdio format
- [ ] `mcp_servers=None` → no `mcp_config` passed
- [ ] Unsupported `mcp_config` param → warning logged, agent created without MCP

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "openhands" -v` — all OpenHands tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 4: Write Unit Tests for OpenHands Tool Filtering and MCP Wiring
**Description**:
Create unit tests for tool filtering, MCP config conversion, and graceful fallback.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_openhands_tool_filtering.py`:
```python
"""Tests for OpenHands agent tool filtering and MCP config."""
import logging

from orchestrator.config.models import MCPServerConfig

# Import the conversion function once implemented
# from orchestrator.agents.openhands import _build_openhands_mcp_config


class TestOpenHandsMCPConfig:
    def test_url_transport(self):
        mcp = MCPServerConfig(name="remote", url="https://mcp.example.com")
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        assert "remote" in config["mcpServers"]
        assert config["mcpServers"]["remote"]["url"] == "https://mcp.example.com"

    def test_stdio_transport(self):
        mcp = MCPServerConfig(name="local", command="ctx7", args=["--verbose"])
        config = _build_openhands_mcp_config([mcp])
        assert config["mcpServers"]["local"]["command"] == "ctx7"
        assert config["mcpServers"]["local"]["args"] == ["--verbose"]

    def test_none_returns_none(self):
        config = _build_openhands_mcp_config(None)
        assert config is None

    def test_multiple_servers(self):
        servers = [
            MCPServerConfig(name="a", url="https://a.com"),
            MCPServerConfig(name="b", command="b-cmd"),
        ]
        config = _build_openhands_mcp_config(servers)
        assert len(config["mcpServers"]) == 2
```

**Functionality (Expected Outcomes)**
- [ ] MCP config conversion tests pass for URL and STDIO transports
- [ ] None handling test passes
- [ ] Multiple server test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_openhands_tool_filtering.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
