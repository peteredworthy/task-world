# Implementation Slices: Phase 3 - Persistence

**Goal:** Implement database persistence with event sourcing for recovery.

**End state:** State persists to SQLite, can recover from crashes via event replay.

**Prerequisites:** Phase 2 complete.

---

## Slice 3.1: Database Setup with Alembic

### Goal
Set up SQLAlchemy with SQLite and Alembic migrations. Create base tables.

### Prerequisites
- Phase 1 complete

### Deliverables

```
src/orchestrator/
├── db/
│   ├── __init__.py
│   ├── base.py        # SQLAlchemy base
│   ├── models.py      # ORM models
│   └── connection.py  # Connection management
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
alembic.ini
tests/integration/test_database.py
```

### Architecture Constraints

1. **SQLite for simplicity** - Single file, no server. Async via aiosqlite.
2. **Alembic for migrations** - Even though we defer complex migrations, set up the infrastructure now.
3. **ORM models separate from Pydantic** - SQLAlchemy models for DB, Pydantic for API/logic.
4. **Connection is injected** - No global connection. Pass engine/session.
5. **String columns for enums** - SQLite has no native enum type. Store enum values as plain String columns and convert via `RunStatus(model.status)` / `run.status.value` in the repository layer.

### Implementation Steps

1. Create `src/orchestrator/db/base.py`:
   ```python
   from sqlalchemy.ext.asyncio import AsyncAttrs
   from sqlalchemy.orm import DeclarativeBase
   
   class Base(AsyncAttrs, DeclarativeBase):
       pass
   ```

2. Create `src/orchestrator/db/models.py`:
   ```python
   from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON
   from sqlalchemy.orm import relationship
   from datetime import datetime
   from orchestrator.db.base import Base

   class RunModel(Base):
       __tablename__ = "runs"

       id = Column(String(36), primary_key=True)
       project_id = Column(String(255), nullable=False, index=True)
       status = Column(String, nullable=False, index=True)  # SQLite: no native enum
       routine_id = Column(String(255))
       routine_sha = Column(String(40))
       routine_source = Column(String(50))
       agent_type = Column(String(50))
       agent_config = Column(JSON, default=dict)
       config = Column(JSON, default=dict)
       worktree_path = Column(String(500))
       created_at = Column(DateTime, default=datetime.utcnow)
       updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
       started_at = Column(DateTime)
       completed_at = Column(DateTime)
       
       steps = relationship("StepModel", back_populates="run", cascade="all, delete-orphan")
   
   class StepModel(Base):
       __tablename__ = "steps"
       
       id = Column(String(36), primary_key=True)
       run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
       config_id = Column(String(255), nullable=False)
       order_index = Column(Integer, nullable=False)
       completed = Column(Integer, default=0)  # SQLite boolean
       
       run = relationship("RunModel", back_populates="steps")
       tasks = relationship("TaskModel", back_populates="step", cascade="all, delete-orphan")
   
   class TaskModel(Base):
       __tablename__ = "tasks"
       
       id = Column(String(36), primary_key=True)
       step_id = Column(String(36), ForeignKey("steps.id"), nullable=False)
       config_id = Column(String(255), nullable=False)
       status = Column(String, nullable=False, default="pending")  # SQLite: no native enum
       current_attempt = Column(Integer, default=0)
       max_attempts = Column(Integer, default=3)
       checklist = Column(JSON, default=list)  # Store as JSON for simplicity
       
       step = relationship("StepModel", back_populates="tasks")
       attempts = relationship("AttemptModel", back_populates="task", cascade="all, delete-orphan")
   
   class AttemptModel(Base):
       __tablename__ = "attempts"
       
       id = Column(String(36), primary_key=True)
       task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
       attempt_num = Column(Integer, nullable=False)
       started_at = Column(DateTime)
       completed_at = Column(DateTime)
       outcome = Column(String(50))
       tokens_read = Column(Integer, default=0)
       tokens_write = Column(Integer, default=0)
       tokens_cache = Column(Integer, default=0)
       duration_ms = Column(Integer, default=0)

       task = relationship("TaskModel", back_populates="attempts")
   
   class EventModel(Base):
       """Event sourcing table for recovery."""
       __tablename__ = "events"
       
       id = Column(Integer, primary_key=True, autoincrement=True)
       run_id = Column(String(36), nullable=False, index=True)
       event_type = Column(String(100), nullable=False)
       timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
       payload = Column(JSON, nullable=False)
   ```

