# External MCP Configuration for CLI and User-Managed Agents

**Investigation Date:** 2026-02-27
**Scope:** How to integrate external MCPs with CLI and User-Managed agents
**Status:** Complete

---

## Executive Summary

This investigation explores three approaches to configure external MCPs for CLI and User-Managed agents:

1. **CLI Agent**: Embed MCP URLs and configs directly in enriched prompts (text-based)
2. **User-Managed Agent**: Expose external MCPs through orchestrator's global MCP server (composition/proxying)
3. **General Patterns**: Standard practices for MCP composition and auth token management

**Key Finding**: Both agents can support external MCPs, but the implementation patterns differ fundamentally:
- **CLI agents** receive MCP config as text in prompts
- **User-Managed agents** would proxy external MCPs through the orchestrator's server
- Neither has built-in support yet, but the underlying APIs support it

---

## Part 1: CLI Agent External MCP Configuration

### Current Architecture

The CLI agent builds an **enriched prompt** that includes:
- Task requirements
- Callback instructions (REST API endpoints)
- MCP server connection details (if `callback_channel="mcp"`)

**File:** `/src/orchestrator/agents/cli.py` (lines 114-263)

```python
# Current implementation:
api_section = (
    f"### MCP Server Connection\n"
    f"Connect to: {base}/mcp/sse\n\n"  # ← Orchestrator's MCP server only
    f"### Available MCP Tools\n"
    f"- **orchestrator_get_requirements**(...)\n"
    f"- **orchestrator_update_checklist**(...)\n"
    ...
)
```

### How to Pass External MCP Configs to Subprocess

#### **Approach 1: URL List in Prompt (Recommended)**

**Effort:** Low | **Reliability:** High | **Complexity:** Low

Add external MCP URLs to the enriched prompt:

```python
# In CLIAgent.build_prompt()
if context.mcp_servers:  # New field in ExecutionContext
    api_section += (
        f"\n\n## External MCP Servers\n"
        f"Additional MCP servers are available:\n"
    )
    for i, mcp_url in enumerate(context.mcp_servers, 1):
        api_section += f"{i}. {mcp_url}\n"

    api_section += (
        f"\nYou can connect to any of these servers in addition to "
        f"the main orchestrator server for expanded capabilities."
    )
```

**Implementation:**
1. Add `mcp_servers: list[str] | None = None` to `ExecutionContext`
2. Extend executor to populate from `run.agent_config.get("mcp_servers", [])`
3. Format URLs in prompt (subprocess parses as text)

**Pros:**
- ✅ No subprocess protocol changes needed
- ✅ Flexible — subprocess decides which MCPs to use
- ✅ Backward compatible
- ✅ Easy to document (plain text in prompt)

**Cons:**
- ❌ Subprocess must implement MCP client logic
- ❌ No validation that URLs are valid MCPs
- ❌ Token/auth handling delegated to subprocess

#### **Approach 2: MCP Configuration JSON in Prompt**

**Effort:** Medium | **Reliability:** Medium | **Complexity:** Medium

Pass structured MCP config as JSON:

```python
# In CLIAgent.build_prompt()
if context.mcp_config:  # JSON structure
    api_section += (
        f"\n\n## MCP Server Configuration\n"
        f"```json\n"
        f"{json.dumps(context.mcp_config, indent=2)}\n"
        f"```\n\n"
        f"Parse the above JSON to configure your MCP clients."
    )
```

**Config structure:**
```json
{
  "mcp_servers": [
    {
      "name": "custom-tools",
      "url": "http://custom.mcp.local:3000/sse",
      "auth": {
        "token": "sk-...",
        "bearer": true
      },
      "capabilities": ["tool_calling", "resource_access"]
    }
  ]
}
```

**Pros:**
- ✅ Structured, machine-readable config
- ✅ Can include auth tokens and metadata
- ✅ Subprocess can validate before connecting
- ✅ Extensible for future additions

**Cons:**
- ❌ Subprocess must parse JSON
- ❌ Auth tokens in plaintext in prompt (security concern)
- ❌ More complex for simple cases

#### **Approach 3: Environment Variables**

**Effort:** Low | **Reliability:** Low | **Complexity:** Low

Pass config through subprocess environment:

```python
# In CLIAgent.execute()
child_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

