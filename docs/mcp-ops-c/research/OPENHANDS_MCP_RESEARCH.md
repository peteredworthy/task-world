# OpenHands SDK MCP Support Research

**Date**: March 1, 2026
**Research Scope**: OpenHands SDK v1.10.0 MCP configuration support
**Status**: COMPLETE

---

## Executive Summary

✅ **OpenHands SDK 1.10.0 FULLY SUPPORTS `mcp_config` parameter**

The installed OpenHands SDK natively supports MCP server configuration via the `mcp_config` parameter on the `Agent()` constructor. No fallback approach needed; native integration is complete and production-ready.

---

## Research Findings

### 1. Installed Version

Verified via `uv pip list`:
```
openhands-sdk                            1.10.0
openhands-ai                             1.3.0
openhands-tools                          1.10.0
openhands-workspace                      1.11.1
```

**Installation Path**: `/Users/peter/code/task-world/.venv/lib/python3.12/site-packages/openhands/`

### 2. Agent Constructor Signature

**Location**: `openhands.sdk.agent.base.py:AgentBase` (inherited by `openhands.sdk.agent.agent.Agent`)

**SDK Inspection Results**:

File: `/Users/peter/code/task-world/.venv/lib/python3.12/site-packages/openhands/sdk/agent/base.py`

The `AgentBase` class includes the `mcp_config` parameter as a Pydantic `Field` (lines 82-88):

```python
mcp_config: dict[str, Any] = Field(
    default_factory=dict,
    description="Optional MCP configuration dictionary to create MCP tools.",
    examples=[
        {"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}
    ],
)
```

**Key Properties**:
- **Parameter Name**: `mcp_config`
- **Type**: `dict[str, Any]`
- **Default**: Empty dict (optional)
- **Pydantic Field**: Fully integrated into model validation

### 3. MCP Configuration Format

**FastMCP MCPConfig Signature** (from SDK inspection):
```python
MCPConfig(
    *,
    mcpServers: dict[str, StdioMCPServer | RemoteMCPServer | TransformingStdioMCPServer | TransformingRemoteMCPServer] = <factory>,
    **extra_data: Any
)
```

The `mcp_config` expects a FastMCP-compatible dictionary structure with the following format:

```python
{
    "mcpServers": {
        "server_name": {
            # For Stdio Transport (local MCP servers):
            "command": "command_name",
            "args": ["arg1", "arg2"],              # Optional
            "env": {"VAR": "value"},               # Optional
            "cwd": "/working/directory",           # Optional
            "timeout": 30,                         # Optional (seconds)

            # For Remote Transport (HTTP/SSE):
            "url": "https://mcp.example.com",      # Or http://, sse://
            "transport": "http|streamable-http|sse",  # Optional
            "headers": {"Authorization": "Bearer token"},  # Optional
            "auth": "bearer_token|oauth|Auth_instance",   # Optional
            "sse_read_timeout": 30,                # Optional (for SSE only)

            # Common Optional Fields:
            "description": "Server description",
            "icon": "⚙️",
            "authentication": {"type": "custom"}
        }
    }
}
```

### 4. Supported Transports

OpenHands/FastMCP supports **four transport types**, confirmed via FastMCP inspection:

#### Stdio Transport (Local MCP Servers)
**Class**: `fastmcp.mcp_config.StdioMCPServer`

Supported fields:
```python
{
    "transport": "stdio",           # Optional (default)
    "command": str,                 # Required: e.g., "ctx7" or "mcp-server-fetch"
    "args": list[str],              # Optional: e.g., ["--verbose"]
    "env": dict[str, Any],          # Optional: environment variables
    "cwd": str | None,              # Optional: working directory
    "timeout": int | None,          # Optional: seconds
    "description": str | None,      # Optional: metadata
    "icon": str | None,             # Optional: emoji/icon
    "authentication": dict | None,  # Optional: auth config
}
```

**Example**:
```python
{
    "command": "uvx",
    "args": ["mcp-server-fetch"],
    "timeout": 30
}
```

#### Remote Transport (HTTP/SSE)
**Class**: `fastmcp.mcp_config.RemoteMCPServer`

Supported fields:
```python
{
    "url": str,                              # Required: https://..., http://..., sse://
    "transport": "http|streamable-http|sse" # Optional: derived from URL or explicit
    "headers": dict[str, str],               # Optional: HTTP headers
    "auth": str | "oauth" | Auth | None,    # Optional: Bearer token or oauth
    "sse_read_timeout": int | float | None, # Optional: for SSE only
    "timeout": int | None,                  # Optional: seconds
    "description": str | None,               # Optional: metadata
    "icon": str | None,                     # Optional: emoji/icon
    "authentication": dict | None,          # Optional: auth config
}
```

**Example**:
```python
{
    "url": "https://mcp.example.com",
    "headers": {"Authorization": "Bearer token"},
    "timeout": 30
}
```

