# CLAUDE.md - Orchestrator Implementation Guide

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**Orchestrator** coordinates LLM-powered coding agents through structured workflows using a **Routine/Run** model:

- **Routines**: Git-versioned workflow templates
- **Runs**: Execution instances with user-selected agents
- **Fresh context**: Builder and verifier phases get clean context

Key design decisions:
- Simplified YAML (no ref/use inheritance)
- User selects agent (no auto-selection)
- Pessimistic locking for state
- Event sourcing for recovery
- Token tracking for cost estimates

## Quick Reference

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest
uv run pytest tests/unit/test_workflow.py
uv run pytest tests/unit/test_workflow.py::test_checklist_gate

# Type checking and linting
uv run pyright
uv run ruff check .
uv run ruff format .

# Start server
uv run orchestrator serve --reload

# CLI
uv run orchestrator routine list
uv run orchestrator run list --status active
uv run orchestrator run agents <run-id>
```

---

## Architecture Overview

### Core Flow

```
User creates Run
       │
       ▼
Select Agent (from detected options)
       │
       ▼
Start Run (create worktree, acquire lock)
       │
       ▼
┌──────┴──────┐
│   Builder   │ ← Fresh context
│   Phase     │
└──────┬──────┘
       │ submit
       ▼
┌─────────────┐
│  Verifier   │ ← Fresh context
│   Phase     │
└──────┬──────┘
       │
  ┌────┴────┐
  │         │
pass     revise
  │         │
  ▼         ▼
next    Builder ← Fresh context (attempt++)
task
```

### Directory Structure

```
src/orchestrator/
├── server/          # FastAPI app
│   ├── routes/      # API endpoints
│   └── websocket.py # Real-time (throttled)
├── workflow/        # State machine
│   ├── engine.py    # Core orchestration
│   ├── gates.py     # Checklist/grade gates
│   └── transitions.py
├── agents/          # Agent integrations
│   ├── base.py      # Interface
│   ├── openhands.py # OpenHands
│   ├── cli.py       # CLI subprocess
│   ├── nudger.py    # Stuck detection
│   └── prompts.py   # Prompt generation
├── routines/        # Routine management
│   ├── resolver.py  # Load from git
│   └── versioning.py # SHA tracking
├── tools/           # Tool detection
│   └── detector.py  # Find available agents
├── projects/        # Git operations
│   └── worktree.py  # Worktree management
└── state/           # Persistence
    ├── database.py  # SQLite
    ├── session.py   # JSON state
    └── history.py   # JSONL events
```

---

## Key Design Decisions

### 1. No Mocking in Tests

**CRITICAL: Never use `patch`, `MagicMock`, or similar.**

```python
# ❌ WRONG
@patch('orchestrator.workflow.engine.run_verification')
def test_submit(mock_verify):
    mock_verify.return_value = VerifyResult(status="pass")

# ✅ CORRECT
def test_submit(tmp_path):
    # Create real routine in git repo
    repo = git.Repo.init(tmp_path / "routines")
    routine_file = tmp_path / "routines" / "test.yaml"
    routine_file.write_text(SAMPLE_ROUTINE)
    repo.index.add(["test.yaml"])
    repo.index.commit("Add routine")
    
    # Use real objects
    engine = WorkflowEngine(routines_dir=tmp_path / "routines", db_path=":memory:")
    result = engine.submit_task(run_id, task_id)
```

### 2. Simplified YAML Schema

No `ref:` or `use:` inheritance. Everything explicit.

```yaml
# ✅ CORRECT - Explicit
routine:
  steps:
    - id: "S-01"
      task:
        requirements:
          - id: "R1"
            desc: "Create file"
            must: true
            priority: critical

# ❌ WRONG - Inheritance
routine:
  steps:
    - id: "S-01"
      task:
        requirements:
          - ref: code_quality  # NO! Don't use ref
