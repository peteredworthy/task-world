# Step Plan: Delete Dead Code

## Purpose

Remove all dead shim files, unused agent implementations, and deprecated parser shims. Reduces noise for subsequent phases and prevents dead code from accidentally being moved into new module locations.

## Prerequisites

- **Phase 0 complete:** Coupling fixes ensure nothing accidentally depends on shim files through indirect imports.

## Functional Contract

### Inputs

- `routers/` shim directory (dead backward-compat re-exports)
- `agent_detector.py` (unused standalone detector)
- `parsers/` shim files (deprecated parser re-exports)
- `openhands.py`, `openhands_docker.py`, `openhands_common.py` (old agent shims)
- `codex_server.py`, `codex_server_common.py` (old agent shims)

### Outputs

- All listed files and directories deleted entirely
- Zero references to deleted files in any import statement across `src/`, `tests/`, `scripts/`, `alembic/`
- No re-export shims, no `# moved to ...` comments, no `TODO: remove` markers

### Error Cases

- **Unexpected consumer of a "dead" shim:** A test or script still imports from a deleted file. Mitigation: run `grep -r` for each file's import path before deleting; fix consumers first.
- **Conftest fixture references deleted module:** Test fixtures may reference old imports. Mitigation: check all `conftest.py` files.
- **Alembic migration references deleted module:** Migration files may import from deleted paths. Mitigation: `grep -r "from orchestrator" alembic/` before and after.

## Tasks

1. Run `grep -r` for each target file/directory to identify any remaining consumers.
2. Fix any discovered consumers (update imports or remove dead test code).
3. Delete `routers/` shim directory.
4. Delete `agent_detector.py`.
5. Delete `parsers/` shim files.
6. Delete `openhands.py`, `openhands_docker.py`, `openhands_common.py`.
7. Delete `codex_server.py`, `codex_server_common.py`.
8. Run full test suite. Fix any failures.
9. Verify zero references: `grep -r "from orchestrator.{deleted}" src/ tests/ scripts/ alembic/` for each deleted module.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.routers" src/ tests/` returns zero results (excluding `api/routers/`)
- `grep -r "agent_detector" src/ tests/` returns zero results
- `grep -r "from orchestrator.parsers" src/ tests/` returns zero results
- `grep -r "openhands_common\|openhands_docker\|codex_server_common\|codex_server\b" src/ tests/` returns zero results (excluding legitimate agent implementations under `runners/agents/`)
- No files exist at the deleted paths: `ls` confirms absence
- `grep -r "shim\|stub\|backward.compat" src/orchestrator/` returns zero matches beyond legitimate uses

### Manual Verification

- Confirm `git status` shows only deletions (no new untracked files in old locations)
- Spot-check that no empty `__init__.py` files remain where directories were deleted

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 1 specification
- Architecture: `docs/module-consolidation/architecture.md` — Current module table identifies dead shims
- Intent: `docs/module-consolidation/intent.md` — Zero tolerance for stubs/shims
