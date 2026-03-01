# User-Managed Agent: MCP Tool Control Analysis

## Current Implementation

The User-Managed agent is passive: it doesn't run any code itself. Instead, it:
1. Registers an `asyncio.Event` on the `WorkflowService`
2. Waits for external agents to call REST endpoints or MCP tools
3. Returns success when the external agent triggers submission

External agents (Cursor, Windsurf, custom tools, etc.) connect to the orchestrator's **global MCP server** at `/mcp/sse` to access tools.

### Architecture

```
┌────────────────────────────────────┐
│  External Agent (Cursor, Windsurf) │
│  - Connects to MCP server          │
│  - Calls orchestrator_* tools      │
│  - Gets requirements, updates      │
│  - Submits work                    │
└────────────┬───────────────────────┘
             │ MCP connection
             ↓
┌────────────────────────────────────┐
│  Global MCP Server                 │
│  - One instance at app startup     │
│  - Handles all tool calls          │
│  - Routes to WorkflowService       │
└────────────┬───────────────────────┘
             │ Method calls
             ↓
┌────────────────────────────────────┐
│  Orchestrator WorkflowService      │
│  - Updates checklist items         │
│  - Grades requirements             │
│  - Stores progress                 │
│  - Signals UserManagedAgent event  │
└────────────────────────────────────┘
```

### Tool Architecture

Tools are exposed via `OrchestratorMCPServer` in `/src/orchestrator/mcp/server.py`:

**Always Available (All Phases):**
- `orchestrator_get_requirements` — Get checklist items
- `orchestrator_update_checklist` — Update checklist status
- `orchestrator_submit` — Submit for verification
- `orchestrator_request_clarification` — Ask for clarification
- `orchestrator_list_repos` — List git repositories
- `orchestrator_list_branches` — List branches in repo

**Phase-Dependent (Conditionally Available):**
- `orchestrator_set_grade` — Grade requirements (VERIFYING phase only)
- `orchestrator_complete_recovery` — Recovery option (special)

### How Tools Are Currently Registered

Phase is hardcoded at startup:
```python
# api/app.py, line 518
mcp_server = OrchestratorMCPServer(handler=handler)  # phase="building" by default
```

This single instance serves all connected clients:
- Builder agents see all builder tools
- Verifier agents **also see builder tools** (bug: verifier tools not available via MCP)
- No per-task or per-step tool isolation

### How Tools Are Currently Called

External agents call tools like:
```python
# Cursor/Windsurf via MCP
result = mcp_client.call_tool(
    name="orchestrator_set_grade",
    arguments={
        "run_id": "run-123",
        "task_id": "task-456",
        "req_id": "req-789",
        "grade": "met"
    }
)
```

All calls include `run_id` and `task_id`, which allows the `ToolHandler` to:
1. Load the current task state
2. Validate the operation (e.g., can only grade during VERIFYING)
3. Execute the operation

## Constraints for Dynamic Tool Control

### 1. **Single Global MCP Server Instance**

One `OrchestratorMCPServer` instance is created at app startup and persists for the lifetime of the server:
```python
# app.py: Global instance
mcp_server = OrchestratorMCPServer(handler=handler)
```

**Impact:**
- All connected clients see the same tools
- Cannot have different tool sets for different tasks
- Cannot enable/disable tools per task or step
- Tool set is fixed at application startup (must restart to change)

### 2. **Phase Hardcoded to "building" at Startup**

The MCP server defaults to builder phase:
```python
# mcp/server.py
class OrchestratorMCPServer:
    def __init__(self, handler: ToolHandler, phase: str = "building"):
        self.phase = phase
        # Tools registered based on phase
```

It never updates even when tasks transition to verification.

**Result:**
- Verifier agents never see `orchestrator_set_grade` available via MCP
- They must use REST API instead
- Inconsistent tool availability between REST and MCP

### 3. **No Context Awareness in Tool Calls**

The MCP server doesn't know which task a client is connecting for. It learns the task context only when tools are called (from `run_id` and `task_id` arguments).

**Result:**
- Cannot pre-filter tools based on task status
- Can only validate/reject tool calls post-hoc
- Example: `orchestrator_submit` is available before BUILDING phase completes (only rejected at call time)

### 4. **Tool Validation Happens Post-Invocation**

Tools are registered and callable by all clients. Validation happens **after** the tool is invoked:

```python
# In ToolHandler.handle()
async def handle(self, name: str, arguments: dict) -> dict:
    # Tool is already called by client at this point
    # Now validate permissions/state

    task = await self.service.get_task(run_id, task_id)

    if name == "orchestrator_set_grade" and task.status != TaskStatus.VERIFYING:
        return {"error": "Can only grade during verification"}

    # If validation passes, execute
    return await getattr(self.service, tool_method)(...)
```

