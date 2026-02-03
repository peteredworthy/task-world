# Implementation Slices: Phase 4 - API Server

**Goal:** Implement REST API and WebSocket for real-time updates.

**End state:** Can manage runs via HTTP, receive live updates via WebSocket.

**Prerequisites:** Phase 3 complete.

---

## Slice 4.1: FastAPI Application Setup

### Goal
Set up FastAPI application with dependency injection, error handling, and health check.

### Prerequisites
- Phase 3 complete

### Deliverables

```
src/orchestrator/
├── api/
│   ├── __init__.py
│   ├── app.py         # FastAPI app factory
│   ├── deps.py        # Dependency providers
│   └── errors.py      # Exception handlers
tests/integration/test_api_health.py
```

### Architecture Constraints

1. **App factory pattern** - `create_app()` function, not global `app`
2. **Dependency injection via FastAPI** - Use `Depends()` for repositories, engine
3. **Structured error responses** - Consistent error format
4. **No global state** - Everything through DI

### Implementation Steps

1. Create `src/orchestrator/api/errors.py`:
   ```python
   from fastapi import Request
   from fastapi.responses import JSONResponse
   from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
   from orchestrator.routines.errors import RoutineNotFoundError, RoutineValidationError
   
   async def run_not_found_handler(request: Request, exc: RunNotFoundError):
       return JSONResponse(
           status_code=404,
           content={"error": "run_not_found", "run_id": exc.run_id},
       )
   
   async def task_not_found_handler(request: Request, exc: TaskNotFoundError):
       return JSONResponse(
           status_code=404,
           content={"error": "task_not_found", "run_id": exc.run_id, "task_id": exc.task_id},
       )
   
   async def routine_not_found_handler(request: Request, exc: RoutineNotFoundError):
       return JSONResponse(
           status_code=404,
           content={"error": "routine_not_found", "path": exc.path},
       )
   
   async def routine_validation_handler(request: Request, exc: RoutineValidationError):
       return JSONResponse(
           status_code=422,
           content={"error": "routine_validation_failed", "path": exc.path, "errors": exc.errors},
       )
   ```

2. Create `src/orchestrator/api/deps.py`:
   ```python
   from typing import AsyncGenerator
   from fastapi import Depends
   from sqlalchemy.ext.asyncio import AsyncSession
   
   from orchestrator.db.connection import create_engine, create_session_factory
   from orchestrator.db.repositories import RunRepository
   from orchestrator.workflow.engine import WorkflowEngine
   
   # These will be set during app startup
   _engine = None
   _session_factory = None
   
   def configure_database(db_path: str):
       global _engine, _session_factory
       _engine = create_engine(db_path)
       _session_factory = create_session_factory(_engine)
   
   async def get_session() -> AsyncGenerator[AsyncSession, None]:
       if _session_factory is None:
           raise RuntimeError("Database not configured")
       async with _session_factory() as session:
           yield session
   
   async def get_run_repository(
       session: AsyncSession = Depends(get_session)
   ) -> RunRepository:
       return RunRepository(session)
   
   async def get_workflow_engine(
       repo: RunRepository = Depends(get_run_repository)
   ) -> WorkflowEngine:
       # Wrap repo in StateManager-compatible interface
       return WorkflowEngine(state_manager=RepoStateAdapter(repo))
   ```

3. Create `src/orchestrator/api/app.py`:
   ```python
   from fastapi import FastAPI
   from contextlib import asynccontextmanager
   
   from orchestrator.api.deps import configure_database, _engine
   from orchestrator.api.errors import (
       run_not_found_handler, task_not_found_handler,
       routine_not_found_handler, routine_validation_handler,
   )
   from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
   from orchestrator.routines.errors import RoutineNotFoundError, RoutineValidationError
   from orchestrator.db.connection import init_db
   
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # Startup
       await init_db(_engine)
       yield
       # Shutdown
       if _engine:
           await _engine.dispose()
   
   def create_app(db_path: str = "orchestrator.db") -> FastAPI:
       configure_database(db_path)
       
       app = FastAPI(
           title="Orchestrator API",
           version="0.1.0",
           lifespan=lifespan,
       )
       
       # Exception handlers
       app.add_exception_handler(RunNotFoundError, run_not_found_handler)
       app.add_exception_handler(TaskNotFoundError, task_not_found_handler)
       app.add_exception_handler(RoutineNotFoundError, routine_not_found_handler)
       app.add_exception_handler(RoutineValidationError, routine_validation_handler)
       
       # Health check
       @app.get("/health")
       async def health():
           return {"status": "ok"}
       
       # Include routers (will add in later slices)
       # app.include_router(routines_router, prefix="/api/routines", tags=["routines"])
       # app.include_router(runs_router, prefix="/api/runs", tags=["runs"])
       
       return app
   ```

