# Module Consolidation Phase 3: Internal Cleanup

**Focus:** Reduce fan-out within surviving modules by extracting service layers from API routers.

**Builds on:** Module consolidation runs 1 and 2, which restructured `src/orchestrator/` from 19 modules to 9 with explicit public interfaces and zero backward-compatibility shims.

---

## Architectural Context

The original design intent for runs and workflows is:

- **Workflow layer** = pure state machine — data in, data out. Owns state transitions, validates gates, emits events. Should have no side effects.
- **Run layer** = world interaction — spawns agents, manages worktrees, talks to git, drives the execution loop.

This boundary is mostly respected in the engine itself (`WorkflowEngine` is largely pure), but the **API routers are where the boundary breaks down in practice**. Both `runs.py` and `review.py` directly orchestrate multi-module operations — they aren't thin HTTP handlers, they are the service layer.

M11 and M12 extract that implicit service layer into explicit service objects, reducing the routers to request/response mapping and restoring the layering intent.

---

## M11: Extract `ReviewService` from API Router

### Current State

`api/routers/review.py` is **1,084 LOC** with direct imports from:

- 5 `git/` sub-modules (`git.ops`, `git.diff`, `git.testing`, `git.errors`, `git` top-level for LRUCache)
- `workflow.events` (6 event types: `AgentFixStarted`, `BackMergeReverted`, `ConflictResolved`, `PruneApplied`, `TestRunCompleted`, `TestRunStarted`)
- `workflow.service` (`WorkflowService`)
- `runners.executor` (`AgentRunnerExecutor`)

The router directly orchestrates: diff generation, prune preview/apply, conflict resolution, test dispatch, back-merge reversion, and agent-triggered conflict fixes. Each of these is a multi-step operation coordinating git state, workflow events, and sometimes agent execution.

### Target State

Extract a `ReviewService` into `git/review_service.py`:

```
src/orchestrator/git/
  review_service.py        ← new file, ~400 LOC
```

`ReviewService` owns:
- **Diff orchestration** — diff fetching with LRU cache, file listing, commit history
- **Prune coordination** — preview, selection, apply (delegating to `git.ops`)
- **Conflict resolution** — resolve blocks, revert back-merge
- **Test dispatch** — trigger test runs, collect and persist results
- **Event emission** — emits the 6 review-related workflow events via injected emitter

`api/routers/review.py` becomes thin HTTP:
- Validates request shapes
- Calls `ReviewService` methods
- Maps results to response schemas
- ~200 LOC, 1–2 direct imports (`ReviewService`, schemas)

### What Moves

| Operation | From | To |
|-----------|------|----|
| `CachedDiffOps` construction and diff fetching | router | `ReviewService.__init__` / `ReviewService.get_diff()` |
| Prune preview / apply logic | router | `ReviewService.preview_prune()` / `ReviewService.apply_prune()` |
| Conflict block resolution | router | `ReviewService.resolve_conflict()` |
| Back-merge reversion + event emit | router | `ReviewService.revert_back_merge()` |
| Test run dispatch + result persistence | router | `ReviewService.run_tests()` |
| Agent conflict-fix spawn | router | `ReviewService.agent_resolve_conflicts()` |
| `_diff_ops` module-level singleton | router | constructor-injected into `ReviewService` |

### Injection Points

`ReviewService` is constructed in `api/deps.py` and injected via `Depends()`, same pattern as `WorkflowService`. Dependencies:
- `WorkflowService` (for event emission on state changes)
- `PersistentEventEmitter` (for review events)
- `TestRunner` (for test dispatch)
- `GlobalConfig` (for repo paths)

### Failure Modes

- **FM1: Module-level `_diff_ops` singleton** — `review.py` creates a `CachedDiffOps` at module load time. Moving this to constructor injection changes initialization order; ensure cache is shared across requests (singleton or app-lifetime scope via `app.state`).
- **FM2: `WorkflowService` dependency direction** — `ReviewService` in `git/` would import from `workflow/`. This is acceptable (git → workflow is allowed by layering), but confirm `workflow/__all__` exports `PersistentEventEmitter`.
- **FM3: Mixed event + git concerns** — Some review operations emit workflow events AND mutate git state atomically. Ensure `ReviewService` preserves atomicity (emit events after git ops succeed, not before).
- **FM4: `AgentRunnerExecutor` import** — review.py imports `AgentRunnerExecutor` to spawn conflict-fix agents. This is runner-layer code; `ReviewService` in `git/` should not import from `runners/`. Options: inject a callback, or keep agent dispatch in the router and have the router call both `ReviewService` + `executor`.