if context.mcp_servers:
    # Pass as JSON
    child_env["ORCHESTRATOR_MCP_SERVERS"] = json.dumps(
        [{"url": url} for url in context.mcp_servers]
    )

    # Pass auth tokens
    if context.mcp_auth_tokens:
        child_env["ORCHESTRATOR_MCP_AUTH"] = json.dumps(context.mcp_auth_tokens)

process = await asyncio.create_subprocess_exec(
    *cmd,
    env=child_env,
    ...
)
```

**Pros:**
- ✅ Doesn't pollute prompt text
- ✅ Clean separation from task content
- ✅ Subprocess can ignore if not implemented

**Cons:**
- ❌ Tokens in environment (security issue)
- ❌ Requires subprocess coordination
- ❌ Less discoverable to subprocess

### Recommended: Hybrid Approach

**Combine Approach 1 (URLs) + Approach 2 (config) with environment variables for auth:**

```python
# ExecutionContext additions:
class ExecutionContext(BaseModel):
    mcp_servers: list[str] | None = None  # Simple URLs
    mcp_config: dict[str, Any] | None = None  # Full config
    # Auth tokens passed via env, not context

# In CLIAgent.build_prompt():
if context.mcp_servers:
    # Add simple readable list
    api_section += "\n## External MCP Servers\n"
    for url in context.mcp_servers:
        api_section += f"- {url}\n"

# In CLIAgent.execute():
if context.mcp_config:
    # Pass full config via env
    child_env["ORCHESTRATOR_MCP_CONFIG"] = json.dumps(context.mcp_config)
```

---

## Part 2: User-Managed Agent External MCP Configuration

### Current Architecture

User-Managed agents don't run code themselves. Instead:
1. External clients connect to the orchestrator's global MCP server at `/mcp/sse`
2. They call orchestrator tools via MCP
3. WorkflowService handles the business logic

**File:** `/src/orchestrator/mcp/server.py` (single global instance)

```python
# app.py: One global MCP server
mcp_server = OrchestratorMCPServer(handler=handler)  # phase="building"
app.mount("/mcp", mcp_server.sse_app)
```

### How to Expose External MCPs

#### **Option 1: Proxy External MCPs Through Orchestrator's Server**

**Effort:** Medium | **Reliability:** High | **Complexity:** Medium

Add external MCP servers as "tool providers" to the orchestrator's MCP server:

```python
# In OrchestratorMCPServer.__init__()
class OrchestratorMCPServer:
    def __init__(
        self,
        service: WorkflowService,
        handler: ToolHandler,
        external_mcps: list[str] | None = None,  # NEW
        repos_dir: Path | None = None,
    ):
        self._handler = handler
        self._external_mcps = external_mcps or []
        self._mcp = FastMCP(name="orchestrator")
        self._register_tools()
        self._register_external_mcps()  # NEW METHOD

    def _register_external_mcps(self) -> None:
        """Proxy tools from external MCP servers."""
        for mcp_url in self._external_mcps:
            try:
                # Connect to external MCP
                client = MCPClient(mcp_url)
                tools = await client.list_tools()

                # Register each tool as a proxy
                for tool in tools:
                    self._mcp.add_tool(
                        self._make_proxy_tool(tool, client),
                        name=tool.name,
                        description=tool.description
                    )
            except Exception as e:
                logger.warning(f"Failed to register external MCP {mcp_url}: {e}")
```

**How it works:**
1. Orchestrator connects to external MCP at startup
2. Discovers available tools
3. Re-registers them with its own FastMCP server
4. External clients see combined tool list (orchestrator + external)
5. Proxy tool calls to original external MCP

**Configuration in run:**
```python
run = await create_run(
    agent_type="user_managed",
    agent_config={
        "mcp_servers": [
            "http://custom-tools.local:3000/sse",
            "http://another-mcp.local:8080/sse"
        ]
    }
)
```

**Pros:**
- ✅ Clients see unified tool list
- ✅ Single connection point for external agents
- ✅ Works with existing MCP clients
- ✅ Transparent tool proxying

**Cons:**
- ⚠️ Orchestrator must connect to external MCPs
- ⚠️ External MCPs must be reachable from server
- ⚠️ Tool naming conflicts possible
- ⚠️ Error handling for external MCPs complex

#### **Option 2: Per-Connection MCP Discovery**

**Effort:** High | **Reliability:** Medium | **Complexity:** High

Each external client discovers/connects to external MCPs independently:

```python
# In CallbackInstructions (in prompt response)
class CallbackInstructions(BaseModel):
    mcp_url: str  # Orchestrator's MCP
    external_mcps: list[str] | None = None  # External MCPs to connect to

