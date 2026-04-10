# Step Plan: Absorb scaffolding/ + agents/ → runners/

## Purpose

Move `scaffolding/` (workspace setup) and `agents/` (agent persona CRUD) into `runners/` as sub-packages. Both are execution-layer concerns: scaffolding prepares workspaces for agent runs, and agent profiles configure how runners behave.

## Prerequisites

- **Phase 0 complete:** C6 coupling fix decoupled `UserManagedAgent` from `WorkflowService` via protocol, so `agents/` can safely move into `runners/` without introducing circular dependencies.

## Functional Contract

### Inputs

- `scaffolding/` module (~200 LOC): `copier.py`, `models.py` — workspace setup utilities
- `agents/` module (~350 LOC): `models.py`, `schemas.py`, `service.py`, `resolution.py`, `errors.py` — agent persona/profile CRUD
- ~3–5 import paths each referencing `orchestrator.scaffolding` and `orchestrator.agents`

### Outputs

- `runners/scaffolding/` sub-package containing `copier.py`, `models.py`
- `runners/profiles/` sub-package containing `models.py`, `schemas.py`, `service.py`, `resolution.py`, `errors.py` (renamed from `agents/` to avoid confusion with `runners/agents/` which holds agent implementations)
- `scaffolding/` and `agents/` directories deleted entirely
- All import paths updated: `from orchestrator.scaffolding` → `from orchestrator.runners.scaffolding`, `from orchestrator.agents` → `from orchestrator.runners.profiles`

### Error Cases

- **Name collision with `runners/agents/`:** The existing `runners/agents/` directory holds agent implementations (claude_cli, openhands, etc.). The absorbed `agents/` module (persona CRUD) goes to `runners/profiles/` to avoid collision. Mitigation: clear naming convention — `profiles/` for persona config, `agents/` for implementations.
- **API router imports:** `api/routers/agents.py` likely imports from `orchestrator.agents`. Must update to `orchestrator.runners.profiles`. Mitigation: grep and update all router imports.
- **Circular imports:** If `agents/` (profiles) imports from `runners/`, moving it inside runners could create issues. Mitigation: profiles only imports from lower layers (config/, state/).

## Tasks

1. Create `runners/scaffolding/` sub-package directory with `__init__.py`.
2. Move `scaffolding/copier.py` and `scaffolding/models.py` to `runners/scaffolding/`.
3. Create `runners/profiles/` sub-package directory with `__init__.py`.
4. Move `agents/models.py`, `agents/schemas.py`, `agents/service.py`, `agents/resolution.py`, `agents/errors.py` to `runners/profiles/`.
5. Update internal imports within moved files.
   - **LAYERING FIX (FM13):** `agents/schemas.py` imports `ApiModel` from `orchestrator.api.schemas.base`. This violates the layering constraint (runners must not import from api/). When copying this file to `runners/profiles/schemas.py`, replace:
     ```python
     from orchestrator.api.schemas.base import ApiModel
     ```
     with:
     ```python
     from pydantic import BaseModel as ApiModel
     ```
     This keeps the same interface (`ApiModel` alias) while removing the upward api/ dependency.
6. Update all external imports: `from orchestrator.scaffolding` → `from orchestrator.runners.scaffolding`, `from orchestrator.agents` → `from orchestrator.runners.profiles`.
   - **Known consumer (FM14):** `src/orchestrator/db/migrations/env.py` imports `orchestrator.agents.models` for Alembic table discovery. This line must be updated to `orchestrator.runners.profiles.models`. Verify with:
     ```
     grep -n "agents" src/orchestrator/db/migrations/env.py
     ```
7. Delete `scaffolding/` and `agents/` directories.
8. Update test imports.
9. Run full test suite. Fix failures.
10. Verify zero references to old paths.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.scaffolding" src/ tests/` returns zero results
- `grep -r "from orchestrator.agents" src/ tests/` returns zero results (excluding `runners/agents/` which holds agent implementations)
- Directories `scaffolding/` and `agents/` no longer exist under `src/orchestrator/`
- Pre-commit hooks pass

### Manual Verification

- Confirm agent profile CRUD still works via API
- Confirm workspace scaffolding still works when starting a run
- Verify `runners/profiles/` and `runners/agents/` are clearly distinct in purpose

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 6 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `runners/` structure
- Depends on: Phase 0 (C6 protocol decoupling)
- After this phase: codebase has 9 top-level modules (M2 milestone complete)
