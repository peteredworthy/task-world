# Codex Server Agent: MCP Tool Control Analysis

## Current Implementation

The Codex Server agent communicates with the Codex server via a JSON-RPC protocol over stdin/stdout. Tools are registered **once at thread creation** and remain immutable for the entire conversation.

### Tool Architecture

Tools are defined via `build_dynamic_tool_specs()` in `/src/orchestrator/agents/codex_server_common.py` (lines 173-258):
- `update_checklist` (all phases)
- `grade` (verifier only)
- `submit` (all phases)
- `request_clarification` (all phases)
- `complete_recovery` (special)

Tools are passed in the `thread/start` JSON-RPC request parameter and persist for the thread lifetime.

### Tool Enforcement

All tool calls are validated post-invocation via `enforce_tool_allowlist()` which checks against a module-level `frozenset` of allowed tools. This provides an additional safety layer but doesn't enable dynamic tool control.

## Constraints for Dynamic Tool Control

### 1. **Tools Specified at Thread Creation Only**

Tools are passed in `thread/start` and cannot be modified:
```json
{
  "method": "thread/start",
  "params": {
    "dynamicTools": [
      {"name": "update_checklist", ...},
      {"name": "submit", ...}
    ]
  }
}
```

Once the thread is created with this tool set, **no API exists to update tools** for the thread's lifetime.

### 2. **No Per-Turn Tool Updates**

The JSON-RPC protocol supports `turn/start` to begin a new turn, but it has no parameter to update tools:
```json
{
  "method": "turn/start",
  "params": {}
  // No "dynamicTools" parameter here
}
```

Adding such a parameter would require **Codex server protocol extension**, which is upstream from this project.

### 3. **Static Allow-List Enforcement**

Tool allowlist is defined at module initialization:
```python
CODEX_SERVER_TOOL_ALLOWLIST = frozenset([
    "update_checklist",
    "grade",
    "submit",
    "request_clarification",
    "complete_recovery",
])
```

This prevents dynamic tool registration but also prevents accidental exposure of undefined tools.

### 4. **Each Execution Gets Its Own Thread**

Each `execute()` call spawns a new `codex app-server` subprocess with isolated `CODEX_HOME`. This means:
- ✅ Tools can differ between different task executions (via different `thread/start` calls)
- ❌ Tools cannot change within a single task execution (conversation is ongoing)

### 5. **ExecutionContext Lacks Step Information**

Like Claude SDK agent, the executor doesn't pass step-level context:
```python
# What executor provides:
context = ExecutionContext(
    run_id=...,
    task_id=...,
    prompt=...,
    requirements=...,
)

# What's needed for step-level control:
context = ExecutionContext(
    run_id=...,
    task_id=...,
    prompt=...,
    requirements=...,
    step_id=...,           # ← MISSING
    step_tools=[...],      # ← MISSING
)
```

## Enabling Step-Level Tool Control

### Option A: Extend ExecutionContext + Filter Tool Specs (Recommended)

**Effort:** Medium | **Compatibility:** Non-breaking | **Per-Step:** ✅ Yes

1. **Add fields to ExecutionContext** (as Claude SDK agent does):
```python
class ExecutionContext(BaseModel):
    # ... existing fields ...
    step_id: str | None = None
    step_tools: list[str] | None = None
```

2. **Refactor `build_dynamic_tool_specs()` to accept context**:
```python
def build_dynamic_tool_specs(
    context: ExecutionContext,
    phase: AgentPhase
) -> list[dict]:
    """Build tool specs, filtering by available tools."""
    all_tools = {
        "update_checklist": {...},
        "grade": {...},
        "submit": {...},
        "request_clarification": {...},
        "complete_recovery": {...},
    }

    # Filter by step-specified tools
    available = context.step_tools or list(all_tools.keys())

    # Phase-aware filtering
    if phase == AgentPhase.BUILDER:
        available = [t for t in available if t != "grade"]

    # Build tool list
    return [all_tools[name] for name in available if name in all_tools]
```

3. **Update executor to populate step context**:
```python
# In executor.py, around line 620
step_index = run.current_step_index
step_config = run.routine.steps[step_index]

context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    prompt=prompt_text,
    requirements=task_state.checklist_items,
    step_id=step_config.id,
    step_tools=step_config.tools,  # ← Use step's tool spec
)
```