# In routers/tasks.py:
async def get_task_prompt(...) -> PromptResponse:
    # ...
    external_mcps = (
        run.agent_config.get("external_mcp_servers") or []
    )

    return PromptResponse(
        ...,
        mcp_instructions=CallbackInstructions(
            mcp_url=...,
            external_mcps=external_mcps,
        )
    )
```

**How it works:**
1. Orchestrator tells client about available external MCPs
2. Client connects to both orchestrator MCP and external MCPs separately
3. Client multiplexes tool calls to appropriate servers

**Pros:**
- ✅ Decoupled — orchestrator doesn't need to reach external MCPs
- ✅ Client controls connections
- ✅ Scales to many external MCPs

**Cons:**
- ❌ Client must implement multi-MCP logic
- ❌ Duplicate auth handling per connection
- ❌ Complex for tool discovery
- ❌ Clients don't see unified tool list upfront

#### **Option 3: Task-Scoped MCP Server**

**Effort:** High | **Reliability:** High | **Complexity:** High

Create per-task MCP server with external MCPs pre-configured:

```python
# In executor or routers/runs.py
async def _get_task_mcp_server(run_id: str, task_id: str) -> FastMCP:
    """Create a task-scoped MCP server with external tools."""
    run = await service.get_run(run_id)
    external_mcp_urls = run.agent_config.get("external_mcp_servers", [])

    mcp = FastMCP(name=f"task-{task_id}")

    # Register orchestrator tools
    handler = ToolHandler(service)
    for tool in ORCHESTRATOR_TOOLS:
        mcp.add_tool(...)

    # Register external tools
    for url in external_mcp_urls:
        external_client = MCPClient(url)
        for tool in await external_client.list_tools():
            mcp.add_tool(proxy_fn, ...)

    return mcp

# Mount at /api/runs/{run_id}/tasks/{task_id}/mcp/sse
```

**Pros:**
- ✅ Full tool isolation per task
- ✅ Can mount/unmount external MCPs per task
- ✅ Clean per-task configuration

**Cons:**
- ❌ Many MCP server instances
- ❌ Lifecycle management complex
- ❌ Breaking API change (new endpoint)
- ❌ Resource overhead

### Recommended: Option 1 (Proxy Pattern)

**For User-Managed agents, implement proxy pattern:**

```python
# 1. Extend agent_config schema
class CreateRunRequest:
    agent_config: dict = {
        "external_mcp_servers": [
            "http://custom.local:3000/sse",
        ]
    }

# 2. Modify OrchestratorMCPServer
class OrchestratorMCPServer:
    def __init__(
        self,
        handler: ToolHandler,
        external_mcp_urls: list[str] | None = None,
    ):
        self._external_mcps = external_mcp_urls or []
        self._mcp = FastMCP()
        self._register_orchestrator_tools()
        self._register_external_tools()  # NEW

# 3. Implement proxy registration
def _register_external_tools(self) -> None:
    for url in self._external_mcps:
        client = MCPClient(url)
        for tool in client.list_tools():
            self._mcp.add_tool(
                self._create_proxy(tool, client)
            )

# 4. Pass URLs from run.agent_config
mcp_server = OrchestratorMCPServer(
    handler=handler,
    external_mcp_urls=run.agent_config.get("external_mcp_servers")
)
```

---

## Part 3: General Patterns for External MCP Integration

### Standard Format for MCP Configuration

**Schema for passing MCP config:**
```python
class MCPServerConfig(BaseModel):
    """Configuration for an external MCP server."""
    url: str  # HTTP URL for SSE or stdio, or command for subprocess
    name: str | None = None  # Display name
    auth: dict[str, str] | None = None  # Auth method (bearer, api_key, etc)
    capabilities: list[str] | None = None  # Advertised capabilities
    timeout_seconds: int = 30
    retry_count: int = 3
    disabled: bool = False  # Allow disabling without removing config

