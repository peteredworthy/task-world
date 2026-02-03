# Implementation Plan

This document provides a step-by-step implementation plan reflecting the design decisions made. Build incrementally with full testing - this is not a traditional MVP.

---

## Build Philosophy

Per decision 8.1:
- Work incrementally with unit and functionality testing
- Build confidence by ensuring full correct functionality
- Start from orchestration and routing (simplest to fully construct and test)
- All features complete before external availability

---

## Phase 1: Configuration & Models

### Step 1.1: Project Structure

**Goal:** Create project skeleton with dependencies.

**Verification:**
```bash
uv sync
uv run python -c "import orchestrator"
uv run pytest --collect-only
```

---

### Step 1.2: Simplified Config Models

**Goal:** Pydantic models with NO inheritance (no ref/use).

Key models:
- `RoutineConfig` - No ref/use fields
- `TaskConfig` - Includes `model_overrides` for per-model prompts
- `RunConfig` - Includes `agent_type`, `completion_action`

**Tests:** Verify ref/use fields raise errors.

---

### Step 1.3: Git-Based Routine Loading

**Goal:** Load routines from git with SHA versioning.

- Routines must be committed
- Record SHA at load time
- Support local, project, and allowlisted external sources

**Tests:** Uncommitted routines fail to load.

---

## Phase 2: State Machine & Orchestration

### Step 2.1: Database Models

**Goal:** SQLite models with token tracking.

Key fields on `Attempt`:
- `tokens_read`, `tokens_write`, `tokens_cache`
- `duration_ms`

**Note:** Defer Alembic until schema stabilizes.

---

### Step 2.2: Event History (Event Sourcing)

**Goal:** JSONL history for crash recovery.

```python
class HistoryLogger:
    async def log(self, event: HistoryEvent) -> None: ...
    async def read(self, run_id: str) -> list[HistoryEvent]: ...
    async def recover_state(self, run_id: str) -> SessionState: ...
```

---

### Step 2.3: Pessimistic Locking

**Goal:** Simple lock with 5-minute timeout.

```python
class LockManager:
    async def acquire(self, resource: str) -> Lock | None: ...
    async def release(self, lock: Lock) -> None: ...
```

---

### Step 2.4: Gate Logic

**Goal:** Checklist and grade threshold gates.

- Critical requirements must be done or justified
- Grade thresholds: A for critical, B for expected

---

### Step 2.5: Workflow Engine

**Goal:** Core orchestration with fresh context per phase.

Key behaviors:
- Fresh prompt generated for each phase (builder, verifier, revision)
- Lock acquired before task starts
- Events logged before state changes
- Token counts aggregated

---

## Phase 3: Tool Detection & Agents

### Step 3.1: Tool Detector

**Goal:** Detect available agents for user selection.

```python
class ToolDetector:
    async def detect_all(self) -> list[AgentOption]:
        # Check OpenHands Local (SDK import check)
        # Check OpenHands Docker (Docker daemon + package import)
        # Check CLI tools: claude, codex (shutil.which)
        # Always offer external MCP
        ...
```

No auto-selection - return options for user to choose.

---

### Step 3.2: OpenHands Agents

**Goal:** OpenHands integration via SDK in two modes: Local (in-process) and Docker (ephemeral containers).

```python
# Local: runs entirely in-process via SDK's LocalConversation
class OpenHandsAgent:
    async def execute(self, context, on_checklist_update, on_submit) -> ExecutionResult:
        # Check SDK available, API key present
        # Register custom orchestrator tools (get_requirements, update_checklist, submit)
        # Create LocalConversation with workspace=context.working_dir
        # Run via asyncio.to_thread (SDK is blocking)
        # Extract metrics from conversation_stats
        ...

# Docker: spawns ephemeral container via DockerWorkspace
class DockerOpenHandsAgent:
    async def execute(self, context, on_checklist_update, on_submit) -> ExecutionResult:
        # Check SDK + Docker available
        # Create DockerWorkspace (starts container)
        # Create Conversation with workspace
        # Run, extract metrics
        # Cleanup: workspace.cleanup() removes container
        ...
```

---

### Step 3.3: CLI Subprocess Agent

**Goal:** Manage CLI tools with nudge mechanism.

```python
class CLISubprocessAgent(AgentInterface):
    def __init__(self, cli_command: str, nudger: CLINudger):
        self.cli = cli_command
        self.nudger = nudger
    
    async def start_session(self, context: SessionContext) -> str:
        # Spawn subprocess
        # Start nudger monitoring
        ...
```

---

### Step 3.4: CLI Nudger

**Goal:** Detect stuck agents and nudge them.

