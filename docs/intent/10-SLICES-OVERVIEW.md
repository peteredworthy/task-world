# Implementation Slices: Overview

This document series defines incremental implementation slices for building Orchestrator from scratch. Each slice is designed to be:

1. **End-to-end functional** - Every slice produces working, verifiable behavior
2. **Fully tested** - Unit, integration, and e2e tests prove correctness
3. **Incrementally buildable** - Later slices extend earlier ones without breaking them

---

## Core Principles

### Why Slicing Matters

LLMs have a blind spot for forming complete systems. They tend to:
- Create disconnected components that don't integrate
- Miss vital glue code that makes systems actually work
- Optimize locally while breaking global architecture

**Counter-measures:**
1. Each slice starts with a barely-functional end-to-end path
2. Validation proves the system works as a whole, not just in parts
3. Architecture decisions are explained with rationale to prevent "clever" local optimizations

### Testing Philosophy

**Three levels, strict separation:**

| Level | Dependencies | Speed | Scope |
|-------|--------------|-------|-------|
| **Unit** | None (pure functions, injected deps) | <1s per test | Single function/class |
| **Integration** | Real deps (DB, files), mocked externals | <10s per test | Component interactions |
| **E2E** | Full running system | <60s per test | User-facing scenarios |

**Critical rules:**
- No monkey patching (use dependency injection)
- Time is an external dependency (inject clocks)
- No sleeping in tests (use events/callbacks)
- Data in, data out functions enable testing

### Verification Standards

Each slice must prove:
1. **It works** - E2E test passes
2. **It integrates** - Doesn't break previous slices
3. **It's correct** - Unit tests cover logic paths
4. **It handles failure** - Error cases are tested

---

## Phase Overview

| Phase | Focus | Slices | Outcome |
|-------|-------|--------|---------|
| **Phase 1** | Foundation | 1.1-1.6 | Config loading, routine parsing, basic state |
| **Phase 2** | Workflow Engine | 2.1-2.5 | State machine, gates, transitions |
| **Phase 3** | Persistence | 3.1-3.4 | Database, sessions, history |
| **Phase 4** | API Server | 4.1-4.5 | REST endpoints, WebSocket |
| **Phase 5** | Agent Integration | 5.1-5.6 | OpenHands, CLI, MCP |
| **Phase 6** | Web UI | 6.1-6.4 | Dashboard, run detail, guidance |
| **Phase 7** | Git Integration | 7.1-7.3 | Worktrees, versioning |
| **Phase 8** | CLI & Polish | 8.1-8.3 | Commands, error handling |
| **Phase 9** | Advanced Workflows | 9.1-9.6 | Human gates, backward transitions, dry-run |
| **Phase 10** | Advanced Config | 10.1-10.5 | Clarification, model escalation, MCP client |

---

## Dependency Graph

```
Phase 1: Foundation
  1.1 Project skeleton
    └── 1.2 Config models
          └── 1.3 Routine loading
                └── 1.4 State models
                      └── 1.5 Run Factory
                            └── 1.6 Session State Manager

Phase 2: Workflow Engine (depends on Phase 1)
  2.1 Checklist logic
    └── 2.2 Grade logic
          └── 2.3 State machine
                └── 2.4 Workflow engine
                      └── 2.5 Prompt generation

Phase 3: Persistence (depends on 1.4, 2.4)
  3.1 Database setup
    └── 3.2 Repository pattern
          └── 3.3 Session persistence
                └── 3.4 Recovery logic

Phase 4: API Server (depends on Phase 2, 3)
  4.1 FastAPI setup
    └── 4.2 Routine endpoints
          └── 4.3 Run endpoints
                └── 4.4 Task endpoints
                      └── 4.5 WebSocket

Phase 5: Agent Integration (depends on 4.4)
  5.1 Agent interface + error types
    └── 5.2 Tool detector
          └── 5.3 Mock agent (for testing)
                └── 5.4 OpenHands agents (local + Docker)
                      └── 5.5 CLI agent + nudger
                            └── 5.6 MCP server

Phase 6: Web UI (depends on Phase 4)
  6.1 React setup
    └── 6.2 Dashboard
          └── 6.3 Run detail
                └── 6.4 Agent guidance

Phase 7: Git Integration (depends on 4.3)
  7.1 Worktree manager
    └── 7.2 Routine versioning
          └── 7.3 Completion actions

Phase 8: CLI & Polish (depends on all)
  8.1 CLI commands
    └── 8.2 Error handling
          └── 8.3 Full e2e suite

Phase 9: Advanced Workflows (depends on Phase 2, 3, 5)
  9.1 Human-only gate type
    └── 9.2 Backward transitions
          └── 9.3 Artifact registry
                └── 9.4 Dry-run verification
                      └── 9.5 Multi-artifact context
                            └── 9.6 Planning routine template

Phase 10: Advanced Config (depends on Phase 2, 5, 9)
  10.1 Clarification state machine
    └── 10.2 Model config inheritance
          └── 10.3 Model escalation on failure
                └── 10.4 MCP client integration
                      └── 10.5 Per-task tool scoping
```