| Transport | Format | Use Case |
|-----------|--------|----------|
| **Stdio** | `command` + `args` | Local MCP servers, shell commands |
| **HTTP** | `url` (http://) | Remote MCP servers, synchronous |
| **Streamable HTTP** | `url` (http://) + SSE | Remote servers with streaming |
| **SSE** | `url` (sse://) | Server-Sent Events transport |

### 5. Grep Search Results for mcp_config Support

**Search Command**: `grep -r "mcp_config" /site-packages/openhands/sdk/ --include="*.py"`

**Key Results** (excerpted):
```
/openhands/sdk/agent/base.py:82    mcp_config: dict[str, Any] = Field(
/openhands/sdk/agent/base.py:272            if self.mcp_config:
/openhands/sdk/agent/base.py:273                future = executor.submit(create_mcp_tools, self.mcp_config, 30)
/openhands/sdk/mcp/utils.py:43   def create_mcp_tools(
/openhands/sdk/mcp/utils.py:44       config: dict | MCPConfig,
/openhands/sdk/plugin/loader.py:16        merged_mcp: dict[str, Any] = dict(agent.mcp_config) if agent.mcp_config else {}
```

This confirms that:
1. `mcp_config` is defined in AgentBase (line 82)
2. It's actively used in tool materialization (lines 272-273)
3. It's passed to `create_mcp_tools()` function
4. Plugin system can merge additional MCP configs

### 6. Implementation in AgentBase

**Location**: `openhands.sdk.agent.base.py:AgentBase.materialize_tools()` (lines 272-274)

```python
# Submit MCP tools creation if configured
if self.mcp_config:
    future = executor.submit(create_mcp_tools, self.mcp_config, 30)
    futures.append(future)
```

**Execution Flow**:
1. Tools are resolved in parallel using `ThreadPoolExecutor` (max_workers=4)
2. If `mcp_config` is provided, `create_mcp_tools()` is submitted as a parallel task
3. MCP tools are created within a 30-second timeout
4. All tools (built-in, explicit, and MCP) are collected and combined
5. Tools are validated, deduplicated, and made available to the agent

**MCP Tool Creation** (`openhands.sdk.mcp.utils.create_mcp_tools()`):
1. Converts dict to Pydantic `MCPConfig` model
2. Creates `MCPClient` instance
3. Connects to MCP server(s) asynchronously
4. Lists available tools from server
5. Wraps each tool as `MCPToolDefinition`
6. Returns client for tool access

### 6. Error Handling

- **Timeout**: Raises `MCPTimeoutError` after 30 seconds (configurable)
- **Connection Failure**: Wrapped as `MCPError`
- **Invalid Config**: Pydantic validation error on model initialization
- **Missing Transport**: Falls back to stdio if transport not specified

---

## Conclusion

### ✅ Wiring Approach Decision: **NATIVE `mcp_config`**

**Rationale**:
1. **Fully Supported**: The `mcp_config` parameter is a first-class field in `AgentBase`
2. **Mature Integration**: MCP tool creation is natively integrated into agent initialization
3. **No Fallback Needed**: No need for prompt-based MCP info or alternative approaches
4. **Production Ready**: Used in OpenHands v1.10.0 without deprecation warnings

### Implementation Strategy

For our orchestrator's `OpenHandsAgent`:

1. **Convert MCPServerConfig → mcp_config dict**:
   ```python
   def _build_openhands_mcp_config(
       mcp_servers: list[MCPServerConfig] | None,
   ) -> dict[str, Any] | None:
       """Convert MCPServerConfig list to OpenHands mcp_config format."""
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
           servers[mcp.name] = entry

       return {"mcpServers": servers}
   ```

2. **Pass to Agent() constructor** (with graceful fallback for unlikely scenario):
   ```python
   mcp_config = _build_openhands_mcp_config(context.mcp_servers)
   agent = OHAgent(
       llm=llm,
       tools=builtin_tools,
       **({"mcp_config": mcp_config} if mcp_config else {}),
   )
   ```

3. **No exception handling needed** for the parameter itself (it's always accepted), but FastMCP connection errors will be raised naturally

### Backward Compatibility

- If `mcp_config` is not provided or empty, agent works normally (no MCP tools)
- Existing agent configurations unaffected
- No breaking changes to agent initialization

---

## References

- **OpenHands SDK Source**: `/site-packages/openhands/sdk/agent/base.py`
- **MCP Module**: `/site-packages/openhands/sdk/mcp/`
- **FastMCP Config**: `fastmcp.mcp_config.MCPConfig`
- **Documentation**: Built-in docstrings in Agent and AgentBase classes

---

## Next Steps

1. Implement Task 2: Step-level tool filtering in OpenHands agent
2. Implement Task 3: MCP config passthrough with conversion function
3. Implement Task 4: Unit tests for tool filtering and MCP wiring
4. Run full test suite to validate all changes
