# Step Plan: Absorb routines/ → config/routines/

## Purpose

Move the `routines/` module into `config/` as a sub-package. Routine discovery and loading are configuration concerns — they parse YAML files that define run templates. Grouping them under `config/` reflects their actual role in the architecture.

## Prerequisites

- **Phase 0 complete:** No coupling dependencies, but clean layering established.

## Functional Contract

### Inputs

- `routines/` module (~400 LOC): `discovery.py`, `loader.py`, `versioning.py`, `__init__.py`
- ~14 import paths referencing `orchestrator.routines` across `src/`, `tests/`

### Outputs

- `config/routines/` sub-package containing `discovery.py`, `loader.py`, `versioning.py`
- `routines/` directory deleted entirely
- All ~14 import paths updated: `from orchestrator.routines` → `from orchestrator.config.routines`
- `config/__init__.py` updated to re-export routine public symbols if needed

### Error Cases

- **Circular import between config/ and routines:** Routines may import config models while config now contains routines. Mitigation: routines only imports from `config.models` and `config.enums` (same-package imports), which is safe.
- **Routine YAML loading path changes:** If `discovery.py` uses `__file__`-relative paths, the filesystem location change could break discovery. Mitigation: verify discovery uses configured paths, not `__file__`-relative.
- **Missed test imports:** Tests for routines may have direct imports. Mitigation: `grep -r "from orchestrator.routines" tests/`.

## Tasks

1. Create `config/routines/` sub-package directory with `__init__.py`.
2. Move `routines/discovery.py`, `routines/loader.py`, `routines/versioning.py` to `config/routines/`.
3. Update internal imports within moved files (e.g., relative imports between routines files).
4. Update all external imports: `from orchestrator.routines` → `from orchestrator.config.routines`.
5. Update `config/__init__.py` if routine symbols need top-level re-export.
6. Delete `routines/` directory.
7. Update test imports.
8. Run full test suite. Fix failures.
9. Verify zero references to old paths.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.routines" src/ tests/` returns zero results
- Directory `routines/` no longer exists under `src/orchestrator/`
- Pre-commit hooks pass

### Manual Verification

- Confirm routine discovery still works (load a routine YAML via API)
- Confirm no re-export shim in old `routines/` location
- Verify `config/routines/__init__.py` exports expected symbols

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 3 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `config/` structure
- Depends on: Phase 0 (clean layering)
- Independent of: Phases 2, 4, 5 (no cross-dependencies)
