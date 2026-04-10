# Implementation Slices: Phase 5 - Agent Integration

**Goal:** Integrate with actual AI agents: OpenHands, CLI tools, and MCP.

**End state:** Can execute tasks using real agents with tool calls for checklist updates.

**Prerequisites:** Phase 4 complete.

---

## Environment Setup

Before starting Phase 5:

1. **`.env` file** at project root with `OPENAI_API_KEY` (used by OpenHands as the LLM provider key). See `.env.example`.
2. **`.gitignore`** must exclude `.env` to prevent committing secrets.
3. **`openhands-ai` Python package** added as a dependency:
   ```bash
   uv add openhands-ai
   ```
4. **Docker** (optional, for OpenHands Docker mode):
   ```bash
   # Only needed if using DockerOpenHandsAgent
   docker info  # Verify Docker daemon is running
   ```
5. **Default LLM model**: `gpt-5-mini` (configured in OpenHands agent settings).

---

## Slice 5.1: Agent Interface Definition

### Goal
Define the abstract interface that all agents must implement.

### Deliverables

```
src/orchestrator/agents/
├── __init__.py
├── errors.py      # AgentError, AgentExecutionError, AgentNotAvailableError, AgentCancelledError
├── interface.py   # Abstract agent interface
└── types.py       # Agent-related types
```

### Architecture Constraints

1. **Protocol-based interface** - Use Python Protocol for duck typing
2. **Async execution** - All agent operations are async  
3. **Tool callbacks** - Agent calls back to orchestrator for checklist updates
4. **Cancellation support** - Agent execution can be cancelled

### Implementation

Create types and protocol as described in the overview. Key interface:

```python
class Agent(Protocol):
    @property
    def info(self) -> AgentInfo: ...
    
    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
    ) -> ExecutionResult: ...
    
    async def cancel(self) -> None: ...
```

### Definition of Done
- [ ] Agent protocol defined
- [ ] ExecutionContext, ExecutionResult types defined
- [ ] Callback types defined

---

## Slice 5.2: Tool Detector

### Goal
Detect which agent tools are available on the system.

### Deliverables

```
src/orchestrator/agents/detector.py
```

### Implementation

Check for CLI tools (claude, codex) via `shutil.which()`. Check OpenHands Local via SDK import check (`openhands.sdk` importable). Check OpenHands Docker via Docker daemon availability (`docker info` returns 0) plus `openhands.workspace` importable. MCP External is always available.

### Definition of Done
- [ ] CLI detection works
- [ ] OpenHands Local detection via SDK import check works
- [ ] OpenHands Docker detection via Docker daemon + package import works
- [ ] Results include install hints for unavailable tools

---

## Slice 5.3: Mock Agent for Testing

### Goal
Create a mock agent that simulates agent behavior for testing.

### Deliverables

```
src/orchestrator/agents/mock.py
```

### Architecture Constraints

1. **Configurable behavior** - Can simulate success, failure, partial completion
2. **Deterministic** - Same inputs produce same outputs
3. **No real I/O** - Fast execution

### Implementation

```python
@dataclass
class MockBehavior:
    complete_requirements: list[str] = field(default_factory=list)
    fail_requirements: list[str] = field(default_factory=list)
    should_submit: bool = True
    should_fail: bool = False
    tokens_read: int = 100
    tokens_write: int = 50
    tokens_cache: int = 0
    duration_ms: int = 1000

class MockAgent:
    def __init__(self, behavior: MockBehavior | None = None): ...
    async def execute(self, context, on_checklist_update, on_submit) -> ExecutionResult: ...
```

### Verification

Test that mock agent:
- Calls on_checklist_update for configured requirements
- Calls on_submit when configured
- Returns correct ExecutionResult

### Definition of Done
- [ ] MockAgent implements Agent protocol
- [ ] Behavior is configurable
- [ ] Integration test passes

---

## Slice 5.4: OpenHands Agent Integration

