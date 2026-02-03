# Implementation Slices: Phase 8 - CLI & Polish

**Goal:** Implement CLI commands and comprehensive E2E tests.

**End state:** Complete, polished system ready for use.

**Prerequisites:** All previous phases complete.

---

## Slice 8.1: CLI Commands

### Goal
Implement CLI for common operations without needing UI.

### Deliverables

```
src/orchestrator/
├── cli/
│   ├── __init__.py
│   ├── main.py        # Click application
│   ├── runs.py        # Run commands
│   ├── routines.py    # Routine commands
│   └── agents.py      # Agent commands
```

### Architecture Constraints

1. **Click for CLI** - Popular, well-documented
2. **Async support** - Use asyncio.run for async operations
3. **JSON output option** - For scripting
4. **Consistent error handling** - User-friendly messages

### Implementation

```python
# src/orchestrator/cli/main.py
import click
import asyncio
from orchestrator.cli.runs import runs
from orchestrator.cli.routines import routines
from orchestrator.cli.agents import agents

@click.group()
@click.option('--db', default='orchestrator.db', help='Database path')
@click.option('--json', is_flag=True, help='Output as JSON')
@click.pass_context
def cli(ctx, db, json):
    """Orchestrator - LLM Agent Workflow Management."""
    ctx.ensure_object(dict)
    ctx.obj['db'] = db
    ctx.obj['json'] = json

cli.add_command(runs)
cli.add_command(routines)
cli.add_command(agents)

# src/orchestrator/cli/runs.py
@click.group()
def runs():
    """Manage runs."""
    pass

@runs.command('list')
@click.option('--project', '-p', help='Filter by project')
@click.option('--status', '-s', help='Filter by status')
@click.pass_context
def list_runs(ctx, project, status):
    """List runs."""
    async def _list():
        # Implementation
        pass
    asyncio.run(_list())

@runs.command('create')
@click.argument('routine_id')
@click.option('--project', '-p', required=True, help='Project ID')
@click.option('--config', '-c', multiple=True, help='Config key=value')
@click.pass_context
def create_run(ctx, routine_id, project, config):
    """Create a new run."""
    async def _create():
        # Parse config
        cfg = dict(kv.split('=', 1) for kv in config)
        # Create run
        pass
    asyncio.run(_create())

@runs.command('start')
@click.argument('run_id')
@click.pass_context
def start_run(ctx, run_id):
    """Start a run."""
    pass

@runs.command('watch')
@click.argument('run_id')
@click.pass_context
def watch_run(ctx, run_id):
    """Watch a run in real-time."""
    pass

# src/orchestrator/cli/routines.py
@click.group()
def routines():
    """Manage routines."""
    pass

@routines.command('list')
@click.option('--project', '-p', help='Project directory')
@click.pass_context
def list_routines(ctx, project):
    """List available routines."""
    pass

@routines.command('validate')
@click.argument('path')
@click.pass_context
def validate_routine(ctx, path):
    """Validate a routine file."""
    pass

# src/orchestrator/cli/agents.py
@click.group()
def agents():
    """Manage agents."""
    pass

@agents.command('detect')
@click.pass_context
def detect_agents(ctx):
    """Detect available agents."""
    pass
```

### Entry Point

Add to `pyproject.toml`:
```toml
[project.scripts]
orchestrator = "orchestrator.cli.main:cli"
```

### Verification

```bash
# Install
uv pip install -e .

# Test commands
orchestrator --help
orchestrator routines list
orchestrator agents detect
orchestrator runs list
```

### Definition of Done
- [ ] All CLI commands work
- [ ] JSON output works
- [ ] Error handling user-friendly
- [ ] Help text complete

---

## Slice 8.2: Error Handling & Edge Cases

### Goal
Comprehensive error handling throughout the system.

### Deliverables

```
src/orchestrator/
├── errors.py          # Central error types
tests/unit/test_error_handling.py
```

### Error Categories

1. **User errors** - Invalid input, missing config (4xx)
2. **System errors** - Database failure, network issues (5xx)
3. **Agent errors** - Agent crashed, timeout (specific handling)

### Implementation

```python
# src/orchestrator/errors.py
from enum import Enum

class ErrorCode(Enum):
    # User errors (4xx)
    ROUTINE_NOT_FOUND = "routine_not_found"
    RUN_NOT_FOUND = "run_not_found"
    INVALID_CONFIG = "invalid_config"
    INVALID_TRANSITION = "invalid_transition"
    GATE_FAILED = "gate_failed"
    
    # System errors (5xx)
    DATABASE_ERROR = "database_error"
    AGENT_ERROR = "agent_error"
    INTERNAL_ERROR = "internal_error"

class OrchestratorError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> dict:
        return {
            "error": self.code.value,
            "message": self.message,
            "details": self.details,
        }
```

### Edge Cases to Test

- Empty routine (no steps)
- Task with no requirements
- Agent times out mid-task
- Database connection lost during save
- WebSocket disconnect during update
- Worktree creation fails (disk full, permissions)
- Concurrent updates to same run

### Definition of Done
- [ ] Error types defined
- [ ] All endpoints return consistent errors
- [ ] Edge cases have tests
- [ ] CLI shows user-friendly errors

---

## Slice 8.3: Full E2E Test Suite

### Goal
Comprehensive E2E tests covering all major scenarios.

### Deliverables

```
tests/e2e/
├── conftest.py        # E2E fixtures
├── test_full_workflow.py
├── test_revision_flow.py
├── test_failure_recovery.py
└── test_multi_run.py
```

