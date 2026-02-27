# MCP Tool Control: Agent-by-Agent Analysis

This directory contains a comprehensive investigation of **how to specify MCP tool availability on a step-by-step basis** across all agent types in the task-world orchestrator.

## Quick Summary

The challenge: Each agent type manages tools differently, and all can support dynamic per-step external MCPs.

**Key findings:**
- All five agent types natively support external MCPs (chrome-mcp, context7, etc.)
- MCPs are naturally scoped per execution boundary (no global registration needed)
- The underlying APIs support dynamic per-call/per-request tool specification
- **Codex Server optimization:** Use one process per run with threads per task (~30% performance gain)

**Recommendation:** Extend `ExecutionContext` with step information across all agents, pass MCPs natively to each agent type per execution boundary.

## Agent Type Analyses

### 1. **Claude SDK Agent** (`claude-sdk-agent.md`)
- **Current:** Hardcoded callback tools, phase-based selection only
- **Capability:** Anthropic API fully supports per-call tool specification
- **Limitation:** Wrapper doesn't expose this capability
- **Recommendation:** Add `tools` parameter, filter based on `context.step_tools`
- **Effort:** Medium | **Feasibility:** ✅ High

### 2. **Codex Server Agent** (`codex-server-agent.md`)
- **Current:** Tools registered at thread creation, immutable for lifetime
- **Capability:** JSON-RPC protocol allows per-thread different tool sets
- **Limitation:** No API to update tools mid-conversation
- **Recommendation:** Different threads per task with filtered tool specs, extend ExecutionContext
- **Effort:** Medium | **Feasibility:** ✅ High

### 3. **OpenHands Agent** (`openhands-agent.md`)
- **Current:** Tools registered globally with idempotency guard
- **Capability:** Can specify tools at agent construction
- **Limitation:** Global registration flag prevents unregistering tools
- **Recommendation:** Runtime tool filtering in execute() method, extend ExecutionContext
- **Effort:** Medium | **Feasibility:** ✅ High (workaround exists)

### 4. **Codex Server Architecture** (`CODEX-SERVER-OPTIMIZATION.md`) ⭐
- **Current Implementation:** One process per task (wasteful, ~500ms overhead per task)
- **Optimized Architecture:** One process per run, threads per task (efficient, ~500ms overhead per run)
- **Key Insight:** Codex protocol supports multiple threads in single process; current implementation doesn't leverage this
- **threadId Tracking:** Codex notifications include threadId/turnId for validation and future parallelism
- **MCP Impact:** No change - MCPs passed to thread via `dynamicTools`, not process
- **Performance:** ~30% faster for typical multi-task runs
- **Future-Ready:** Infrastructure prepared for parallel task support (via threadId routing)
- **Effort:** 6-7.5 hours (includes threadId tracking) | **Feasibility:** ✅ High | **Benefit:** Significant performance improvement + future parallelism support

### 5. **Codex threadId Tracking** (`CODEX-THREADID-TRACKING.md`) 🔮
- **Design Document:** How threadId tracking enables current robustness and future parallelism
- **Notification Routing:** Protocol includes threadId for routing notifications to correct thread
- **Current Use:** Validation and better logging in sequential execution mode
- **Future Use:** Foundation for parallel task execution (no architectural changes needed)
- **Implementation:** ThreadState tracking, validation, routing, and test fixtures
- **Infrastructure Ready:** Can support parallel tasks immediately when executor changes

### 4. **CLI Agent** (`cli-agent.md`)
- **Current:** Tools described as text in prompt, subprocess reads and adapts
- **Capability:** Subprocess can independently manage MCP connections
- **Limitation:** Prompt is immutable after sending, no bidirectional channel
- **Recommendation:** Template-based phase control, or process-per-step redesign
- **Effort:** Low-High depending on approach | **Feasibility:** ✅ Medium

### 5. **User-Managed Agent** (`user-managed-agent.md`)
- **Current:** Single global MCP server with phase hardcoded to "building"
- **Capability:** MCP server can be context-aware
- **Limitation:** No per-task or per-step tool scoping today
- **Recommendation:** Per-connection MCP server instance, extract phase from task context
- **Effort:** Medium | **Feasibility:** ✅ High

## Common Pattern Across All Agents