class MCPConfiguration(BaseModel):
    """MCP configuration per step/task."""
    orchestrator_tools: bool = True  # Include orchestrator tools
    external_servers: list[MCPServerConfig] = []
```

### Standard Way to Pass MCP Configs to Subprocesses

**Pattern 1: Via Environment Variable (Preferred)**
```bash
ORCHESTRATOR_MCP_CONFIG='{
  "external_servers": [
    {"url": "http://...", "auth": {"token": "..."}}
  ]
}'
```

**Pattern 2: Via Stdin (Alternative)**
```
# First line of stdin: JSON config
{"external_servers": [...]}
# Remaining lines: task prompt
```

**Pattern 3: Via Temp File (Legacy)**
```bash
# Write config to temp file
echo $MCP_CONFIG > /tmp/mcp-config.json
export ORCHESTRATOR_MCP_CONFIG=/tmp/mcp-config.json
```

### Multiple MCP Composition Best Practices

**Tool Namespacing:**
```
orchestrator_get_requirements     # Orchestrator tools
custom_tools_run_script          # External MCP "custom_tools"
debug_tools_print                # External MCP "debug_tools"
```

**Conflict Resolution:**
1. Orchestrator tools always available (non-negotiable)
2. External tools prefixed with server name
3. If conflict, namespace or rename

**Error Handling:**
```python
# When external MCP is unavailable
try:
    result = await proxy_tool.call()
except MCPConnectionError:
    return {
        "error": "External tool unavailable",
        "tool": tool_name,
        "hint": "Check MCP server connectivity"
    }
```

### Authentication Token Management

**Security Considerations:**

1. **Never put tokens in prompt text** (CLI subprocess can leak in logs)
2. **Use environment variables** when passing to subprocesses
3. **Use headers** when proxying through orchestrator MCP
4. **Validate token expiration** before tool calls
5. **Support multiple auth methods:**
   - Bearer token: `Authorization: Bearer <token>`
   - API key: `X-API-Key: <key>`
   - Custom headers: `X-Custom-Auth: <value>`

**Implementation Pattern:**
```python
# In CLI Agent
class ExecutionContext(BaseModel):
    mcp_auth: dict[str, str] | None = None  # {server_name: token}
    # Token is passed via environment, not in prompt

# In CLIAgent.execute()
if context.mcp_auth:
    child_env["ORCHESTRATOR_MCP_AUTH"] = json.dumps(context.mcp_auth)
    # Subprocess reads env: token = os.getenv("ORCHESTRATOR_MCP_AUTH")

# In User-Managed / Proxy Pattern
@mcp.add_tool
async def proxy_call(self, tool_name: str, arguments: dict):
    mcp_server = self._external_clients[server_for(tool_name)]
    headers = {
        "Authorization": f"Bearer {self._get_auth_token(server_name)}"
    }
    return await mcp_server.call_tool(tool_name, arguments, headers=headers)
```

### Dynamic MCP Mount/Unmount Per Execution

**Pattern for enabling different MCPs per step:**

```python
# 1. Extend StepConfig with tools
class StepConfig:
    available_tools: list[str] | None = None  # Specific tools for step
    external_mcp_servers: list[MCPServerConfig] | None = None  # NEW

# 2. In executor, determine MCPs for step
step_config = routine.steps[step_index]
mcp_urls = [s.url for s in (step_config.external_mcp_servers or [])]

# 3. Pass to agent
context = ExecutionContext(
    ...,
    mcp_servers=mcp_urls,
    available_tools=step_config.available_tools
)