3. Create `src/orchestrator/db/connection.py`:
   ```python
   from pathlib import Path
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
   from sqlalchemy.pool import StaticPool
   from orchestrator.db.base import Base

   def create_engine(db_path: Path | str = ":memory:") -> AsyncEngine:
       """Create async SQLite engine."""
       db_path_str = str(db_path)
       if db_path_str == ":memory:":
           return create_async_engine(
               "sqlite+aiosqlite://",
               echo=False,
               connect_args={"check_same_thread": False},
               poolclass=StaticPool,
           )
       return create_async_engine(f"sqlite+aiosqlite:///{db_path_str}", echo=False)
   
   def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
       """Create session factory for dependency injection."""
       return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
   
   async def init_db(engine):
       """Initialize database tables."""
       async with engine.begin() as conn:
           await conn.run_sync(Base.metadata.create_all)
   ```

4. Set up Alembic with `alembic init alembic` and configure for async

5. Create integration tests:
   ```python
   import pytest
   from orchestrator.db.connection import create_engine, create_session_factory, init_db
   from orchestrator.db.models import RunModel
   from orchestrator.config.enums import RunStatus
   
   @pytest.fixture
   async def db_session():
       engine = create_engine(":memory:")
       await init_db(engine)
       factory = create_session_factory(engine)
       async with factory() as session:
           yield session
   
   @pytest.mark.asyncio
   async def test_create_run(db_session):
       run = RunModel(
           id="test-run-1",
           project_id="test-project",
           status=RunStatus.DRAFT,
       )
       db_session.add(run)
       await db_session.commit()
       
       result = await db_session.get(RunModel, "test-run-1")
       assert result is not None
       assert result.project_id == "test-project"
   ```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_database.py -v