All agents lack **step-level context** in their `ExecutionContext`:

```python
# Current ExecutionContext (missing step info)
class ExecutionContext(BaseModel):
    run_id: str
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    # ← NO step_id, step_index, step_tools, etc.
```

**Solution:** Extend ExecutionContext uniformly:
```python
class ExecutionContext(BaseModel):
    # ... existing fields ...
    step_id: str | None = None
    step_index: int | None = None
    step_total: int | None = None
    step_tools: list[str] | None = None
```

Update executor to populate these when creating context.

## Phase-1 Implementation Strategy

For **all agents**, use this three-phase approach:

### Phase 1: Extend ExecutionContext (Low Risk)
- Add `step_id`, `step_index`, `step_tools` to `types.py`
- Update executor to populate from step config
- **Impact:** Non-breaking, enables step awareness

### Phase 2: Agent-Specific Tool Filtering (Medium Risk)
- **Claude SDK:** Add `tools` parameter, filter at execute time
- **Codex Server:** Refactor `build_dynamic_tool_specs()` to filter by context
- **OpenHands:** Filter builtin tools in execute() method
- **CLI:** Create phase-based prompt templates
- **User-Managed:** Per-connection MCP server with context

### Phase 3: Uniform Tool Registry (Future)
- Create shared `ToolRegistry` class
- Decouple tool specs from agent implementations
- Enable custom tools per step

## Files Requiring Changes

| File | Change | Agents Affected |
|------|--------|-----------------|
| `src/orchestrator/agents/types.py` | Extend `ExecutionContext` | All 5 |
| `src/orchestrator/agents/executor.py` | Populate step context | All 5 |
| `src/orchestrator/agents/claude_sdk.py` | Add tools parameter + filtering | Claude SDK |
| `src/orchestrator/agents/codex_server_common.py` | Refactor tool spec builder | Codex Server |
| `src/orchestrator/agents/openhands.py` | Add runtime tool filtering | OpenHands |
| `src/orchestrator/agents/cli.py` | Phase-based templates | CLI |
| `src/orchestrator/mcp/server.py` | Per-connection scoping | User-Managed |
| Test files | Update for new context fields | All 5 |

## Implementation Checklist

- [ ] **Phase 1:** Extend `ExecutionContext` in `types.py`
- [ ] **Phase 1:** Update executor to populate step context
- [ ] **Phase 2:** Claude SDK — add tools parameter and filtering
- [ ] **Phase 2:** Codex Server — refactor tool specs with filtering
- [ ] **Phase 2:** OpenHands — implement runtime tool filtering
- [ ] **Phase 2:** CLI — create phase-based templates
- [ ] **Phase 2:** User-Managed — implement per-connection MCP server
- [ ] **Testing:** Unit tests for tool filtering per agent
- [ ] **Testing:** Integration tests for step-level tool availability
- [ ] **Documentation:** Update agent configuration docs
- [ ] **Documentation:** Add examples of step-level tool configuration

## Comparison Matrix

| Feature | Claude SDK | Codex | OpenHands | CLI | User-Managed |
|---------|---|---|---|---|---|
| **Tool Param at Construction** | ❌ → ✅ | ❌ | ✅ | ❌ | N/A |
| **Per-Call Tool Spec** | ✅ (API) | ✅ (threads) | ⚠️ (SDK blocks) | ❌ | ✅ (MCP/REST) |
| **Phase-Based Control** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| **Step-Level Control** | ❌ → ✅ | ❌ → ✅ | ❌ → ✅ | ❌ → ⚠️ | ❌ → ✅ |
| **Mid-Execution Updates** | ✅ | ❌ | ⚠️ | ❌ | ⚠️ |
| **MCP Integration** | ❌ | ❌ | ✅ | ⚠️ (text) | ✅ |

## Key Insights

1. **API Support is Better Than Implementations**
   - Anthropic SDK supports per-call tools
   - Codex server can have different tool sets per thread
   - OpenHands SDK accepts tool parameters
   - But our wrappers don't expose these capabilities

2. **Phase Detection Works, Step Detection Doesn't**
   - All agents can distinguish builder from verifier
   - None can distinguish step-level configurations
   - Executor has step info but doesn't pass it through

