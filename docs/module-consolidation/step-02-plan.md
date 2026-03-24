# Step Plan: Absorb cache/ + review/ + repos/ → git/

## Purpose

Consolidate three small single-consumer modules (`cache/`, `review/`, `repos/`) into `git/` as sub-packages. This removes 3 top-level modules and groups related git-infrastructure functionality together (diffs, repos, testing, operations).

## Prerequisites

- **Phase 0 complete:** C2 coupling fix already moved `CommitInfo`/`FileStatus`/`ModifiedFile` to `git/diff_models.py`, so review types are already in `git/`.
- **Phase 1 complete:** Dead code removed, no risk of moving shims.

## Functional Contract

### Inputs

- `cache/` module (~100 LOC): LRU cache used by `git/`
- `review/` module (~300 LOC): Review models and test runner used by `api/` and `git/`
- `repos/` module (~250 LOC): Repo discovery used by `api/`
- Existing `git/` root-level files: `branch_ops.py`, `conflict_ops.py`, `prune_ops.py`
- ~14 import paths referencing `orchestrator.cache`, `orchestrator.review`, `orchestrator.repos`

### Outputs

- `git/diff/` sub-package: `models.py` (from Phase 0), `diff_ops.py`, `cached_diff_ops.py`, `lru_cache.py` (from `cache/`)
- `git/repos/` sub-package: `models.py`, `discovery.py`, `errors.py` (from `repos/`)
- `git/testing/` sub-package: `test_runner.py` (from `review/`)
- `git/ops/` sub-package: `branch_ops.py`, `conflict_ops.py`, `prune_ops.py` (moved from `git/` root)
- `cache/`, `review/`, `repos/` directories deleted entirely
- All ~14 import paths updated across `src/`, `tests/`, `scripts/`
- `git/__init__.py` re-exports public symbols from sub-packages

### Error Cases

- **Circular imports between git sub-packages:** `diff/` importing from `ops/` or vice versa. Mitigation: sub-packages are independent; verify import graph after moves.
- **Missed import paths in tests:** Test files often import directly from module internals. Mitigation: `grep -r` for all old paths in `tests/` specifically.
- **`git/__init__.py` becomes too large:** Re-exporting all symbols. Mitigation: only re-export public API symbols, keep sub-package details internal.

## Tasks

1. Create `git/diff/` sub-package: move `diff_ops.py` and `diff_models.py` (from Phase 0) into it. Move `cached_diff_ops.py` if it exists at git root. Create `lru_cache.py` from `cache/` contents.
2. Create `git/repos/` sub-package from `repos/` module files.
3. Create `git/testing/` sub-package from `review/test_runner.py` (and any remaining review files).
4. Create `git/ops/` sub-package: move `branch_ops.py`, `conflict_ops.py`, `prune_ops.py` from `git/` root.
5. Update `git/__init__.py` to re-export public symbols.
6. Update all import paths: `from orchestrator.cache` → `from orchestrator.git.diff`, `from orchestrator.review` → `from orchestrator.git.testing` (or `git.diff` for models), `from orchestrator.repos` → `from orchestrator.git.repos`.
7. Delete `cache/`, `review/`, `repos/` directories.
8. Update test imports.
9. Run full test suite. Fix failures.
10. Verify zero references to old paths.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.cache" src/ tests/` returns zero results
- `grep -r "from orchestrator.review" src/ tests/` returns zero results
- `grep -r "from orchestrator.repos" src/ tests/` returns zero results
- Directories `cache/`, `review/`, `repos/` no longer exist under `src/orchestrator/`
- Pre-commit hooks pass (`uv run pre-commit run --all-files`)

### Manual Verification

- Confirm `git/` sub-packages have proper `__init__.py` files
- Confirm no re-export shims left in old locations
- Verify `git/__init__.py` exports only public API

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 2 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `git/` structure
- Depends on: Phase 0 (C2 type relocation), Phase 1 (dead code cleanup)