---

## Document Index

| Document | Phases | Focus |
|----------|--------|-------|
| [11-SLICES-PHASE-1.md](./11-SLICES-PHASE-1.md) | 1 (1.1-1.6) | Foundation |
| [12-SLICES-PHASE-2.md](./12-SLICES-PHASE-2.md) | 2 (2.1-2.5) | Workflow Engine |
| [13-SLICES-PHASE-3.md](./13-SLICES-PHASE-3.md) | 3 (3.1-3.4) | Persistence |
| [14-SLICES-PHASE-4.md](./14-SLICES-PHASE-4.md) | 4 (4.1-4.5) | API Server |
| [15-SLICES-PHASE-5.md](./15-SLICES-PHASE-5.md) | 5 (5.1-5.6) | Agent Integration |
| [16-SLICES-PHASE-6.md](./16-SLICES-PHASE-6.md) | 6 (6.1-6.4) | Web UI |
| [17-SLICES-PHASE-7.md](./17-SLICES-PHASE-7.md) | 7 (7.1-7.3) | Git Integration |
| [18-SLICES-PHASE-8.md](./18-SLICES-PHASE-8.md) | 8 (8.1-8.3) | CLI & Polish |
| [19-SLICES-PHASE-9.md](./19-SLICES-PHASE-9.md) | 9 (9.1-9.6) | Advanced Workflows |
| [21-SLICES-PHASE-10.md](./21-SLICES-PHASE-10.md) | 10 (10.1-10.5) | Advanced Config |

---

## Slice Template

Each slice follows this structure:

```markdown
## Slice X.Y: [Name]

### Goal
What this slice achieves and why it matters.

### Prerequisites
- Which slices must be complete
- What functionality to build on

### Deliverables
- Specific files/modules to create
- Functions/classes to implement

### Architecture Constraints
- Design decisions that MUST be followed
- Why these constraints exist (to prevent local optimization)

### Implementation Steps
1. Step-by-step instructions
2. With clear boundaries

### Verification

#### Unit Tests
- What to test
- Expected behaviors
- Edge cases

#### Integration Tests  
- Component interactions to verify
- Real dependencies to use

#### E2E Tests
- User-facing scenario to execute
- How to run it
- Expected outcome

### Definition of Done
- [ ] Checklist of completion criteria
- [ ] Including all tests passing
```

---

## Critical Architecture Decisions

These decisions apply across ALL slices. Implementing LLMs must follow them.

### 1. No Global State

**Why:** Global state makes testing impossible and creates hidden dependencies.

```python
# ❌ WRONG
_db = None
def get_db():
    global _db
    if _db is None:
        _db = create_db()
    return _db

# ✅ CORRECT
class RunRepository:
    def __init__(self, db: Database):
        self._db = db
```

### 2. Dependency Injection Everywhere

**Why:** Enables testing with mocks/fakes, makes dependencies explicit.