### Goal
Implement agents that execute via the `openhands-ai` SDK in two modes: **Local** (in-process via `LocalConversation`) and **Docker** (ephemeral container via `DockerWorkspace`).

### Deliverables

```
src/orchestrator/agents/openhands.py          # Local in-process agent
src/orchestrator/agents/openhands_docker.py   # Docker container agent
```

### Architecture Constraints

1. **Use `openhands-ai` SDK** - Not raw HTTP calls. Install via `uv add openhands-ai`.
2. **Two execution modes:**
   - **Local** (`OpenHandsAgent`): Uses SDK's `LocalConversation`, runs entirely in-process. No remote server needed. Detection via SDK import check.
   - **Docker** (`DockerOpenHandsAgent`): Uses `DockerWorkspace` from `openhands-workspace` package, spawns ephemeral containers. Detection via Docker daemon + package import.
3. **LLM provider key from environment** - `OPENAI_API_KEY` is loaded from `.env` and passed to OpenHands for LLM access.
4. **Default model: `gpt-5-mini`** - Configurable in agent settings.
5. **Custom tools for orchestrator callbacks** - Agent calls orchestrator tools (get_requirements, update_checklist, submit) registered as custom SDK tools. Tool executors bridge the SDK's sync execution to orchestrator's async callbacks via `asyncio.run_coroutine_threadsafe()`.
6. **Registry pattern** - Non-serializable callbacks stored in a module-level registry keyed by run/task ID, avoiding passing them through Tool.params.

### Implementation Notes

#### Local Agent (`openhands.py`)
- Check SDK availability via import
- Register custom tool types (Action/Observation/ToolDefinition) at module level for SDK's DiscriminatedUnion
- Build LLM + Agent with tools (terminal, file_editor, custom orchestrator tools)
- Create `LocalConversation` with `workspace=context.working_dir`
- Run via `asyncio.to_thread` since SDK is blocking
- Extract metrics from `conversation.conversation_stats`

#### Docker Agent (`openhands_docker.py`)
- Check Docker daemon availability and `openhands.workspace` importable
- Detect platform (`linux/amd64` or `linux/arm64`) for container image
- Separate tool registries (Docker-prefixed types) to avoid name collisions with Local agent
- Create `DockerWorkspace` which starts the container
- Create `Conversation` with workspace
- Automatic container cleanup via `workspace.cleanup()`

### Definition of Done
- [ ] `openhands-ai` added as dependency
- [ ] OpenHandsAgent runs in-process via LocalConversation
- [ ] DockerOpenHandsAgent spawns ephemeral containers via DockerWorkspace
- [ ] `OPENAI_API_KEY` passed to SDK for LLM access
- [ ] Custom orchestrator tools registered and functional
- [ ] Prompts sent correctly with requirements and tool instructions
- [ ] Tool calls bridge async callbacks correctly
- [ ] Metrics captured from conversation stats
- [ ] Integration test with `@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No OPENAI_API_KEY")` passes

---

## Slice 5.5: CLI Agent with Nudger

### Goal
Implement agent that runs CLI tools (Claude, Codex) as subprocess with nudge mechanism.

### Deliverables

```
src/orchestrator/agents/cli.py
src/orchestrator/agents/nudger.py
```

### Architecture Constraints

1. **Nudge on stuck** - Detect no output for 60s, send nudge
2. **Max nudges** - 3 nudges before kill
3. **Time injection** - Nudger timeout checks use injected time for testing

### Implementation: Nudger

```python
class TimeProvider(Protocol):
    def now(self) -> datetime: ...

class NudgeAction:
    NONE = "none"
    NUDGE = "nudge"
    KILL = "kill"

@dataclass
class NudgerConfig:
    output_timeout: timedelta = timedelta(seconds=60)
    nudge_interval: timedelta = timedelta(seconds=30)
    max_nudges: int = 3
    nudge_message: str = "Please continue or call orchestrator tools to submit."

class Nudger:
    def __init__(self, config: NudgerConfig, time_provider: TimeProvider): ...
    def record_output(self) -> None: ...
    def check(self) -> str: ...  # Returns NudgeAction constant (NONE, NUDGE, or KILL)
    def record_nudge(self) -> str: ...  # Returns nudge message, increments count
    @property
    def nudge_count(self) -> int: ...
```