**Impact:**
- No pre-call filtering of unavailable tools
- Clients see all tools but some fail at call time
- Error messages must explain why tools are unavailable

### 5. **No Per-Connection Tool Filtering**

Each MCP client connection receives the same tool list. There's no way to:
- Scope tools to a specific task
- Filter tools based on step requirements
- Hide tools from clients not authorized to use them

### 6. **Hard-Coded Tool Sets in Constants**

Tool availability is defined as module-level constants:
```python
# mcp/server.py
BUILDER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_update_checklist",
    "orchestrator_submit",
    "orchestrator_request_clarification",
    "orchestrator_list_repos",
    "orchestrator_list_branches",
}

VERIFIER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_set_grade",
    "orchestrator_submit",
}
```

These cannot be modified at runtime or per-task.

## How Phase Is Currently Determined

**MCP Server Level:** Fixed at startup (hardcoded "building")

**REST API Level:** Dynamic per request
```python
# routers/tasks.py: prompt endpoint
async def get_task_prompt(run_id: str, task_id: str):
    task = await service.get_task(run_id, task_id)

    # Determine phase from task status
    phase = "verifying" if task.status == TaskStatus.VERIFYING else "building"

    # Return phase in response
    return PromptResponse(
        phase=phase,
        callback=CallbackInstructions(...)
    )
```

**Result:** REST API is phase-aware, MCP is not. Inconsistency for external agents.

## Enabling Step-Level Tool Control

### Option A: Context-Aware MCP Server (Recommended)

**Effort:** Medium | **Complexity:** Medium | **Scalability:** Good | **Recommended:** ✅

Create multiple MCP server instances or a router that knows task context:

**Approach 1: Per-Connection Scoping**
```python
class OrchestratorMCPServer:
    async def handle_sse_connection(self, run_id: str, task_id: str):
        """Create a scoped handler for this connection."""
        # Determine phase from task status
        task = await service.get_task(run_id, task_id)
        phase = "verifying" if task.status == TaskStatus.VERIFYING else "building"

        # Create handler that knows the task context
        handler = TaskScopedToolHandler(
            service=service,
            run_id=run_id,
            task_id=task_id,
            phase=phase
        )

        # Register only phase-appropriate tools
        server = FastMCP()
        for tool_name in get_tools_for_phase(phase):
            server.add_tool(
                name=tool_name,
                fn=handler.call_tool,
            )

        # Return SSE stream with scoped server
        async for message in server.handle_sse_async():
            yield message
```

Then MCP clients pass context in SSE URL:
```
GET /mcp/sse?run_id=run-123&task_id=task-456
```

**Pros:**
- ✅ Phase-aware tools per connection
- ✅ Step-level context available in handlers
- ✅ Non-breaking to REST API
- ✅ Shared with prompt endpoint design

**Cons:**
- ⚠️ Requires SSE endpoint changes
- ⚠️ Clients must pass context in URL
- ⚠️ Multiple server instances if many connections

**Approach 2: Tool Filtering Middleware**
```python
class ToolFilteringMiddleware:
    async def __call__(self, request: Request, call_next):
        # Extract context from tool call arguments
        body = await request.json()
        arguments = body.get("arguments", {})

        run_id = arguments.get("run_id")
        task_id = arguments.get("task_id")

        # Check if tool is allowed for this task's phase
        task = await service.get_task(run_id, task_id)
        phase = determine_phase(task)

        tool_name = body.get("method")  # or name, depending on protocol
        allowed_tools = get_tools_for_phase(phase)

        if tool_name not in allowed_tools:
            return JSONResponse(
                status_code=400,
                content={"error": f"Tool {tool_name} not available in {phase} phase"}
            )

        return await call_next(request)
```

**Pros:**
- ✅ Minimal server changes
- ✅ Validation at call time
- ✅ Clear error messages

**Cons:**
- ❌ Still shows all tools as available
- ❌ Only rejects at call time (UX issue)

### Option B: Per-Task MCP Server Instances

**Effort:** High | **Complexity:** High | **Scalability:** Medium | **Recommended:** ⚠️

Create a new MCP server for each task:
```python
# When task starts
task_mcp_server = OrchestratorMCPServer(
    handler=handler,
    phase=determine_task_phase(task),
    run_id=run_id,
    task_id=task_id,
)

# Register server with discovery mechanism
mcp_registry.register(run_id, task_id, task_mcp_server)
```

Clients connect to task-specific endpoints:
```
GET /api/runs/{run_id}/tasks/{task_id}/mcp/sse
```

