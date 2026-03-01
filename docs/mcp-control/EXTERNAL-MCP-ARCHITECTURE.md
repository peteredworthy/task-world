# External MCP Architecture: Dynamic Per-Step Configuration

**Updated Investigation:** 2026-02-27 (Corrected for External MCPs)
**Status:** All five agent types CAN support dynamic external MCPs per step

---

## The Corrected Understanding

Your original concern was valid: **the first investigation missed external MCP support entirely**. Here's what changes with this corrected investigation:

### Original Gap
The first investigation focused on:
- ❌ Orchestrator's internal tools (orchestrator_update_checklist, orchestrator_set_grade, etc.)
- ❌ Phase-based filtering of those tools
- ❌ Assumed MCPs would be registered globally and blocked per-task

### Corrected Scope
This investigation covers:
- ✅ **External MCPs** (chrome-mcp, context7, custom MCPs, etc.)
- ✅ **Dynamic per-step** MCP configuration (not global registration)
- ✅ **No blocking needed** — MCPs are naturally scoped per execution
- ✅ **Multiple MCPs** per step without conflicts

---

## Key Finding: All Agents Support External MCPs Natively

| Agent Type | MCP Support | Mechanism | Per-Call/Per-Step | Effort |
|-----------|---|---|---|---|
| **Claude SDK** | ✅ Native | `mcp_servers` parameter in Messages API | Per-request (per-turn) | Low |
| **Codex Server** | ✅ Native | config.toml in CODEX_HOME | Per-process (per-thread) | Medium |
| **OpenHands** | ✅ Native | `mcp_config` parameter in Agent constructor | Per-instance | Low |
| **CLI** | ✅ Via config | `.mcp.json` in subprocess working dir | Per-execution | Medium |
| **User-Managed** | ✅ Via endpoint | MCP server info in prompt response | Per-request | Low |

**Critical insight:** Each agent type has a **natural execution boundary** that maps to a task. No global registration needed.

---

## New Architecture: MCP Configuration Flow

```
┌─────────────────────────────────────────────────────┐
│  Routine Definition (YAML)                          │
│  steps:                                             │
│    - id: step-1                                     │
│      mcp_servers:                   # ← NEW         │
│        - name: chrome                               │
│          url: http://localhost:3000                 │
│        - name: context7                             │
│          command: context7-mcp                      │
│          args: [--verbose]                          │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│  StepConfig (in src/orchestrator/config/models.py) │
│  mcp_servers: list[MCPServerConfig] | None          │
│    - name: str                                      │
│    - url: str | None (HTTP)                         │
│    - command: str | None (STDIO)                    │
│    - args: list[str] | None                         │
│    - env: dict[str, str] | None                     │
│    - auth_token_env: str | None                     │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│  Executor (src/orchestrator/agents/executor.py)     │
│  1. Read step_config.mcp_servers                    │
│  2. Create ExecutionContext.mcp_servers             │
│  3. Pass to agent.execute(context)                  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────┐
│  Agent-Specific Wiring                              │
│  ├─ Claude SDK: Pass to Messages API mcp_servers    │
│  ├─ Codex: Write to CODEX_HOME/config.toml          │
│  ├─ OpenHands: Pass to Agent(mcp_config=...)        │
│  ├─ CLI: Generate .mcp.json in subprocess dir       │
│  └─ User-Managed: Include in prompt response        │
└─────────────────────────────────────────────────────┘
```

---

## New Data Model

### MCPServerConfig (New)

