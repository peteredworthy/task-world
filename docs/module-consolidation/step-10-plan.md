# Step Plan: Explicit __all__ + Interface Narrowing

## Purpose

Add explicit `__all__` declarations to all 9 module `__init__.py` files, narrowing public interfaces to hide internal implementation details. Also fixes the remaining cross-layer violation (`runners/executor.py` → `api/websocket.ConnectionManager`) by introducing a `BroadcastCallback` protocol.

## Prerequisites

- **Phases 7–9 complete:** Internal restructuring of workflow/, db/, and runners/ must be done first, so `__init__.py` re-exports reflect the final sub-package structure.

## Functional Contract

### Inputs

- 9 module `__init__.py` files without `__all__` declarations (or with incomplete ones)
- `runners/executor.py` importing `ConnectionManager` from `api/websocket.py` (cross-layer violation)
- `RunWorkflow` publicly accessible from `workflow/`
- `check_step_progression`, `check_run_completion` publicly accessible from `workflow/`
- Various internal symbols exported that should be hidden (see architecture doc Interface Narrowing table)

### Outputs

- All 9 modules (`config/`, `state/`, `db/`, `git/`, `envfiles/`, `workflow/`, `runners/`, `api/`, `cli/`) have `__all__` in their `__init__.py`
- `BroadcastCallback` protocol defined in `runners/types.py`; `executor.py` and `event_broadcaster.py` use the protocol instead of importing `ConnectionManager`
- `RunWorkflow` prefixed as `_RunWorkflow` (private) or removed from `workflow/__all__`
- `check_step_progression` and `check_run_completion` hidden behind `WorkflowService` methods
- ORM models (`RunModel`, `StepModel`, etc.) not in `db/__all__` — external callers use repository methods
- `generate_id` moved to `state/_utils.py` (internal utility)
- `NoTaskReason`/`resolve_no_task_action` accessible from `workflow/` (moved in Phase 7)
- Internal utilities (`project_init.py`, `utils.py`, `security.py`, `versioning.py`, etc.) excluded from `__all__`

### Error Cases

- **External callers depend on narrowed symbols:** Code outside a module imports a symbol that's been removed from `__all__`. This only affects `from module import *` usage, not explicit imports. Mitigation: `__all__` doesn't prevent explicit imports; it narrows the _recommended_ public API. Add `WorkflowService` wrapper methods for any hidden functions that have external callers.
- **`RunWorkflow` consumers resist privatization:** If `executor.py` or other code can't be refactored. Mitigation: keep `RunWorkflow` in `__all__` with a TODO if needed.
- **`BroadcastCallback` protocol incomplete:** Doesn't cover all WebSocket methods runners actually call. Mitigation: audit all `ConnectionManager` method calls in runners before defining the protocol.
- **ORM model access patterns not covered by repositories:** External code directly queries ORM models. Mitigation: add repository methods for any missing access patterns before removing from `__all__`.

## Tasks

1. Audit all `from orchestrator.X import *` usage (should be rare/none).
2. Audit all `ConnectionManager` usage in `runners/` — define `BroadcastCallback` protocol in `runners/types.py` covering required methods.
3. Refactor `executor.py` and `event_broadcaster.py` to use `BroadcastCallback` instead of `ConnectionManager`. Wire the adapter in `api/deps.py`.
4. Move `generate_id` to `state/_utils.py`. Update internal importers.
5. Add `WorkflowService` wrapper methods for `check_step_progression` and `check_run_completion` if needed by external callers.
6. Make `RunWorkflow` private (`_RunWorkflow`) or exclude from `__all__`.
7. Define `__all__` for each of the 9 modules:
   - `config/__init__.py`: enums, models, global_config public symbols; exclude `routines/versioning`
   - `state/__init__.py`: domain models, factory; exclude `_utils`
   - `db/__init__.py`: session factories, repository classes; exclude ORM models
   - `git/__init__.py`: worktree ops, public diff/repos APIs; exclude `project_init`, `utils`
   - `envfiles/__init__.py`: lifecycle, store, resolution; exclude `security`
   - `workflow/__init__.py`: WorkflowService, engine, events; exclude `_RunWorkflow`, internal transitions
   - `runners/__init__.py`: executor, interface, types; exclude `AGENT_CONFIG_FIELDS`, internal detection
   - `api/__init__.py`: app factory; exclude internal routers/schemas
   - `cli/__init__.py`: CLI entry points
8. Run full test suite. Fix any failures from narrowing.
9. Verify no file outside `orchestrator.X` imports from `orchestrator.X.Y` (sub-package) — only top-level imports.
10. Run `grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/` to confirm zero results.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- All 9 `__init__.py` files contain `__all__` declarations: `grep -l "__all__" src/orchestrator/*/__init__.py` returns 9 files
- `grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/` returns zero results
- `grep -r "from orchestrator.db.models import" src/ tests/` returns zero results outside `db/` (ORM models hidden)
- Pre-commit hooks pass

### Manual Verification

- Confirm `from orchestrator.workflow import WorkflowService` works
- Confirm `from orchestrator.workflow import RunWorkflow` raises ImportError or isn't in `__all__`
- Verify `BroadcastCallback` protocol is used throughout runners
- Spot-check that `help(orchestrator.workflow)` shows only public API

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 10 specification
- Architecture: `docs/module-consolidation/architecture.md` — Interface Narrowing table, BroadcastCallback decision
- Depends on: Phases 7–9 (internal restructuring complete)
- This is the final phase — completes M3 milestone
- Future follow-up: import linting rule to enforce `__all__` boundaries automatically
