# Step Plan: Restructure workflow/ Internals

## Purpose

Reorganize `workflow/` internal files into well-defined sub-packages (`engine/`, `events/`, `signals/`, `agent/`). This improves navigability of the largest module (~2,500 LOC). No external import changes — all access continues via `workflow/__init__.py`.

## Prerequisites

- **Phase 4 complete:** `workflow/artifacts/` sub-package already exists from the artifacts absorption.
- **Phase 6 complete:** `runners/` absorptions complete, so workflow's consumers are stable.

## Functional Contract

### Inputs

- `workflow/` flat files: `engine.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py` (engine-related)
- `workflow/` flat files: event types and logger files
- `workflow/` flat files: `signals.py`, `handlers.py`, `runtime.py` (signal-related)
- `workflow/` flat files: `prompts.py`, `templates.py`, `context_builder.py`, `clarifications.py`, `auto_verify.py`, `summary_cache.py` (agent-related)
- `workflow/` top-level files that stay: `service.py`, `locks.py`, `completion.py`, `dry_run.py`

### Outputs

- `workflow/engine/` sub-package: `engine.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py`
- `workflow/events/` sub-package: `types.py`, `logger.py`
- `workflow/signals/` sub-package: `signals.py`, `handlers.py`, `runtime.py`
- `workflow/agent/` sub-package: `prompts.py`, `templates.py`, `context_builder.py`, `clarifications.py`, `auto_verify.py`, `summary_cache.py`
- `workflow/__init__.py` re-exports all public symbols (no external import changes)
- Zero changes to any file outside `workflow/`

### Error Cases

- **Internal circular imports between sub-packages:** `engine/` may import from `signals/` and vice versa. Mitigation: map internal dependency graph before moving; use lazy imports if needed.
- **`workflow/__init__.py` missing re-exports:** External callers that import `from orchestrator.workflow import X` break if X isn't re-exported. Mitigation: exhaustive audit of all `from orchestrator.workflow import` statements before restructuring.
- **NoTaskReason move:** `NoTaskReason` and `resolve_no_task_action` need to move from `runners/` to `workflow/signals/runtime.py`. This is a cross-module change. Mitigation: handle this as a sub-task with its own grep verification.

## Tasks

1. Audit all `from orchestrator.workflow import X` statements across the codebase to build the complete public API list.
2. Create `workflow/engine/` sub-package. Move engine-related files.
3. Create `workflow/events/` sub-package. Move event-related files.
4. Create `workflow/signals/` sub-package. Move signal-related files.
5. Create `workflow/agent/` sub-package. Move agent-prompt-related files.
6. Move `NoTaskReason` and `resolve_no_task_action` from `runners/` to `workflow/signals/runtime.py`. Update all importers.
7. Move `DEFAULT_SUMMARIZE_MODEL` from `config/models.py` to `workflow/agent/summary_cache.py` (single consumer).
8. Update `workflow/__init__.py` to re-export all public symbols from sub-packages.
9. Update internal imports within workflow sub-packages (relative imports).
10. Run full test suite. Fix failures.
11. Verify no external import changes needed: `grep -r "from orchestrator.workflow" src/ tests/` should all still resolve.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- No files remain at `workflow/` root that should be in sub-packages (only `service.py`, `locks.py`, `completion.py`, `dry_run.py`, `__init__.py`)
- `grep -r "from orchestrator.runners.*NoTaskReason" src/` returns zero results (moved to workflow)
- Pre-commit hooks pass

### Manual Verification

- Confirm `from orchestrator.workflow import WorkflowEngine` still works (re-export intact)
- Confirm `from orchestrator.workflow import WorkflowService` still works
- Verify all sub-packages have proper `__init__.py` files

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 7 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `workflow/` internal structure
- Depends on: Phases 4 and 6 (absorptions into workflow/ and runners/ complete)