**Pros:**
- ✅ Full per-task tool isolation
- ✅ Phase-aware from creation
- ✅ Clean separation

**Cons:**
- ❌ Many servers (one per task)
- ❌ Resource overhead
- ❌ Lifecycle management complexity
- ❌ Breaking change to MCP endpoints

### Option C: Dynamic Tool Updates via Heartbeat

**Effort:** Medium | **Complexity:** Medium | **Scalability:** Good | **Recommended:** ⚠️

MCP server periodically sends tool update notifications:
```python
# In server: detect phase changes
async def monitor_task_phase():
    while True:
        await asyncio.sleep(5)  # Check every 5 seconds
        for task_id, (old_phase, _) in task_phases.items():
            new_phase = determine_phase(task_id)
            if new_phase != old_phase:
                # Phase changed, update tools
                await broadcast_tool_update(task_id, new_phase)
```

Clients listen for updates and refresh tool list:
```
New tool update received:
- orchestrator_set_grade now available
- update your UI
```

**Pros:**
- ✅ Dynamic tool updates
- ✅ No server proliferation
- ✅ Works with existing global server

**Cons:**
- ⚠️ Polling overhead (latency)
- ⚠️ Clients must implement listener logic
- ⚠️ No guaranteed propagation speed

### Option D: Accept Current Limitations

**Effort:** None | **Complexity:** None | **Recommended:** ✅ Practical for now

User-managed agents are for external clients that manage their own tool lifecycle. Accept:
- Tools are phase-aware at REST API level (prompt endpoint)
- MCP tools are broader, with post-hoc validation
- External agents must check availability or handle errors
- For fine-grained control, use integrated agents (Claude SDK, Codex)

Document clearly that MCP tool availability is best-effort.

## Feasibility Summary

| Approach | Effort | Per-Task | Per-Step | Scope | Recommended |
|----------|--------|----------|----------|---|---|
| **Option A1** (Per-Conn) | Medium | ✅ | ✅ | SSE URL | ✅ **YES** |
| **Option A2** (Middleware) | Medium | ✅ | ✅ | Validation | ✅ **YES** |
| **Option B** (Per-Task Server) | High | ✅ | ✅ | Full | ⚠️ If needed |
| **Option C** (Heartbeat) | Medium | ✅ | ⚠️ | Updates | ⚠️ Advanced |
| **Option D** (Accept Limits) | None | ⚠️ | ❌ | Current | ✅ Practical |

## Comparison with Other Agents

| Agent | Tool Model | Scope | Phase-Aware | Per-Step | Enforcement |
|-------|---|---|---|---|---|
| Claude SDK | Integrated | Call | ✅ | ❌ | Pre-call |
| Codex Server | Integrated | Thread | ✅ | ❌ | Pre-call |
| OpenHands | Integrated | Agent | ✅ | ❌ | Pre-call |
| CLI | Text-based | Task | ✅ | ❌ | Post-call |
| User-Managed | MCP/REST | Global | ⚠️ | ❌ | Post-call |

## Recommendation

**Implement Option A1 (Per-Connection Scoping) to enable step-level control:**

1. **Modify SSE endpoint** to accept `run_id` and `task_id` query parameters
2. **Create TaskScopedToolHandler** that determines phase from task status
3. **Filter tools** registered to server based on phase
4. **Update CallbackInstructions** to indicate per-connection phase
5. **Document** that external agents should pass context in SSE URL

This approach:
- ✅ Enables phase-aware tools for MCP clients
- ✅ Supports step-level control via context
- ✅ Non-breaking to REST API
- ✅ Clear, scoped tool availability

**If more advanced filtering needed**, layer Option A2 (middleware) on top for post-hoc validation and better error messages.

## Files to Modify

1. `src/orchestrator/mcp/server.py` — Add context-aware tool registration
2. `src/orchestrator/api/routers/mcp.py` (or equivalent) — Update SSE endpoint to accept query params
3. `src/orchestrator/mcp/tools.py` — Create TaskScopedToolHandler
4. Test files — Integration tests for phase-aware tool filtering
5. Documentation — Clarify MCP tool availability model

## Implementation Checklist

- [ ] Update `/mcp/sse` endpoint to accept `?run_id=X&task_id=Y` parameters
- [ ] Create `TaskScopedToolHandler` class
- [ ] Modify `OrchestratorMCPServer.__init__()` to accept context parameters
- [ ] Implement phase detection in server initialization
- [ ] Register only phase-appropriate tools
- [ ] Add validation middleware for tool calls
- [ ] Test phase transitions and tool availability changes
- [ ] Update CallbackInstructions to show which tools are available
- [ ] Document SSE connection requirements for external agents
