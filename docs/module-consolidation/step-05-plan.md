# Step Plan: Absorb metrics/ + mcp/ → api/

## Purpose

Move the `metrics/` and `mcp/` modules into `api/` — `metrics/` becomes `api/metrics.py` and `mcp/` becomes `api/mcp/` sub-package. Both are API-layer concerns: metrics computes cost data for API responses, and MCP exposes an alternative API interface.

## Prerequisites

- **Step 2 (`cache/review/repos → git`) must be complete before this step.** `mcp/tools.py` imports from `orchestrator.repos` (e.g., `from orchestrator.repos import ...`). Step 2 moves that module to `orchestrator.git.repos`. If Step 5 runs before Step 2, the newly created `api/mcp/tools.py` will contain stale `orchestrator.repos` imports that Step 2 won't update (since Step 2 only scans the old `mcp/` path, not the new `api/mcp/` path).

## Functional Contract

### Inputs

- `metrics/` module (~150 LOC): cost calculation utilities, single consumer (`api/`)
- `mcp/` module (~400 LOC): `server.py`, `tools.py`, `clarification_tools.py`, `__init__.py`
- ~1–2 import paths each referencing `orchestrator.metrics` and `orchestrator.mcp`

### Outputs

- `api/metrics.py` — absorbed from `metrics/` (flattened to single file)
- `api/mcp/` sub-package containing `server.py`, `tools.py`, `clarification_tools.py`
- `metrics/` and `mcp/` directories deleted entirely
- All import paths updated: `from orchestrator.metrics` → `from orchestrator.api.metrics`, `from orchestrator.mcp` → `from orchestrator.api.mcp`

### Error Cases

- **MCP server registration path changes:** If `mcp/server.py` is mounted in `app.py` via module path, the import path must be updated. Mitigation: check `app.py` MCP mounting code.
- **Metrics imported by non-API code:** If workflow or runners import metrics, moving to api/ would create an upward dependency. Mitigation: verify metrics is only consumed by api/ before moving.

## Tasks

1. Create `api/mcp/` sub-package directory with `__init__.py`.
2. Move `mcp/server.py`, `mcp/tools.py`, `mcp/clarification_tools.py` to `api/mcp/`.
3. Move `metrics/` content to `api/metrics.py` (flatten if single file, or create sub-package if multiple files).
4. Update internal imports within moved files.
5. Update all external imports in `src/`, `tests/`, `scripts/`.
6. Update `app.py` MCP mounting if it references old module path.
7. Delete `metrics/` and `mcp/` directories.
8. Update test imports.
9. Run full test suite. Fix failures.
10. Verify zero references to old paths.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.metrics" src/ tests/` returns zero results (excluding `api/metrics`)
- `grep -r "from orchestrator.mcp" src/ tests/` returns zero results (excluding `api/mcp`)
- Directories `metrics/` and `mcp/` no longer exist under `src/orchestrator/`
- Pre-commit hooks pass

### Manual Verification

- Confirm MCP server still starts and serves tools
- Confirm cost estimation still appears in API responses
- Verify no re-export shims at old locations

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 5 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `api/` structure
- Depends on: Step 2 (`cache/review/repos → git`) — `mcp/tools.py` imports from `orchestrator.repos` which Step 2 moves to `orchestrator.git.repos`; Step 7 will also need to update `api/mcp/tools.py` if it imports from `workflow.clarifications` after Step 7 restructures workflow internals