4. Create integration test:
   ```python
   import pytest
   from httpx import AsyncClient, ASGITransport
   from orchestrator.api.app import create_app
   
   @pytest.fixture
   def app(tmp_path):
       return create_app(db_path=str(tmp_path / "test.db"))
   
   @pytest.fixture
   async def client(app):
       async with AsyncClient(
           transport=ASGITransport(app=app),
           base_url="http://test"
       ) as client:
           yield client
   
   @pytest.mark.asyncio
   async def test_health_check(client):
       response = await client.get("/health")
       assert response.status_code == 200
       assert response.json() == {"status": "ok"}
   ```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_api_health.py -v
```

### Definition of Done
- [ ] FastAPI app factory works
- [ ] Health check endpoint works
- [ ] Exception handlers registered
- [ ] Database initializes on startup

---

## Slice 4.2: Routine Endpoints

### Goal
Implement REST endpoints to list and view routines.

### Prerequisites
- Slice 4.1 complete

### Deliverables

```
src/orchestrator/api/
├── routers/
│   ├── __init__.py
│   └── routines.py    # Routine endpoints
├── schemas/
│   └── routines.py    # Response schemas
tests/integration/test_api_routines.py
```

### Architecture Constraints

1. **Read-only for now** - No routine creation via API (they come from files)
2. **Routine discovery** - Scan configured directories for .yaml files
3. **Response schemas** - Pydantic models for API responses (separate from internal models)

### Implementation Steps

1. Create `src/orchestrator/api/schemas/routines.py`:
   ```python
   from pydantic import BaseModel
   from orchestrator.config.enums import RoutineSource
   
   class RoutineSummary(BaseModel):
       id: str
       name: str
       description: str | None
       source: RoutineSource
       step_count: int
       input_count: int
   
   class RoutineDetail(BaseModel):
       id: str
       name: str
       description: str | None
       source: RoutineSource
       inputs: list[dict]
       steps: list[dict]
   
   class RoutineListResponse(BaseModel):
       routines: list[RoutineSummary]
   ```

2. Create `src/orchestrator/routines/discovery.py`:
   ```python
   from dataclasses import dataclass
   from pathlib import Path
   from orchestrator.routines.loader import load_routine_from_path
   from orchestrator.config.models import RoutineConfig
   from orchestrator.config.enums import RoutineSource

   @dataclass
   class DiscoveredRoutine:
       config: RoutineConfig
       source: RoutineSource
       path: Path

   def discover_routines(
       directories: list[tuple[Path, RoutineSource]],
   ) -> list[DiscoveredRoutine]:
       """Discover routines from configured directories.

       Args:
           directories: List of (directory_path, source_type) tuples.

       Returns:
           List of DiscoveredRoutine for each valid routine found.
           Invalid files are silently skipped.
       """
       routines = []
       for directory, source in directories:
           if not directory.is_dir():
               continue
           for yaml_path in sorted(directory.glob("*.yaml")):
               try:
                   config = load_routine_from_path(yaml_path)
                   routines.append(DiscoveredRoutine(config=config, source=source, path=yaml_path))
               except Exception:
                   continue
       return routines
   ```

3. Create `src/orchestrator/api/routers/routines.py`:
   ```python
   from fastapi import APIRouter, Depends, HTTPException
   from pathlib import Path
   
   from orchestrator.api.schemas.routines import (
       RoutineSummary, RoutineDetail, RoutineListResponse
   )
   from orchestrator.routines.discovery import discover_routines
   from orchestrator.routines.loader import load_routine_from_path
   from orchestrator.config.enums import RoutineSource
   
   router = APIRouter()
   
   # Configuration - will be injected properly later
   LOCAL_ROUTINES_DIR = Path.home() / ".orchestrator" / "routines"
   
   @router.get("", response_model=RoutineListResponse)
   async def list_routines(project_dir: str | None = None):
       """List available routines."""
       project_path = Path(project_dir) / "routines" if project_dir else None
       
       discovered = discover_routines(
           local_dir=LOCAL_ROUTINES_DIR,
           project_dir=project_path,
       )
       
       summaries = [
           RoutineSummary(
               id=r.config.id,
               name=r.config.name,
               description=r.config.description,
               source=r.source,
               step_count=len(r.config.steps),
               input_count=len(r.config.inputs),
           )
           for r in discovered
       ]
       
       return RoutineListResponse(routines=summaries)
   
   @router.get("/{routine_id}", response_model=RoutineDetail)
   async def get_routine(routine_id: str, project_dir: str | None = None):
       """Get routine details."""
       project_path = Path(project_dir) / "routines" if project_dir else None
       
       discovered = discover_routines(
           local_dir=LOCAL_ROUTINES_DIR,
           project_dir=project_path,
       )
       
       for r in discovered:
           if r.config.id == routine_id:
               return RoutineDetail(
                   id=r.config.id,
                   name=r.config.name,
                   description=r.config.description,
                   source=r.source,
                   inputs=[i.model_dump() for i in r.config.inputs],
                   steps=[s.model_dump() for s in r.config.steps],
               )
       
       raise HTTPException(status_code=404, detail=f"Routine '{routine_id}' not found")
   ```

4. Update `app.py` to include router

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_api_routines.py -v
```