```python
from pydantic import BaseModel
from typing import Literal

class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    # Name for identification (must be unique per step)

    # HTTP transport
    url: str | None = None
    # Example: "http://localhost:3000"
    # Indicates HTTP-based MCP server

    # STDIO transport
    command: str | None = None
    # Example: "chrome-mcp" or "/usr/local/bin/context7"
    # Indicates subprocess-based MCP server

    args: list[str] | None = None
    # Command-line arguments if using STDIO
    # Example: ["--verbose", "--config", "/path/to/config"]

    env: dict[str, str] | None = None
    # Environment variables to set for subprocess
    # Example: {"HOME": "/tmp/sandbox", "DEBUG": "true"}

    auth_token_env: str | None = None
    # Name of environment variable containing auth token
    # NEVER put actual token in YAML
    # Example: "CHROME_MCP_TOKEN" → agent reads from env.CHROME_MCP_TOKEN

    timeout_seconds: int = 30
    # Connection timeout for HTTP MCPs

class StepConfig(BaseModel):
    """Updated StepConfig with MCP servers."""
    id: str
    description: str
    instruction: str | None = None
    available_tools: list[str] | None = None  # From original investigation

    # NEW:
    mcp_servers: list[MCPServerConfig] | None = None
    # List of external MCP servers available for this step
```

### ExecutionContext Extension

```python
class ExecutionContext(BaseModel):
    """Updated with MCP server information."""

    # ... existing fields ...
    available_tools: list[str] | None = None  # From original investigation

    # NEW:
    mcp_servers: list[MCPServerConfig] | None = None
    # External MCP servers for this task
    # Populated by executor from step_config.mcp_servers
```

---

## Why This Works: Execution Boundaries

Each agent type has a **natural execution boundary** that maps cleanly to a step/task:

### Claude SDK
- **Boundary:** Per API request (each turn/iteration is a new request)
- **MCP Handling:** Pass `mcp_servers` to `messages.create()`
- **Scoping:** Different requests get different MCPs naturally
- **Effort:** Very Low (just pass parameter through)

```python
async def execute(self, context: ExecutionContext, ...):
    # Convert context.mcp_servers to Claude API format
    mcp_servers = context.mcp_servers if context.mcp_servers else []

    response = await client.messages.create(
        model=self.model,
        max_tokens=self.max_tokens,
        tools=...,
        mcp_servers=convert_to_claude_format(mcp_servers),  # ← NEW
        messages=messages,
    )
```

### Codex Server
- **Boundary:** Per run (one `codex app-server` process per run, multiple threads per task)
- **MCP Handling:** Create new thread via `thread/start` with step-specific MCPs for each task
- **Scoping:** Single process per run, but each task gets isolated thread with its own tools via `dynamicTools` parameter
- **Effort:** Low-Medium (thread management within existing process lifecycle)
- **Note:** Tasks within a run execute sequentially. Codex protocol includes `threadId` in notifications for validation and future parallel support.

```python
class CodexServerSession:
    """Manages a single Codex process for a run's lifetime."""

    async def start(self):
        # Spawn once per run
        self._codex_home = tempfile.mkdtemp(prefix=f"codex-{self.run_id}-")
        self._process = await spawn_codex_app_server(self._codex_home)
        await self._initialize()
        await self._authenticate()

    async def create_task_thread(self, context: ExecutionContext):
        # Create new thread once per task with step-specific MCPs
        tool_specs = build_dynamic_tool_specs(
            mcp_servers=context.mcp_servers,
            available_tools=context.available_tools
        )
        thread_id = await self._thread_start(dynamicTools=tool_specs)
        return thread_id

    async def cleanup(self):
        # Kill process once at run end
        self._process.terminate()
        shutil.rmtree(self._codex_home)

# In executor's _run_agent_loop:
async def _run_agent_loop(self, run: RunModel):
    # Create session once per run
    codex_session = CodexServerSession(run.id)
    await codex_session.start()

    try:
        while True:
            task_state = ...
            # Create thread once per task (not new process)
            thread_id = await codex_session.create_task_thread(context)
            agent = CodexServerAgent(codex_session, thread_id)
            result = await agent.execute(context, ...)
    finally:
        await codex_session.cleanup()
```