```

### 3. User-Selected Agents

Never auto-select agents. Always present options.

```python
# ✅ CORRECT
available = await tool_detector.detect_available()
# Returns: [openhands, claude-cli, external-mcp]
# User picks one

# ❌ WRONG
agent = auto_select_best_agent(task)  # NO!
```

### 4. Fresh Context Per Phase

Each phase gets clean context. No carryover.

```python
# ✅ CORRECT
async def start_builder_phase(run_id: str) -> str:
    prompt = generate_builder_prompt(task)  # Fresh prompt
    return await agent.start_session(SessionContext(prompt=prompt))

async def start_verifier_phase(run_id: str) -> str:
    prompt = generate_verifier_prompt(task)  # Fresh prompt, no builder context
    return await agent.start_session(SessionContext(prompt=prompt))
```

### 5. Git-Versioned Routines

Routines must be committed. Record SHA.

```python
# ✅ CORRECT
async def load_routine(routine_id: str, source_path: Path) -> Routine:
    repo = git.Repo(source_path)
    
    # Verify committed
    if repo.is_dirty(path=routine_file):
        raise RoutineNotCommittedError(routine_id)
    
    # Record SHA
    sha = repo.head.commit.hexsha
    routine = parse_routine(routine_file)
    routine.git_sha = sha
    return routine
```

### 6. Pessimistic Locking

Lock task when agent starts. Simple approach.

```python
# ✅ CORRECT
async def start_task(run_id: str, task_id: str) -> None:
    lock = await acquire_lock(f"task:{task_id}", timeout=300)
    if not lock:
        raise TaskLockedError(task_id)
    try:
        # Do work
        pass
    finally:
        await release_lock(lock)
```

### 7. Event Sourcing for Recovery

Log critical transitions. Reconstruct on startup.

```python
# ✅ CORRECT
async def transition_to_verifying(run_id: str, task_id: str) -> None:
    # Log event FIRST
    await history.log(HistoryEvent(
        event_type="transition",
        data={"from": "building", "to": "verifying"}
    ))
    # Then update state
    await state_manager.update_status(run_id, task_id, "verifying")
```

---

## CLI Agent Nudging

When using CLI in subprocess mode:

```python
class CLINudger:
    def __init__(self):
        self.nudge_count = 0
        self.max_nudges = 3
        self.nudge_interval = 30  # seconds
        self.output_timeout = 60  # seconds
    
    async def monitor(self, process: Process) -> None:
        last_output = time.time()
        
        while process.running:
            # Check for output
            if has_new_output(process):
                last_output = time.time()
                self.nudge_count = 0
                continue
            
            # Check timeout
            if time.time() - last_output > self.output_timeout:
                if self.nudge_count >= self.max_nudges:
                    await self.kill_agent(process)
                    return
                
                await self.send_nudge(process)
                self.nudge_count += 1
                await asyncio.sleep(self.nudge_interval)
    
    async def send_nudge(self, process: Process) -> None:
        nudge = "Please continue with the task or call the orchestrator tools."
        process.stdin.write(nudge)
```

---

## Token Tracking

Track tokens per attempt:

```python
class Attempt(BaseModel):
    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0

# Update after agent interaction
attempt.tokens_read += response.usage.input_tokens
attempt.tokens_write += response.usage.output_tokens
attempt.duration_ms += response.elapsed_ms
```

Display with estimate:

```python
def format_cost_display(run: Run) -> str:
    return f"""
Tokens: {run.total_tokens_read:,} read / {run.total_tokens_write:,} write
Est. Cost: ${estimate_cost(run):.2f} ⓘ
"""
# Hover: "Estimate only. Hidden costs may exist for some providers."
```

---

## Testing Guidelines

### Unit Tests
- State machine transitions
- Gate logic
- Nudge mechanism
- Config validation

### Integration Tests (Need Credentials)
```python
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No OPENAI_API_KEY for LLM provider")
async def test_openhands_integration():
    # Requires: openhands-ai SDK installed + OPENAI_API_KEY in .env
    agent = OpenHandsAgent(model="gpt-5-mini")
    result = await agent.execute(context, on_checklist_update, on_submit)
    # ...