### Definition of Done
- [ ] GET /api/routines returns list
- [ ] GET /api/routines/{id} returns detail
- [ ] 404 for unknown routine
- [ ] Discovery finds routines in directories

---

## Slice 4.3: Run Endpoints

### Goal
Implement CRUD endpoints for runs.

### Prerequisites
- Slices 4.1, 4.2 complete

### Deliverables

```
src/orchestrator/api/
├── routers/
│   └── runs.py        # Run CRUD endpoints
├── schemas/
│   └── runs.py        # Run schemas
tests/integration/test_api_runs.py
```

### Architecture Constraints

1. **Create run from routine** - POST specifies routine_id and config
2. **State machine transitions via dedicated endpoints** - Not PATCH
3. **Include nested state** - Steps and tasks in response

### Implementation Steps

1. Create `src/orchestrator/api/schemas/runs.py`:
   ```python
   from pydantic import BaseModel
   from datetime import datetime
   from orchestrator.config.enums import RunStatus, TaskStatus, AgentType
   
   class CreateRunRequest(BaseModel):
       routine_id: str
       project_id: str
       config: dict = {}
       agent_type: AgentType | None = None
   
   class TaskSummary(BaseModel):
       id: str
       config_id: str
       status: TaskStatus
       current_attempt: int
       max_attempts: int
   
   class StepSummary(BaseModel):
       id: str
       config_id: str
       completed: bool
       tasks: list[TaskSummary]
   
   class RunResponse(BaseModel):
       id: str
       project_id: str
       status: RunStatus
       routine_id: str | None
       agent_type: AgentType | None
       config: dict
       steps: list[StepSummary]
       created_at: datetime
       updated_at: datetime
       started_at: datetime | None
       completed_at: datetime | None
   
   class RunListResponse(BaseModel):
       runs: list[RunResponse]
   ```

