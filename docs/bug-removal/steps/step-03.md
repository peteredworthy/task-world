# Step 3: Implement Failed-Run Recovery API (FAILED-RUN-RECOVERY — Backend)

This step adds `POST /api/runs/{id}/recover`, the first-class recovery mechanism that lets a user
roll a FAILED run back to a chosen task and resume execution from that point. FAILED is currently a
terminal state with no outbound transitions; the only recovery path is direct SQL manipulation. This
step introduces the endpoint, service method, schemas, and integration tests needed to restore run
state and the git worktree, transitioning the run to PAUSED so it can be resumed normally.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "FAILED-RUN-RECOVERY: Implement `POST /api/runs/{id}/recover` endpoint with git worktree rollback and run status reset"
**Functionality to Produce**:
- `RecoverRequest` / `RecoverResponse` schemas in `api/schemas/runs.py`
- `WorkflowService.recover_run()` implementing the 8-step recovery logic
- `POST /api/runs/{id}/recover` route in `api/routers/runs.py`
- 409 returned for non-FAILED runs (including COMPLETED which is deferred)
- `preserve_checklist` flag supported (default: reset to open)

**Final Verification Criteria**:
- `pytest tests/integration/ -k "recover"` passes
- `POST /api/runs/{id}/recover` appears in the OpenAPI schema
- 409 is returned when run is not in FAILED status

---

## Task 1: Add RecoverRequest and RecoverResponse schemas
**Description**:
Add the Pydantic request and response schemas for the recovery endpoint to `api/schemas/runs.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/schemas/runs.py`
- [ ] Add `RecoverRequest` schema:
```python
class RecoverRequest(BaseModel):
    target_task_id: str
    additional_attempts: int = 1
    agent_type: str | None = None
    agent_config: dict | None = None
    preserve_checklist: bool = False
```
- [ ] Add `RecoverResponse` schema (a run summary including new status):
```python
class RecoverResponse(BaseModel):
    run_id: str
    status: str
    pause_reason: str | None
    current_step_index: int | None
    # include other relevant RunSummary fields as needed
```
- [ ] Run `uv run pyright src/orchestrator/api/schemas/runs.py` to confirm no type errors

**References**
- `docs/bug-removal/step-03-plan.md` — Task 1 description
- `docs/bug-removal/architecture.md` — "Modified Components: api/schemas/runs.py"
- `docs/bugs/FAILED-RUN-RECOVERY.md` — RecoverRequest fields

**Constraints**
- [ ] Only `api/schemas/runs.py` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `RecoverRequest` is importable from `orchestrator.api.schemas.runs` with all documented fields
- [ ] `RecoverResponse` is importable with run status and pause_reason fields

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `python -c "from orchestrator.api.schemas.runs import RecoverRequest, RecoverResponse; print('OK')"` exits 0
- [ ] `uv run pyright src/orchestrator/api/schemas/runs.py` exits 0
- [ ] `uv run ruff check src/orchestrator/api/schemas/runs.py` exits 0

---

## Task 2: Implement WorkflowService.recover_run()
**Description**:
Add `recover_run()` async method to `WorkflowService` implementing the 8-step recovery logic:
validate FAILED status, reset target task, reset downstream tasks, restore worktree, transition run.

**Implementation Plan (Do These Steps)**
The recovery logic must execute in order; each step depends on the previous. Use the existing
`GitPython`-based `git/` module (consistent with existing worktree operations).

- [ ] Open `src/orchestrator/workflow/service.py`
- [ ] Add the `recover_run` async method:
```python
async def recover_run(
    self,
    run_id: str,
    target_task_id: str,
    additional_attempts: int = 1,
    agent_type: str | None = None,
    agent_config: dict | None = None,
    preserve_checklist: bool = False,
) -> RecoverResponse:
    # Step 1: Load run; assert FAILED status
    run = await self.repo.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    if run.status != RunStatus.FAILED:
        raise ConflictError(f"Run must be FAILED to recover; current status: {run.status}")

    # Step 2: Validate target_task_id belongs to this run
    target_task = await self.repo.get_task(target_task_id)
    if target_task is None or target_task.run_id != run_id:
        raise NotFoundError(f"Task {target_task_id} not found for run {run_id}")

    # Step 3: Identify target task and all downstream tasks in execution order
    # Step 4: Reset target task: status → BUILDING, bump max_attempts, new attempt record
    # Step 5: Reset downstream tasks: status → PENDING, clear attempt records/grades
    # Step 6: Reset downstream task checklist items to open unless preserve_checklist=True
    # Step 7: Un-complete affected steps (completed → False)
    # Step 8: Restore worktree: git checkout {end_commit}
    # Step 9: Transition run: FAILED → PAUSED, pause_reason="recovered", clear completed_at
    ...
```
- [ ] Use the run's `end_commit` from the target task's last attempt as the git checkout target
- [ ] Fall back to `source_branch` HEAD if no `end_commit` is available
- [ ] Use `git checkout {end_commit}` via the existing `git/` module
- [ ] Return a `RecoverResponse` with the updated run state