### Effort Estimate

~400 LOC to extract. Mechanical — the logic moves mostly intact, with injection replacing direct construction.

---

## M12: Extract `RunService` from API Router

### Current State

`api/routers/runs.py` is **1,321 LOC** with direct imports from **15+ modules**:

```python
from orchestrator.api.deps import (...)          # 9 deps
from orchestrator.envfiles.resolution import resolve_env_specs
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.git.testing import TestRunner
from orchestrator.api.schemas.runs import (...)  # 20+ schema types
from orchestrator.config.enums import (...)
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import RoutineConfig
from orchestrator.db import EventStore, RunRepository
from orchestrator.api.metrics import estimate_cost
from orchestrator.config import discover_routines
from orchestrator.config.routines.errors import RoutineNotFoundError
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.errors import RunNotFoundError, StepNotFoundError, TaskNotFoundError
from orchestrator.state.models import HumanApproval, Run
from orchestrator.workflow import InvalidTransitionError
from orchestrator.workflow.service import WorkflowService
```

The router directly orchestrates: run creation from routines or embedded YAML, run lifecycle transitions (start/pause/resume/cancel/recover), activity feed queries, branch status and merge-readiness checks, step approval, agent cancellation, backward transitions, and run-to-response mapping with embedded cost estimation.

This is exactly the "run = world interaction" responsibility that belongs in a service layer — but it currently lives in HTTP handler functions.

### Target State

Extract a `RunService` into `workflow/run_service.py`:

```
src/orchestrator/workflow/
  run_service.py           ← new file, ~600–700 LOC
```

`RunService` owns:
- **Run creation** — routine discovery, validation, `create_run_from_routine()`, env file resolution, worktree setup initiation
- **Lifecycle transitions** — start, pause, resume, cancel, recover (delegating to `WorkflowService`)
- **Activity queries** — fetch and classify activity events for a run
- **Branch operations** — branch status, merge readiness, back-merge
- **Step operations** — human approval, step condition evaluation
- **Agent control** — agent cancellation signal dispatch
- **Backward transitions** — coordinating state rollback
- **Response assembly** — `_run_to_response()`, cost estimation, routine config parsing

`api/routers/runs.py` becomes thin HTTP:
- Validates request shapes
- Calls `RunService` methods
- Returns responses or raises `HTTPException`
- ~300–400 LOC, 2–3 direct imports (`RunService`, schemas, `HTTPException`)

### What Moves

| Responsibility | Current location | Target |
|----------------|-----------------|--------|
| Routine discovery + validation | `POST /runs` handler | `RunService.create_run()` |
| `create_run_from_routine()` + env resolution | `POST /runs` handler | `RunService.create_run()` |
| Worktree setup initiation | `POST /runs` handler | `RunService.create_run()` |
| Start/pause/resume/cancel lifecycle | individual handlers | `RunService.{start,pause,resume,cancel}_run()` |
| Recovery coordination | `POST /runs/{id}/recover` | `RunService.recover_run()` |
| Activity event fetch + classification | `GET /runs/{id}/activity` | `RunService.get_activity()` |
| Branch status + merge readiness | `GET /runs/{id}/branch-status` | `RunService.get_branch_status()` |
| Human approval routing | `POST /steps/{id}/approve` | `RunService.approve_step()` |
| Agent cancellation | `POST /runs/{id}/cancel-agent` | `RunService.cancel_agent()` |
| Backward transitions | `POST /runs/{id}/back` | `RunService.backward_transition()` |
| `_run_to_response()` + cost estimation | module-level helper | `RunService.to_response()` |

### Architectural Alignment

