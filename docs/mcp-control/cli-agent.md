# CLI Agent: MCP Tool Control Analysis

## Current Implementation

The CLI agent is unique: **it does not directly use MCP or Claude/Codex APIs**. Instead, it embeds MCP server URLs and tool descriptions as **text in the prompt sent to a subprocess**. The subprocess (assumed to be a local agent like Cursor, Windsurf, or custom CLI script) reads the prompt and initiates its own MCP connections.

### Architecture

```
┌──────────────────────────────────────┐
│   Orchestrator (CLI Agent)           │
│  - Builds enriched prompt with:      │
│    * Task requirements               │
│    * MCP server URL (http://...)     │
│    * Tool descriptions               │
│    * REST API endpoint instructions  │
└──────────────┬──────────────────────┘
               │ Sends prompt to subprocess
               ↓
┌──────────────────────────────────────┐
│   External Subprocess                │
│  - Reads prompt with tool info       │
│  - Initiates MCP connection          │
│  - Calls tools via MCP or REST       │
│  - Calls callbacks via REST/MCP      │
└──────────────────────────────────────┘
```

### Tool Specification Approach

Tools are **hardcoded in prompt templates** in `/src/orchestrator/agents/cli.py` (lines 114-263):

```python
MCP_INSTRUCTIONS_TEMPLATE = """
Available MCP server: {mcp_server_url}

Tools available through MCP:
- {tool_name} - {tool_description}
...
"""

REST_INSTRUCTIONS_TEMPLATE = """
Available REST endpoints:
- POST /api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}
...
"""
```

## Constraints for Dynamic Tool Control

### 1. **Prompt is Immutable After Sending**

Once the prompt is sent to the subprocess, it cannot be changed:
```python
# cli.py execute() method sends prompt once
process = await asyncio.create_subprocess_exec(
    *cmd,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

# Subprocess reads stdin and begins work
# ← No way to send updated prompt or tool info mid-execution
```

**Impact:** Tool availability is fixed at task start and cannot change during the task.

### 2. **No Bidirectional Channel to Subprocess**

The CLI agent communicates with its subprocess through:
- **Stdin:** One-way transmission of prompt (at start)
- **Stdout:** Line-by-line log output (read by orchestrator)
- **Callbacks:** REST/MCP calls made by subprocess **back to** orchestrator

There's no mechanism for the orchestrator to send updated tool information mid-execution.

### 3. **Tools Specified via Text, Not Structured Data**

Tools are described as **plain text in the prompt**, not as machine-readable schemas:
```
Available MCP tools:
- orchestrator_update_checklist: Updates the checklist item status
  Usage: orchestrator_update_checklist(run_id, task_id, req_id, status, note)
```

The subprocess must parse this text to understand available tools. This is:
- ✅ Flexible (subprocess can adapt to text changes)
- ❌ Fragile (parsing errors if text format changes)
- ❌ Not machine-verifiable (no validation of tool descriptions)

### 4. **Tool Instructions Are Template-Based and Static**

Tools are listed once in the prompt via hardcoded templates. Different subprocesses see the same tool list regardless of their phase or requirements.

**Current behavior:**
- All tools listed in one prompt template
- Same tools sent to builder and verifier subprocesses
- Verifier receives builder tool names (but may not be designed to use them)

### 5. **No API for Tool Specification at Construction**

The CLI agent has no parameter to specify tools:
```python
# Current: no tools parameter
agent = CLIAgent(
    command=...,
    callback_channel=...,
    phase=...,
)

# Desired for step-level control:
agent = CLIAgent(
    command=...,
    callback_channel=...,
    phase=...,
    tools=[...],  # ← Does not exist
)
```

## How Tools Currently Vary (Limited Phase Control)

Phase awareness is partial and text-based:

```python
# cli.py: build_prompt() method
def build_prompt(self, context: ExecutionContext, phase: AgentPhase) -> str:
    prompt = f"Phase: {phase.name}\n"

    if phase == AgentPhase.VERIFIER:
        prompt += "You are in verification phase. Grade the following...\n"
    else:
        prompt += "You are in building phase. Complete the following...\n"

    # Tool instructions are still the same in both phases
    prompt += MCP_INSTRUCTIONS_TEMPLATE.format(...)
```

**Result:** Different task description and guidance, but the **same tools** are always listed.

To make tools phase-aware would require:
1. Separate MCP_INSTRUCTIONS templates for builder vs. verifier
2. Passing template selection to `build_prompt()`
3. Subprocess parsing the correct tool list from prompt

This is **text-based and unverified** — the subprocess might try to call tools not designed for its phase.

## Enabling Step-Level Tool Control

### Option A: Template-Based Phase Control (Text Level)

**Effort:** Low | **Complexity:** Low | **Reliability:** Low | **Recommended:** ⚠️ Quick Win

Create separate tool instruction templates per phase:
```python
BUILDER_TOOLS_TEMPLATE = """
Available MCP tools in BUILDER phase:
- orchestrator_update_checklist
- orchestrator_submit
- orchestrator_request_clarification
"""

VERIFIER_TOOLS_TEMPLATE = """
Available MCP tools in VERIFIER phase:
- orchestrator_set_grade
- orchestrator_submit
"""

def build_prompt(self, context: ExecutionContext, phase: AgentPhase) -> str:
    if phase == AgentPhase.VERIFIER:
        tools_section = VERIFIER_TOOLS_TEMPLATE
    else:
        tools_section = BUILDER_TOOLS_TEMPLATE

    return f"{prompt_text}\n{tools_section}"
```