### Verification

Unit tests for Nudger with mock time provider:
- No output timeout triggers stuck
- Nudge sent when stuck
- Max nudges triggers kill
- Output resets timeout

### Definition of Done
- [ ] Nudger logic works with mock time
- [ ] CLIAgent starts subprocess
- [ ] Nudges sent on stuck
- [ ] Kill after max nudges

---

## Slice 5.6: MCP Server for External Agents

### Goal
Implement MCP server that external agents (Cursor, etc.) can connect to.

### Deliverables

```
src/orchestrator/mcp/
├── __init__.py
├── server.py      # MCP server implementation
└── tools.py       # Tool definitions
```

### Architecture Constraints

1. **Standard MCP protocol** - Compatible with Cursor, etc.
2. **Orchestrator tools exposed** - update_checklist, submit, get_requirements
3. **Task context in tools** - Agent can query what it needs to do

### Implementation: Tool Definitions

```python
ORCHESTRATOR_TOOLS = [
    {
        "name": "orchestrator_update_checklist",
        "description": "Mark a requirement as done, not applicable, or blocked",
        "inputSchema": {...},
    },
    {
        "name": "orchestrator_submit", 
        "description": "Submit task for verification",
        "inputSchema": {...},
    },
    {
        "name": "orchestrator_get_requirements",
        "description": "Get the list of requirements for a task",
        "inputSchema": {...},
    },
    {
        "name": "orchestrator_set_grade",
        "description": "Set grade for a requirement (verifier only)",
        "inputSchema": {...},
    },
]
```

### Definition of Done
- [ ] MCP server starts
- [ ] Tools registered correctly
- [ ] Tool calls update state
- [ ] External agent can connect

---

## Phase 5 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Verify OpenHands SDK availability (Local mode)
uv run python -c "
try:
    import openhands.sdk
    print('SUCCESS: openhands-ai SDK available (Local mode ready)')
except ImportError:
    print('openhands-ai not installed. Install with: uv add openhands-ai')
"

# Verify Docker availability (Docker mode, optional)
uv run python -c "
import subprocess, shutil
if not shutil.which('docker'):
    print('Docker CLI not found - Docker mode unavailable')
else:
    result = subprocess.run(['docker', 'info'], capture_output=True)
    if result.returncode == 0:
        print('SUCCESS: Docker daemon running (Docker mode ready)')
    else:
        print('Docker daemon not running - Docker mode unavailable')
"

# Manual verification with mock agent
uv run python -c "
import asyncio
from orchestrator.agents.mock import MockAgent, MockBehavior
from orchestrator.agents.types import ExecutionContext

async def main():
    behavior = MockBehavior(
        complete_requirements=['R1', 'R2'],
        should_submit=True,
    )
    agent = MockAgent(behavior)

    updates = []
    submitted = False

    async def on_update(req_id, status, note):
        updates.append((req_id, status))

    async def on_submit():
        nonlocal submitted
        submitted = True

    context = ExecutionContext(
        run_id='run-1',
        task_id='task-1',
        working_dir='/tmp',
        prompt='Do something',
        requirements=['R1', 'R2'],
        # auth_token: set from app.state.auth_config when auth is enabled.
        # CLIAgent.build_prompt includes "Authorization: Bearer <token>"
        # instructions in the enriched prompt so the subprocess can
        # authenticate against REST/MCP endpoints.
        # For UserManagedAgent: the caller (API/UI) must surface the token
        # to the human operator (see Phase 6 Slice 6.4 AgentGuidancePanel).
    )

    result = await agent.execute(context, on_update, on_submit)

    assert result.success
    assert len(updates) == 2
    assert submitted
    print('SUCCESS!')

asyncio.run(main())
"
```

If agent integration works, Phase 5 is complete. Proceed to Phase 6.