**References**
- `docs/bug-removal/step-03-plan.md` — Task 2 description
- `docs/bug-removal/architecture.md` — "Modified Components: service.py" (full 8-step list)
- `docs/bugs/FAILED-RUN-RECOVERY.md` — Recovery Logic
- `docs/bug-removal/clarifications.md` — preserve_checklist defaults to false

**Constraints**
- [ ] `git checkout` must use the DB-recorded `end_commit` (not user-supplied refs) for security
- [ ] COMPLETED run recovery must return 409 (not proceed with recovery)
- [ ] Only `service.py` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `WorkflowService.recover_run()` exists and is async
- [ ] Run transitions from FAILED to PAUSED with `pause_reason="recovered"`
- [ ] Target task status is BUILDING with incremented max_attempts
- [ ] Downstream tasks are PENDING with cleared checklist items (unless `preserve_checklist=True`)
- [ ] Worktree is restored to `end_commit`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pyright src/orchestrator/workflow/service.py` exits 0
- [ ] `uv run ruff check src/orchestrator/workflow/service.py` exits 0

---

## Task 3: Add POST /api/runs/{id}/recover route
**Description**:
Wire the `WorkflowService.recover_run()` method to a new FastAPI route in `api/routers/runs.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/routers/runs.py`
- [ ] Add the recovery route:
```python
@router.post("/{run_id}/recover", response_model=RecoverResponse)
async def recover_run(
    run_id: str,
    body: RecoverRequest,
    service: WorkflowService = Depends(get_workflow_service),
) -> RecoverResponse:
    try:
        return await service.recover_run(
            run_id=run_id,
            target_task_id=body.target_task_id,
            additional_attempts=body.additional_attempts,
            agent_type=body.agent_type,
            agent_config=body.agent_config,
            preserve_checklist=body.preserve_checklist,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
```
- [ ] Import `RecoverRequest`, `RecoverResponse` from the schemas module

**References**
- `docs/bug-removal/step-03-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "Modified Components: api/routers/runs.py"

**Constraints**
- [ ] Only `api/routers/runs.py` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `POST /api/runs/{run_id}/recover` route exists and is registered
- [ ] Route returns 404 when run or task_id not found
- [ ] Route returns 409 when run is not FAILED

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pyright src/orchestrator/api/routers/runs.py` exits 0
- [ ] `uv run ruff check src/orchestrator/api/routers/runs.py` exits 0
- [ ] `python -c "from orchestrator.api.routers.runs import router; routes = [r.path for r in router.routes]; assert any('recover' in r for r in routes)"` exits 0

---

## Task 4: Write integration tests for recovery endpoint
**Description**:
Write integration tests that cover the happy path (FAILED run recovers to PAUSED), the 409
conflict case (non-FAILED run), and the `preserve_checklist` flag behavior.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_api_runs_recover.py`
- [ ] Test 1 — happy path: create a run in FAILED state with known task structure; POST to `/api/runs/{id}/recover` with a valid `target_task_id`; assert run is PAUSED with `pause_reason="recovered"`, target task is BUILDING, downstream tasks are PENDING, checklist items are open
- [ ] Test 2 — preserve_checklist: same setup but POST with `preserve_checklist=true`; assert checklist items are NOT reset (prior statuses preserved)
- [ ] Test 3 — non-FAILED status: create a run in ACTIVE state; POST to recover; assert 409 Conflict
- [ ] Test 4 — invalid task_id: POST with a `target_task_id` that belongs to a different run; assert 404

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_recover_failed_run(client: AsyncClient, failed_run_with_tasks):
    run_id, target_task_id = failed_run_with_tasks
    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": target_task_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PAUSED"
    assert data["pause_reason"] == "recovered"
```

**References**
- `docs/bug-removal/step-03-plan.md` — Task 4 description
- `docs/bug-removal/architecture.md` — Testing Strategy (integration tests)
- `docs/bug-removal/clarifications.md` — preserve_checklist behavior

**Functionality (Expected Outcomes)**
- [ ] Integration test for happy path recovery exists and passes
- [ ] Integration test for 409 conflict case exists and passes
- [ ] Integration test for `preserve_checklist=true` exists and passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/integration/ -k "recover" -v` exits 0 with all tests shown as PASSED
- [ ] Test file exists at `tests/integration/test_api_runs_recover.py`
