# MCP Control Analysis: Verification Report and Corrections

**Verified by:** Opus 4.6 model
**Date:** 2026-02-27

## Executive Summary

The analysis documents are **largely accurate** in scope but contain **several factual errors** about current implementation and some **overly optimistic feasibility assessments**. The recommendations are sound but miss simpler alternatives. Most critically, **the analysis assumes a prerequisite that doesn't exist yet** (tools field in StepConfig).

**Status:** The investigation is valid and useful, but these corrections must be applied before implementation.

---

## Critical Corrections Required

### 1. Codex Server: Tools Are NOT Phase-Filtered at Registration

**ERROR IN DOCUMENT:** `codex-server-agent.md` claims tools are "selected based on phase" during thread creation.

**ACTUAL BEHAVIOR:** `build_dynamic_tool_specs()` (line 173 of `codex_server_common.py`) **takes no parameters** and returns **ALL FIVE TOOLS unconditionally**. Every Codex thread gets the same tool set regardless of phase.

**Impact on Recommendations:**
- The Phase 2 recommendation to "refactor build_dynamic_tool_specs() to accept context" is valid but mischaracterizes the current state
- **SIMPLER ALTERNATIVE:** Add an `is_verifier: bool` parameter to exclude `grade` tool from builder threads. This solves the phase-filtering issue immediately without full ExecutionContext integration.

**Correction Action:** Update Codex recommendations to include immediate fix:
```python
def build_dynamic_tool_specs(is_verifier: bool = False) -> list[dict]:
    all_tools = [...]
    if not is_verifier:
        # Remove grade tool for builder phase
        all_tools = [t for t in all_tools if t["name"] != "grade"]
    return all_tools
```

Call site (line 435 of `codex_server.py`):
```python
is_verifier = on_grade is not None
tool_specs = build_dynamic_tool_specs(is_verifier=is_verifier)
```

This is a **very low effort fix** that addresses a real current issue: builder agents see the `grade` tool as available.

---

### 2. CLI Agent: Already Has Phase-Specific Tool Instructions

**ERROR IN DOCUMENT:** `cli-agent.md` states "Tool instructions are still the same in both phases" and "Same tools sent to builder and verifier subprocesses."

**ACTUAL BEHAVIOR:** `cli.py` already implements phase-aware prompts:
- Line 136: `if phase == "verifying": return _build_verifier_prompt()`
- Lines 156-163: Verifier prompt includes `orchestrator_set_grade` and `orchestrator_submit`
- Lines 165-195: Builder prompt includes `orchestrator_update_checklist`, `orchestrator_submit`, `orchestrator_request_clarification`

**Impact on Recommendations:**
- The analysis's "Option A: Template-Based Phase Control" is **already implemented**
- CLI agent already provides phase-specific tool lists in prompts
- The real limitation is that step-level tool filtering (not phase-level) is not possible

**Correction Action:**
- Acknowledge CLI already has phase control
- Reframe the limitation: step-level (not phase-level) tool control requires executor changes
- The analysis correctly concludes CLI has the most limitations for per-step control

---

### 3. OpenHands: Two-Tier Registration System Not Single Flag

**ERROR IN DOCUMENT:** `openhands-agent.md` oversimplifies the registration mechanism.

**ACTUAL BEHAVIOR:** Two separate mechanisms exist:
1. **`_tools_registered` boolean** (line 267 of `openhands.py`): Once True, entire `_register_sdk_tools()` is skipped. This is a simple binary guard.
2. **`_registered_tool_sets` set** (line 409 of `openhands_common.py`): Tracks unique frozensets of tool names. The `register_builtin_tools()` function is properly idempotent per tool set.

So: `register_builtin_tools(["terminal"])` followed by `register_builtin_tools(["terminal", "file_editor"])` would both execute (per-set idempotency). But `_register_sdk_tools()` wraps both built-in AND custom tool registration, so the outer boolean flag prevents any changes after the first call.

**Impact on Recommendations:**
- The analysis's conclusion is correct: custom tools cannot be re-registered within a process lifetime
- But the mechanism is more nuanced than "simple global flag"

