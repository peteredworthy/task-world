# Module Consolidation: Execution Summary

**Project:** Consolidate `src/orchestrator/` from 19 modules to 9 with explicit public interfaces and zero backward-compatibility shims.

**Status:** Planning phase complete. Dry-run analysis identified 35 failure modes and hardening actions. Execution plan is ready.

**Date:** 2026-03-23

---

## Intent Satisfaction Summary

### What We're Solving

The current `src/orchestrator/` has 19 loosely-bounded modules with:
- 6 cross-layer coupling violations (C1–C6)
- Dead code: shim files, abandoned agent implementations
- Modules distributed across shallow directory hierarchy (makes boundaries unclear)
- No explicit public interfaces (`__all__`)
- Backward-compat stubs creating confusion about what's "canonical"

### What Success Looks Like

- **9 cohesive modules** with explicit layering: CLI → API → Runners → Workflow → Config/State/Git/DB/Envfiles
- **Zero cross-layer imports** — runners cannot import from API, workflow cannot import from runners
- **Explicit `__all__` on every module** — external callers use only top-level imports, not sub-packages
- **100% moved, zero shims** — no re-export stubs, no deprecated warnings, no "#removed" comments
- **All tests passing** — 2500+ backend tests + 200+ frontend tests + TypeScript + ESLint + build

### Project Scope

**In Scope:**
- Resolve all 6 coupling violations (C1–C6)
- Delete all dead code (agent shims, parsers shims, routers stub)
- Move 10 modules into target modules (routines, cache, review, repos, artifacts, metrics, mcp, scaffolding, agents, and internal reorganization)
- Restructure 3 large modules (workflow, db, runners) into well-organized sub-packages
- Add explicit `__all__` to all 9 modules
- Update every import path across the codebase

**Out of Scope:**
- Functional behavior changes
- New API endpoints or features
- Database schema migrations
- Extraction of RunService/ReviewService (separate effort)
- Linting rules to enforce import discipline (future follow-up)

---

## Execution Structure: 11 Phases (0–10)

### Phase Overview

| Phase | Name | Prerequisite | Impact | Est. Files | Critical? |
|-------|------|--------------|--------|------------|-----------|
| 0 | Resolve Couplings C1–C6 | None | Fix cross-layer imports, move 4 types | ~20 | YES |
| 1 | Delete Dead Code | Phase 0 | Remove 10+ shim files, update imports | ~30 | YES |
| 2 | Absorb cache/ + review/ + repos/ → git/ | Phase 1 | Create git/ sub-packages, delete 3 dirs | ~25 | YES |
| 3 | Absorb routines/ → config/routines/ | Phase 1 | Create config/ sub-package, delete dir | ~15 | NO |
| 4 | Absorb artifacts/ → workflow/artifacts/ | Phase 1 | Create workflow/ sub-package, delete dir | ~5 | NO |
| 5 | Absorb metrics/ + mcp/ → api/ | Phase 2 | Create api/ sub-packages, delete 2 dirs | ~5 | NO |
| 6 | Absorb scaffolding/ + agents/ → runners/ | Phase 1 | Create runners/ sub-packages, delete 2 dirs | ~15 | NO |
| 7 | Restructure workflow/ internals | Phases 4, 6 | Create engine/, events/, signals/, agent/ | ~35 | NO |
| 8 | Restructure db/ internals | Phases 1, 6 | Create orm/, access/, recovery/ | ~20 | NO |
| 9 | Restructure runners/ internals | Phase 6 | Create detection/, runtime/ | ~15 | NO |
| 10 | Explicit `__all__` + interface narrowing | Phases 7–9 | Declare `__all__` on all 9 modules | ~10 | YES |

### Dependency Graph

```
Phase 0 (coupling fixes)
  ↓ required by
Phase 1 (dead code deletion)
  ↓ required by
Phases 2, 3, 4, 6 (module absorptions) + Phase 5 (hidden dependency on Phase 2)
  ↓ required by
Phases 7, 8, 9 (internal restructuring)
  ↓ required by
Phase 10 (interface narrowing)
```

**Execution Order:** 0 → 1 → 2 → {3, 4, 6} in parallel → 5 → {7, 8, 9} in parallel → 10

---

## Phase Details: Tasks and Scope

### Phase 0: Resolve Couplings C1–C6

