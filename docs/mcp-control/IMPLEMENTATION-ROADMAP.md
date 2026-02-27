# MCP Tool Control: Implementation Roadmap

## Overview

This document provides a practical roadmap for enabling step-by-step MCP tool availability control across all agent types. Based on comprehensive investigation and verification by multiple agents.

---

## The Challenge

Currently, MCP tool availability is:
- ✅ Phase-aware (builder vs. verifier)
- ❌ Step-unaware (all steps in a phase see same tools)
- ❌ Not configurable (hardcoded or derived from agent initialization)

**Goal:** Make tool availability configurable per-step in routine definitions.

---

## Core Architecture

### Data Flow

```
┌─────────────────────────────────┐
│  Routine Definition (YAML)      │
│  steps:                         │
│    - id: step-1                 │
│      available_tools: [...]     │  ← NEW: Tools for this step
│    - id: step-2                 │
│      available_tools: [...]     │
└────────────────┬────────────────┘
                 │
                 ↓
┌─────────────────────────────────┐
│  Executor                       │
│  - Loads step config            │
│  - Creates ExecutionContext     │
│  - Populates available_tools    │  ← Reads from step
└────────────────┬────────────────┘
                 │
                 ↓
┌─────────────────────────────────┐
│  Agent (Claude, Codex, etc)    │
│  - Receives ExecutionContext    │
│  - Filters available_tools      │  ← Filters based on context
│  - Restricts to configured set  │
└─────────────────────────────────┘
```

### Key Components

1. **StepConfig.available_tools** — Which tools are available for this step
2. **ExecutionContext.available_tools** — Passed to agent with step's tool list
3. **Agent tool filtering** — Each agent type restricts to available set

---

## Implementation Phases

### Phase 0: Prerequisite (Must Do First)

#### 0.1: Add `available_tools` to `StepConfig`

File: `/src/orchestrator/config/models.py` (around line 152)

```python
class StepConfig(BaseModel):
    """Configuration for a workflow step."""
    id: str
    description: str
    instruction: str | None = None

    # NEW FIELD:
    available_tools: list[str] | None = None
    # Optional list of tool names available in this step.
    # If None, all standard tools are available.
    # Example: ["terminal", "file_editor"] or None for all tools.
```

**Effort:** Very Low (3 lines)
**Breaking:** No (optional field)
**Must complete before:** Phase 1

---

### Phase 1: Executor and Context Extension

#### 1.1: Extend `ExecutionContext`

File: `/src/orchestrator/agents/types.py` (around line 52)

```python
class ExecutionContext(BaseModel):
    """Context provided to an agent for execution."""

    run_id: str
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None

    # NEW FIELDS:
    step_id: str | None = None
    # Step ID for reference

    available_tools: list[str] | None = None
    # List of tool names available for this task.
    # Passed to agents for filtering.
```

**Effort:** Very Low (5 lines + docstring)
**Breaking:** No (optional fields)

#### 1.2: Update Executor to Populate Step Context

File: `/src/orchestrator/agents/executor.py` (around line 654 where ExecutionContext is created)

```python
# Current code (around line 654):
context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=...,
    prompt=prompt_text,
    requirements=task_state.checklist_items,
    api_base_url=...,
    auth_token=...,
    end_commit=...,
)

# Updated code:
# Get step context
step_index = run.current_step_index
if 0 <= step_index < len(run.routine.steps):
    step_config = run.routine.steps[step_index]
    step_id = step_config.id
    available_tools = step_config.available_tools
else:
    step_id = None
    available_tools = None

context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=...,
    prompt=prompt_text,
    requirements=task_state.checklist_items,
    api_base_url=...,
    auth_token=...,
    end_commit=...,
    step_id=step_id,                    # NEW
    available_tools=available_tools,    # NEW
)
```

**Effort:** Low
**Breaking:** No
**Tests:** Update unit tests that create ExecutionContext

---

### Phase 2a: Quick Wins (Implement These Immediately)

#### 2a.1: Codex Server Phase Filtering

File: `/src/orchestrator/agents/codex_server_common.py` (around line 173)

**Current Issue:** All five tools (including `grade`) are registered for all threads, regardless of phase.

**Fix:** Add phase parameter to control which tools are registered.

```python
def build_dynamic_tool_specs(is_verifier: bool = False) -> list[dict[str, Any]]:
    """Build tool specifications for Codex server.

    Args:
        is_verifier: If True, include grading tool; if False, exclude it.
    """
    base_tools = [
        # ... update_checklist, submit, request_clarification, complete_recovery
    ]

    # Add grade tool only for verifier phase
    if is_verifier:
        base_tools.append({
            "name": "grade",
            "description": "Grade a requirement",
            # ... schema
        })

    return base_tools
```

**Update call site** in `codex_server.py` (around line 435):
```python
# Before calling build_dynamic_tool_specs:
is_verifier = on_grade is not None

# Then:
tool_specs = build_dynamic_tool_specs(is_verifier=is_verifier)
```