**Correction Action:** Clarify the mechanism in the documentation. The practical impact description remains accurate.

---

### 4. User-Managed MCP: `complete_recovery` Tool Not Actually Exposed

**ERROR IN DOCUMENT:** Analysis mentions `complete_recovery` as "special" or "conditionally available."

**ACTUAL BEHAVIOR:** `complete_recovery` is defined in `tools.py` but **never registered** in the MCP server. It exists in `ORCHESTRATOR_TOOLS` but the `_register_tools()` method in `server.py` only registers the tools in `BUILDER_TOOLS` and `VERIFIER_TOOLS` sets. It is NOT in either set.

**Impact:** Minor documentation error. The tool is handled by REST API but not MCP.

**Correction Action:** Remove references to `complete_recovery` being available via MCP.

---

### 5. CRITICAL PREREQUISITE: StepConfig Doesn't Have `tools` Field

**ERROR IN ALL DOCUMENTS:** The analysis assumes `context.step_tools` comes from `step_config.tools`, but this field **does not exist**.

**ACTUAL STATE:** `StepConfig` in `/src/orchestrator/config/models.py` (lines 152-162) has NO `tools` field:
```python
class StepConfig:
    id: str
    description: str
    instruction: str | None = None
    # ... no tools field
```

**Impact:** The entire Phase 1 recommendation cannot work as described. Before any agent can filter tools based on step context, the schema must be extended.

**CRITICAL ACTION:** Add to StepConfig before implementing any agent changes:
```python
class StepConfig:
    # ... existing fields ...
    available_tools: list[str] | None = None  # NEW
```

This is **not optional** — it's a prerequisite for the entire approach.

---

## Simpler Alternatives to Some Recommendations

### For Codex Server Phase Filtering
**Analysis recommends:** Full ExecutionContext integration with tool filtering

**SIMPLER ALTERNATIVE:** Just add `is_verifier` parameter to `build_dynamic_tool_specs()` (as shown above). This immediately fixes the phase-filtering issue without requiring ExecutionContext changes.

**Effort:** Very Low | **Impact:** High | **Do first:** YES

---

### For User-Managed MCP Tool Availability
**Analysis recommends:** Per-connection MCP server scoping or heartbeat polling

**SIMPLER ALTERNATIVE:** Register **ALL tools** (both builder and verifier) with the MCP server at startup. Rely on existing `ToolHandler` runtime validation to reject phase-inappropriate calls. The validation is already there — it just returns an error explaining why the tool is unavailable.

Benefits:
- ✅ Zero code changes to MCP server initialization
- ✅ MCP tools are consistent with REST API (both have all tools)
- ✅ Runtime validation already works
- ✅ Better UX: tools are discoverable but fail with clear error if wrong phase

**Effort:** Very Low | **Impact:** Medium | **Do first:** YES

Code change (in `server.py`):
```python
def _register_tools(self) -> None:
    # Register ALL tools regardless of phase
    # Runtime validation will reject phase-inappropriate calls
    for name, tool_schema in ORCHESTRATOR_TOOLS.items():
        self._server.add_tool(
            name=name,
            fn=self._tool_handler.handle,
        )
```

---

## Corrected Implementation Order

### Must Do First (Prerequisite):
1. **Add `available_tools` field to `StepConfig`** in `/src/orchestrator/config/models.py`
   - Effort: Very Low
   - Without this, step-level tool control has no data source

### Quick Wins (Very Low Effort, High Value):
2. **Codex Server: Add phase filtering to `build_dynamic_tool_specs(is_verifier)`**
   - Effort: Very Low
   - Fixes real current issue: builders seeing grade tool

3. **User-Managed MCP: Register all tools, use runtime validation**
   - Effort: Very Low
   - Makes MCP tools consistent with REST API

4. **ExecutionContext Extension** (Phase 1)
   - Effort: Low
   - Now this is Phase 2 instead of Phase 1 due to prerequisite

5. **Agent Tool Filtering** (Phase 2, can be parallelized):
   - Claude SDK: Add `context.available_tools` filtering
   - OpenHands: Add `context.available_tools` filtering
   - Codex: Add full ExecutionContext-based filtering (builds on phase filtering above)
   - CLI: Step-level filtering via prompt (lowest priority, text-based only)

