# Plan: Module Consolidation

## Overview

Consolidate `src/orchestrator/` from 19 modules to 9 in 11 iterative phases (0–10), ordered by dependency and risk. Each phase delivers a working codebase with all tests passing. Early phases fix couplings and delete dead code (zero risk). Middle phases move files between modules (low risk, mechanical). Late phases restructure module internals (medium risk, no external import changes).

Critical constraint: every phase must leave zero stubs, shims, or unconnected code. Every import path must be fully updated before a phase is considered complete.

## Milestones

### M1: Coupling Fixes (Phases 0–1)

**Goal:** Resolve all 6 anomalous cross-layer couplings and delete all dead code, establishing clean layering before any file moves.

**Deliverables:**
- C1: Move `NudgerConfig` to `config/models.py`, update imports in `global_config.py` and `runners/nudger.py`
- C2: Move `CommitInfo`, `FileStatus`, `ModifiedFile` to `git/diff_models.py`, update imports in `review/` and `git/diff_ops.py`
- C3: Move `ActionLog` to `state/models.py`, update imports in `runners/action_log.py` consumers
- C4: Move `EnvFileSpec` to `config/models.py`, update imports in `envfiles/models.py` consumers and `state/models.py`
- All type relocations (C1–C4) are completed in Phase 0 alongside the coupling fixes — no separate type relocation phase needed
- C5: Define `RecoveryResult` dataclass in `workflow/`, translate to `RecoverResponse` in the API router
- C6: Define a protocol/callback interface for `UserManagedAgent`, remove direct `WorkflowService` import
- Delete all dead shim files: `routers/` shim dir, `agent_detector.py`, `parsers/` shims, `openhands.py`, `openhands_docker.py`, `openhands_common.py`, `codex_server.py`, `codex_server_common.py`

**Verification:** All tests pass. `grep -r` confirms no imports from deleted files. No cross-layer imports in the 6 identified locations.

### M2: Module Absorptions (Phases 2–6)

**Goal:** Move all absorbed modules into their target locations, updating every import path. After this milestone, the codebase has 9 top-level modules.

**Deliverables:**
- Phase 2: Absorb `cache/` + `review/` + `repos/` → `git/` sub-packages (diff/, repos/, testing/, ops/)
- Phase 3: Absorb `routines/` → `config/routines/`
- Phase 4: Absorb `artifacts/` → `workflow/artifacts/`
- Phase 5: Absorb `metrics/` + `mcp/` → `api/` (metrics.py + mcp/ sub-package)
- Phase 6: Absorb `scaffolding/` + `agents/` (profiles) → `runners/` (scaffolding/ + profiles/ sub-packages)
- For each phase: delete original directory entirely, update all imports, verify zero references to old paths

**Verification:** All tests pass after each phase. Original directories no longer exist. `grep -r "from orchestrator.{old_module}" src/` returns zero results for each absorbed module.

### M3: Internal Restructuring (Phases 7–10)

**Goal:** Reorganize internals of the three largest modules into well-defined sub-packages and establish explicit `__all__` interfaces on all 9 modules.

**Deliverables:**
- Phase 7: Restructure `workflow/` → engine/, events/, signals/, agent/ sub-packages
- Phase 8: Restructure `db/` → orm/, access/, recovery/ sub-packages
- Phase 9: Restructure `runners/` → detection/, runtime/ sub-packages (note: `execution/` sub-package already exists)
- Phase 10: Add explicit `__all__` to all 9 module `__init__.py` files; narrow public interfaces (hide ORM models, make `RunWorkflow` private, move `check_step_progression`/`check_run_completion` behind `WorkflowService`)
- Fix `runners/executor.py` → `api/websocket.ConnectionManager` violation (define `BroadcastCallback` protocol)
- Move `NoTaskReason`/`resolve_no_task_action` from `runners` to `workflow/`

**Verification:** All tests pass. No file outside `orchestrator.X` imports from `orchestrator.X.Y` (sub-package). All `__init__.py` files have `__all__` defined.

## Implementation Order

### Phase 0: Resolve Couplings C1–C6 (M1 core)
**Prerequisites:** None — import fixes and type relocations only.
**Deliverables:** All 6 coupling violations fixed. Each fix is a targeted import change + type relocation. Type moves for C1 (`NudgerConfig` → `config/models.py`), C2 (`CommitInfo`/`FileStatus`/`ModifiedFile` → `git/diff_models.py`), C3 (`ActionLog` → `state/models.py`), C4 (`EnvFileSpec` → `config/models.py`) are completed in this phase — not deferred.
**Why first:** Clean layering is required before moving files, otherwise moves just relocate the coupling mess.

### Phase 1: Delete Dead Code (M1 remaining)
**Prerequisites:** Phase 0 (ensures nothing accidentally depended on shims).
**Deliverables:** All shim files and dead code removed. Verified zero consumers via grep.
**Why early:** Reduces noise for subsequent phases; dead code can't accidentally get moved into new locations.