# 4. CLI Agent includes in prompt; User-Managed creates scoped server
```

---

## Part 4: Architecture Changes Needed

### For CLI Agent (Low Effort)

**Required changes:**
1. Add `mcp_servers` field to `ExecutionContext`
2. Add `mcp_config` field to `ExecutionContext` (optional)
3. Update `CLIAgent.build_prompt()` to include MCP server list
4. Update executor to read from `run.agent_config["external_mcp_servers"]`

**Files to modify:**
- `src/orchestrator/agents/types.py` — ExecutionContext
- `src/orchestrator/agents/cli.py` — build_prompt()
- `src/orchestrator/agents/executor.py` — where ExecutionContext is created

**Example:**
```python
# In executor.py, around line 654
context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=working_dir,
    prompt=f"{prompt.system}\n\n{prompt.user}",
    requirements=requirements,
    api_base_url=self._api_base_url,
    mcp_servers=run.agent_config.get("external_mcp_servers"),  # NEW
)
```

### For User-Managed Agent (Medium Effort)

**Option 1 (Recommended): Proxy Pattern**

Required changes:
1. Modify `OrchestratorMCPServer.__init__()` to accept `external_mcp_urls`
2. Implement `_register_external_tools()` method
3. Create proxy tool wrappers
4. Update app initialization to pass URLs from run config
5. Handle auth token propagation in proxy calls

**Files to modify:**
- `src/orchestrator/mcp/server.py` — OrchestratorMCPServer
- `src/orchestrator/api/app.py` — How MCP server is initialized
- `src/orchestrator/agents/executor.py` — Pass URLs when creating server

**Estimated scope:** 200-300 lines of code

### For MCP Client Integration (Medium Effort)

If implementing true MCP client in orchestrator:
1. Choose MCP client library (likely `mcp` package)
2. Implement MCPClient wrapper class
3. Add connection pooling
4. Implement auth token management
5. Handle tool discovery and caching

**Estimated scope:** 300-400 lines of code

---

## Part 5: Feasibility Assessment

### CLI Agent: External MCP Configuration

| Aspect | Feasibility | Notes |
|--------|------------|-------|
| **Pass URLs in prompt** | ✅ High | Just text, subprocess parses |
| **Pass config JSON** | ✅ High | Subprocess parses JSON |
| **Auth tokens** | ⚠️ Medium | Can use env vars, not prompt |
| **Dynamic updates** | ❌ Low | Prompt is immutable after send |
| **Tool filtering** | ✅ High | Subprocess filters locally |
| **Per-step MCPs** | ⚠️ Medium | Text hints, not enforced |

**Recommendation:** ✅ **Definitely Feasible**
- Start with approach 1 (URL list in prompt)
- Add approach 3 (env vars) for auth tokens
- Document expectations clearly

**Implementation timeline:** 2-4 hours

### User-Managed Agent: External MCP Exposure

| Aspect | Feasibility | Notes |
|--------|------------|-------|
| **Option 1 (Proxy)** | ✅ High | Needs MCP client lib + glue code |
| **Option 2 (Discovery)** | ✅ High | Just return URLs in response |
| **Option 3 (Per-task)** | ⚠️ Medium | Many server instances |
| **Tool filtering** | ✅ High | Proxy can filter or validate |
| **Per-step MCPs** | ✅ High | Create different scopes per step |
| **Dynamic updates** | ⚠️ Medium | Possible with heartbeat or polling |

**Recommendation:** ✅ **Definitely Feasible (Option 1)**
- Proxy pattern is cleanest
- Transparent to external clients
- Scales well for multiple external MCPs

**Implementation timeline:** 4-6 hours

### General MCP Composition

| Capability | Feasibility | Notes |
|---|---|---|
| **Multiple MCP composition** | ✅ High | Standard MCP pattern |
| **Tool namespacing** | ✅ High | Prefix tool names |
| **Auth token handling** | ✅ High | Standard HTTP auth |
| **Dynamic enabling/disabling** | ✅ High | Config per step |
| **Error handling** | ✅ High | Try-catch on tool calls |

---

## Part 6: Implementation Roadmap

### Phase 1: Foundation (Effort: 2 hours)

**Goal:** Enable basic external MCP discovery

1. **Add `mcp_servers` field to ExecutionContext**
   - File: `src/orchestrator/agents/types.py`
   - Change: Add `mcp_servers: list[str] | None = None`

2. **Update CLI agent to include MCP URLs in prompt**
   - File: `src/orchestrator/agents/cli.py`
   - Change: Format external MCP URLs in callback instructions

3. **Update executor to read from agent_config**
   - File: `src/orchestrator/agents/executor.py`
   - Change: Pass `run.agent_config.get("external_mcp_servers")` to context

### Phase 2: CLI Agent Auth Support (Effort: 3 hours)

1. **Add `mcp_auth` to ExecutionContext**
2. **Pass auth tokens via environment variable**
3. **Document subprocess expectations**

### Phase 3: User-Managed Proxy Implementation (Effort: 5 hours)

1. **Implement MCPClient wrapper class**
2. **Add external tool registration to OrchestratorMCPServer**
3. **Create proxy tool wrappers**
4. **Handle auth token propagation**
5. **Add error handling for external MCPs**

### Phase 4: Per-Step Configuration (Effort: 4 hours)

1. **Add external_mcp_servers to StepConfig**
2. **Update executor to read step-level config**
3. **Pass to both CLI and User-Managed agents**

**Total estimated effort: 14-16 hours**

---

## Summary of Findings

### CLI Agent

**Current state:** Can only access orchestrator's MCP server (hardcoded in prompt)

**How to configure externals:**
- Add `mcp_servers` list to ExecutionContext
- Format as text in build_prompt()
- Subprocess discovers and connects independently
- Auth via environment variables

**Complexity:** Low
**Feasibility:** ✅ High
**Recommended:** Approach 1 (URL list in prompt)

### User-Managed Agent

**Current state:** Connects to global orchestrator MCP server; no external MCPs exposed

**How to configure externals:**
- Implement proxy pattern in OrchestratorMCPServer
- Register external tools alongside orchestrator tools
- Handle auth in proxy calls
- Optional: create per-task MCP servers for more control

**Complexity:** Medium
**Feasibility:** ✅ High
**Recommended:** Option 1 (Proxy pattern through orchestrator)

### General Patterns

**Standard approaches:**
- Pass config via environment variables (secure, subprocess-friendly)
- Use HTTP headers for auth (Bearer tokens, API keys)
- Namespace external tools to avoid conflicts
- Implement error handling for disconnected external MCPs
- Support per-step MCP configuration via StepConfig

**Key insight:** Both agent types can be extended, but CLI requires text-based protocols (immutable prompt) while User-Managed can do sophisticated proxying (runtime control).

---

## Code Examples

### CLI Agent: Minimal Implementation

```python
# 1. In types.py
class ExecutionContext(BaseModel):
    # ... existing fields ...
    mcp_servers: list[str] | None = None  # URLs like "http://..."