### Lower Priority (Step-level control for external agents):
6. **User-Managed MCP: Per-connection scoping** (if simple filtering isn't sufficient)
   - Only if runtime validation approach proves insufficient

---

## Revised Field Names and Consistency

**Standardize across all agents:**
- Use `available_tools: list[str] | None` in ExecutionContext
- Use `available_tools: list[str] | None` in StepConfig
- Not `step_tools`, not `allowed_tools` — consistent naming

---

## Architecture Validation

### Phase 1: Schema Extension
✅ Valid — `StepConfig.available_tools` is a simple, non-breaking addition

### Phase 2: ExecutionContext Extension
✅ Valid — All agents receive ExecutionContext, adding optional fields is non-breaking

### Phase 3: Agent Tool Filtering
✅ Valid — Each agent can independently filter based on context

### Will This Enable Step-Level Tool Control?
✅ YES
- **Claude SDK, Codex, OpenHands:** Via pre-call tool filtering ✅
- **CLI:** Via prompt hints (text-based, unenforceable) ⚠️
- **User-Managed (REST/MCP):** Via runtime validation ✅

---

## What the Analysis Got Right

1. ✅ All five agent types are identified and analyzed
2. ✅ ExecutionContext extension is the right common foundation
3. ✅ Each agent has different implementation strategies — this is correctly identified
4. ✅ Phase-level control already exists; step-level control is missing
5. ✅ The underlying APIs (Anthropic, OpenHands, Codex) do support dynamic tool specification
6. ✅ The overall architecture understanding is sound
7. ✅ The feasibility assessments are mostly correct (with noted caveats)

---

## What Needs Correction

| Item | Status | Fix |
|------|--------|-----|
| Codex tool phase filtering | ❌ Inaccurate | Clarify that it happens post-hoc only, recommend immediate `is_verifier` parameter |
| CLI phase-specific prompts | ❌ Missing | Acknowledge already implemented, refocus on step-level limitations |
| StepConfig.tools assumption | ❌ Critical Gap | Add to schema first before agent implementation |
| OpenHands registration mechanism | ⚠️ Oversimplified | Clarify two-tier system but conclusion is correct |
| User-Managed MCP simplification | ❌ Missed | Register all tools, use runtime validation (simpler than per-connection) |
| Field name consistency | ⚠️ Inconsistent | Standardize on `available_tools` |

---

## Files Actually Requiring Changes

| Phase | File | Change | Priority |
|-------|------|--------|----------|
| 0 | `src/orchestrator/config/models.py` | Add `available_tools` to `StepConfig` | **FIRST** |
| 1 | `src/orchestrator/agents/types.py` | Add `available_tools` to `ExecutionContext` | High |
| 1 | `src/orchestrator/agents/executor.py` | Populate `available_tools` from step | High |
| 2a | `src/orchestrator/agents/codex_server_common.py` | Add `is_verifier` parameter | **Quick Win** |
| 2a | `src/orchestrator/mcp/server.py` | Register all tools (remove phase filtering) | **Quick Win** |
| 2b | `src/orchestrator/agents/claude_sdk.py` | Filter tools based on context | Medium |
| 2b | `src/orchestrator/agents/openhands.py` | Filter tools based on context | Medium |
| 2c | `src/orchestrator/agents/cli.py` | Optional: step-level prompt hints | Low |
| Tests | Various | Update for new context fields | Medium |

---

## Conclusion

The investigation is **fundamentally sound and provides valuable insights**. The errors are mainly in details and missed simpler alternatives, not in the overall approach.

**Key action:** Before implementing any of the Phase 2 recommendations, add the `available_tools` field to `StepConfig`. This is a one-line change but essential.

**Quick wins available:** Codex phase filtering and User-Managed MCP all-tools registration can be implemented immediately (very low effort, clear benefits).

**Timeline:** With these corrections, the full step-level tool control can be implemented in phases over 2-3 development cycles without breaking changes.