### Phase 2: Absorb cache/ + review/ + repos/ → git/
**Prerequisites:** Phase 0 (C2 coupling fix moves review types to git/).
**Deliverables:** `git/diff/`, `git/repos/`, `git/testing/`, `git/ops/` sub-packages created. Existing root-level files (`branch_ops.py`, `conflict_ops.py`, `prune_ops.py`) moved into `git/ops/`. `cache/`, `review/`, `repos/` directories deleted. ~14 import paths updated.

### Phase 3: Absorb routines/ → config/routines/
**Prerequisites:** Phase 0 (no coupling dependencies).
**Deliverables:** `config/routines/` sub-package with discovery.py, loader.py, versioning.py. `routines/` directory deleted. ~14 import paths updated.

### Phase 4: Absorb artifacts/ → workflow/artifacts/
**Prerequisites:** None (independent).
**Deliverables:** `workflow/artifacts/` sub-package. `artifacts/` directory deleted. 3 import paths updated.

### Phase 5: Absorb metrics/ + mcp/ → api/
**Prerequisites:** None (independent).
**Deliverables:** `api/mcp/` sub-package + `api/metrics.py`. `metrics/` and `mcp/` directories deleted. 1–2 import paths each.

### Phase 6: Absorb scaffolding/ + agents/ → runners/
**Prerequisites:** Phase 0 (C6 coupling fix for agents).
**Deliverables:** `runners/scaffolding/` + `runners/profiles/` sub-packages. `scaffolding/` and `agents/` directories deleted. 3–5 import paths each.

### Phase 7: Restructure workflow/ Internals
**Prerequisites:** Phases 4, 6 (artifacts and runners absorptions complete).
**Deliverables:** Internal files moved into engine/, events/, signals/, agent/ sub-packages. No external import changes — all access via `workflow/__init__.py`.

### Phase 8: Restructure db/ Internals
**Prerequisites:** None (independent).
**Deliverables:** Internal files moved into orm/, access/, recovery/ sub-packages. No external import changes.

### Phase 9: Restructure runners/ Internals
**Prerequisites:** Phase 6 (absorptions complete).
**Deliverables:** Internal files moved into detection/, runtime/ sub-packages. Note: `execution/` sub-package already exists with `phase_handler.py`, `attempt_store.py`, `event_broadcaster.py` — no changes needed there. No external import changes.

### Phase 10: Explicit __all__ + Interface Narrowing
**Prerequisites:** Phases 7–9 (internal restructuring complete).
**Deliverables:** All 9 module `__init__.py` files declare `__all__`. Public interfaces narrowed per intent doc. `BroadcastCallback` protocol replaces direct `ConnectionManager` import. `RunWorkflow` made private. `NoTaskReason` moved to workflow/.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution order | Couplings → dead code → absorptions → internals | Fix dependencies before moving files; delete dead code early to reduce noise |
| Phase granularity | One module absorption per phase | Each phase is independently testable; easier to bisect if something breaks |
| Backward-compat shims | Zero tolerance — delete entirely | Shims mask incomplete migrations; the intent explicitly requires no stubs left behind |
| Import path updates | Find-and-replace across entire codebase per phase | Mechanical but must be exhaustive; grep verification after each phase |
| Sub-package access discipline | External callers use top-level only | Enforced by `__all__`; linting rule is a future follow-up |
| Internal restructuring scope | workflow, db, runners only | These are the three largest modules; others are already well-structured |
| RunService/ReviewService extraction | Out of scope | High risk (~800 LOC extraction); separate effort after consolidation stabilizes |

## Risks and Unknowns

| Risk | Impact | Mitigation |
|------|--------|------------|
| Circular imports after absorptions | Build failure | Resolve couplings first (Phase 0); test imports after each file move |
| Missed import paths | Runtime errors, test failures | Exhaustive `grep -r` after each phase; run full test suite; CI catches missed paths |
| ORM model imports from outside db/ | Phase 10 narrowing breaks callers | Audit all `from orchestrator.db.models import` before narrowing; provide repository methods for any missing access patterns |
| `RunWorkflow` consumers resist privatization | Can't narrow interface | If executor can't be refactored, keep `RunWorkflow` in `__all__` with a TODO |
| Large number of import path changes in single phase | Merge conflicts with concurrent work | Coordinate timing; do absorptions during low-activity periods; each phase is a single commit |
| `BroadcastCallback` protocol may not cover all WebSocket usage | Incomplete abstraction | Audit all `ConnectionManager` methods called by runners before defining protocol |
| Test files import internal paths | Tests break on restructuring | Update test imports alongside source imports; tests are first-class consumers |
| Alembic migration imports may reference old paths | DB init fails | Check alembic/versions/*.py for orchestrator imports; update if found |

## References

- [intent.md](intent.md) — Original module consolidation specification with target structure
- `src/orchestrator/` — Current 19-module source tree
- `AGENTS.md` — Project coding conventions and test commands
