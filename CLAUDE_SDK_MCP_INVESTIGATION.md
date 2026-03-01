# Claude SDK Agent: MCP/Tool Handling Investigation

**Date:** February 27, 2026
**Focus:** Understanding tool/MCP capabilities, constraints, and architectural patterns for step-level tool control

---

## Executive Summary

The Claude SDK agent currently implements **static tool schemas** that are fixed at initialization time and do **not support dynamic tool specification at call time**. The Anthropic Messages API accepts a `tools` parameter per call, but the SDK agent does not expose a mechanism to vary tools per execution or step.

This contrasts sharply with OpenHands, which supports **dynamic tool selection** via constructor arguments that filter from a pool of available tools.

---

## 1. Current MCP/Tool Handling Approach

### 1.1 Claude SDK Tool Architecture

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/claude_sdk.py` (lines 172-292)

The SDK agent defines two **static tool schemas** as module-level constants:

```python
_BUILDER_TOOLS: list[dict[str, Any]] = [
    {"name": "update_checklist", ...},
    {"name": "submit", ...},
    {"name": "request_clarification", ...},
]

_VERIFIER_TOOLS: list[dict[str, Any]] = [
    {"name": "grade", ...},
    {"name": "update_checklist", ...},
    {"name": "submit", ...},
    {"name": "request_clarification", ...},
]
```

**Phase-based selection** (line 563):
```python
tools = _VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS
```

Tools are determined at execution time based on whether `on_grade` callback is provided:
- **Builder phase** (no verifier): 4 tools (update_checklist, submit, request_clarification, implicitly no grade)
- **Verifier phase** (with verifier): 5 tools (adds grade)

### 1.2 Orchestrator Callback Tools vs. MCP

The current implementation provides **orchestrator callback tools only** — NOT actual MCP resources:

1. **update_checklist** — Mark requirement status
2. **submit** — Submit work for verification
3. **grade** — Set grade on requirement (verifier only)
4. **request_clarification** — Ask for clarification

These are **hardcoded**, **not MCP-based**, and dispatched via `_dispatch_tool()` function (lines 353-402).

**No MCP server integration exists** in the Claude SDK agent. The agent does not:
- Connect to any MCP server
- Expose resources from MCPs
- Expose tools beyond the four callback tools
- Support dynamic MCP tool registration

---

## 2. API Capabilities for Dynamic Tool Specification

### 2.1 Anthropic Messages API: Per-Call Tool Support

The Anthropic Messages API **does support** dynamic tool specification at call time:

```python
response = client.messages.create(
    model=model,
    max_tokens=max_tokens,
    tools=tools,  # ← Dynamic per-call
    messages=messages,
)
```

**What this enables:**
- Different tools per API call
- Conditional tool availability based on state
- Runtime filtering of tool sets

### 2.2 Claude SDK Agent: Tools Parameter

**Current signature** (line 490-498):

```python
async def execute(
    self,
    context: ExecutionContext,
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_output: LogLineCallback | None = None,
    on_grade: GradeCallback | None = None,
    on_agent_metadata: AgentMetadataCallback | None = None,
) -> ExecutionResult:
```

**No tools parameter** — tools are derived internally from phase (builder vs. verifier).

**Comparable to OpenHands agent** (line 328, openhands.py):

```python
def __init__(
    self,
    server_url: str = "http://localhost:3000",
    model: str = "gpt-5-mini",
    api_key: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_iterations: int = 100,
    tools: list[str] | None = None,  # ← Dynamic tool specification!
    llm_config: dict[str, Any] | None = None,
) -> None:
```

OpenHands **accepts `tools` as a constructor parameter** to filter from the available tool pool.

---

## 3. Constraints Identified

### 3.1 Constraint 1: No Tools Parameter at Instantiation

**Issue:** Claude SDK agent constructor (lines 445-472) does not accept a `tools` parameter:

```python
def __init__(
    self,
    model: str = "claude-sonnet-4-5",
    api_key: str | None = None,
    auth_token: str | None = None,
    max_tokens: int = 4096,
    max_iterations: int = 50,
    *,
    _client: Any | None = None,
    _environ: dict[str, str] | None = None,
) -> None:
```

**Impact:** Cannot configure tools when creating the agent instance.

### 3.2 Constraint 2: Tools Only Vary by Phase, Not by Context

**Issue:** Tools are selected based solely on `is_verifier` flag (derived from `on_grade` callback presence):

```python
is_verifier = on_grade is not None
tools = _VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS
```

**Impact:** No way to:
- Enable/disable individual callback tools
- Add custom tools
- Filter tools based on ExecutionContext properties
- Support step-level or task-level tool configurations

### 3.3 Constraint 3: ExecutionContext Does Not Carry Step Information

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/types.py` (lines 52-62)

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
```

**Missing:**
- `step_id` — No reference to which step is being executed
- `step_config` — No step configuration
- `step_context` — No step-level metadata

**Current workaround in executor.py** (lines 573-595):
- Step context is extracted from routine config in executor
- **Not passed to agent** — only included in the prompt text
- Agent receives step info only via natural language in prompt

### 3.4 Constraint 4: Tool Schemas Are Hardcoded, Not Metadata-Driven

**Issue:** Tool definitions are literal Python dicts at module scope (lines 172-292):

```python
_BUILDER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "update_checklist",
        "description": "...",
        "input_schema": { ... },
    },
    ...
]
```

**Impact:**
- No way to generate tool schemas from config
- No way to add conditional fields to tool schemas
- Tool names and descriptions are not configurable

### 3.5 Constraint 5: No Distinction Between Callback Tools and Custom/MCP Tools

**Architecture issue:** The four callback tools are mixed with the same dispatch mechanism. There is no:
- Separation between orchestrator tools and external tools
- Registry for custom tools
- MCP tool integration point
- Tool provider abstraction

---

## 4. Step-Level Control: What's Needed

### 4.1 Information Currently Available

**At agent creation time** (executor.py, lines 550-561):

```python
agent = self._create_agent(agent_type, agent_config, run.id, phase=phase)
```

The executor has:
- Full `Run` object (with step and task hierarchy)
- `RoutineConfig` (with step configurations)
- Current `TaskState` and `StepState`
- Step context extracted (lines 586-593)

**What's passed to agent:**
- Phase (builder/verifying)
- ExecutionContext with only basic IDs and prompt

### 4.2 Step-Level Configuration Example

From `RoutineConfig.steps[i].tools` (hypothetical):

```yaml
steps:
  - id: "step-1"
    name: "Architecture Design"
    tools: ["terminal", "file_editor"]  # Restrict to these
  - id: "step-2"
    name: "Implementation"
    tools: ["terminal", "file_editor", "browser"]  # Add browser
  - id: "step-3"
    name: "Testing"
    tools: ["terminal"]  # Restrict further