**Effort:** Very Low (5 lines changed)
**Breaking:** No
**Benefit:** Builders no longer see the `grade` tool as available

---

#### 2a.2: User-Managed MCP: Register All Tools

File: `/src/orchestrator/mcp/server.py` (around line 70 in `_register_tools()`)

**Current Issue:** Phase is hardcoded to "building", so verifiers never see `orchestrator_set_grade`.

**Simple Fix:** Register all tools (both builder and verifier), rely on runtime validation.

```python
def _register_tools(self) -> None:
    """Register all available tools with the MCP server.

    Runtime validation in ToolHandler will reject phase-inappropriate calls.
    """
    # Register ALL tools (both builder and verifier)
    all_tools = {
        "orchestrator_get_requirements": {...},
        "orchestrator_update_checklist": {...},
        "orchestrator_submit": {...},
        "orchestrator_request_clarification": {...},
        "orchestrator_set_grade": {...},
        "orchestrator_list_repos": {...},
        "orchestrator_list_branches": {...},
    }

    for name, schema in all_tools.items():
        self._server.add_tool(
            name=name,
            description=schema.get("description", ""),
            fn=self._tool_handler.handle,
            # ... params
        )
```

**Effort:** Very Low (remove phase filtering logic)
**Breaking:** No (tools are still validated at call time)
**Benefit:** MCP clients see same tools as REST clients; better discoverability

---

### Phase 2b: Standard Agent Implementation

#### 2b.1: Claude SDK Agent Tool Filtering

File: `/src/orchestrator/agents/claude_sdk.py` (in `execute()` method, around line 560)

```python
async def execute(
    self,
    context: ExecutionContext,
    ...
) -> ExecutionResult:
    # ... existing code ...

    # Build tool list with filtering
    tools_list = []

    # Determine available tools
    available = context.available_tools or self._get_default_tools()

    # Filter builder tools
    if "update_checklist" in available:
        tools_list.append(_BUILDER_TOOLS["update_checklist"])
    if "submit" in available:
        tools_list.append(_BUILDER_TOOLS["submit"])
    if "request_clarification" in available:
        tools_list.append(_BUILDER_TOOLS["request_clarification"])

    # Filter verifier tools
    if on_grade is not None and "grade" in available:
        tools_list.append(_VERIFIER_TOOLS["grade"])

    # Use filtered tools in API call
    response = self.client.messages.create(
        model=self.model,
        max_tokens=self.max_tokens,
        tools=tools_list,  # Use filtered list
        messages=messages,
    )
```

**Effort:** Medium (new filtering logic)
**Breaking:** No
**Benefit:** Claude SDK now respects step-level tool config

**Tests to update:**
- Test tool filtering in builder phase
- Test tool filtering in verifier phase
- Test with custom tool lists

---

#### 2b.2: OpenHands Agent Tool Filtering

File: `/src/orchestrator/agents/openhands.py` (in `execute()` method, around line 456)

```python
async def execute(
    self,
    context: ExecutionContext,
    ...
) -> ExecutionResult:
    # ... existing code ...

    # Filter built-in tools based on context
    available_builtin = context.available_tools or self._tools or DEFAULT_OPENHANDS_TOOLS

    # Only include requested built-in tools
    builtin_tool_names = [
        name for name in available_builtin
        if name in ["terminal", "file_editor", "browser", "glob", "grep"]
    ]

    builtin_tools = [OHTool(name=name) for name in builtin_tool_names]

    # Orchestrator tools (custom)
    orchestrator_tools = [
        OHTool(name="OrcGetRequirementsTool", params={...}),
        OHTool(name="OrcUpdateChecklistTool", params={...}),
        OHTool(name="OrcSubmitTool", params={...}),
        # OrcSetGradeTool only if on_grade:
        OHTool(name="OrcSetGradeTool", params={...}) if on_grade else None,
    ]

    # Pass filtered lists to agent
    agent = OHAgent(llm=llm, tools=builtin_tools + [t for t in orchestrator_tools if t])
```

**Effort:** Medium (new filtering logic)
**Breaking:** No
**Benefit:** OpenHands respects step-level tool config

---

#### 2b.3: Codex Server Full Context Integration

File: `/src/orchestrator/agents/codex_server_common.py` (refactor `build_dynamic_tool_specs()`)

```python
def build_dynamic_tool_specs(context: ExecutionContext | None = None) -> list[dict]:
    """Build dynamic tool specs, optionally filtered by context.

    Args:
        context: ExecutionContext with available_tools to filter by.
                 If None, returns all tools.
    """
    all_tools = [
        # all tools defined here
    ]

    # Filter by context if provided
    if context and context.available_tools:
        tool_names = set(context.available_tools)
        all_tools = [t for t in all_tools if t["name"] in tool_names]

    return all_tools
```

Update call site in `codex_server.py`:
```python
tool_specs = build_dynamic_tool_specs(context=context)
```

**Effort:** Medium (adds context parameter, filtering logic)
**Breaking:** No (backward compatible with None default)
**Benefit:** Full step-level control