### E2E Test Scenarios

#### 1. Happy Path Workflow
```python
@pytest.mark.e2e
async def test_full_workflow():
    """Complete workflow: create → start → build → verify → complete."""
    # 1. Start API server
    # 2. Create run via API
    # 3. Start run
    # 4. Start task (mock agent)
    # 5. Update checklist items
    # 6. Submit for verification
    # 7. Set grades
    # 8. Complete verification
    # 9. Verify final state
```

#### 2. Revision Flow
```python
@pytest.mark.e2e
async def test_revision_flow():
    """Task fails verification, gets revision, passes."""
    # 1. Create and start run
    # 2. Complete building with missing requirements
    # 3. Submit → gate fails
    # 4. Complete remaining requirements
    # 5. Submit → passes
    # 6. Verify with failing grades
    # 7. Revision triggered
    # 8. Build again, verify again
    # 9. Pass verification
```

#### 3. Failure Recovery
```python
@pytest.mark.e2e
async def test_failure_recovery():
    """System recovers from crash via event replay."""
    # 1. Create run, start task
    # 2. Simulate crash (restart server)
    # 3. Verify state recovered
    # 4. Continue workflow
```

#### 4. Multiple Concurrent Runs
```python
@pytest.mark.e2e
async def test_multi_run():
    """Multiple runs can execute concurrently."""
    # 1. Create 3 runs
    # 2. Start all concurrently
    # 3. Progress each independently
    # 4. Verify no cross-contamination
```

### Running E2E Tests

```bash
# Start server in test mode
uv run uvicorn orchestrator.api.app:create_app --factory --port 8001 &
export TEST_API_URL=http://localhost:8001

# Run E2E tests
uv run pytest tests/e2e -v --tb=short

# Cleanup
kill %1
```

### Definition of Done
- [ ] All E2E scenarios pass
- [ ] Tests are reproducible
- [ ] Tests clean up after themselves
- [ ] CI can run E2E tests

---

## Final Milestone: Complete System Verification

### Manual Verification Checklist

Run through this checklist to verify the complete system:

#### Setup
- [ ] `uv sync` installs all dependencies
- [ ] `uv run orchestrator --help` shows CLI help
- [ ] `uv run uvicorn orchestrator.api.app:create_app --factory` starts server
- [ ] UI builds and serves

#### Routines
- [ ] CLI: `orchestrator routines list` shows routines
- [ ] CLI: `orchestrator routines validate <path>` validates YAML
- [ ] API: GET /api/routines returns list
- [ ] API: GET /api/routines/{id} returns detail
- [ ] Invalid YAML rejected with clear error

#### Runs
- [ ] CLI: `orchestrator runs create <routine> -p <project>` creates run
- [ ] CLI: `orchestrator runs list` shows runs
- [ ] CLI: `orchestrator runs start <id>` starts run
- [ ] API: POST /api/runs creates run
- [ ] API: GET /api/runs/{id} returns detail
- [ ] API: POST /api/runs/{id}/start transitions state

#### Tasks
- [ ] API: Task start transition works
- [ ] API: Checklist update works
- [ ] API: Submit for verification works
- [ ] API: Grade submission works
- [ ] Gate blocks incomplete checklists
- [ ] Grades evaluated correctly
- [ ] Revision triggered on failed grades

#### Agents
- [ ] CLI: `orchestrator agents detect` shows available agents
- [ ] Mock agent completes task
- [ ] CLI agent nudger works (with mock time)
- [ ] MCP server accepts connections

#### UI
- [ ] Dashboard shows runs
- [ ] Status updates in real-time
- [ ] Run detail shows checklist
- [ ] Agent guidance panel works

#### Git
- [ ] Worktree created for run
- [ ] Worktree isolated from main
- [ ] Worktree cleaned up on completion
- [ ] Routine version tracked

#### Persistence
- [ ] State persists across restart
- [ ] Events logged
- [ ] Recovery works

### Automated Test Summary

```bash
# Run all tests
uv run pytest tests/ -v --tb=short

# Expected:
# - Unit tests: ~100+ tests
# - Integration tests: ~50+ tests  
# - E2E tests: ~10+ tests
# - All passing
```

### Performance Baseline

- [ ] API response time < 100ms for reads
- [ ] WebSocket latency < 50ms
- [ ] Database queries < 50ms
- [ ] UI renders < 500ms

---

## Post-Implementation Notes

### What to Monitor in Production

1. **Run completion rate** - % of runs that complete vs fail
2. **Revision rate** - % of tasks needing revision
3. **Agent reliability** - % of agent executions that complete
4. **Gate pass rate** - How often checklist gates block

### Future Enhancements

From competitive analysis, consider adding:
1. Dead Letter Queue for failed tasks
2. MapReduce parallelism for batch operations
3. Knowledge persistence across runs
4. Template registry for sharing routines

### Known Limitations

1. Single SQLite database (not distributed)
2. Polling-based UI updates (WebSocket improves this)
3. No authentication/authorization (single user)
4. No cost tracking (token estimates only)

---

## Congratulations! 🎉

If you've completed all phases and verifications, you have a working Orchestrator system that:

- Loads routines from YAML
- Creates and manages runs
- Executes tasks through the builder/verifier workflow
- Enforces checklist gates and grade thresholds
- Integrates with multiple agent backends
- Provides a web UI for monitoring
- Uses git worktrees for isolation
- Has comprehensive test coverage

The system is ready for real-world use with AI coding agents!