```

---

## 5. Recommendations for Step-Level Tool Control

### 5.1 Short Term: Extend ExecutionContext

**Minimal change** to pass step information:

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
    step_id: str | None = None              # ← NEW
    step_tools: list[str] | None = None     # ← NEW (if step has tool config)
    step_config: dict[str, Any] | None = None  # ← NEW (step metadata)
```

**Impact:** Minimal — no API change, just additional optional fields.

### 5.2 Medium Term: Add Tools Parameter to Claude SDK Agent

**Pattern:** Follow OpenHands pattern

```python
class ClaudeSDKAgent:
    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        auth_token: str | None = None,
        max_tokens: int = 4096,
        max_iterations: int = 50,
        tools: list[str] | None = None,        # ← NEW
        custom_tools: dict[str, Any] | None = None,  # ← NEW (for MCP)
        *,
        _client: Any | None = None,
        _environ: dict[str, str] | None = None,
    ) -> None:
        self._tools = tools or _DEFAULT_CLAUDE_SDK_TOOLS  # builder + clarification
```

**Change execute() to build dynamic tool set:**

```python
async def execute(
    self,
    context: ExecutionContext,
    ...
) -> ExecutionResult:
    is_verifier = on_grade is not None

    # Start with core orchestrator tools
    tools = []
    if "update_checklist" in (self._tools or []):
        tools.append(_ORCHESTRATOR_TOOLS["update_checklist"])
    if "submit" in (self._tools or []):
        tools.append(_ORCHESTRATOR_TOOLS["submit"])
    if "request_clarification" in (self._tools or []):
        tools.append(_ORCHESTRATOR_TOOLS["request_clarification"])

    # Add grade if verifier phase
    if is_verifier and "grade" in (self._tools or []):
        tools.append(_ORCHESTRATOR_TOOLS["grade"])

    # Add custom/MCP tools from context
    if context.step_tools:
        tools.extend(context.step_tools)
```

**Impact:** Enables per-agent configuration + per-execution context.

### 5.3 Long Term: MCP Server Integration

**Pattern:** Create an MCP bridge similar to OpenHands/CLI agents:

```python
class MCPToolProvider:
    """Connects Claude SDK to MCP servers."""

    def __init__(self, mcp_config: dict[str, Any]) -> None:
        self._servers = {}  # name -> MCPClient

    async def register_server(self, name: str, config: dict) -> None:
        # e.g., stdio, sse, or websocket transport
        pass

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return Anthropic tool schema for all MCP tools."""
        pass

    async def call_tool(
        self, name: str, input: dict[str, Any]
    ) -> str:
        """Call an MCP tool and return result."""
        pass
```