---

### Phase 2c: Optional Enhancements

#### 2c.1: CLI Agent Step-Level Tool Hints (Optional)

File: `/src/orchestrator/agents/cli.py` (in `build_prompt()`)

The CLI agent already has phase-specific tool instructions. To add step-level control:

```python
def build_prompt(self, context: ExecutionContext, phase: str) -> str:
    # ... existing phase-specific logic ...

    # If context specifies available tools, add hint to prompt
    if context.available_tools:
        tools_hint = f"\nAvailable tools for this step: {', '.join(context.available_tools)}\n"
        prompt += tools_hint

    return prompt
```

**Effort:** Very Low (hint only)
**Breaking:** No
**Limitation:** Unenforceable (subprocess can ignore hints)
**Benefit:** Better guidance for external agents

---

## Rollout Strategy

### Week 1: Prerequisites
- [ ] Add `available_tools` to `StepConfig`
- [ ] Extend `ExecutionContext`
- [ ] Update executor
- [ ] Update tests

### Week 2: Quick Wins
- [ ] Codex Server phase filtering
- [ ] User-Managed MCP all-tools registration
- [ ] Test both changes thoroughly

### Week 3: Standard Agents
- [ ] Claude SDK tool filtering
- [ ] OpenHands tool filtering
- [ ] Comprehensive integration tests

### Week 4: Polish
- [ ] Codex Server full context integration
- [ ] CLI optional hints
- [ ] Documentation updates
- [ ] Example routines with custom tool configs

---

## Testing Strategy

### Unit Tests Per Agent

For each agent, add tests:
```python
async def test_tool_filtering_respects_context():
    """Verify agent filters tools to available_tools from context."""
    context = ExecutionContext(
        ...,
        available_tools=["terminal"]  # Only terminal
    )
    agent = CLaudeSDKAgent(...)
    # Execute and verify only terminal tool is in request

async def test_unavailable_tools_not_passed():
    """Verify unavailable tools are excluded."""
    context = ExecutionContext(
        ...,
        available_tools=["file_editor"]  # NOT terminal
    )
    # Verify terminal tool not in API request
```

### Integration Tests

```python
async def test_step_level_tool_control():
    """End-to-end: routine specifies tools per step."""
    routine = Routine(
        steps=[
            StepConfig(
                id="step-1",
                available_tools=["terminal", "file_editor"]
            ),
            StepConfig(
                id="step-2",
                available_tools=["file_editor"]  # No terminal
            ),
        ]
    )

    # Create run, execute step-1
    # Verify terminal tool available

    # Advance to step-2
    # Verify terminal tool NOT available
```

---

## Validation Checklist

- [ ] `StepConfig` has `available_tools` field
- [ ] `ExecutionContext` has `available_tools` field
- [ ] Executor populates `available_tools` from step config
- [ ] Codex Server filters tools by `is_verifier` parameter
- [ ] User-Managed MCP registers all tools
- [ ] Claude SDK filters tools by context
- [ ] OpenHands filters tools by context
- [ ] All agent unit tests pass
- [ ] Integration tests cover step-level tool control
- [ ] Phase transitions work correctly (builder→verifier)
- [ ] Tools unavailable in a phase are properly rejected
- [ ] Documentation updated with examples

---

## Example: Step-Level Tool Control in Practice

### Routine Definition

```yaml
routine:
  name: Code Review
  steps:
    - id: setup
      description: "Set up development environment"
      available_tools:
        - terminal
        - file_editor

    - id: build
      description: "Build the project"
      available_tools:
        - terminal
        # No file_editor (read-only build phase)

    - id: review
      description: "Review code changes"
      available_tools:
        - file_editor
        # No terminal (review only)
```

### What Happens

1. **Step 1 (setup):** Agent can access terminal and file_editor
2. **Step 2 (build):** Agent only has terminal (no file editing)
3. **Step 3 (review):** Agent only has file_editor (cannot execute commands)

---

## Success Criteria

✅ **Achieved when:**
1. StepConfig supports `available_tools` field
2. Executor populates ExecutionContext with step tools
3. All agents respect `available_tools` from context
4. Integration tests verify step-level control works end-to-end
5. Phase transitions still work (builder→verifier)
6. Documentation includes examples

---

## Questions and Gotchas

### Q: What if `available_tools` is not specified on a step?
A: Default to all standard tools (backward compatible).

### Q: Can tools be added dynamically during step execution?
A: No. Tools are fixed when the step starts. Designed this way for safety.

### Q: What if an agent tries to call an unavailable tool?
A: Most integrated agents (Claude, Codex, OpenHands) won't see it in their tool list. External agents (CLI, User-Managed) will get a validation error at call time.

### Q: Do routine definitions need to be updated?
A: No. The `available_tools` field is optional. Existing routines without it use all standard tools.

---

## Success Timeline

With focused effort on the roadmap above, full step-level tool control should be achievable in **2-3 weeks** without breaking changes to the public API.
