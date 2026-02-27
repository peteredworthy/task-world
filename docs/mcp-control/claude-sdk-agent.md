# Claude SDK Agent: MCP Tool Control Analysis

## Current Implementation

The Claude SDK agent provides callback tools via the Anthropic Messages API. Currently, **no MCP integration exists** — the agent only uses the four hardcoded orchestrator callback tools.

### Tool Architecture

Tools are **statically defined** in `/src/orchestrator/agents/claude_sdk.py`:
- `update_checklist` (all phases)
- `submit` (all phases)
- `request_clarification` (all phases)
- `grade` (verifier phase only)

Tools are selected based on whether the `on_grade` callback is provided, giving basic phase detection.

### API Capabilities

**Good news:** The underlying Anthropic Messages API fully supports per-call tool specification:
```python
response = client.messages.create(
    model=model,
    max_tokens=max_tokens,
    tools=tools,  # ← Can differ per call
    messages=messages,
)
```

**Current limitation:** The Claude SDK agent wrapper doesn't expose this capability. There's no constructor parameter for tool specification (unlike OpenHands agent which accepts `tools: list[str]`).

## Constraints for Dynamic Tool Control

### 1. **No Tool Parameter in Constructor**
The agent doesn't accept a `tools` parameter:
```python
# Current: no tools parameter
agent = ClaudeSDKAgent(api_key=..., model=...)

# Desired:
agent = ClaudeSDKAgent(api_key=..., model=..., tools=[...])
```

### 2. **Tools Only Vary by Phase**
No way to enable/disable individual tools or add custom ones. The only conditional logic is:
```python
if on_grade:  # verifier phase
    include_grade_tool()
```

### 3. **ExecutionContext Lacks Step Information**
When the agent executes, it receives minimal context:
- `run_id`, `task_id` (for identifying the work)
- `prompt`, `requirements` (for task description)
- **Missing:** `step_id`, `step_config`, `step_tools`

The executor has all this information but doesn't pass it through.

### 4. **Tool Schemas Are Hardcoded**
Tool definitions are literal Python dicts with no metadata-driven approach:
```python
{
    "name": "update_checklist",
    "description": "...",
    "input_schema": {...}
}
```

Dynamically constructing tools requires building these schemas at runtime.

## Enabling Step-Level Tool Control

### Phase 1: Extend ExecutionContext (Low Risk)

Add optional fields to `ExecutionContext` in `types.py`:
```python
class ExecutionContext(BaseModel):
    run_id: str
    task_id: str
    # ... existing fields ...

    # NEW: Step-level context
    step_id: str | None = None
    step_index: int | None = None
    step_total: int | None = None
    step_tools: list[str] | None = None
```

Update executor to populate these when creating the context.

### Phase 2: Add Tool Parameter to ClaudeSDKAgent (Medium Risk)

Modify the agent constructor to accept tools:
```python
class ClaudeSDKAgent:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-opus-4-6",
        tools: list[str] | None = None,  # ← NEW
    ):
        self._tools = tools
```

In `execute()`, build the tool set based on available tools and phase:
```python
async def execute(self, context: ExecutionContext, ...):
    # Start with context-specified tools
    available_tools = context.step_tools or self._tools

    # Build tool list with filtering
    tools_to_use = []
    if available_tools is None or "update_checklist" in available_tools:
        tools_to_use.append(build_update_checklist_tool())
    if available_tools is None or "submit" in available_tools:
        tools_to_use.append(build_submit_tool())
    # ... etc, with phase-based filtering for grade tool

    # Use in API call
    response = self.client.messages.create(
        model=self.model,
        tools=tools_to_use,
        messages=messages,
        max_tokens=4000,
    )
```

### Phase 3: Add Tool Registry (Future)

Create a composable tool registry instead of hardcoded schemas:
```python
class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name: str, tool_def: dict):
        self._tools[name] = tool_def

    def get_tools(self, names: list[str] | None = None) -> list[dict]:
        if names is None:
            return list(self._tools.values())
        return [self._tools[name] for name in names if name in self._tools]
```

## Feasibility Summary

| Aspect | Status | Effort |
|--------|--------|--------|
| **Underlying API support** | ✅ Full support in Anthropic SDK | — |
| **Phase 1 (ExecutionContext)** | ✅ Safe, non-breaking | Low |
| **Phase 2 (Tool parameter)** | ✅ Feasible | Medium |
| **Phase 3 (Registry)** | ✅ Feasible | Medium |
| **Step-level control** | ⚠️ Achievable with phases 1-2 | Medium |
| **Custom MCP tools** | ⚠️ Requires registry + MCP server | High |

## Comparison with Other Agents

| Agent | Tool Param | Per-Call | Phase-Based | Step-Based | MCP Support |
|-------|-----------|----------|-------------|-----------|-------------|
| Claude SDK | ❌ | ✅ (API) | ✅ | ❌ | ❌ |
| Codex Server | ❌ | ❌ (immutable) | ✅ | ❌ | ❌ |
| OpenHands | ✅ | ⚠️ (flags prevent re-register) | ✅ | ❌ | ✅ |
| CLI | ❌ | ❌ (prompt immutable) | ✅ | ❌ | ⚠️ (text-based) |
| User-Managed | ⚠️ | ⚠️ (MCP static at startup) | ⚠️ | ❌ | ✅ |

## Recommendation

**Implement Phase 1 + 2** to enable step-level control for Claude SDK agent:
1. Extend `ExecutionContext` with step information (non-breaking)
2. Add `tools` parameter to `ClaudeSDKAgent`
3. Filter callback tools based on `context.step_tools` and phase

This gives flexibility without major API changes. Phase 3 (registry) can wait until multiple agents need it.

## Files to Modify

1. `src/orchestrator/agents/types.py` — Add fields to ExecutionContext
2. `src/orchestrator/agents/claude_sdk.py` — Add tools parameter and filtering
3. `src/orchestrator/agents/executor.py` — Populate step fields in context
4. Test files — Update unit/integration tests with new context fields
