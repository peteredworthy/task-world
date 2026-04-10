# Step Plan: Registry Isolation

## Purpose

Restrict `register_active_run()`, `unregister_active_run()`, and `has_active_workflow()`
to the consumer module only. Remove these functions from the public API surface of the
signals package and workflow package. This locks in the invariant that only the consumer
manages the active-run registry.

## Prerequisites

- **S-03 complete**: All lifecycle operations route through signal queue. Consumer is
  the sole caller of registry functions in practice (verified by grep).

## Functional Contract

### Inputs

- Registry functions (`register_active_run`, `unregister_active_run`, `has_active_workflow`)
  currently exported from `src/orchestrator/workflow/signals/signals.py` and re-exported
  via `__init__.py` files.
- After S-03, these functions are only called from `consumer.py` and tests.
- Various files may still import them (now unused after S-03 rewiring).

### Outputs

- **`signals.py`**: Registry functions remain defined here but are NOT listed in
  `__all__` or any public export.
- **`src/orchestrator/workflow/signals/__init__.py`**: `register_active_run`,
  `unregister_active_run`, `has_active_workflow` removed from `__all__` and exports.
- **`src/orchestrator/workflow/__init__.py`**: Same removals from `__all__`.
- **`consumer.py`**: Imports registry functions directly from `signals.py`
  (private import within the package).
- **All other files**: Any remaining imports of these functions removed.
- **Tests**: Consumer-focused tests import from `consumer.py` or directly from
  `signals.py` within the signals package.

### Error Cases

- Executor tests break because they import registry functions — update tests to
  use consumer-aware test helpers or remove the imports.
- A missed import outside consumer causes runtime failure — mitigated by grep
  audit and pre-commit guard (S-05).

## Tasks

1. Grep all Python files for `register_active_run`, `unregister_active_run`,
   `has_active_workflow` imports and calls.
2. Remove these from `__all__` in `signals/__init__.py` and `workflow/__init__.py`.
3. Update `consumer.py` to import directly from `signals.py` (relative import).
4. Remove now-unused imports from all other files (service.py, executor.py,
   run_workflow.py, etc.).
5. Update affected tests to not import registry functions from public surface.
6. Verify: grep confirms no imports outside consumer module and its tests.

## Verification Approach

### Auto-Verify

- `grep -rn "from.*signals import.*register_active_run" src/` only matches
  `consumer.py`.
- `grep -rn "from.*signals import.*unregister_active_run" src/` only matches
  `consumer.py`.
- `grep -rn "from.*signals import.*has_active_workflow" src/` only matches
  `consumer.py`.
- `grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/__init__.py`
  returns no hits (removed from exports).
- All existing tests pass.

### Manual Verification

- Attempt to `from orchestrator.workflow.signals import register_active_run` from
  an external module — should fail or not be available via `__all__`.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 4 (§4.1)
- Architecture: `docs/single-queue-2/architecture.md` — Module Boundaries
- Key files: `src/orchestrator/workflow/signals/signals.py`,
  `src/orchestrator/workflow/signals/__init__.py`,
  `src/orchestrator/workflow/__init__.py`,
  `src/orchestrator/workflow/signals/consumer.py`