4. **Update `codex_server.py` to use filtered specs**:
```python
async def execute(self, context: ExecutionContext, ...):
    tool_specs = build_dynamic_tool_specs(context, self._phase)
    # Pass to thread/start request
    await self._json_rpc_client.call("thread/start", {
        "dynamicTools": tool_specs,
        ...
    })
```

**Pros:**
- ✅ Non-breaking to existing API
- ✅ Allows per-task tool variation
- ✅ Supports step-level control
- ✅ Uses existing Codex capabilities

**Cons:**
- ❌ Cannot change tools mid-conversation (only at task start)
- ❌ Requires executor changes

### Option B: Thread-Per-Step Pattern (More Granular)

**Effort:** High | **Compatibility:** Breaking | **Per-Step:** ✅ Full control

If a routine has multiple steps within a single run, create a separate thread for each step:
```python
# Step 1: Thread A with tools=[...]
await execute(context_step1)  # Creates new thread

# Step 2: Thread B with different tools=[...]
await execute(context_step2)  # New thread, no conversation history
```

**Pros:**
- ✅ Full per-step tool control
- ✅ Each step isolated

**Cons:**
- ❌ Loses conversation context across steps
- ❌ More threads = more overhead
- ❌ Requires task/step model redesign

### Option C: Codex Protocol Extension (Future)

**Effort:** Very High | **Compatibility:** Requires upstream | **Per-Step:** ✅ Dynamic

Propose to Codex team:
```json
{
  "method": "turn/start",
  "params": {
    "dynamicTools": [...]  // Update tools per turn
  }
}
```

**Pros:**
- ✅ True per-turn tool control
- ✅ Maintains conversation continuity

**Cons:**
- ❌ Requires changes upstream (Codex server)
- ❌ High complexity
- ❌ Uncertain timeline

## Current Phase Detection

Phase is currently inferred from callback presence:
```python
# In codex_server.py:364
is_verifier = on_grade is not None
phase = AgentPhase.VERIFIER if is_verifier else AgentPhase.BUILDER
```

This is adequate but means phase is baked into tool specs at `thread/start` time. If a single conversation transitioned from builder to verifier, tools wouldn't update.

## Feasibility Summary

| Approach | Effort | Per-Task | Per-Turn | Breaking | Recommended |
|----------|--------|----------|----------|----------|-------------|
| **Option A** | Medium | ✅ | ❌ | ❌ | ✅ **YES** |
| **Option B** | High | ✅ | ✅ | ✅ | ⚠️ If needed |
| **Option C** | Very High | ✅ | ✅ | N/A | ⚠️ Future |

## Comparison with Other Agents

| Agent | Per-Task Tools | Per-Turn Tools | Phase-Based | Step Context |
|-------|---|---|---|---|
| Claude SDK | ✅ (via API) | ✅ (via API) | ✅ | ❌ |
| Codex Server | ✅ (new thread) | ❌ (immutable) | ✅ | ❌ |
| OpenHands | ⚠️ (SDK flags prevent) | ❌ | ✅ | ❌ |
| CLI | ❌ | ❌ | ✅ | ❌ |

## Recommendation

**Implement Option A** to enable step-level tool control:
1. Extend `ExecutionContext` with `step_id` and `step_tools` (same as Claude SDK)
2. Refactor `build_dynamic_tool_specs()` to filter based on context
3. Update executor to populate step context
4. Keep thread model as-is (per-task threads work fine)

This approach:
- ✅ Enables step-level tool configuration
- ✅ Doesn't break existing API
- ✅ Works within Codex server's protocol constraints
- ✅ Shares implementation pattern with Claude SDK agent

**Future:** If per-turn tool updates become critical, evaluate Option B or propose Option C upstream.

## Files to Modify

1. `src/orchestrator/agents/types.py` — Extend ExecutionContext
2. `src/orchestrator/agents/codex_server_common.py` — Update `build_dynamic_tool_specs()`
3. `src/orchestrator/agents/codex_server.py` — Pass context to tool builder
4. `src/orchestrator/agents/executor.py` — Populate step context
5. Test files — Unit/integration tests with new fields

## Implementation Checklist

- [ ] Add `step_id`, `step_tools` to `ExecutionContext`
- [ ] Update `build_dynamic_tool_specs()` signature and implementation
- [ ] Update all calls to `build_dynamic_tool_specs()` with context parameter
- [ ] Add step context extraction in executor
- [ ] Test phase-based filtering (builder vs verifier)
- [ ] Test step-specific tool filtering
- [ ] Update integration tests for tool availability