```

### Definition of Done
- [ ] SQLAlchemy models created
- [ ] Connection factory works
- [ ] In-memory tests pass
- [ ] Events table exists for event sourcing

---

## Slice 3.2: Repository Pattern

### Goal
Implement repository classes that abstract database operations.

### Prerequisites
- Slice 3.1 complete

### Deliverables

```
src/orchestrator/
├── db/
│   └── repositories.py  # RunRepository, etc.
tests/integration/test_repositories.py
```

### Architecture Constraints

1. **Repository per aggregate** - RunRepository handles runs and their children
2. **Async all the way** - All methods are async
3. **Convert ORM ↔ Pydantic** - Repository returns Pydantic models, takes Pydantic models
4. **No business logic** - Repositories do CRUD only

### Implementation Steps

1. Create `src/orchestrator/db/repositories.py`:
   ```python
   from sqlalchemy.ext.asyncio import AsyncSession
   from sqlalchemy import select
   from sqlalchemy.orm import selectinload
   
   from orchestrator.db.models import RunModel, StepModel, TaskModel, AttemptModel
   from orchestrator.state.models import Run, StepState, TaskState, Attempt, ChecklistItem
   from orchestrator.state.errors import RunNotFoundError
   
   class RunRepository:
       def __init__(self, session: AsyncSession):
           self._session = session
       
       async def get(self, run_id: str) -> Run:
           """Get run by ID with all relations."""
           stmt = (
               select(RunModel)
               .options(
                   selectinload(RunModel.steps)
                   .selectinload(StepModel.tasks)
                   .selectinload(TaskModel.attempts)
               )
               .where(RunModel.id == run_id)
           )
           result = await self._session.execute(stmt)
           model = result.scalar_one_or_none()
           if model is None:
               raise RunNotFoundError(run_id)
           return self._to_domain(model)
       
       async def list_by_project(self, project_id: str) -> list[Run]:
           """List runs for a project."""
           stmt = (
               select(RunModel)
               .options(selectinload(RunModel.steps).selectinload(StepModel.tasks))
               .where(RunModel.project_id == project_id)
               .order_by(RunModel.created_at.desc())
           )
           result = await self._session.execute(stmt)
           return [self._to_domain(m) for m in result.scalars()]
       
       async def save(self, run: Run) -> None:
           """Save or update a run."""
           model = self._to_model(run)
           await self._session.merge(model)
           await self._session.commit()
       
       async def delete(self, run_id: str) -> None:
           """Delete a run."""
           model = await self._session.get(RunModel, run_id)
           if model:
               await self._session.delete(model)
               await self._session.commit()
       
       def _to_domain(self, model: RunModel) -> Run:
           """Convert ORM model to domain model."""
           steps = []
           for step_model in sorted(model.steps, key=lambda s: s.order_index):
               tasks = []
               for task_model in step_model.tasks:
                   attempts = [
                       Attempt(
                           id=a.id,
                           attempt_num=a.attempt_num,
                           started_at=a.started_at,
                           completed_at=a.completed_at,
                           outcome=a.outcome,
                       )
                       for a in sorted(task_model.attempts, key=lambda a: a.attempt_num)
                   ]
                   checklist = [ChecklistItem.model_validate(c) for c in task_model.checklist]
                   tasks.append(TaskState(
                       id=task_model.id,
                       config_id=task_model.config_id,
                       status=task_model.status,
                       checklist=checklist,
                       attempts=attempts,
                       current_attempt=task_model.current_attempt,
                       max_attempts=task_model.max_attempts,
                   ))
               steps.append(StepState(
                   id=step_model.id,
                   config_id=step_model.config_id,
                   tasks=tasks,
                   completed=bool(step_model.completed),
               ))
           
           return Run(
               id=model.id,
               project_id=model.project_id,
               status=model.status,
               routine_id=model.routine_id,
               routine_sha=model.routine_sha,
               config=model.config or {},
               steps=steps,
               created_at=model.created_at,
               updated_at=model.updated_at,
               started_at=model.started_at,
               completed_at=model.completed_at,
           )
       
       def _to_model(self, run: Run) -> RunModel:
           """Convert domain model to ORM model."""
           steps = []
           for i, step in enumerate(run.steps):
               tasks = []
               for task in step.tasks:
                   attempts = [
                       AttemptModel(
                           id=a.id,
                           task_id=task.id,
                           attempt_num=a.attempt_num,
                           started_at=a.started_at,
                           completed_at=a.completed_at,
                           outcome=a.outcome,
                       )
                       for a in task.attempts
                   ]
                   tasks.append(TaskModel(
                       id=task.id,
                       step_id=step.id,
                       config_id=task.config_id,
                       status=task.status,
                       checklist=[c.model_dump() for c in task.checklist],
                       current_attempt=task.current_attempt,
                       max_attempts=task.max_attempts,
                       attempts=attempts,
                   ))
               steps.append(StepModel(
                   id=step.id,
                   run_id=run.id,
                   config_id=step.config_id,
                   order_index=i,
                   completed=int(step.completed),
                   tasks=tasks,
               ))
           
           return RunModel(
               id=run.id,
               project_id=run.project_id,
               status=run.status,
               routine_id=run.routine_id,
               routine_sha=run.routine_sha,
               config=run.config,
               steps=steps,
               created_at=run.created_at,
               updated_at=run.updated_at,
               started_at=run.started_at,
               completed_at=run.completed_at,
           )
   ```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_repositories.py -v
```

### Definition of Done
- [ ] RunRepository implemented
- [ ] CRUD operations work
- [ ] ORM ↔ Pydantic conversion works
- [ ] Relations loaded correctly

---

## Slice 3.3: Event Logging for Recovery

### Goal
Log all state-changing events for crash recovery via replay.

### Prerequisites
- Slices 3.1, 3.2 complete

### Deliverables

```
src/orchestrator/
├── db/
│   └── event_store.py  # Event persistence
├── workflow/
│   └── event_logger.py # EventEmitter that persists
tests/integration/test_event_recovery.py
```

### Architecture Constraints

1. **Events are append-only** - Never update or delete events
2. **Events have order** - Sequence number or timestamp for replay order
3. **Events are JSON-serializable** - Payload stored as JSON
4. **Replay rebuilds state** - Can reconstruct Run from events

### Implementation Steps

