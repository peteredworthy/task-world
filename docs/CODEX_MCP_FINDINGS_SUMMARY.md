# Codex Server MCP Investigation: One-Page Summary

**Investigation Date:** February 27, 2026 | **Status:** Complete

---

## Quick Answers

### Q1: Does Codex Server support MCPs at all currently?

**✅ YES** — Codex accepts `dynamicTools` in JSON-RPC `thread/start` request, which can represent any MCP tool definition.

### Q2: Can MCPs be passed to the codex app-server subprocess?

**✅ YES** — Via the JSON-RPC protocol. Each subprocess (spawned per task) receives tool definitions in the `thread/start` handshake message.

### Q3: What format would MCPs need to be in?

**JSON Schema format:**
```json
{
  "name": "tool_name",
  "description": "What the tool does",
  "inputSchema": {
    "type": "object",
    "properties": {"param": {"type": "string"}},
    "required": ["param"]
  }
}
```

Compatible with Claude API, OpenHands, and MCP tool specs (after conversion).

### Q4: Can the JSON-RPC protocol handle MCP specifications?

**✅ FULLY** — JSON-RPC just transports JSON. MCPs are plain objects in the `dynamicTools` array. No protocol limitations.

### Q5: Can MCPs be different per thread/per execution?

**✅ PER-TASK** — Each task gets a new subprocess thread. Different tasks = different threads = different tool sets possible.

**❌ PER-STEP** — Within a task, tools are locked at thread creation. No per-turn tool updates. Would need:
- Multiple threads per task (high overhead, loses context), OR
- Upstream Codex protocol extension (add `dynamicTools` to `turn/start`)

---

## Current Behavior

### Tool Lifecycle

```
Agent.execute() called
    ↓
Spawn subprocess: codex app-server
    ↓
Send JSON-RPC initialize (enable experimentalApi)
    ↓
Send JSON-RPC thread/start with dynamicTools: [...]
    ↓ ← TOOLS LOCKED HERE
    ↓
Send JSON-RPC turn/start with prompt
    ↓
Agent processes prompt, invokes tools
    ↓
Server sends item/tool/call notifications
    ↓
Client responds with tool results
    ↓
Server sends item/agentMessage/delta notifications
    ↓
Server sends turn/completed (terminal)
    ↓
Close subprocess, clean up CODEX_HOME
```

**Key constraint:** Once `thread/start` succeeds, tool set is immutable. No way to change tools until thread closes.

### Tool Specs Passed to Subprocess

Currently, `build_dynamic_tool_specs()` returns 5 tools (always):
1. `update_checklist` — Mark requirement status
2. `grade` — Set requirement grade (verifier phase, but currently always registered)
3. `submit` — Submit work
4. `request_clarification` — Ask questions
5. `complete_recovery` — Finalize recovery

**Post-hoc filtering** via `CODEX_SERVER_TOOL_ALLOWLIST` frozenset only prevents invocation, doesn't prevent registration.

---

## To Enable Dynamic MCPs Per Task

### Minimal Changes (3 steps)

**Step 1: Extend ExecutionContext** (5 minutes)
```python
# src/orchestrator/agents/types.py
class ExecutionContext(BaseModel):
    # ... existing fields ...
    available_tools: list[str] | None = None  # NEW: which tools are allowed
```

**Step 2: Update Executor** (10 minutes)
```python
# src/orchestrator/agents/executor.py, line 654+
step_config = run.routine.steps[run.current_step_index]
context = ExecutionContext(
    # ... existing fields ...
    available_tools=step_config.available_tools,  # NEW
)
```

**Step 3: Filter Tools in Agent** (15 minutes)
```python
# src/orchestrator/agents/codex_server.py, line 435
tool_specs = build_dynamic_tool_specs()
if context.available_tools:
    allowed = set(context.available_tools)
    tool_specs = [t for t in tool_specs if t["name"] in allowed]
```

**Result:** Different tasks/threads can have different tool sets based on step configuration.

---

## Architectural Constraints

| Aspect | Status | Notes |
|--------|--------|-------|
| **Per-task tool variation** | ✅ Possible | Each task = new thread = new tool set |
| **Per-step tool variation** | ⚠️ Workaround only | Would need thread-per-step or protocol extension |
| **Dynamic tool registration** | ✅ Possible | Read from config/context, pass to `thread/start` |
| **Per-turn tool changes** | ❌ Not supported | No `dynamicTools` in `turn/start` |
| **Tool schema flexibility** | ✅ Full | Any JSON Schema tool accepted |
| **External MCP integration** | ✅ Possible | Build tool specs from MCP server, pass to thread |

---

## JSON-RPC Handshake Overview

Four steps, each with request/response:

