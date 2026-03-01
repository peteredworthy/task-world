# OpenHands Agent: MCP Tool Control Analysis

## Current Implementation

The OpenHands agent integrates with the OpenHands SDK, which has its own tool registration and management system. Tools can be specified at agent construction time but are subject to **idempotency constraints** that limit per-call changes.

### Tool Architecture

OpenHands has two categories of tools:

**1. Built-in SDK Tools** (managed by OpenHands SDK):
- `terminal` — Execute shell commands
- `file_editor` — Read/write/edit files
- `browser` — Web navigation (optional)
- `glob` — File pattern matching
- `grep` — File searching

Registered via `register_builtin_tools(tool_names)` in `openhands_common.py:412-433`.

**2. Custom Orchestrator Tools** (defined in this project):
- `OrcGetRequirementsTool` — Get checklist items
- `OrcUpdateChecklistTool` — Update checklist status
- `OrcSubmitTool` — Submit for verification
- `OrcSetGradeTool` — Grade requirements (verifier only)
- `DockerOrcValidateRoutineTool` — Validate YAML (Docker version only)

Custom tools are implemented as `ToolDefinition` subclasses that must exist at **module scope** (required by SDK's `DiscriminatedUnionMixin`).

## Constraints for Dynamic Tool Control

### 1. **Global Registration with Idempotency Guard**

Built-in tools are registered via a global flag:
```python
_tools_registered = False

def _register_sdk_tools(tool_names: list[str] | None = None) -> None:
    global _tools_registered
    if _tools_registered:
        return  # Early exit prevents re-registration
    # ... register tools ...
    _tools_registered = True
```

**Impact:** Once tools are registered in a process, the flag prevents re-registration. Different `execute()` calls **cannot use different built-in tool sets** because:
- First call registers `["terminal", "file_editor"]`
- Second call with `["terminal"]` still sees both tools (flag prevents unregistering)
- No way to unregister tools without killing the process

### 2. **Tool Definitions Must Be Module-Level**

The OpenHands SDK requires all `ToolDefinition` subclasses to be defined at module level:
```python
# Valid (module level):
class OrcGetRequirementsTool(ToolDefinition):
    ...

# Invalid (inside function):
def create_custom_tools():
    class OrcGetRequirementsTool(ToolDefinition):  # ← Rejected by SDK
        ...
```

The SDK checks `__qualname__` to reject local classes. **Impact:** Tools cannot be created on-demand per task; they must exist at module definition time.

### 3. **Tool Specs Built at execute() Time**

While the underlying SDK tools are statically registered, the orchestrator tools **are instantiated per call**:
```python
# In execute() method (openhands.py:459-478):
registry_key = f"{run_id}:{task_id}"
_callback_registry.register(registry_key, ...)  # Create new callback set

# Build tool specs
orchestrator_tools = [
    OHTool(name="OrcGetRequirementsTool", params={"requirements": context.requirements}),
    OHTool(name="OrcUpdateChecklistTool", params={"registry_key": registry_key}),
    OHTool(name="OrcSubmitTool", params={"registry_key": registry_key}),
    OHTool(name="OrcSetGradeTool", params={"registry_key": registry_key}),
]
```

**Positive:** Custom tools can pass different `params` per call.
**Negative:** Built-in tools are fixed once registered.

### 4. **Callback Registry Lacks Step Context**

The `CallbackRegistry` stores callbacks per task but has no awareness of step configuration:
```python
class CallbackRegistry:
    def register(self, key: str, on_checklist_update, on_submit, loop, on_grade=None):
        self._store[key] = {
            "on_checklist_update": on_checklist_update,
            "on_submit": on_submit,
            "on_grade": on_grade,  # Only here - determines phase
            "loop": loop,
        }
```

The presence of `on_grade` is the **only** signal for phase detection. No step-level configuration is possible.

### 5. **ExecutionContext Lacks Step Information**

No `step_id`, `step_tools`, or other step context is available in `ExecutionContext`. The executor has this information but doesn't pass it through.

## Enabling Step-Level Tool Control

### Option A: Per-Tool-Set Process Pool (Most Robust)

**Effort:** Very High | **Complexity:** High | **Feasibility:** ✅ Possible

Keep separate agent instances in a pool, one per tool set:
```python
class OpenHandsAgentPool:
    def __init__(self):
        self._agents = {}  # tool_set -> agent instance

    async def get_agent(self, tool_set: frozenset[str]) -> OpenHandsAgent:
        if tool_set not in self._agents:
            # Create new agent for this tool set
            agent = OpenHandsAgent(tools=list(tool_set))
            self._agents[tool_set] = agent
        return self._agents[tool_set]

    async def execute(self, context: ExecutionContext, ...):
        tool_set = frozenset(context.available_tools or DEFAULT_OPENHANDS_TOOLS)
        agent = await self.get_agent(tool_set)
        return await agent.execute(context, ...)
```

**Pros:**
- ✅ Solves idempotency problem (each process registers once)
- ✅ Full per-task tool control
- ✅ Minimal code changes in agent itself

**Cons:**
- ❌ Multiple OpenHands processes running simultaneously
- ❌ Resource overhead (memory, network connections)
- ❌ Pool management complexity

### Option B: Runtime Tool Filtering (Recommended Short-Term)

**Effort:** Medium | **Complexity:** Low | **Feasibility:** ✅ Practical

Don't actually remove built-in tools from the SDK, but filter them in the agent's tool list sent to OpenHands:

```python
class OpenHandsAgent:
    def __init__(self, ..., tools: list[str] | None = None):
        self._tools = tools  # Store requested tools

    async def execute(self, context: ExecutionContext, ...):
        _register_sdk_tools(self._tools)  # Register (idempotent)

        # Filter: only include tools that were requested
        requested_tools = context.available_tools or self._tools or DEFAULT_OPENHANDS_TOOLS

        # Filter built-in tools
        builtin_tools = []
        for name in requested_tools:
            if name in ["terminal", "file_editor", "browser", "glob", "grep"]:
                builtin_tools.append(OHTool(name=name))

        # Include custom tools (all always available)
        orchestrator_tools = [
            OHTool(name="OrcGetRequirementsTool", params={...}),
            OHTool(name="OrcUpdateChecklistTool", params={...}),
            # ... others ...
        ]

        # Pass filtered list to OpenHands
        agent = OHAgent(llm=llm, tools=builtin_tools + orchestrator_tools)
        ...
```

**Note:** The SDK still has all tools registered, but we don't use them if not requested. OpenHands won't call tools we don't pass in the `tools` parameter.

**Pros:**
- ✅ Minimal code changes
- ✅ Single OpenHands process per agent
- ✅ Achieves functional per-task tool control

**Cons:**
- ⚠️ SDK still has registered tools (not removed, just unused)
- ⚠️ If OpenHands SDK changes behavior, might break

### Option C: Extended ExecutionContext (Phase 1)

**Effort:** Low | **Complexity:** Minimal | **Feasibility:** ✅ Non-breaking

Add step context to `ExecutionContext`:
```python
class ExecutionContext(BaseModel):
    # ... existing ...
    step_id: str | None = None
    available_tools: list[str] | None = None
```

Update executor to populate these. Then in agent, use context fields for tool filtering.

**Pros:**
- ✅ Shared with Claude SDK and Codex agents
- ✅ Non-breaking
- ✅ Low effort

**Cons:**
- ⚠️ Requires executor changes
- ⚠️ Still subject to SDK registration idempotency

### Option D: OpenHands SDK Extension (Future)

**Effort:** Very High | **Compatibility:** Requires upstream | **Feasibility:** Uncertain

Propose to OpenHands SDK team:
- Per-call tool registration (not global)
- Tool unregistration support
- Module-local tool definitions

**Cons:**
- ❌ Requires upstream changes
- ❌ Uncertain timeline
- ❌ High complexity

## Current Phase Detection

Phase detection uses callback presence:
```python
# In executor.py: line 712-718
if task_state.status == TaskStatus.VERIFYING:
    on_grade = on_grade_callback  # Grading enabled
else:
    on_grade = None  # Grading disabled

result = await agent.execute(context, ..., on_grade=on_grade)
```

Then in `OrcSetGradeTool.create()`:
```python
@classmethod
def create(cls, *args, **kwargs):
    reg = _callback_registry.get(kwargs["registry_key"])
    on_grade = reg.get("on_grade")
    if on_grade is None:
        return []  # Tool not available in builder phase
    # ... create tool ...
```

This works well for phase detection but doesn't support step-level tool control.

## Feasibility Summary

| Approach | Effort | Process Count | Per-Task | Per-Turn | Recommended |
|----------|--------|---|---|---|---|
| **Option A** (Pool) | Very High | Multiple | ✅ | ✅ | ⚠️ Future |
| **Option B** (Filtering) | Medium | Single | ✅ | ✅ | ✅ **YES** |
| **Option C** (Context) | Low | Single | ✅ | ✅ | ✅ **YES** |
| **Option D** (SDK Ext) | Very High | — | ? | ? | ⚠️ Future |

## Comparison with Other Agents

| Agent | Tool Param | Per-Call | Idempotency | Step Context | MCP |
|-------|---|---|---|---|---|
| Claude SDK | ❌ | ✅ (API) | N/A | ❌ | ❌ |
| Codex Server | ❌ | ❌ (immutable) | N/A | ❌ | ❌ |
| OpenHands | ✅ | ⚠️ (SDK blocks) | ❌ (global flag) | ❌ | ✅ |
| CLI | ❌ | ❌ | N/A | ❌ | ⚠️ |

## Recommendation

**Implement Options C + B together:**

1. **Phase 1:** Extend `ExecutionContext` with step information (same as other agents)
2. **Phase 2:** Implement Option B (runtime filtering in agent)

This approach:
- ✅ Achieves step-level tool control
- ✅ Minimal code changes
- ✅ Single process per agent (no pooling overhead)
- ✅ Shared with other agents' ExecutionContext extension
- ✅ Non-breaking to existing API

**Later:** If full tool lifecycle management becomes critical (unregistering tools), explore Option A (process pool).

## Files to Modify

1. `src/orchestrator/agents/types.py` — Add `step_id`, `available_tools` to ExecutionContext
2. `src/orchestrator/agents/openhands.py` — Update `execute()` to filter tools based on context
3. `src/orchestrator/agents/executor.py` — Populate step context
4. `src/orchestrator/agents/openhands_common.py` — Update CallbackRegistry if needed for step config
5. Test files — Unit/integration tests with tool filtering

## Implementation Checklist

- [ ] Add `step_id`, `available_tools` to `ExecutionContext` in types.py
- [ ] Update executor to populate step context when creating ExecutionContext
- [ ] Modify `OpenHandsAgent.execute()` to filter built-in tools based on `context.available_tools`
- [ ] Test filtering logic (builder vs verifier, step-specific tools)
- [ ] Test that OpenHands SDK only receives filtered tool list
- [ ] Add integration test: verify tools unavailable to agent are not called
- [ ] Document tool filtering behavior in agent class docstring