2. Create `src/orchestrator/api/routers/runs.py`:
   ```python
   from fastapi import APIRouter, Depends, HTTPException
   from orchestrator.api.schemas.runs import (
       CreateRunRequest, RunResponse, RunListResponse, StepSummary, TaskSummary
   )
   from orchestrator.api.deps import get_run_repository, get_workflow_engine
   from orchestrator.db.repositories import RunRepository
   from orchestrator.workflow.engine import WorkflowEngine
   from orchestrator.routines.discovery import discover_routines
   from orchestrator.state.factory import create_run_from_routine
   from orchestrator.config.enums import RunStatus
   from pathlib import Path
   
   router = APIRouter()
   
   def run_to_response(run) -> RunResponse:
       return RunResponse(
           id=run.id,
           project_id=run.project_id,
           status=run.status,
           routine_id=run.routine_id,
           agent_type=run.agent_type,
           config=run.config,
           steps=[
               StepSummary(
                   id=s.id,
                   config_id=s.config_id,
                   completed=s.completed,
                   tasks=[
                       TaskSummary(
                           id=t.id,
                           config_id=t.config_id,
                           status=t.status,
                           current_attempt=t.current_attempt,
                           max_attempts=t.max_attempts,
                       )
                       for t in s.tasks
                   ],
               )
               for s in run.steps
           ],
           created_at=run.created_at,
           updated_at=run.updated_at,
           started_at=run.started_at,
           completed_at=run.completed_at,
       )
   
   @router.post("", response_model=RunResponse, status_code=201)
   async def create_run(
       request: CreateRunRequest,
       repo: RunRepository = Depends(get_run_repository),
   ):
       """Create a new run from a routine."""
       # Find routine
       discovered = discover_routines(local_dir=Path.home() / ".orchestrator" / "routines")
       routine = None
       for r in discovered:
           if r.config.id == request.routine_id:
               routine = r.config
               break
       
       if routine is None:
           raise HTTPException(status_code=404, detail=f"Routine '{request.routine_id}' not found")
       
       # Create run
       run = create_run_from_routine(
           routine=routine,
           project_id=request.project_id,
           config=request.config,
       )
       run.agent_type = request.agent_type
       
       await repo.save(run)
       return run_to_response(run)
   
   @router.get("", response_model=RunListResponse)
   async def list_runs(
       project_id: str | None = None,
       status: RunStatus | None = None,
       repo: RunRepository = Depends(get_run_repository),
   ):
       """List runs with optional filters."""
       if project_id:
           runs = await repo.list_by_project(project_id)
       else:
           runs = await repo.list_all()
       
       if status:
           runs = [r for r in runs if r.status == status]
       
       return RunListResponse(runs=[run_to_response(r) for r in runs])
   
   @router.get("/{run_id}", response_model=RunResponse)
   async def get_run(
       run_id: str,
       repo: RunRepository = Depends(get_run_repository),
   ):
       """Get run details."""
       run = await repo.get(run_id)
       return run_to_response(run)
   
   @router.post("/{run_id}/start", response_model=RunResponse)
   async def start_run(
       run_id: str,
       engine: WorkflowEngine = Depends(get_workflow_engine),
       repo: RunRepository = Depends(get_run_repository),
   ):
       """Start a run (DRAFT → ACTIVE)."""
       run = engine.start_run(run_id)
       return run_to_response(run)
   
   @router.delete("/{run_id}", status_code=204)
   async def delete_run(
       run_id: str,
       repo: RunRepository = Depends(get_run_repository),
   ):
       """Delete a run."""
       await repo.delete(run_id)
   ```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_api_runs.py -v
```

**Test scenarios:**
- Create run from routine
- List runs (with filters)
- Get run detail
- Start run
- Delete run
- 404 for unknown run

### Definition of Done
- [ ] POST /api/runs creates run
- [ ] GET /api/runs lists runs
- [ ] GET /api/runs/{id} returns detail
- [ ] POST /api/runs/{id}/start transitions state
- [ ] DELETE /api/runs/{id} removes run

---

## Slice 4.4: Task Endpoints

### Goal
Implement endpoints for task operations (start, submit, update checklist).

### Prerequisites
- Slice 4.3 complete

### Deliverables

```
src/orchestrator/api/
├── routers/
│   └── tasks.py       # Task endpoints
├── schemas/
│   └── tasks.py       # Task schemas
tests/integration/test_api_tasks.py
```

### Implementation Steps

1. Create task schemas with checklist detail
2. Create endpoints:
   - GET /api/runs/{run_id}/tasks/{task_id}
   - POST /api/runs/{run_id}/tasks/{task_id}/start
   - POST /api/runs/{run_id}/tasks/{task_id}/submit
   - POST /api/runs/{run_id}/tasks/{task_id}/complete-verification
   - PATCH /api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}
   - PUT /api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade

The verifier grades individual requirements, not the task as a whole. Each
requirement (checklist item) receives its own grade. On `complete-verification`,
`evaluate_grades` checks each item's grade against its priority threshold:
CRITICAL must be A, EXPECTED must be B, NICE is informational only.

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_api_tasks.py -v
```