**Wire into execute():**

```python
async def execute(
    self,
    context: ExecutionContext,
    ...
) -> ExecutionResult:
    # Build tools from MCP
    mcp_tools = []
    if self._mcp_provider:
        mcp_tools = await self._mcp_provider.list_tools()

    tools = _build_orchestrator_tools(...) + mcp_tools
```

---

## 6. Comparison Matrix

### Tool Configuration Capabilities

| Aspect | Claude SDK | OpenHands | CLI Agents | User-Managed |
|--------|-----------|-----------|-----------|--------------|
| **Static tool set** | ✓ (4 callback tools) | ✓ (builtin + custom) | N/A | N/A |
| **Per-instance tools** | ✗ | ✓ (`tools` param) | ✗ | ✗ |
| **Per-execution tools** | ✗ | ✗ | N/A | N/A |
| **Phase-based (builder/verifier)** | ✓ (grade only) | ✗ | ✓ (callback channel) | ✓ (callback channel) |
| **MCP support** | ✗ | ✓ (via tool registry) | ✓ (MCP SSE channel) | ✓ (REST/MCP channel) |
| **Custom tools** | ✗ | ✓ (via registration) | ✓ (CLI defines) | ✗ |
| **Tool filtering** | ✗ | ✓ (tool_names list) | ✗ | ✗ |
| **Context-aware tools** | ✗ | ✗ | ✗ | ✗ |

---

## 7. Implementation Roadmap

### Phase 1: Information Flow (Low Risk)
- Extend `ExecutionContext` with step info
- Update executor to populate new fields
- Update agent signatures (optional params only)

### Phase 2: Tool Configuration (Medium Risk)
- Add `tools` parameter to Claude SDK agent
- Refactor `_BUILDER_TOOLS` and `_VERIFIER_TOOLS` to a composable registry
- Implement tool filtering in execute()
- Add config schema for tool selection

### Phase 3: MCP Integration (High Risk, Future)
- Create MCPToolProvider bridge
- Support MCP SSE, stdio, websocket transports
- Add MCP configuration to RoutineConfig
- Test MCP server integration

---

## 8. Code Locations and Dependencies

### Core Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `claude_sdk.py` | Main agent implementation | `ClaudeSDKAgent`, `build_claude_sdk_prompt()` |
| `agents/types.py` | Type definitions | `ExecutionContext`, `ExecutionResult` |
| `agents/executor.py` | Agent lifecycle | `AgentExecutor._create_agent()`, `_execute_task()` |
| `openhands.py` | OpenHands reference | `OpenHandsAgent` (shows tool pattern) |
| `openhands_common.py` | OpenHands shared | `register_builtin_tools()`, `DEFAULT_OPENHANDS_TOOLS` |

### Configuration Files

| File | Purpose |
|------|---------|
| `detector.py` | Agent config schemas (lines 26-119) |
| `state/models.py` | Run/Step/Task state models |
| `config/models.py` | RoutineConfig, StepConfig, TaskConfig |

---

## 9. Known Gaps

1. **No MCP Server Support** — Claude SDK agent cannot use MCP-exposed tools
2. **No Custom Tools** — Only 4 hardcoded orchestrator callback tools
3. **No Per-Execution Tool Filtering** — Tools fixed at phase time
4. **No Step-Level Configuration** — Cannot vary tools by step
5. **Lost Step Context** — Executor knows step info but doesn't pass it to agent

---

## 10. Validation Strategy

### Test Additions Needed

```python
# test_claude_sdk_tools.py

def test_builder_tools_exclude_grade():
    """Verify grade tool not in builder phase."""
    assert "grade" not in [t["name"] for t in _BUILDER_TOOLS]

def test_verifier_tools_include_grade():
    """Verify grade tool in verifier phase."""
    assert "grade" in [t["name"] for t in _VERIFIER_TOOLS]

async def test_execution_context_with_step_info():
    """Verify step info flows through ExecutionContext."""
    # Once extended, test that:
    # - executor populates step_id, step_tools
    # - agent receives them in context

async def test_dynamic_tools_selection():
    """Verify agent can filter tools based on context."""
    # Once implemented, test that:
    # - tools=[...] parameter is respected
    # - tool set sent to API matches specification
```

---

## Conclusion

The Claude SDK agent currently has **zero MCP/custom tool support** and **fixed tool schemas** that vary only by phase. The Anthropic Messages API supports per-call tool specification, but the agent doesn't expose this capability.

**Key architectural pattern missing:** The executor has all the context needed for step-level tool control (step ID, config, tools list) but doesn't pass it to the agent. Extending `ExecutionContext` and the agent constructor would enable this with minimal breaking changes.

**Recommended approach:** Phase 1 (context extension) is low-risk and enables future patterns without disrupting current behavior.