1. Create `src/orchestrator/db/event_store.py`:
   ```python
   from sqlalchemy.ext.asyncio import AsyncSession
   from sqlalchemy import select
   from orchestrator.db.models import EventModel
   from orchestrator.workflow.events import WorkflowEvent
   import json
   from datetime import datetime
   
   class EventStore:
       def __init__(self, session: AsyncSession):
           self._session = session
       
       async def append(self, event: WorkflowEvent) -> None:
           """Append event to store."""
           model = EventModel(
               run_id=event.run_id,
               event_type=event.event_type,
               timestamp=event.timestamp,
               payload=self._serialize_event(event),
           )
           self._session.add(model)
           await self._session.commit()
       
       async def get_events_for_run(self, run_id: str) -> list[dict]:
           """Get all events for a run in order."""
           stmt = (
               select(EventModel)
               .where(EventModel.run_id == run_id)
               .order_by(EventModel.id)  # Sequential ID = order
           )
           result = await self._session.execute(stmt)
           return [
               {"type": e.event_type, "timestamp": e.timestamp, "payload": e.payload}
               for e in result.scalars()
           ]
       
       def _serialize_event(self, event: WorkflowEvent) -> dict:
           """Serialize event to JSON-compatible dict."""
           # Convert dataclass to dict, handling nested objects
           from dataclasses import asdict
           data = asdict(event)
           # Convert enums and datetimes
           return json.loads(json.dumps(data, default=str))
   ```

2. Create `src/orchestrator/workflow/event_logger.py`:
   ```python
   from orchestrator.db.event_store import EventStore
   from orchestrator.workflow.events import WorkflowEvent
   
   class PersistentEventEmitter:
       """EventEmitter that persists events to database."""
       
       def __init__(self, event_store: EventStore):
           self._store = event_store
           self._listeners: list[callable] = []
       
       def add_listener(self, listener: callable) -> None:
           self._listeners.append(listener)
       
       async def emit(self, event: WorkflowEvent) -> None:
           """Emit event: persist then notify listeners."""
           await self._store.append(event)
           for listener in self._listeners:
               listener(event)
   ```

3. Create integration test for recovery:
   ```python
   @pytest.mark.asyncio
   async def test_recovery_from_events():
       # Setup: Create run, perform actions, events are logged
       # Simulate crash: Clear in-memory state
       # Recovery: Replay events, verify state matches
       pass
   ```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_event_recovery.py -v
```

### Definition of Done
- [ ] EventStore appends events
- [ ] Events retrieved in order
- [ ] PersistentEventEmitter works
- [ ] Recovery test passes

---

## Slice 3.4: Integrated Persistence

### Goal
Wire everything together: WorkflowEngine uses repositories and event logging.

### Prerequisites
- Slices 3.1-3.3 complete

### Deliverables

```
src/orchestrator/
├── workflow/
│   └── engine.py      # Updated to use repositories
tests/integration/test_full_persistence.py
```

### Architecture Constraints

1. **StateManager replaced by Repository** - Or wrap repository in StateManager interface
2. **All state changes persist** - No in-memory-only changes in production mode
3. **Events logged on all transitions** - For recovery

### Implementation Steps

1. Update `WorkflowEngine` to accept repository instead of SessionStateManager
2. Ensure all state mutations go through repository.save()
3. Ensure all events go through PersistentEventEmitter

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_full_persistence.py -v
```

**Test scenario:**
1. Create engine with real database
2. Run task through full lifecycle
3. Query database directly, verify state
4. Restart engine, verify state loads correctly

### Definition of Done
- [ ] WorkflowEngine uses repository
- [ ] State persists to database
- [ ] Events logged
- [ ] State survives restart

---

## Phase 3 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Manual verification: Persistence survives restart
uv run python -c "
import asyncio
from pathlib import Path
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.repositories import RunRepository
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine

async def main():
    db_path = Path('/tmp/orchestrator-test.db')
    db_path.unlink(missing_ok=True)
    
    # First session: Create run
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    
    async with factory() as session:
        repo = RunRepository(session)
        routine = load_routine_from_path(Path('tests/fixtures/routines/valid_simple.yaml'))
        run = create_run_from_routine(routine, 'test-project')
        await repo.save(run)
        print(f'Created run: {run.id}')
    
    await engine.dispose()
    
    # Second session: Load run (simulating restart)
    engine2 = create_engine(db_path)
    factory2 = create_session_factory(engine2)
    
    async with factory2() as session:
        repo2 = RunRepository(session)
        loaded = await repo2.get(run.id)
        print(f'Loaded run: {loaded.id}, status: {loaded.status}')
        print(f'Steps: {len(loaded.steps)}')
        assert loaded.id == run.id
        print('SUCCESS: Persistence works!')
    
    await engine2.dispose()

asyncio.run(main())
"
```

If this works, Phase 3 is complete. Proceed to Phase 4.