```python
# ❌ WRONG
class WorkflowEngine:
    def __init__(self):
        self.db = Database()  # Hidden dependency
        
# ✅ CORRECT
class WorkflowEngine:
    def __init__(self, run_repo: RunRepository, history: HistoryLogger):
        self._run_repo = run_repo
        self._history = history
```

### 3. Time as Dependency

**Why:** Tests shouldn't wait. Time-based logic must be testable.

```python
# ❌ WRONG
def check_timeout(started_at: datetime) -> bool:
    return datetime.now() - started_at > timedelta(minutes=5)

# ✅ CORRECT
def check_timeout(started_at: datetime, now: datetime, timeout: timedelta) -> bool:
    return now - started_at > timeout
    
# In production, inject datetime.now()
# In tests, inject a fixed time
```

### 4. Pure Functions for Logic

**Why:** Pure functions are trivially testable.

```python
# ❌ WRONG - mixes logic with I/O
def evaluate_checklist(run_id: str) -> GateResult:
    checklist = db.get_checklist(run_id)  # I/O
    # ... logic ...
    return result

# ✅ CORRECT - pure function
def evaluate_checklist(checklist: list[ChecklistItem], requirements: list[Requirement]) -> GateResult:
    # Pure logic, no I/O
    return result

# Caller handles I/O
checklist = db.get_checklist(run_id)
result = evaluate_checklist(checklist, requirements)
```

### 5. Explicit Error Types

**Why:** Exceptions should be part of the API, not surprises.

```python
# ❌ WRONG
def load_routine(id: str) -> Routine:
    if not exists:
        raise Exception("Not found")  # Generic
        
# ✅ CORRECT
class RoutineNotFoundError(Exception):
    def __init__(self, routine_id: str):
        self.routine_id = routine_id

def load_routine(id: str) -> Routine:
    if not exists:
        raise RoutineNotFoundError(id)
```

### 6. Pydantic for All Data

**Why:** Validation, serialization, and type safety in one.

```python
# ❌ WRONG
def create_run(data: dict) -> dict:
    return {"id": str(uuid4()), **data}

# ✅ CORRECT
class CreateRunRequest(BaseModel):
    routine_id: str
    config: dict[str, Any]

class Run(BaseModel):
    id: str
    routine_id: str
    status: RunStatus
```

### 7. Async by Default

**Why:** I/O operations should not block.

```python
# ❌ WRONG
def get_run(id: str) -> Run:
    return db.query(...)  # Blocks

# ✅ CORRECT
async def get_run(id: str) -> Run:
    return await db.query(...)
```

---

## Testing Infrastructure

### Directory Structure

```
tests/
├── conftest.py           # Shared fixtures
├── unit/
│   ├── test_checklist.py
│   ├── test_grades.py
│   └── ...
├── integration/
│   ├── test_workflow_engine.py
│   ├── test_api_runs.py
│   └── ...
└── e2e/
    ├── test_full_run.py
    └── ...
```

### Shared Fixtures (conftest.py)

```python
import pytest
from pathlib import Path
import tempfile

@pytest.fixture
def tmp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)

@pytest.fixture
def fixed_time():
    """Fixed datetime for deterministic tests."""
    return datetime(2025, 1, 15, 10, 30, 0)

@pytest.fixture
def in_memory_db():
    """In-memory SQLite database."""
    # Setup
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    # Teardown automatic
```

### Running Tests

```bash
# All tests
uv run pytest

# Unit only (fast)
uv run pytest tests/unit -v

# Integration only
uv run pytest tests/integration -v

# E2E only (requires running server)
uv run pytest tests/e2e -v

# With coverage
uv run pytest --cov=orchestrator --cov-report=html
```

---

## Getting Started

1. Read this overview completely
2. Read Phase 1 document (11-SLICES-PHASE-1.md)
3. Implement slice 1.1 (Project Skeleton)
4. Verify slice 1.1 passes all tests
5. Continue to slice 1.2
6. Never skip ahead - each slice builds on previous

**The implementing LLM should:**
- Read the current slice completely before coding
- Follow architecture constraints exactly
- Implement all tests before moving on
- Run the full test suite after each slice
- Not "improve" the architecture without explicit approval