3. **Two Strategies for Tool Control**
   - **Pre-call filtering:** Claude SDK, Codex (registered at agent creation)
   - **Post-call validation:** CLI, User-Managed (tools always available, rejected at execution)

4. **No One-Size-Fits-All Solution**
   - Integrated agents (Claude, Codex, OpenHands) control tools at initialization
   - External agents (CLI, User-Managed) can only validate at call time
   - Trade-off: convenience vs. flexibility

## ⚠️ Verification Report

**Important:** Read `VERIFICATION-AND-CORRECTIONS.md` for critical corrections to this analysis:
- Several factual errors in agent implementation descriptions
- A critical prerequisite not yet in the codebase (tools field in StepConfig)
- Simpler alternatives to some recommendations
- Corrected implementation order with quick wins

**Status:** Investigation is valid and useful, but corrections must be applied before implementation.

---

## Implementation Prerequisites

### Phase 0: Schema Extension (DO FIRST)
1. **Add `available_tools` field to `StepConfig`** in `/src/orchestrator/config/models.py`
   ```python
   class StepConfig:
       # ... existing fields ...
       available_tools: list[str] | None = None  # NEW
   ```
   - Effort: Very Low
   - **Without this**, step-level tool control has no data source

### Phase 1: Executor and Context Extension
2. **Extend `ExecutionContext`** in `/src/orchestrator/agents/types.py`
   - Add `available_tools: list[str] | None = None`

3. **Update executor** to populate from step config
   - Read `step_config.available_tools`
   - Pass to `ExecutionContext`

### Phase 2: Agent-Specific Filtering

**Quick Wins (Very Low Effort):**
- **Codex Server:** Add `is_verifier` parameter to `build_dynamic_tool_specs()` to exclude grade tool from builders
- **User-Managed MCP:** Register all tools, rely on runtime validation (simpler than per-connection scoping)

**Standard Implementation:**
- **Claude SDK:** Filter tools based on `context.available_tools`
- **OpenHands:** Filter tools based on `context.available_tools`
- **CLI:** Phase-specific prompts already work; step-level filtering via prompt hints

---

## Implementation Checklist (Corrected)

- [ ] **Phase 0:** Add `available_tools` to `StepConfig`
- [ ] **Phase 0:** Add `available_tools` to `ExecutionContext`
- [ ] **Phase 0:** Update executor to populate step context
- [ ] **Phase 2a:** Codex Server phase filtering (quick win)
- [ ] **Phase 2a:** User-Managed MCP all-tools registration (quick win)
- [ ] **Phase 2b:** Claude SDK tool filtering
- [ ] **Phase 2b:** OpenHands tool filtering
- [ ] **Phase 2c:** CLI step-level prompt hints (optional)
- [ ] **Testing:** Unit tests per agent
- [ ] **Testing:** Integration tests for tool availability
- [ ] **Documentation:** Update agent configuration docs

---

## Files to Modify (Corrected)

| File | Change | Priority |
|------|--------|----------|
| `src/orchestrator/config/models.py` | Add `available_tools` to `StepConfig` | **First** |
| `src/orchestrator/agents/types.py` | Add `available_tools` to `ExecutionContext` | High |
| `src/orchestrator/agents/executor.py` | Populate `available_tools` from step | High |
| `src/orchestrator/agents/codex_server_common.py` | Add `is_verifier` parameter | **Quick Win** |
| `src/orchestrator/mcp/server.py` | Register all tools, remove phase filtering | **Quick Win** |
| `src/orchestrator/agents/claude_sdk.py` | Filter by `context.available_tools` | Medium |
| `src/orchestrator/agents/openhands.py` | Filter by `context.available_tools` | Medium |
| `src/orchestrator/agents/cli.py` | Optional step-level prompt filtering | Low |
| Test files | Update for new context fields | Medium |

---

## References

- **Verification Report:** `VERIFICATION-AND-CORRECTIONS.md` (READ THIS FIRST)
- **Individual Agent Analyses:** See individual `*.md` files
- **StepConfig:** `/src/orchestrator/config/models.py` (lines 152-162)
- **ExecutionContext:** `/src/orchestrator/agents/types.py` (lines 52-63)
- **Executor:** `/src/orchestrator/agents/executor.py` (context creation at lines 654-661)