**Benefits:**
- ✅ Eliminates per-task spawn overhead (~500ms per task saved)
- ✅ Each task gets isolated thread with step-specific MCPs via `dynamicTools`
- ✅ Codex protocol includes `threadId` in notifications for validation
- ✅ Infrastructure ready for future parallel task support (threadId routing)
- ✅ Matches Codex protocol design intent

### OpenHands
- **Boundary:** Per agent instance (each execution creates new agent)
- **MCP Handling:** Pass `mcp_config` to `Agent()` constructor
- **Scoping:** Different instances get different MCPs
- **Effort:** Very Low (single parameter)

```python
async def execute(self, context: ExecutionContext, ...):
    # Convert context.mcp_servers to OpenHands format
    mcp_config = convert_to_openhands_format(context.mcp_servers)

    agent = OHAgent(
        llm=llm,
        tools=...,
        mcp_config=mcp_config,  # ← NEW
    )
```

### CLI Agent
- **Boundary:** Per subprocess (subprocess gets fresh working directory)
- **MCP Handling:** Write `.mcp.json` to subprocess working directory
- **Scoping:** Each subprocess has isolated working dir, so different MCPs
- **Effort:** Medium (config generation, similar to Codex)

```python
async def execute(self, context: ExecutionContext, ...):
    # Write .mcp.json to working_dir
    mcp_config_path = Path(context.working_dir) / ".mcp.json"
    write_mcp_config(mcp_config_path, context.mcp_servers)

    # Subprocess will discover and use .mcp.json
    prompt = self.build_prompt(context)
    # (Include hint about .mcp.json availability)
```

### User-Managed
- **Boundary:** Not applicable (agent is external)
- **MCP Handling:** Include in CallbackInstructions/prompt response
- **Scoping:** External agent decides which MCPs to connect to
- **Effort:** Low (information exposure)

```python
# In GET /tasks/{task_id}/prompt endpoint
mcp_info = {
    "available_mcp_servers": context.mcp_servers,
    "mcp_instructions": format_mcp_instructions(context.mcp_servers)
}
return PromptResponse(
    callback=CallbackInstructions(..., mcp_info=mcp_info)  # ← NEW
)
```

---

## The Benefit: No Global Registration

**Original (incorrect) concern:** "MCPs registered globally, then blocked per task"

**Reality:** MCPs are naturally scoped to execution boundaries:
- Each Claude SDK request is independent (per API call)
- Each Codex process is isolated (per run, with threads per task)
- Each OpenHands agent instance is separate (per task)
- Each CLI subprocess has isolated working directory (per task)

**Result:** No blocking needed, no global state to manage. Step-level MCPs "just work."

```yaml
# Example: Different steps, different MCPs
routine:
  steps:
    - id: analyze-code
      mcp_servers:
        - name: filesystem
          command: filesystem-mcp
        - name: code-analyzer
          url: http://localhost:5000

    - id: test-code
      mcp_servers:
        - name: test-runner
          command: test-runner-mcp
        - name: filesystem
          command: filesystem-mcp
        # Note: can reuse 'filesystem' in different step

    - id: review
      mcp_servers:
        # Only human-readable tools for review step
        - name: browser
          command: browser-mcp
```

Each step automatically gets only its configured MCPs. No conflicts, no blocking.

---

## Implementation Phases

### Phase 0: Schema (Very Low Effort)
Add `MCPServerConfig` and `mcp_servers` to models:
- File: `/src/orchestrator/config/models.py`
- Time: 1-2 hours

### Phase 1: ExecutionContext (Low Effort)
Extend ExecutionContext and populate in executor:
- Files: `/src/orchestrator/agents/types.py`, `/src/orchestrator/agents/executor.py`
- Time: 1-2 hours

### Phase 2: Claude SDK (Very Low Effort, Start Here)
- File: `/src/orchestrator/agents/claude_sdk.py`
- Time: 1-2 hours
- Why first: Cleanest API, easiest to test