**Goal:** Fix all cross-layer imports and type relocations before moving files.

| Coupling | From | To | Type | Files to Update |
|----------|------|----|----|-----------------|
| C1 | runners/nudger.py | config/models.py | Move `NudgerConfig` dataclass | global_config.py, nudger.py, tests |
| C2 | review/models.py | git/diff_models.py | Move `CommitInfo`, `FileStatus`, `ModifiedFile` | review/*.py, git/diff_ops.py, tests |
| C3 | runners/action_log.py | state/action_log.py | Move `ActionLog` + supporting types | db/models.py, runners/*.py, tests (7 consumers) |
| C4 | envfiles/models.py | config/models.py | Move `EnvFileSpec` | state/models.py, envfiles/*.py, tests |
| C5 | workflow/service.py | N/A | Create `RecoveryResult` dataclass in workflow; translate to API in router | routers/runs.py |
| C6 | runners/agents.py | N/A | Define `TaskSubmitCallback` protocol; remove direct `WorkflowService` import | agents/user_managed.py |

**Tasks:** 6 independent coupling fixes. Each is an import path update + type relocation.

**Critical Failures:** FM1–FM3 (naming collision, missed consumers, wrong type descriptors). **Hardening:** Explicit audit of both `NudgerConfig` classes; add missed consumer to update list.

---

### Phase 1: Delete Dead Code

**Goal:** Remove all verified-zero-consumer shim files. Fallback if consumers found: update imports, then delete.

**Files to Delete:**
1. `routers/` (stub directory with shims)
2. `agent_detector.py` (old agent detection, replaced by detector.py)
3. `parsers/base.py`, `parsers/custom_token_counting.py` (unused protocols)
4. `agents/openhands.py`, `agents/openhands_docker.py`, `agents/openhands_common.py` (wrapped by detector)
5. `agents/codex_server.py`, `agents/codex_server_common.py` (wrapped by detector)

**Expected Import Updates:** ~22 (1 production file, ~21 test files using OpenHands/Codex shims)

**Critical Failures:** FM4 (shims have many active consumers, not "zero"), FM5 (parsers may contain real protocols), FM6 (grep regex word boundary). **Hardening:** Audit before deletion; if consumers found, update all; check parsers for lazy-loading usage.

---

### Phase 2: Absorb cache/ + review/ + repos/ → git/

**Goal:** Consolidate Git-related modules into a unified `git/` package with sub-packages for different concerns.

**Structure After Phase 2:**
```
src/orchestrator/git/
  __init__.py (re-exports canonical symbols)
  diff/
    __init__.py
    models.py (moved from review/models.py, includes CommitInfo, FileStatus, ModifiedFile from C2)
    diff_ops.py (moved from git/diff_ops.py)
  repos/
    __init__.py
    discovery.py (moved from repos/discovery.py)
    access.py (moved from repos/access.py)
  ops/
    __init__.py
    branch_ops.py, conflict_ops.py, prune_ops.py (moved from git/ root)
  testing/
    __init__.py
    test_runner.py (moved from repos/test_runner.py)
```

**Directories to Delete:** cache/, review/, repos/

**Import Updates:** ~25 files updating `from orchestrator.{cache,review,repos}` to `from orchestrator.git.*`

**Key Tasks:**
1. Create sub-package directories and `__init__.py` files
2. Move files into appropriate sub-packages
3. Update `git/__init__.py` with canonical re-exports (all public symbols)
4. Update all consumers (25+ files)
5. Delete original directories

**Critical Failures:** FM7 (git/diff_models.py doesn't exist; Phase 0 prerequisite), FM8 (test_discovery.py not in consumer list), FM9 (naming collision). **Hardening:** Add preflight check for Phase 0 artifact; add test file to explicit consumer list; document `BranchNotFoundError` distinction.

---

### Phase 3: Absorb routines/ → config/routines/

**Goal:** Move routine discovery, loading, and versioning into config module.

**Structure After Phase 3:**
```
src/orchestrator/config/
  routines/
    __init__.py
    discovery.py (moved from routines/discovery.py)
    loader.py (moved from routines/loader.py)
    versioning.py (moved from routines/versioning.py)
```

**Directory to Delete:** routines/

**Import Updates:** ~13 files (discovery, loader, versioning consumers, tests)

**Key Tasks:**
1. Create `config/routines/` sub-package
2. Move 3 files into sub-package
3. Update `config/__init__.py` with re-exports
4. Update all consumers
5. Delete original directory

**Critical Failures:** None identified. This phase is straightforward.

---

### Phase 4: Absorb artifacts/ → workflow/artifacts/

**Goal:** Move artifact registry into workflow module.

**Structure After Phase 4:**
```
src/orchestrator/workflow/
  artifacts/
    __init__.py
    registry.py (moved from artifacts/registry.py)
```

**Directory to Delete:** artifacts/

**Import Updates:** ~3 files (executor, tests)

**Key Tasks:**
1. Create `workflow/artifacts/` sub-package
2. Move artifact code
3. Update `workflow/__init__.py` with re-exports
4. Update consumers
5. Delete original directory
6. Verify `executor.py:826` lazy import (`context_from`) is exercised by tests

**Critical Failures:** FM10 (lazy import not tested). **Hardening:** Grep audit sufficient; no explicit test needed.

---

### Phase 5: Absorb metrics/ + mcp/ → api/

**Goal:** Consolidate cost metrics and MCP server into API module.

**Structure After Phase 5:**
```
src/orchestrator/api/
  metrics.py (moved from metrics/models.py)
  mcp/
    __init__.py
    client.py, server.py, tools.py (moved from mcp/)
```

**Directories to Delete:** metrics/, mcp/

**Import Updates:** ~3 files (executor, server setup, tests)

**HIDDEN DEPENDENCY:** Phase 5 depends on Phase 2 (mcp/tools.py imports from repos). **Hardening:** Remove "independent" claim; add explicit prerequisite.

**Key Tasks:**
1. Create `api/metrics.py` from flat module
2. Create `api/mcp/` sub-package
3. Move MCP files
4. Update `api/__init__.py` re-exports
5. Update consumers
6. Delete original directories
7. **After Phase 7:** Phase 7's workflow internal restructuring will move things like `workflow.clarifications`, requiring `api/mcp/tools.py` update

**Critical Failures:** FM11–FM12 (hidden dependency, Phase 7 follow-up). **Hardening:** Make dependency explicit; document Phase 7 follow-up in Task 7.

---

### Phase 6: Absorb scaffolding/ + agents/ → runners/

**Goal:** Move workspace setup and agent profiles into runners module.

**Structure After Phase 6:**
```
src/orchestrator/runners/
  scaffolding/
    __init__.py
    workspace_setup.py (moved from scaffolding/)
  profiles/
    __init__.py
    models.py (moved from agents/models.py)
    schemas.py (moved from agents/schemas.py)
    registry.py (moved from agents/registry.py)
```

**Directories to Delete:** scaffolding/, agents/

**Import Updates:** ~15 files (workspace setup callers, agent profile users, tests)

**CRITICAL ISSUE FM13:** agents/schemas.py imports `ApiModel` from api/schemas.base — violates layering (runners cannot import from api). **Hardening:** Before Phase 6 execution, choose fix:
- Option A: Replace `ApiModel` with `pydantic.BaseModel` in agents/schemas.py
- Option B: Move `ApiModel` to config/models.py (lower layer)

**CRITICAL ISSUE FM14:** db/migrations/env.py imports `orchestrator.agents.models` for Alembic table discovery — not in consumer list. **Hardening:** Add explicitly to Task 4 update list.

**CRITICAL ISSUE FM15:** agents/__init__.py is empty (only docstring). **Hardening:** Specify explicit exports for `runners/profiles/__init__.py` after audit.

**Key Tasks:**
1. Create `runners/scaffolding/` and `runners/profiles/` sub-packages
2. Move files into sub-packages
3. Resolve ApiModel layering violation (Option A or B, must decide before execution)
4. Update `runners/__init__.py` re-exports
5. Update all consumers (including db/migrations/env.py if present)
6. Delete original directories

---

### Phase 7: Restructure workflow/ Internals

**Goal:** Organize workflow module internals into coherent sub-packages (engine, events, signals, agent).

**Structure After Phase 7:**
```
src/orchestrator/workflow/
  engine/
    __init__.py
    runtime.py, state.py, executor.py (workflow execution)
  events/
    __init__.py
    emitter.py, models.py, handlers.py (workflow events)
  signals/
    __init__.py
    runtime.py (NoTaskReason, LoopAction, async control), registry functions
  agent/
    __init__.py
    summary_cache.py (agent run summarization)
  __init__.py (re-exports all public symbols + bridges for backward compat if needed)
```

**No External Changes:** All access is via `workflow/__init__.py`; external callers see no difference.

**Internal File Moves:** ~35 files reorganized within workflow/

**HIGH FAILURE MODES:**
- FM16: `events/__init__.py` template lists 11 symbols; actual `events.py` exports 35 symbols
- FM17: `signals/__init__.py` missing `SignalQueue` and registry functions
- FM18: `LoopAction` dataclass not moved with `NoTaskReason` — incomplete coupling fix (C6)
- FM19: Bridges (re-export files) may violate "zero shims" policy — decision needed
- FM20: Task must update canonical `workflow/agent/summary_cache.py`, not bridge file

**Hardening:**
- FM16–FM17: Audit symbols before writing `__init__.py` files; enumerate all exports from source
- FM18: Explicitly move `LoopAction` to `workflow/signals/runtime.py` alongside `NoTaskReason`
- FM19: Decide: update all external callers to new paths OR keep bridges documented as intra-module optimization (unlikely to violate "zero shims" if internal-only)
- FM20: Target new sub-package file location, not root bridge

**Key Tasks:**
1. Organize workflow files into engine/, events/, signals/, agent/ sub-packages
2. Audit and move `NoTaskReason` and `LoopAction` together (C6 completion)
3. Write comprehensive `__init__.py` re-exports (audit first)
4. Test all imports; verify no external changes needed
5. Update `api/mcp/tools.py` if workflow imports moved (from Phase 5's `workflow.clarifications` relocation)

---

### Phase 8: Restructure db/ Internals

**Goal:** Organize db module internals into orm/, access/, and recovery/ sub-packages.

**Structure After Phase 8:**
```
src/orchestrator/db/
  orm/
    __init__.py
    models.py, base.py (ORM definitions, not for external use)
  access/
    __init__.py
    repositories.py, queries.py (data access abstractions)
  recovery/
    __init__.py
    journal_replay.py, recovery_service.py (recovery procedures)
  __init__.py (re-exports public APIs only; hides ORM models)
```

**CRITICAL ISSUE FM21:** `db/recovery.py` flat file and `db/recovery/` directory cannot coexist — package shadows flat file immediately. Breaks 4 integration tests, 1 script, internal `journal_replay.py`. **Hardening:** Delete flat `recovery.py` atomically when creating directory. Update all consumers first (Task 1): `scripts/restore_from_journal.py`, `scripts/seed_db.py`, `scripts/worker.py`, integration tests.

**HIGH FAILURE MODES:**
- FM22: scripts/ directory (3 files) callers not in Phase 1 consumer list
- FM23: Phase 6 dependency — if agents moved, env.py needs updated agents import path
- FM24: migrations/env.py imports both db.base and agents.models — Task only mentions db.base

**Hardening:**
- FM21: Restructure Task 3 — update consumers first, delete flat file and create directory atomically
- FM22: Add scripts/ files to explicit consumer list
- FM23–FM24: Conditional update — if Phase 6 ran first, add agents import path update

**Key Tasks:**
1. Update all `from orchestrator.db.recovery import` statements
2. Delete flat `db/recovery.py` file
3. Create `db/orm/`, `db/access/`, `db/recovery/` sub-packages
4. Move files into sub-packages
5. Write `__init__.py` files with canonical re-exports
6. Test; verify no external import path changes

---

### Phase 9: Restructure runners/ Internals

**Goal:** Organize runners module internals into detection/, runtime/ sub-packages.

**Structure After Phase 9:**
```
src/orchestrator/runners/
  detection/
    __init__.py
    detector.py (agent detection + config)
  runtime/
    __init__.py
    execution.py, nudger.py, executor.py (agent runtime)
  execution/
    __init__.py (already exists, no changes)
  __init__.py (re-exports all public symbols + sub-packages created by Phase 6)
```

**Note:** `execution/` sub-package already exists with phase_handler.py, attempt_store.py, event_broadcaster.py — no changes needed.

**MEDIUM FAILURE MODES:**
- FM25: Phase 6 prerequisite unchecked — `runners/scaffolding/` and `runners/profiles/` may not exist
- FM26: `runners/__init__.py` template may clobber Phase 6 re-exports
- FM27: Fallback import for `NudgerConfig` uses wrong path
- FM28: Docstring wording change may trigger linting

**Hardening:**
- FM25: Add explicit check at Task 1 start; verify Phase 6 completed
- FM26: Read current `runners/__init__.py` first; merge Phase 6 content before rewriting
- FM27: Fix import path to `from orchestrator.config.models import NudgerConfig`
- FM28: Preserve existing docstring; only add new re-exports

**Key Tasks:**
1. Verify Phase 6 completed (runners/scaffolding/ and runners/profiles/ exist)
2. Create `runners/detection/` and `runners/runtime/` sub-packages
3. Move files into sub-packages
4. Write `__init__.py` files (preserve Phase 6 re-exports)
5. Fix fallback import paths if any
6. Test; verify no external changes

---

### Phase 10: Explicit `__all__` + Interface Narrowing

**Goal:** Declare explicit `__all__` on all 9 modules; narrow public interfaces to reduce surface area.

**Critical Prerequisites:** Phases 7–9 must be complete (internal restructuring).

**Current State of `__all__`:**
- `config/__all__`: Already exists (26 symbols)
- `state/__all__`: Already exists (12 symbols, includes `generate_id` — to be hidden)
- `git/__all__`: Already exists (17 symbols)
- `workflow/__all__`: Already exists (37 symbols)
- `db/__init__.py`: Empty, needs `__all__`
- `api/__init__.py`: Empty, needs `__all__`
- `runners/__init__.py`: Empty, needs `__all__`
- `envfiles/__init__.py`: Empty, needs `__all__`
- `cli/__init__.py`: Empty, needs `__all__`

**Tasks:**
1. **config/**: Audit existing `__all__` (26 symbols); ensure all moved types are included
2. **state/**: Edit existing `__all__` — remove `generate_id` (privatize), keep others
3. **git/**: Audit existing `__all__` (17 symbols from Phase 2)
4. **workflow/**: Edit existing `__all__` (37 symbols) — add moved `NoTaskReason`/`LoopAction`; hide `RunWorkflow` if possible
5. **db/**: Create `__all__` — include only public repositories/access APIs; hide ORM models
6. **api/**: Create `__all__` — include schemas, routers, mcp server
7. **runners/**: Create `__all__` — include executor, detection, profiles; hide internal executor details
8. **envfiles/**: Create `__all__` — include models and utils
9. **cli/**: Create `__all__` — include main CLI entry points

**Interface Narrowing Specific Tasks:**
- **Hide ORM Models:** Remove `from orchestrator.db.models import` from public `__all__`. Ensure all consumers use repository accessors instead.
- **Make `RunWorkflow` Private:** Rename to `_RunWorkflow` or remove from `workflow/__all__`. If executor can't be refactored, keep it public with a TODO.
- **Hide `check_step_progression`/`check_run_completion`:** Move behind `WorkflowService` or make private. Update 6 test files that import these directly.
- **Define `BroadcastCallback` Protocol:** Create in `runners/types.py`; replace direct `ConnectionManager` import in `runners/executor.py`.
- **Remove 8 Backward-Compat Shims:** Verify Phase 1 deleted agent shims; don't include them in `runners/__all__`.

**CRITICAL FAILURES:**
- FM29: Phase 7–9 prerequisite unchecked — workflow may still be flat
- FM30: `RunWorkflow` location assumed wrong; must audit first
- FM31: 4 modules already have `__all__` — tasks are edits, not creations
- FM32: `generate_id` already in `state/__all__` — edit existing, don't recreate
- FM33: Empty modules need imports added before `__all__` declarations
- FM34: Backward-compat shims may still exist (Phase 1 incomplete)
- FM35: 6 test files import `check_step_progression`/`check_run_completion` directly

**Hardening:**
- Gate on Phase 7 completion before starting
- Audit `RunWorkflow` location; create diff for existing `__all__` files
- Enumerate all test files needing updates; create list before editing
- Don't add new imports unless consumers exist; audit first

---

## Key Decisions

| Decision | Choice | Rationale | Risk |
|----------|--------|-----------|------|
| **Execution order** | Couplings → dead code → absorptions → internals | Fix dependencies before moving files; dead code first reduces noise | Low — ordering is solid |
| **Phase granularity** | One module absorption per phase (except 2, 5, 6) | Independently testable; easier to bisect failures | Medium — tight scheduling |
| **Backward-compat policy** | Zero tolerance; delete shims immediately | "No stubs" explicitly mandated in intent; shims mask incomplete migrations | Low — aligned with intent |
| **Import path updates** | Find-and-replace across entire codebase per phase | Mechanical but exhaustive; grep verification after each phase | Medium — many files to update |
| **Sub-package access** | External callers use top-level only; enforced by `__all__` | Keeps boundaries clear; future linting can strengthen | Low — `__all__` is standard Python |
| **ApiModel layering** | Option A (replace with BaseModel) OR Option B (move to config) — decision needed before Phase 6 | runners cannot import from api/; choice affects Phase 6 scope | HIGH — must decide before execution |
| **Bridge files** | Likely none (internal-only re-exports acceptable) | External callers won't see them; reduces scope of Phase 7 | Low — confined to module internals |
| **RunWorkflow privatization** | Attempt to privatize; fallback to keeping public if executor resists | Reduces surface area; executor may have consumers we can't easily refactor | Medium — may need fallback |

---

## Critical Execution Constraints

### Constraint 1: Phase 0 Must Succeed

Phase 0 resolves all 6 couplings. Phases 1–10 depend on these fixes. **If Phase 0 fails, project is blocked.**

**Critical Fix:** Resolve naming collision between two `NudgerConfig` classes (dataclass in runners vs Pydantic in config). Audit both; use aliases in global_config.py to disambiguate.

### Constraint 2: Phase 1 Fallback Logic Must Work

Phase 1 assumes "zero consumers" for agent shims. **Reality:** OpenHands/Codex shims have ~22 active consumers.

**Critical Fix:** Step 1 includes fallback: "if consumers found, update imports then delete." Phase 1 must not proceed until all ~22 import paths are updated.

### Constraint 3: Phase 2 Prerequisite: git/diff_models.py Must Exist

Phase 2 assumes `git/diff_models.py` is created in Phase 0 (C2 coupling fix). If Phase 0 is skipped or incomplete, Phase 2 fails immediately.

**Critical Fix:** Preflight check at Phase 2 start: verify Phase 0 artifact exists before proceeding.

### Constraint 4: Phase 5 Hidden Dependency on Phase 2

Phase 5 claims to be independent. **Reality:** mcp/tools.py imports from repos, which Phase 2 moves to git/.

**Critical Fix:** If Phase 5 runs before Phase 2, api/mcp/tools.py imports become stale. Enforce order: 2 → 5.

### Constraint 5: Phase 6 ApiModel Layering Violation

agents/schemas.py imports `ApiModel` from api/schemas.base. This violates layering (runners cannot import from api).

**Critical Decision Required Before Phase 6 Execution:**
- **Option A:** Replace `ApiModel` with `pydantic.BaseModel` in agents/schemas.py
- **Option B:** Move `ApiModel` to config/models.py (lower layer)

Choose before Phase 6 starts. **Default recommendation:** Option A (simpler, no cross-module changes).

### Constraint 6: Phase 8 db/recovery.py Shadowing

`db/recovery.py` flat file and `db/recovery/` directory cannot coexist. Creating the directory shadows the file immediately, breaking imports.

**Critical Fix:** Delete flat recovery.py file atomically when creating directory. Update all consumers first:
- scripts/restore_from_journal.py
- scripts/seed_db.py
- scripts/worker.py
- Integration tests (4 files)

---

## Risks and Mitigations

### Risk Category: Import Path Errors

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|-----------|
| Missed import path update | Runtime error; test failure; incomplete phase | Medium | `grep -r "from orchestrator.{old_module}"` after each phase; full test suite |
| Circular imports after absorptions | Build failure; import loop | Low | Phase 0 resolves couplings first; test imports immediately after moves |
| Test files import internal paths | Tests break on restructuring | Medium | Update test imports alongside source; tests are first-class consumers |

### Risk Category: Design Assumptions

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|-----------|
| "Dead code" has active consumers | Deletion breaks production | Medium | Audit before deletion; fallback: update imports if consumers found (FM4) |
| `RunWorkflow` has hidden consumers | Can't privatize in Phase 10 | Low | Audit all imports; keep public with TODO if needed (FM30) |
| ORM models accessed from outside db/ | Interface narrowing breaks callers | Medium | Audit all `from orchestrator.db.models import`; provide repository methods (FM31–FM33) |
| Alembic migrations reference moved types | DB init fails | Low | Check migrations/env.py and version files; update if needed |

### Risk Category: Merge Conflicts & Coordination

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|-----------|
| Concurrent work during phases | Merge conflicts; lost work | Low | Coordinate timing; each phase is single commit; worktree isolation |
| Phase interdependencies broken | Subsequent phase fails | Medium | Document dependency graph; enforce execution order |
| Sub-package `__init__.py` clobbering | Re-exports lost | Low | Read current file first; merge new content (FM26, FM31) |

### Risk Category: Specification Gaps

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|-----------|
| `events/__init__.py` symbols incomplete | Imports fail | Medium | Audit `events.py` exports before writing `__init__.py` (FM16) |
| `RunWorkflow` location wrong | Privatization targets wrong file | Low | Grep for definition before refactoring (FM30) |
| Phase 7 must update `api/mcp/tools.py` | Stale imports after Phase 5 | High | Document in Phase 7 plan (FM12) |

---

## Caveats and Gotchas

### Gotcha 1: Two `NudgerConfig` Classes

There are TWO classes named `NudgerConfig`:
1. **Dataclass** in `runners/nudger.py` (simple, configuration-only)
2. **Pydantic model** in `config/global_config.py` (with validation)

Phase 0 moves the dataclass to `config/models.py`. This will be **in the same module** as the Pydantic version. Use explicit aliases in `global_config.py` to avoid confusion. **Document the distinction** in any comments.

### Gotcha 2: `ActionLog` Has Many Consumers

`ActionLog` is a simple dataclass in `runners/action_log.py`, but it's imported by **7 files**:
- db/models.py
- runners/executor.py, runners/nudger.py, runners/discovery.py
- tests/unit/runners/*, tests/integration/*

Phase 0 must update all 7 consumers. This is a broader scope than other coupling fixes.

### Gotcha 3: Dead Code Fallback

Phase 1 assumes agent shims (openhands.py, codex_server.py, etc.) have "zero consumers." **They don't.** They have ~22 active consumers (mostly test files). The phase includes fallback logic: "if consumers found, update imports then delete." **This fallback must work correctly**, or Phase 1 stalls.

**Auditing is NOT optional** — grep first, then update, then delete.

### Gotcha 4: Phase 2 Prerequisite

Phase 2 creates `git/diff_models.py` by moving types from review/models.py. **This file does not exist yet.** Phase 0 must complete first. Add a preflight check at Phase 2 start.

### Gotcha 5: Phase 5 Hidden Dependency

Phase 5 (absorb metrics/mcp to api) claims independence from Phase 2. **It's not.** `mcp/tools.py` imports from `repos`, which Phase 2 moves to `git/repos/`. If Phase 5 runs before Phase 2, api/mcp/tools.py gets stale imports and Phase 2 won't update the new copy (it's already been moved). **Execute in order: 2 → 5.**

### Gotcha 6: Phase 8 Shadowing Bug

Creating `db/recovery/` directory shadows the flat `db/recovery.py` file immediately. All existing imports break on the spot. **Must delete the flat file first** (atomically with directory creation). Update consumers before deletion.

### Gotcha 7: ApiModel Layering Violation

`agents/schemas.py` imports `ApiModel` from `api/schemas.base`. Runners cannot import from api/ per layering rules. **Must decide before Phase 6 execution:**
- Option A: Replace with `pydantic.BaseModel` (simpler)
- Option B: Move `ApiModel` to config/models.py

Document your choice in Phase 6 plan.

### Gotcha 8: Bridges vs Shims

Phase 7–9 internal restructuring may use "bridge files" (thin re-export files like `workflow/__init__.py` that re-exports all sub-package symbols). These are **intra-module only** (external callers still use top-level) and do NOT violate the "zero shims" rule. Bridges are an acceptable internal optimization. **Document this decision explicitly** if used.

### Gotcha 9: Existing `__all__` Are Edits, Not Creations

Four modules already have `__all__` declarations (config, state, git, workflow). Phase 10 is not "add `__all__`" for these; it's "audit and edit existing." Use `git diff` to show before/after. **Reading existing `__all__` is mandatory** before editing.

### Gotcha 10: `generate_id` Removal from state `__all__`

`generate_id` is currently in `state/__all__` (public). Phase 10 removes it (privatize). **This is a breaking change for any external consumers.** Audit all imports of `from orchestrator.state import generate_id` before removal. If external consumers exist, keep it public (or provide migration path).

---

## Verification Gates

Each phase must pass the following verification before proceeding:

1. **All backend tests pass:** `uv run pytest tests/ -q`
2. **All frontend tests pass:** `cd ui && npx vitest run`
3. **TypeScript type check:** `cd ui && npx tsc --noEmit`
4. **ESLint:** `cd ui && npx eslint . --max-warnings 0`
5. **Frontend build:** `cd ui && npm run build`
6. **No stray imports:** `grep -r "from orchestrator.{old_module}"` returns zero results

### Phase 0 Specific

- Verify both `NudgerConfig` classes are disambiguated
- Verify C1–C6 coupling violations are resolved (no cross-layer imports in identified locations)

### Phase 1 Specific

- Verify all consumers of shim files are updated
- Verify original shim directories are deleted
- `grep -r "from orchestrator.{routers,agent_detector,parsers,agents.openhands}"` returns zero results

### Phases 2–6 Specific

- Verify original directories are deleted entirely
- Verify all imports use new paths
- Verify no imports of old paths remain: `grep -r "from orchestrator.{old}"` zero results

### Phases 7–9 Specific

- Verify internal file reorganization is complete
- Verify no external import changes (all access via top-level module)
- Verify `__init__.py` re-exports include all needed symbols

### Phase 10 Specific

- Verify all 9 modules have `__all__` declared
- Verify `generate_id`, `RunWorkflow`, `check_step_progression`, `check_run_completion` are privatized/hidden
- Verify `BroadcastCallback` protocol replaces direct `ConnectionManager` import
- Verify no test files import internal symbols directly

---

## Timeline and Dependencies

```
DAY 1: Phase 0 (couplings) → Phase 1 (dead code)
       ↓
DAY 2: Phase 2 (cache/review/repos → git)
       ↓
DAY 3: Phases 3, 4, 6 in parallel (routines, artifacts, scaffolding/agents)
       ↓
DAY 4: Phase 5 (metrics/mcp → api)
       ↓
DAY 5: Phases 7, 8, 9 in parallel (internal restructuring)
       ↓
DAY 6: Phase 10 (explicit __all__ + interface narrowing)
```

**Actual timeline depends on:**
- Scope of import path updates (especially Phase 1 fallback)
- Complexity of interface narrowing (Phase 10)
- Test suite run time (must pass after each phase)

---

## Success Criteria

### Quantitative

- [ ] 11 phases completed (0–10)
- [ ] 0 shim files remain in codebase
- [ ] 9 modules with explicit `__all__`
- [ ] 0 cross-layer imports
- [ ] 0 imports from old module paths
- [ ] 2500+ backend tests pass
- [ ] 200+ frontend tests pass
- [ ] TypeScript clean
- [ ] ESLint clean
- [ ] Build succeeds

### Qualitative

- [ ] Module layering is clear and enforced
- [ ] Public interfaces are intentional and documented
- [ ] Internal organization supports future maintenance
- [ ] No confusion about canonical vs deprecated import paths
- [ ] Developers understand which symbols are public vs internal

---

## Next Steps

1. **Decide on Phase 6 ApiModel fix** (Option A or B) before starting execution
2. **Review failure modes FM1–FM35** and ensure hardening actions are understood
3. **Prepare audit scripts** for import path verification (`grep -r`, test file enumeration)
4. **Schedule execution** with 6-day timeline, accounting for test suite runs
5. **Create checklist** mapping each phase's tasks to concrete git commits
6. **Set up CI/CD** to run full test suite after each phase commit

---

## References

- **Intent:** [intent.md](intent.md) — Original module consolidation specification
- **Plan:** [plan.md](plan.md) — 11-phase execution plan with dependencies
- **Dry-Run Analysis:** Consolidated analysis document with 35 failure modes and hardening actions
- **Clarifications:** [clarifications.md](clarifications.md) — Design decisions already resolved
- **Architecture:** [architecture.md](architecture.md) — Target structure with file layouts

