# Step Plan: Absorb artifacts/ → workflow/artifacts/

## Purpose

Move the `artifacts/` module into `workflow/` as a sub-package. The artifact registry tracks build outputs within the workflow lifecycle — it belongs in the orchestration layer, not as a standalone top-level module.

## Prerequisites

- None — this phase is independent and can run in parallel with other absorption phases.

## Functional Contract

### Inputs

- `artifacts/` module (~200 LOC): `models.py`, `registry.py`, `__init__.py`
- ~3 import paths referencing `orchestrator.artifacts` across `src/`, `tests/`

### Outputs

- `workflow/artifacts/` sub-package containing `models.py`, `registry.py`
- `artifacts/` directory deleted entirely
- All ~3 import paths updated: `from orchestrator.artifacts` → `from orchestrator.workflow.artifacts`
- `workflow/__init__.py` updated to re-export artifact public symbols if needed

### Error Cases

- **Circular import:** `artifacts/` may import from `workflow/` while now living inside it. Mitigation: check that artifact files only import from lower layers (config/, state/, db/) — not from workflow internals.
- **Missed import in API routers:** Artifact endpoints in `api/routers/` likely import directly. Mitigation: `grep -r "from orchestrator.artifacts" src/orchestrator/api/`.

## Tasks

1. Create `workflow/artifacts/` sub-package directory with `__init__.py`.
2. Move `artifacts/models.py` and `artifacts/registry.py` to `workflow/artifacts/`.
3. Update internal imports within moved files.
4. Update all external imports: `from orchestrator.artifacts` → `from orchestrator.workflow.artifacts`.
5. Delete `artifacts/` directory.
6. Update test imports.
7. Run full test suite. Fix failures.
8. Verify zero references to old paths.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.artifacts" src/ tests/` returns zero results
- Directory `artifacts/` no longer exists under `src/orchestrator/`
- Pre-commit hooks pass

### Manual Verification

- Confirm artifact registration still works in a workflow run
- Verify no re-export shim at old location

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 4 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `workflow/` structure
- Independent of: All other phases (no cross-dependencies)