```
1. initialize (enable experimentalApi)
   ↓
2. account/login/start (optional, if API key provided)
   ↓
3. thread/start (REGISTER TOOLS HERE via dynamicTools param) ← CRITICAL
   ↓
4. turn/start (submit prompt, model optional, tools NO)
   ↓
(Notifications stream until turn/completed)
```

**Critical points:**
- `experimentalApi: true` in `initialize` enables `dynamicTools`
- `dynamicTools` only in `thread/start`, not `turn/start`
- Tools are immutable after `thread/start` response

---

## Recommended Implementation Path

### Phase 0: Prerequisites (5 min)
Add `available_tools` field to `StepConfig`:
```python
class StepConfig(BaseModel):
    id: str
    description: str
    available_tools: list[str] | None = None  # ← NEW
```

### Phase 1: Context Extension (30 min)
Extend `ExecutionContext` and update executor to populate from step config.

### Phase 2a: Quick Win — Codex Phase Filtering (15 min)
Make `build_dynamic_tool_specs()` accept `is_verifier` parameter:
```python
def build_dynamic_tool_specs(is_verifier: bool = False) -> list[dict]:
    base_tools = [update_checklist, submit, request_clarification]
    if is_verifier:
        base_tools.append(grade)
    return base_tools
```

### Phase 2b: Agent Filtering (20 min per agent)
Implement filtering in Claude SDK, Codex, OpenHands agents.

**Total effort:** ~2 hours for full implementation, 30 minutes for Codex only.

---

## Files to Modify

### For Step-Level Tool Control

| File | Purpose | Effort | Phase |
|------|---------|--------|-------|
| `src/orchestrator/config/models.py` | Add `available_tools` to StepConfig | 5 min | 0 |
| `src/orchestrator/agents/types.py` | Add `available_tools` to ExecutionContext | 5 min | 1 |
| `src/orchestrator/agents/executor.py` | Populate context from step config | 15 min | 1 |
| `src/orchestrator/agents/codex_server_common.py` | Add `is_verifier` parameter | 15 min | 2a |
| `src/orchestrator/agents/codex_server.py` | Filter tools, pass phase info | 20 min | 2a |

### Reference Documentation

| File | Content |
|------|---------|
| `/docs/CODEX_SERVER_MCP_INVESTIGATION.md` | Full investigation with code examples |
| `/docs/CODEX_JSONRPC_HANDSHAKE_REFERENCE.md` | JSON-RPC protocol details, message flow |
| `/docs/mcp-control/codex-server-agent.md` | Original MCP control analysis |
| `/docs/mcp-control/IMPLEMENTATION-ROADMAP.md` | Implementation guide for all agents |

---

## Key Insights

1. **Codex subprocess is stateless per-task** — Each execution gets its own process, so different executions can have different tool sets trivially.

2. **JSON-RPC handshake is the integration point** — MCPs are represented as JSON Schema tools in the `dynamicTools` array passed to `thread/start`.

3. **Tools are locked per-thread** — Once `thread/start` succeeds, tool set is immutable for that thread's lifetime. Per-turn changes would require protocol extension.

4. **Execution model is per-task** — The executor creates one task per workflow step, and each task creation involves a full subprocess lifecycle. This enables per-task tool variation.

5. **Step context is available but not passed** — The executor has access to step configuration with tools info, but doesn't currently pass it to agents. Minimal changes enable this.

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|-----------|
| Add `available_tools` to StepConfig | Very Low | Optional field, backward compatible |
| Add `available_tools` to ExecutionContext | Very Low | Optional field, doesn't affect existing code |
| Modify tool filtering logic | Low | Existing tests cover tool allow-list enforcement |
| Pass context to agents | Low | Only adds optional fields to existing signature |

**Recommended approach:** Implement Phase 0 + Phase 1 first as non-breaking foundation. Then implement Phase 2 per-agent.

---

## Next Actions

1. **Decision:** Proceed with Phase 0 + Phase 1 (Foundation)
2. **Implementation:** Codex Server Phase Filtering (Phase 2a) as quick win
3. **Expansion:** Apply pattern to Claude SDK, OpenHands, CLI agents
4. **Testing:** Update unit/integration tests for tool filtering

**Timeline:** 2-3 weeks for full implementation across all agents.

---

## See Also

- **For protocol details:** `/docs/CODEX_JSONRPC_HANDSHAKE_REFERENCE.md`
- **For full analysis:** `/docs/CODEX_SERVER_MCP_INVESTIGATION.md`
- **For all agents:** `/docs/mcp-control/00-START-HERE.md`
- **For code examples:** `/docs/mcp-control/IMPLEMENTATION-ROADMAP.md`
