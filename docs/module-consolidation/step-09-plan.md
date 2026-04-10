# Step Plan: Restructure runners/ Internals

## Purpose

Reorganize `runners/` internal files into `detection/` and `runtime/` sub-packages. The existing `execution/` sub-package (`phase_handler.py`, `attempt_store.py`, `event_broadcaster.py`) is already well-structured and requires no changes.

## Prerequisites

- **Phase 6 complete:** `scaffolding/` and `agents/` (profiles) absorptions into `runners/` must be done first, so all files that will live in `runners/` are in place.

## Functional Contract

### Inputs

- `runners/` files related to agent detection: `detector.py`, `profile_resolution.py`, `config_utils.py`
- `runners/` files related to runtime monitoring: `monitor.py`, `nudger.py`, `quota.py`, `repetition_detector.py`
- `runners/` top-level files that stay: `interface.py`, `types.py`, `errors.py`, `executor.py`, `__init__.py`
- Existing sub-packages that stay: `agents/`, `execution/`, `scaffolding/`, `profiles/`

### Outputs

- `runners/detection/` sub-package: `detector.py`, `profile_resolution.py`, `config_utils.py`
- `runners/runtime/` sub-package: `monitor.py`, `nudger.py`, `quota.py`, `repetition_detector.py`
- `runners/__init__.py` re-exports all public symbols (no external import changes)
- Zero changes to any file outside `runners/`

### Error Cases

- **Detection ↔ runtime circular imports:** Detector may use runtime config or vice versa. Mitigation: verify dependency direction — detection should be independent of runtime.
- **Executor imports from moved files:** `executor.py` likely imports from detector and monitor. These imports must use the new sub-package paths (internal to runners). Mitigation: update executor's internal imports.
- **`NudgerConfig` import path:** After C1 fix (Phase 0), `NudgerConfig` is in `config/models.py`, but `nudger.py` may have internal references to update. Mitigation: verify after move.

## Tasks

1. Audit all `from orchestrator.runners import X` statements to build the public API list.
2. Create `runners/detection/` sub-package. Move `detector.py`, `profile_resolution.py`, `config_utils.py`.
3. Create `runners/runtime/` sub-package. Move `monitor.py`, `nudger.py`, `quota.py`, `repetition_detector.py`.
4. Update `runners/__init__.py` to re-export all public symbols.
5. Update internal imports within runners (especially `executor.py` and sub-package cross-references).
6. Run full test suite. Fix failures.
7. Verify no external import changes needed.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- No detection/runtime files remain at `runners/` root level
- `runners/execution/` unchanged (no files added or removed)
- Pre-commit hooks pass

### Manual Verification

- Confirm `from orchestrator.runners import AgentExecutor` still works (re-export intact)
- Confirm executor can still detect and launch agents
- Verify all sub-packages have proper `__init__.py` files

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 9 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `runners/` internal structure
- Depends on: Phase 6 (all absorptions into runners/ complete)
- Note: `execution/` sub-package already exists with `phase_handler.py`, `attempt_store.py`, `event_broadcaster.py` — no changes needed there