# 2. In cli.py build_prompt()
if context.mcp_servers:
    api_section += (
        "\n## External MCP Servers\n"
        "Additional MCP servers available:\n"
    )
    for url in context.mcp_servers:
        api_section += f"- {url}\n"

# 3. In executor.py
context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=working_dir,
    prompt=f"{prompt.system}\n\n{prompt.user}",
    requirements=requirements,
    api_base_url=self._api_base_url,
    mcp_servers=run.agent_config.get("external_mcp_servers"),
)
```

### User-Managed Agent: Proxy Pattern Skeleton

```python
# In mcp/server.py
class OrchestratorMCPServer:
    def __init__(
        self,
        handler: ToolHandler,
        external_mcp_urls: list[str] | None = None,
    ):
        self._external_mcps = external_mcp_urls or []
        self._mcp = FastMCP(name="orchestrator")
        self._register_orchestrator_tools()
        self._register_external_tools()

    def _register_external_tools(self) -> None:
        """Proxy tools from external MCP servers."""
        for url in self._external_mcps:
            try:
                # 1. Connect to external MCP
                client = SSEClient(url)  # or HTTPClient

                # 2. List available tools
                tools = client.list_tools()

                # 3. Register as proxy
                for tool in tools:
                    self._mcp.add_tool(
                        self._create_proxy_tool(tool, client)
                    )
            except Exception as e:
                logger.warning(f"Failed to register {url}: {e}")

    def _create_proxy_tool(self, tool, client):
        async def proxy_fn(**kwargs):
            return await client.call_tool(tool.name, kwargs)
        return proxy_fn
```