This move directly fulfills the original design intent. Today, `WorkflowService` bleeds into world interaction (it calls `WorktreeManager`, runs auto-verify, does git operations inside what should be a pure state mutation layer). Extracting `RunService` provides the right place for those concerns:

```
Before:
  Router (HTTP) → WorkflowService (state + world)

After:
  Router (HTTP) → RunService (world interaction, orchestration)
                      → WorkflowService (pure state mutations, atomic persistence)
                      → WorktreeManager, git ops, auto-verify (side effects)
```

This also creates a natural seam for moving the world-interaction code *out* of `WorkflowService` in a follow-on cleanup: `WorkflowService.handle_run_completion()` git operations and `LocalAutoVerifyRunner` invocations belong in `RunService`, not the workflow state machine.

### Injection Points

`RunService` is constructed in `api/deps.py`. Dependencies:
- `WorkflowService`
- `AgentRunnerExecutor`
- `RunRepository`
- `EventStore`
- `GlobalConfig`
- `TestRunner` (for merge-readiness checks)
- `session_factory`

### Failure Modes

- **FM5: `_run_to_response()` is a module-level function used in multiple places** — currently called from both endpoint handlers and from `GET /runs` (list). Must migrate all call sites when moving to `RunService.to_response()`.
- **FM6: `RunService` in `workflow/` importing from `runners/`** — `RunService` needs `AgentRunnerExecutor` to spawn runs and cancel agents. `workflow/` importing from `runners/` would create the exact circular coupling that was fixed in consolidation phase 0 (C6). Options:
  - Keep `RunService` in `api/` (not `workflow/`), as `api/` is allowed to import from both layers
  - Define a `RunnerCallback` protocol in `workflow/` and inject the executor through it
  - Place `RunService` in a new `api/services/` sub-package
- **FM7: Large response schema dependencies** — `_run_to_response()` references 20+ schema types from `api/schemas/runs`. `RunService` in `workflow/` cannot import from `api/schemas/`. This reinforces FM6: `RunService` belongs in `api/`, not `workflow/`.
- **FM8: Backward transition logic is stateful** — backward transitions coordinate across multiple tasks/steps and depend on current run state. Must ensure `RunService` loads run state correctly before calling `WorkflowService`.
- **FM9: Async/sync boundary** — `WorkflowService` is async; `RunService` must be async throughout. Ensure injected dependencies' async patterns are preserved.

### Correct Placement Decision

Based on FM6 and FM7: `RunService` should live in **`api/run_service.py`** (or `api/services/run_service.py`), not in `workflow/`. The router description in the original M12 prompt says `workflow/run_service.py`, but importing `api/schemas/` and `runners.executor` from `workflow/` violates layering.

`api/` is the appropriate layer for a service that:
- Shapes domain objects into response schemas
- Coordinates between `workflow/`, `runners/`, and `git/` layers
- References HTTP-adjacent concepts (cost estimation, response assembly)

### Effort Estimate

~700 LOC to extract. Larger than M11 due to the breadth of operations and schema dependency surface. Highest-impact single change for API boundary health.

---

## Sequencing

M11 and M12 are independent — neither depends on the other's output. M11 is lower risk and can serve as a template for the injection pattern before tackling M12.

```
M11 (ReviewService) → validates the extraction pattern, ~400 LOC
M12 (RunService)    → same pattern at larger scale, ~700 LOC
```

Both are pure internal refactors: no behavior changes, no API contract changes, no schema changes, no DB migrations.

### Verification Gates (same as consolidation phases 1–2)

After each extraction:

1. `uv run pytest tests/ -q` — all backend tests pass
2. `cd ui && npx vitest run` — all frontend tests pass
3. `cd ui && npx tsc --noEmit` — TypeScript clean
4. `cd ui && npx eslint . --max-warnings 0` — ESLint clean
5. `cd ui && npm run build` — build passes
6. No imports of `api.routers.review` or `api.routers.runs` for business logic (only HTTP layer imports the router)

---

## Out of Scope

- Moving `WorkflowService` world-interaction code (git ops, auto-verify) into `RunService` — that's a follow-on once `RunService` exists and provides the right home
- Functional changes to any operation
- New endpoints or API contract changes
- Frontend changes