```python
class CLINudger:
    output_timeout: int = 60      # seconds
    nudge_interval: int = 30      # seconds
    max_nudges: int = 3
    
    async def monitor(self, process: Process) -> None:
        while process.running:
            if no_output_for(self.output_timeout):
                if self.nudge_count >= self.max_nudges:
                    await self.kill(process)
                    return
                await self.send_nudge(process)
                self.nudge_count += 1
    
    async def send_nudge(self, process: Process) -> None:
        msg = "Please continue or call orchestrator tools to submit."
        process.stdin.write(msg)
```

---

### Step 3.5: MCP Server

**Goal:** MCP tools for external agents.

Tools:
- `checklist_set(req_id, status, note?)`
- `verify_run()`
- `task_submit(message?)`
- `grade_requirement(req_id, grade, reason?)`
- `complete_verification()`
- `state_get()`

---

### Step 3.6: External Agent UX

**Goal:** Guidance for external agents.

```python
class ExternalAgentGuidance(BaseModel):
    prompt: str
    mcp_server_url: str
    expected_actions: list[str]
    started_at: datetime | None
    timeout_minutes: int = 5

# Endpoints
GET  /api/runs/{id}/guidance       # Get prompt and MCP URL
POST /api/runs/{id}/agent-started  # User clicked "I've started"
POST /api/runs/{id}/agent-cancelled
```

---

## Phase 4: API Server

### Step 4.1: FastAPI App

**Goal:** App factory with lifespan.

```python
def create_app(db_path: str = ":memory:") -> FastAPI:
    app = FastAPI(title="Orchestrator")
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Init DB, routine resolver, tool detector
        yield
        # Cleanup
    
    app.include_router(routines_router)
    app.include_router(runs_router)
    app.include_router(tasks_router)
    
    return app
```

---

### Step 4.2: Routine Endpoints

```
GET  /api/routines              List routines
GET  /api/routines/{id}         Get routine details
POST /api/routines/validate     Validate YAML
```

---

### Step 4.3: Run Endpoints

```
GET  /api/runs                  List runs
GET  /api/runs?status=active    Filter by status
GET  /api/runs?recent_hours=24  Recent runs
POST /api/runs                  Create run
GET  /api/runs/{id}             Get run
GET  /api/runs/{id}/agents      Get available agents

POST /api/runs/{id}/queue       Queue run
POST /api/runs/{id}/start       Start (with agent_type)
POST /api/runs/{id}/pause       Pause
POST /api/runs/{id}/resume      Resume
POST /api/runs/{id}/cancel      Cancel
```

---

### Step 4.4: Task Endpoints

```
GET   /api/runs/{rid}/tasks/{tid}                             Get task
POST  /api/runs/{rid}/tasks/{tid}/start                       Start building
POST  /api/runs/{rid}/tasks/{tid}/submit                      Builder submit
PATCH /api/runs/{rid}/tasks/{tid}/checklist/{req_id}          Update checklist item
PUT   /api/runs/{rid}/tasks/{tid}/checklist/{req_id}/grade    Grade a requirement
POST  /api/runs/{rid}/tasks/{tid}/complete-verification       Trigger grade evaluation
```

---

### Step 4.5: WebSocket (Throttled)

**Goal:** Real-time updates with throttling.

```python
class ConnectionManager:
    throttle_ms: int = 100
    
    async def broadcast(self, run_id: str, message: dict) -> None:
        # Throttle updates
        # Batch related messages
        ...
```

---

## Phase 5: Web UI

### Step 5.1: React Setup

```bash
cd ui
npm create vite@latest . -- --template react-ts
npm install tailwindcss lucide-react @tanstack/react-query zustand
```

---

### Step 5.2: Dashboard

**Goal:** Active + recent runs (configurable recency).

Features:
- Show active runs
- Show recent (1hr, 4hrs, 24hrs, 1 week - configurable)
- Filter by project
- Group by project
- Multi-project view

---

### Step 5.3: Run Detail

**Goal:** Run status, steps, metrics.

Display:
- Run status and agent type
- Routine info (ID, SHA)
- Step progress
- Token counts and cost estimate
- Hover note: "Estimate only. Hidden costs may exist."

---

### Step 5.4: Agent Guidance Panel

**Goal:** UX for external agents.

Components:
- Copyable prompt
- MCP server URL
- Expected actions list
- "I've started the agent" button
- "Cancel waiting" button
- Connection status
- Timeout countdown

---

### Step 5.5: Agent Selection UI

**Goal:** Present detected agents for selection.

- List available agents from `/api/runs/{id}/agents`
- Show availability status
- Show config hints for unavailable
- User selects one to start

---

## Phase 6: Git Integration

### Step 6.1: Worktree Management