```

### Test Routines in Git
```python
@pytest.fixture
def routine_repo(tmp_path):
    """Create a git repo with test routines."""
    repo_path = tmp_path / "routines"
    repo_path.mkdir()
    repo = git.Repo.init(repo_path)
    
    # Add routine
    routine_file = repo_path / "test.yaml"
    routine_file.write_text(SAMPLE_ROUTINE_YAML)
    repo.index.add(["test.yaml"])
    repo.index.commit("Add test routine")
    
    return repo_path
```

---

## Build Order

Work incrementally with full testing:

1. **Config & Models** - Simplified schema, no inheritance
2. **Routine Loading** - Git versioning, SHA tracking
3. **State Machine** - Run/task lifecycle
4. **Gates** - Checklist, grade thresholds
5. **Event History** - JSONL logging, recovery
6. **Tool Detection** - Find available agents
7. **OpenHands Agent** - API integration
8. **CLI Agent** - Subprocess, nudging
9. **MCP Server** - External agent support
10. **API Endpoints** - REST, WebSocket
11. **Dashboard UI** - Active + recent runs
12. **Agent Guidance UI** - External agent UX
13. **Worktree** - Git worktree management
14. **Completion Actions** - MR, merge, cleanup

---

## Common Patterns

### Creating a Run

```python
# Detect available agents
agents = await tool_detector.detect_available()

# Create run
run = await engine.create_run(
    project_id=project.id,
    routine_id="planning",
    routine_source="local",
    config={"feature_name": "auth"},
)

# User selects agent
run.agent_type = AgentType.OPENHANDS_LOCAL  # User choice!

# Start
await engine.start_run(run.id)
```

### External Agent Flow

```python
# User clicks "Start with external agent"
guidance = await engine.get_agent_guidance(run_id)
# Returns: prompt, MCP URL, expected actions

# UI shows guidance, user clicks "I've started"
await engine.mark_agent_started(run_id)

# Wait for MCP connection
async for status in engine.watch_agent_connection(run_id):
    if status == "connected":
        break
    if status == "timed_out":
        raise AgentTimeoutError()
```

### Recovery on Startup

```python
async def recover_state():
    for run in await get_active_runs():
        events = await history.read(run.id)
        
        # Find last known state
        last_event = events[-1]
        
        # Reconstruct
        if last_event.event_type == "transition":
            await state.update_status(run.id, last_event.data["to"])
```

---

## Environment Variables

Store secrets in `.env` at project root (see `.env.example`). Never commit `.env`.

```bash
# LLM provider key (required for OpenHands agent)
OPENAI_API_KEY="sk-your-key-here"

# Database
ORCHESTRATOR_DB_PATH="~/.orchestrator/orchestrator.db"

# Routines
ORCHESTRATOR_ROUTINES_DIR="~/.orchestrator/routines"

# Agents
ORCHESTRATOR_OPENHANDS_MODEL="gpt-5-mini"

# Dashboard
ORCHESTRATOR_RECENT_HOURS=24  # 1, 4, 24, 168

# Logging
ORCHESTRATOR_LOG_LEVEL="INFO"
```

---

## Debugging

```bash
# Check state
cat .orchestrator/state/session.json | jq

# Check history (event sourcing)
tail -20 .orchestrator/state/history.jsonl | jq

# Check routine version
git -C routines log --oneline -1 planning.yaml
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `docs/01-ARCHITECTURE.md` | System design |
| `docs/02-OPEN-QUESTIONS.md` | Decisions made + new questions |
| `docs/03-PRD.md` | Requirements |
| `docs/05-IMPLEMENTATION-PLAN.md` | Build order |
| `docs/06-EXAMPLE-CONFIGS.md` | YAML examples |