### Phase 3: Codex Server (Medium Effort)
- Files: `/src/orchestrator/agents/executor.py`, `/src/orchestrator/agents/codex_server.py`, `codex_server_common.py`
- Time: 4-5 hours (includes threadId tracking for future parallelism)
- Key change: Refactor to use one `CodexServerSession` per run with threadId tracking
- Benefit: Eliminates per-task spawn overhead (~500ms per task), improves performance
- Features:
  - Creates new thread per task with step-specific MCPs via `dynamicTools` parameter
  - Tracks threadId for notification validation
  - Infrastructure ready for future parallel task execution
  - Better debugging and logging

### Phase 4: OpenHands (Very Low Effort)
- File: `/src/orchestrator/agents/openhands.py`
- Time: 1-2 hours

### Phase 5: CLI Agent (Medium Effort)
- File: `/src/orchestrator/agents/cli.py`
- Time: 2-3 hours

### Phase 6+: User-Managed, Frontend UI, Tests
- Time: 3-4 hours

**Total: 14-21 hours for complete implementation**
**MVP (Claude SDK + Codex): 6-9 hours**
  - Phase 0: 1-2 hours
  - Phase 1: 1-2 hours
  - Phase 2 (Claude SDK): 1-2 hours
  - Phase 3 (Codex Server): 4-5 hours (includes process-per-run refactor + threadId tracking)

---

## Example: Adding chrome-mcp and context7

### Step 1: Define in Routine YAML

```yaml
routine:
  name: "Web Analysis"
  steps:
    - id: browse-and-analyze
      description: "Browse web and analyze context"
      mcp_servers:
        - name: chrome
          url: "http://localhost:3000"
          # Assumes chrome-mcp running on port 3000
          # Requires CHROME_MCP_TOKEN env var at runtime
          auth_token_env: "CHROME_MCP_TOKEN"

        - name: context7
          command: "context7-mcp"
          args: ["--language", "en", "--memory", "8GB"]
          env:
            CONTEXT7_HOME: "/tmp/context7"
```

### Step 2: Executor Automatically Threads It

```python
# In executor.py, when creating ExecutionContext:
step_config = run.routine.steps[step_index]
context = ExecutionContext(
    run_id=...,
    task_id=...,
    mcp_servers=step_config.mcp_servers,  # ← Automatically threaded
    ...
)
```

### Step 3: Agent Uses It

**Claude SDK:**
```python
# In claude_sdk.py execute()
mcp_servers = context.mcp_servers or []
response = client.messages.create(
    ...,
    mcp_servers=[
        {
            "name": "chrome",
            "url": "http://localhost:3000"
        },
        {
            "name": "context7",
            "command": "context7-mcp",
            "args": ["--language", "en", "--memory", "8GB"]
        }
    ]
)
```

**Done.** Claude SDK agent now has chrome-mcp and context7 available.

---

## Security Considerations

### ✅ DO: Use Environment Variable References
```yaml
mcp_servers:
  - name: chrome
    url: "http://localhost:3000"
    auth_token_env: "CHROME_MCP_TOKEN"
    # At runtime, agent reads env.CHROME_MCP_TOKEN
```

### ❌ DON'T: Put Secrets in YAML
```yaml
# WRONG - NEVER DO THIS
mcp_servers:
  - name: chrome
    auth_token: "sk-1234567890abcdef"  # ← EXPOSED IN YAML FILE
```

### Auth Token Flow
```
Routine YAML: auth_token_env: "CHROME_MCP_TOKEN"
    ↓
Executor reads: os.environ.get("CHROME_MCP_TOKEN")
    ↓
ExecutionContext.mcp_servers carries reference (not token)
    ↓
Agent wiring passes to SDK: agent reads same env var
    ↓
MCP server connects with token
```

Token never appears in logs, configs, or prompts.

---

## Comparison: Before vs After