**Goal:** Per-run worktrees (default on, configurable).

```python
class WorktreeManager:
    async def create(self, run_id: str, branch: str | None) -> Path:
        # Create worktree in .worktrees/{run_id}
        ...
    
    async def cleanup(self, run_id: str) -> None:
        # Remove worktree
        ...
```

---

### Step 6.2: Completion Actions

**Goal:** Simple worktree cleanup on completion.

```python
async def complete_run(run: Run) -> None:
    # Mark run as completed
    run.status = RunStatus.COMPLETED
    await run_repo.update(run)
    
    # Handle worktree based on setting
    if run.delete_worktree_on_completion:
        await worktree_manager.cleanup(run.id)
    
    # Note: Git operations (MR, merge, etc.) are handled by
    # the routine itself via agent instructions, not orchestrator
```

**Configuration:**
```yaml
run:
  delete_worktree_on_completion: false  # Default: keep
```

---

## Phase 7: CLI

### Step 7.1: CLI Commands

```bash
# Server
orchestrator serve

# Routines
orchestrator routine list
orchestrator routine show <id>
orchestrator routine validate <path>

# Runs
orchestrator run list [--status STATUS] [--recent HOURS]
orchestrator run create <routine> --project <path> --config '<json>'
orchestrator run agents <id>
orchestrator run start <id> --agent <type>
orchestrator run status <id>
orchestrator run pause <id>
orchestrator run resume <id>
orchestrator run cancel <id>
```

---

## Phase 8: Polish

### Step 8.1: Error Handling

Standard error format:
```json
{
  "error": {
    "code": "ROUTINE_NOT_COMMITTED",
    "message": "Routine 'planning' has uncommitted changes",
    "details": { "routine_id": "planning" }
  }
}
```

---

### Step 8.2: Recovery on Startup

```python
async def recover_on_startup():
    for run in await get_runs_by_status(RunStatus.ACTIVE):
        try:
            state = await history.recover_state(run.id)
            await session_manager.save(state)
            logger.info(f"Recovered run {run.id}")
        except Exception as e:
            logger.error(f"Failed to recover {run.id}: {e}")
            await mark_run_failed(run.id, "Recovery failed")
```

---

### Step 8.3: Documentation

- README with quick start
- API reference (OpenAPI)
- Routine authoring guide
- Agent integration guide

---

## Implementation Checklist

```
Phase 1: Configuration
[ ] 1.1 Project structure
[ ] 1.2 Simplified config models (no ref/use)
[ ] 1.3 Git-based routine loading

Phase 2: State Machine
[ ] 2.1 Database models with token tracking
[ ] 2.2 Event history (JSONL)
[ ] 2.3 Pessimistic locking
[ ] 2.4 Gate logic
[ ] 2.5 Workflow engine (fresh context)

Phase 3: Agents
[ ] 3.1 Tool detector
[ ] 3.2 OpenHands agent
[ ] 3.3 CLI subprocess agent
[ ] 3.4 CLI nudger
[ ] 3.5 MCP server
[ ] 3.6 External agent UX

Phase 4: API
[ ] 4.1 FastAPI app
[ ] 4.2 Routine endpoints
[ ] 4.3 Run endpoints
[ ] 4.4 Task endpoints
[ ] 4.5 WebSocket (throttled)

Phase 5: UI
[ ] 5.1 React setup
[ ] 5.2 Dashboard (active + recent)
[ ] 5.3 Run detail with metrics
[ ] 5.4 Agent guidance panel
[ ] 5.5 Agent selection UI

Phase 6: Git
[ ] 6.1 Worktree management
[ ] 6.2 Completion actions

Phase 7: CLI
[ ] 7.1 CLI commands

Phase 8: Polish
[ ] 8.1 Error handling
[ ] 8.2 Recovery on startup
[ ] 8.3 Documentation
```

---

## Testing Requirements

### Unit Tests (No Credentials)
- Config validation (reject ref/use)
- Routine loading (mock git repo)
- Gate logic
- State machine transitions
- Nudger logic

### Integration Tests (Need Credentials)
- OpenHands (need openhands-ai SDK + OPENAI_API_KEY for LLM; Docker mode also needs Docker daemon)
- CLI tools (need authenticated CLIs)
- Git operations (real repos)

### E2E Tests
- Full run workflow
- External agent connection
- Crash recovery

---

## Notes for Implementation

1. **No mocking** - Use real temp files, in-memory DBs
2. **Simplified YAML** - Reject any ref/use inheritance
3. **User selects agent** - Never auto-select
4. **Fresh context** - New prompt each phase
5. **Git versioning** - Must be committed
6. **Token tracking** - Aggregate for cost display
7. **Event sourcing** - Log before state change