### Definition of Done
- [ ] Task operations work via API
- [ ] Checklist updates work
- [ ] Grade submission works
- [ ] Gate errors returned properly

---

## Slice 4.5: WebSocket for Real-time Updates

### Goal
Implement WebSocket endpoint for live state updates.

### Prerequisites
- Slice 4.4 complete

### Deliverables

```
src/orchestrator/api/
├── websocket.py       # WebSocket handling
tests/integration/test_api_websocket.py
```

### Architecture Constraints

1. **Events broadcast via WebSocket** - UI subscribes to run updates
2. **Per-run subscriptions** - Client subscribes to specific run(s)
3. **Throttle updates** - Max 10 updates/second per client
4. **Graceful disconnect** - Handle client disconnects cleanly

### Implementation Steps

1. Create `src/orchestrator/api/websocket.py`:
   ```python
   from fastapi import WebSocket, WebSocketDisconnect
   from typing import Dict, Set
   import asyncio
   import json
   from datetime import datetime
   from orchestrator.workflow.events import WorkflowEvent
   
   class ConnectionManager:
       def __init__(self):
           self._connections: Dict[str, Set[WebSocket]] = {}  # run_id -> connections
           self._throttle_interval = 0.1  # 100ms
       
       async def connect(self, websocket: WebSocket, run_id: str):
           await websocket.accept()
           if run_id not in self._connections:
               self._connections[run_id] = set()
           self._connections[run_id].add(websocket)
       
       def disconnect(self, websocket: WebSocket, run_id: str):
           if run_id in self._connections:
               self._connections[run_id].discard(websocket)
               if not self._connections[run_id]:
                   del self._connections[run_id]
       
       async def broadcast_event(self, event: WorkflowEvent):
           """Broadcast event to subscribed clients."""
           run_id = event.run_id
           if run_id not in self._connections:
               return
           
           message = json.dumps({
               "type": event.event_type,
               "timestamp": event.timestamp.isoformat(),
               "data": self._serialize_event(event),
           })
           
           disconnected = []
           for websocket in self._connections[run_id]:
               try:
                   await websocket.send_text(message)
               except Exception:
                   disconnected.append(websocket)
           
           for ws in disconnected:
               self.disconnect(ws, run_id)
       
       def _serialize_event(self, event: WorkflowEvent) -> dict:
           from dataclasses import asdict
           return asdict(event)
   
   manager = ConnectionManager()
   
   async def websocket_endpoint(websocket: WebSocket, run_id: str):
       await manager.connect(websocket, run_id)
       try:
           while True:
               # Keep connection alive, handle client messages if needed
               data = await websocket.receive_text()
               # Could handle subscription changes here
       except WebSocketDisconnect:
           manager.disconnect(websocket, run_id)
   ```

2. Wire manager to event emitter
3. Add WebSocket route to app

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_api_websocket.py -v
```

**Test scenario:**
1. Connect WebSocket for run
2. Trigger state change
3. Verify event received on WebSocket
4. Disconnect, verify cleanup

### Definition of Done
- [ ] WebSocket connections work
- [ ] Events broadcast to subscribers
- [ ] Disconnects handled cleanly
- [ ] Throttling prevents flood

---

## Phase 4 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Start server
uv run uvicorn orchestrator.api.app:create_app --factory --reload &

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/api/routines
curl -X POST http://localhost:8000/api/runs -H "Content-Type: application/json" -d '{"routine_id": "simple-routine", "project_id": "test"}'

# Kill server
kill %1
```

If API works, Phase 4 is complete. Proceed to Phase 5.