### Before This Investigation
- ❌ No external MCP support
- ❌ Only internal orchestrator tools
- ❌ Phase-based filtering (not step-level)
- ❌ Would need global registration + blocking
- ❌ Limited to 5-10 tools per agent

### After This Investigation
- ✅ Full external MCP support
- ✅ Internal + external MCPs
- ✅ Step-level configuration (dynamic per execution)
- ✅ Natural execution boundaries (no blocking needed)
- ✅ Unlimited MCPs per step (limited only by availability)

---

## Testing Strategy

### Unit Tests Per Agent

```python
async def test_mcp_servers_passed_to_claude_api():
    """Verify MCP servers from context reach Claude API."""
    context = ExecutionContext(
        ...,
        mcp_servers=[
            MCPServerConfig(name="chrome", url="http://localhost:3000")
        ]
    )
    agent = ClaudeSDKAgent(...)

    # Capture what was sent to API
    with mock.patch("client.messages.create") as mock_api:
        await agent.execute(context, ...)

        # Verify mcp_servers in call
        assert mock_api.call_args.kwargs["mcp_servers"] == [...]

async def test_mcp_servers_in_codex_config():
    """Verify MCP servers written to CODEX_HOME/config.toml."""
    context = ExecutionContext(
        ...,
        mcp_servers=[
            MCPServerConfig(name="context7", command="context7-mcp")
        ]
    )
    agent = CodexServerAgent(...)

    # Capture CODEX_HOME
    with mock.patch("subprocess.Popen") as mock_popen:
        await agent.execute(context, ...)

        # Verify config.toml was written with MCP
        codex_home = mock_popen.call_args.env["CODEX_HOME"]
        config = read_codex_config(codex_home / "config.toml")
        assert "context7" in config.mcp_servers
```

### Integration Tests

```python
async def test_external_mcp_per_step():
    """End-to-end: different steps get different MCPs."""
    routine = Routine(
        steps=[
            StepConfig(
                id="step-1",
                mcp_servers=[
                    MCPServerConfig(name="chrome", url="...")
                ]
            ),
            StepConfig(
                id="step-2",
                mcp_servers=[
                    MCPServerConfig(name="context7", command="...")
                ]
            ),
        ]
    )

    run = create_run(routine)

    # Execute step-1
    result1 = await execute_step(run, step_index=0)
    assert "chrome" in result1.mcp_servers_used

    # Advance to step-2
    run.current_step_index = 1

    # Execute step-2
    result2 = await execute_step(run, step_index=1)
    assert "context7" in result2.mcp_servers_used
    assert "chrome" not in result2.mcp_servers_used
```

---

## Quick Reference: What Changed from Original Investigation

| Aspect | Original Investigation | External MCP Correction |
|--------|---|---|
| **Scope** | Internal tools only (orchestrator_*) | External MCPs + internal tools |
| **Registration** | Global, then blocked per step | Per-execution, natural scoping |
| **Configuration** | Tool filtering | MCP server specification |
| **Data Model** | `available_tools: list[str]` | `mcp_servers: list[MCPServerConfig]` |
| **Agent Support** | Partial (filters only) | Full (native MCP support) |
| **Implementation** | Complex filtering | Simple parameter passing |

---

## Next Steps

1. ✅ Read this document
2. ✅ Read the full guide at `/docs/intent/24-EXTERNAL-MCP-IMPLEMENTATION-GUIDE.md`
3. **Create MCPServerConfig model** (Phase 0, 1 hour)
4. **Start with Claude SDK** (Phase 2, 1-2 hours)
5. **Test with chrome-mcp** (2-3 hours)
6. **Roll out to other agents** (2-3 hours each)

**Total MVP: 6-8 hours to have chrome-mcp + context7 working across agents.**

---

## Key Takeaway

You were right to push back on the original investigation. **The fundamental architecture is different than discovered initially:**

- **Not:** Global registration + blocking
- **Actually:** Per-execution scoping + natural isolation

This makes external MCPs much simpler to implement and use than originally thought.