**Pros:**
- ✅ Zero code changes to agent infrastructure
- ✅ Low effort
- ✅ Text is easy for humans to read

**Cons:**
- ❌ Subprocess must parse text (error-prone)
- ❌ No enforcement if subprocess ignores instructions
- ❌ Text-based hints, not actual tool availability
- ❌ Doesn't scale to custom per-step tools

### Option B: Heartbeat Polling for Tool Updates (Medium Effort)

**Effort:** Medium | **Complexity:** Medium | **Reliability:** Medium | **Recommended:** ⚠️ Advanced

Add a bidirectional channel for tool updates:
```python
# Subprocess periodically polls for tool updates
while executing:
    # Do work
    ...

    # Periodically check for tool updates
    if should_check_tools():
        response = requests.get(
            f"{api_base_url}/api/runs/{run_id}/tasks/{task_id}/available-tools"
        )
        updated_tools = response.json()["tools"]
        if updated_tools != current_tools:
            update_mcp_clients(updated_tools)
```

Would require:
1. New REST endpoint: `GET /api/runs/{run_id}/tasks/{task_id}/available-tools`
2. Subprocess implementation to poll and update connections
3. Coordination of MCP client lifecycle

**Pros:**
- ✅ True dynamic tool updates mid-execution
- ✅ Supports per-step tool changes
- ✅ Subprocess can respond to tool availability changes

**Cons:**
- ❌ Requires new API endpoint
- ❌ Polling overhead (latency + network calls)
- ❌ Complex MCP client lifecycle management
- ❌ Subprocess must implement polling logic

### Option C: Process-Per-Step Pattern (Redesign Task Model)

**Effort:** Very High | **Complexity:** High | **Reliability:** High | **Recommended:** ⚠️ Future

Instead of one subprocess per task spanning multiple steps, create one subprocess per step:
```python
# For each step:
for step in routine.steps:
    agent = CLIAgent(
        command=...,
        tools=step.tools,  # ← Step-specific tools
    )
    context = ExecutionContext(..., step_id=step.id)
    await agent.execute(context)
```

Would require:
1. Executor changes to loop over steps instead of tasks
2. Task model changes (steps become execution units)
3. Step-level tool configuration in routine schemas

**Pros:**
- ✅ True per-step tool control
- ✅ Clean separation per step
- ✅ Subprocess doesn't need polling/bidirectional logic

**Cons:**
- ❌ Major executor redesign
- ❌ Task and step models must change
- ❌ Loss of in-process conversation state

### Option D: Accept Current Limitations

**Effort:** None | **Complexity:** None | **Reliability:** Current | **Recommended:** ✅ Practical

The CLI agent is designed for external agents that manage their own tool connections. Accept that:
- Tools are fixed per phase (builder/verifier)
- Step-level control requires subprocess redesign
- Text-based hints are what's supported

For fine-grained tool control, use Claude SDK or Codex agents where tool management is integrated.

## Feasibility Summary

| Approach | Effort | Per-Step | Per-Task | Mid-Execution | Recommended |
|----------|--------|----------|----------|---|---|
| **Option A** (Templates) | Low | ❌ | ⚠️ | ❌ | ✅ Quick Win |
| **Option B** (Polling) | Medium | ✅ | ✅ | ✅ | ⚠️ If needed |
| **Option C** (Process-Per-Step) | Very High | ✅ | ✅ | ✅ | ⚠️ Future |
| **Option D** (Accept Limits) | None | ❌ | ⚠️ | ❌ | ✅ Practical |

## Comparison with Other Agents

| Agent | Tool Specification | API Support | Per-Task | Per-Step | Mid-Task Updates |
|-------|---|---|---|---|---|
| Claude SDK | Integrated | ✅ | ✅ | ❌ | ✅ (Messages API) |
| Codex Server | Integrated | ⚠️ | ✅ | ❌ | ❌ |
| OpenHands | Integrated | ✅ | ⚠️ | ❌ | ⚠️ |
| CLI | Text-based | ❌ | ⚠️ | ❌ | ❌ |

## Recommendation

**For step-level control in CLI agents, use Option A as a quick win, but be aware of limitations:**

1. Create separate tool instruction templates for builder vs. verifier phases
2. Select appropriate template in `build_prompt()` based on phase
3. Document that tool availability is phase-based, not enforced by orchestrator
4. For true step-level control, consider switching to Claude SDK or Codex agents

**If dynamic tool updates are critical:**
- Implement Option B (polling) for advanced external agents
- Requires new REST endpoint and subprocess implementation
- Higher complexity, better flexibility

**If fine-grained tool control is essential:**
- Consider executor redesign (Option C) to make steps execution units
- Major refactoring, but cleanest long-term solution
- Applies to all agent types, not just CLI

## Files to Modify

1. `src/orchestrator/agents/cli.py` — Add phase-based tool templates
2. Optionally: `src/orchestrator/api/routers/tasks.py` — Add `/available-tools` endpoint if implementing Option B
3. Documentation — Clarify tool availability model for CLI agents

## Implementation Checklist

- [ ] Create `BUILDER_TOOLS_TEMPLATE` and `VERIFIER_TOOLS_TEMPLATE` in cli.py
- [ ] Update `build_prompt()` to select template based on phase
- [ ] Test prompt generation for both phases
- [ ] Document tool availability expectations in CLI agent docstring
- [ ] Add test cases for phase-specific tool instructions
