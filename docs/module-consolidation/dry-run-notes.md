# Consolidated Dry-Run Analysis: Module Consolidation (Steps 0–10)

**Analysis Date:** 2026-03-23
**Scope:** All 11 implementation phases (0–10) of module consolidation project
**Baseline:** Current worktree state pre-execution

---

## Executive Summary

The module consolidation plan is structurally sound and implementable. Phases are ordered correctly by dependency, and most tasks are mechanically straightforward. However, there are **14 identified failure modes** across phases, ranging from HIGH severity (blocking issues) to LOW severity (documentation/verification gaps). All failure modes have identified hardening actions.

**Key findings:**
- Most phases are low-risk file-move-and-import-update operations
- Phase 0 (coupling fixes) and Phase 1 (dead code deletion) are prerequisites for subsequent phases
- Phases 7–10 have stricter dependencies (internal restructuring + interface narrowing)
- No fundamental design flaws detected — all coupling issues are fixable as described
- **6 blocking issues require resolution before execution**

---

## Per-Step Simulation Results

### Phase 0: Resolve Couplings C1–C6

**Status:** Well-structured, 6 failure modes identified

**Summary:**
- All 6 coupling violations (C1–C6) can be fixed through targeted import changes and type relocations
- C1: Move `NudgerConfig` (dataclass, not Pydantic model) to `config/models.py`
- C2: Move `CommitInfo`, `FileStatus`, `ModifiedFile` to `git/diff_models.py`
- C3: Move `ActionLog` and supporting types to `state/action_log.py` (~100 LOC)
- C4: Move `EnvFileSpec` to `config/models.py`
- C5: Define `RecoveryResult` dataclass in workflow, translate in API router
- C6: Define `TaskSubmitCallback` protocol for `UserManagedAgent`

**Key Issues:**
- Two distinct `NudgerConfig` classes exist (dataclass in runners, Pydantic in config) — naming collision risk
- `ActionLog` has 7 consumer files across db/, runners/, and tests/ — high update scope
- `UserManagedAgent` wiring unclear (not constructed in documented code path) — verification points at wrong file
- `db/migrations/env.py` imports moved types for Alembic table discovery (not in initial scope)

---

### Phase 1: Delete Dead Code

**Status:** Critical false assumptions, recoverable with fallback logic

**Key Issues:**
- OpenHands and Codex shim files have **many active consumers** (not "zero" as assumed)
  - `openhands.py`: 9 consumers (1 production, 8 tests)
  - `openhands_docker.py`: 2 consumers
  - `openhands_common.py`: 4 consumers
  - `codex_server.py`: 8 consumers
  - `codex_server_common.py`: 6 consumers
- Requires ~22 import path updates (1 production file + ~21 test files)
- `parsers/base.py` may contain real protocols used via `__getattr__` lazy loading — must audit before deletion
- Word boundary `\b` in grep patterns requires `-P` flag for Perl regex

**Resolution:** Step's fallback ("if consumers found, update them") handles this correctly — audit first, then update imports, then delete.

---

### Phase 2: Absorb cache/, review/, repos/ → git/

**Status:** Mechanically sound, one blocking prerequisite, one missing consumer

**Key Issues:**
- **BLOCKING:** `git/diff_models.py` does NOT exist in current codebase (Phase 0 artifact)
- **Missing:** `tests/unit/repos/test_discovery.py` not listed as consumer but will fail after deletion
- `BranchNotFoundError` naming collision at different import paths (`git.errors` vs `git.repos.errors`) — low risk, needs documentation
- Task 7's `git/ops/__init__.py` missing 7+ exports (`sync_branch_to_worktree`, `parse_conflict_blocks`, etc.)

**Resolution:** Add preflight check for Phase 0 completion; enumerate complete symbol list before writing `__init__.py`.

---

### Phase 3: Absorb routines/ → config/routines/

**Status:** Low-risk, documented accurately

**Key Issues:**
- Import count discrepancy (9 claimed vs 13 actual) — no functional impact
- `api/errors.py` location mislabeled as "in api/routers/" — documentation only
- `loader.py` imports from `config.models` (sibling) after move — confirmed safe, no circular import

**Resolution:** None required — step plan correctly handles all cases.

---

### Phase 4: Absorb artifacts/ → workflow/artifacts/

**Status:** Well-specified, 1 gap in intent vs implementation

**Key Issues:**
- Intent says `workflow/__init__.py` should re-export `Artifact` and `ArtifactRegistry` — not explicitly tasked
- Lazy import in `executor.py:826` correctly identified but won't be tested by existing test suite
- Need explicit verification that `context_from` path is exercised

**Resolution:** Add task to update `workflow/__init__.py` re-exports; verification gaps are acceptable given grep audit.

---

### Phase 5: Absorb metrics/ + mcp/ → api/

**Status:** Structurally sound, hidden ordering dependency

**Key Issues:**
- **HIDDEN DEPENDENCY:** Step claims independence from Step 2, but `mcp/tools.py` imports from `repos` which Step 2 moves
  - If Step 5 runs before Step 2: `api/mcp/tools.py` gets stale imports; Step 2 won't update the new copy
  - If executed sequentially (normal order): Works correctly by accident, not by design
- `time_utils` import not mentioned in Task 2
- `workflow.clarifications` import will move during Phase 7 — Step 7 must update `api/mcp/tools.py`

**Resolution:** Remove "independent" claim; add explicit prerequisite "Step 2 must complete first"; Step 7 must know to update `api/mcp/` paths.

---

### Phase 6: Absorb scaffolding/ + agents/ → runners/

**Status:** Two HIGH-severity issues, one design question

**Key Issues:**
- **CRITICAL:** `agents/schemas.py` imports `ApiModel` from `api/schemas.base` — violates stated layering constraint (runners must not import from api/)
- **CRITICAL:** `db/migrations/env.py` imports `orchestrator.agents.models` for Alembic table discovery — not in consumer list
- **CRITICAL:** `agents/__init__.py` is empty (only docstring) — mirroring it produces blank file
- Layering violation requires explicit fix: replace `ApiModel` with `pydantic.BaseModel` or move `ApiModel` to lower layer

**Resolution:** Before implementation, choose and document ApiModel fix; add `db/migrations/env.py` to consumer list explicitly.

---

### Phase 7: Restructure workflow/ Internals

**Status:** Multiple HIGH-severity specification gaps

**Key Issues:**
- `events/__init__.py` template lists 11 symbols; `events.py` actually exports 35 — missing 24 symbols including `ApprovalRequested`, `BufferingEmitter`
- `signals/__init__.py` missing `SignalQueue` and registry functions (`register_active_run`, `unregister_active_run`)
- `LoopAction` dataclass not moved with `NoTaskReason` in Task 6 — creates incomplete coupling fix
- Bridges (thin re-export files) may violate "zero shims" policy — design choice needs explicit documentation
- Task 7 must update `workflow/agent/summary_cache.py` (not just bridge file) for `DEFAULT_SUMMARIZE_MODEL` move

**Resolution:** Require explicit symbol audits before writing `__init__.py` files; explicitly move `LoopAction`; decide on bridge policy.

---

### Phase 8: Restructure db/ Internals

**Status:** One CRITICAL blocking issue, multiple coverage gaps

**Key Issues:**
- **CRITICAL:** `db/recovery.py` flat file and `db/recovery/` package directory cannot coexist — package shadows module immediately
  - Breaks 4 integration tests + 1 script + internal `journal_replay.py` when directory is created
  - Current instruction "don't delete until Task 8" is incompatible with the naming conflict
- Coverage gap: `scripts/` directory (3 files) callers not listed in Task 6
- Phase 6 dependency: If agents moved to `runners/profiles`, Task 6 tries to edit file at old path
- `migrations/env.py` imports both `db.base` and `agents.models` — Task 5 mentions only `db.base`
- Alembic version files have zero `orchestrator` imports — confirmed safe

**Resolution:** Restructure Task 3 — update all `orchestrator.db.recovery.*` callers first, then delete flat file and create directory atomically.

---

### Phase 9: Restructure runners/ Internals

**Status:** Low-risk, Phase 6 prerequisite not verified

**Key Issues:**
- Phase 6 prerequisite claim unchecked — `runners/scaffolding/` and `runners/profiles/` may not exist
- `runners/__init__.py` template may clobber Phase 6 re-exports if they exist
- `NudgerConfig` fallback import uses wrong path (`from orchestrator.runners import` instead of `from orchestrator.config.models import`)
- Docstring wording change could trigger pre-commit linting

**Resolution:** Add explicit Phase 6 prerequisite check; preserve existing docstring; fix fallback import path.

---

### Phase 10: Explicit __all__ + Interface Narrowing

**Status:** Highest complexity, multiple prerequisite gaps

**Key Issues:**
- Phase 7–9 prerequisite unchecked — `workflow/` may still be flat (no `engine/`, `events/`, `signals/` sub-packages)
- `RunWorkflow` location assumed wrong (`signals/runtime.py` vs actual `workflow/runtime.py`)
- 4 of 9 modules already have `__all__` — tasks frame as creation when they're edits
  - `config/__all__`: 26 symbols
  - `state/__all__`: 12 symbols (includes `generate_id`, which plan wants hidden)
  - `git/__all__`: 17 symbols
  - `workflow/__all__`: 37 symbols
- `generate_id` removal from `state/__all__` must be coordinated edit in existing `__all__`, not a new creation
- Empty modules (db, envfiles, runners, api, cli) need imports added before `__all__` can be declared
- 8 backward-compat shims in `runners/` may still exist (Phase 1 responsibility)
- 6 test files import `check_step_progression`/`check_run_completion` directly — all must be updated

**Resolution:** Gate on Phase 7–9 completion; treat all existing `__all__` as edits not creations; audit wildcard shims; explicitly enumerate files needing updates.

---

## Persistence Mapping Audit

**Status:** No new state fields introduced in this consolidation

All phases are structural (file moves, import updates, module reorganization). No new database tables, ORM models, or persistent state fields are added or modified. Alembic migrations are unchanged except for import path updates in `env.py`.

**Affected Files:**
- `src/orchestrator/db/migrations/env.py` — import path updates only
- All other files — no schema changes

---

## Failure Mode Analysis (Consolidated Table)

| Phase | ID | Severity | Failure Mode | Likelihood | Hardening Action |
|-------|----|-----------| ------------|------------|-----------------|
| 0 | FM1 | MEDIUM | Two `NudgerConfig` classes with same name; collision risk in `global_config.py` | Medium | Explicitly document both classes; use aliases in `global_config.py` |
| 0 | FM2 | MEDIUM | Missed consumer `runners/agents/claude_cli/factory.py` | Medium | Add explicitly to update list |
| 0 | FM3 | LOW | Wrong type descriptor (`NudgerConfig` is `@dataclass`, not Pydantic model) | Low | Correct descriptor in step description |
| 1 | FM4 | HIGH | OpenHands/Codex shim files have many active consumers, not "zero" | High | Audit first, update imports, then delete; expect ~22 file updates |
| 1 | FM5 | MEDIUM | `parsers/base.py` may contain real protocols used via lazy loader | Medium | Read file; grep for protocol usage; move if needed |
| 1 | FM6 | LOW | Word boundary `\b` in grep requires `-P` flag in BRE | Low | Add `-P` flag to grep commands |
| 2 | FM7 | BLOCKING | `git/diff_models.py` doesn't exist; Phase 0 must complete first | High | Add preflight check for Phase 0 artifact |
| 2 | FM8 | MEDIUM | `tests/unit/repos/test_discovery.py` not in consumer list | Medium | Add explicitly to Task 3 update list |
| 2 | FM9 | LOW | `BranchNotFoundError` naming collision at different paths | Low | Document distinction; no code change needed |
| 4 | FM10 | LOW | Lazy import in `executor.py:826` won't be tested by known tests | Low | Verify `context_from` test path exists; grep audit sufficient |
| 5 | FM11 | HIGH | Hidden dependency: Step 5 must run after Step 2 (mcp/tools.py imports from repos) | High | Remove "independent" claim; add explicit prerequisite |
| 5 | FM12 | LOW | Step 7 must update `api/mcp/tools.py` for workflow import moves | Low | Flag in Step 7 plan |
| 6 | FM13 | HIGH | `agents/schemas.py` imports `ApiModel` from api/ — violates layering constraint | High | Choose fix: replace `ApiModel` with `BaseModel` OR move `ApiModel` to config/ |
| 6 | FM14 | CRITICAL | `db/migrations/env.py` imports `orchestrator.agents.models` for Alembic — not in consumer list | High | Add explicitly to Task 4 update list |
| 6 | FM15 | MEDIUM | `agents/__init__.py` is empty — mirroring produces blank exports | Medium | Specify explicit exports for `runners/profiles/__init__.py` |
| 7 | FM16 | HIGH | `events/__init__.py` template missing 24+ symbols (35 actual vs 11 template) | High | Audit before writing; include all symbols from `events.py` |
| 7 | FM17 | HIGH | `signals/__init__.py` missing `SignalQueue` and registry functions | High | Audit before writing; include all imported symbols |
| 7 | FM18 | HIGH | `LoopAction` not moved with `NoTaskReason` — incomplete coupling fix | High | Explicitly move `LoopAction` to `workflow/signals/runtime.py` |
| 7 | FM19 | MEDIUM | Bridges (re-export files) may violate "zero shims" policy | Medium | Decide explicitly: update all external callers OR keep bridges documented as intra-module |
| 7 | FM20 | MEDIUM | Task 7 must update canonical `workflow/agent/summary_cache.py`, not bridge | Medium | Explicitly target new sub-package file, not workflow root |
| 8 | FM21 | CRITICAL | `db/recovery.py` and `db/recovery/` cannot coexist — package shadows flat file immediately | Critical | Delete flat file atomically when creating directory; update all consumers first |
| 8 | FM22 | HIGH | `scripts/` directory (3 files) callers not in Task 6 consumer list | High | Add scripts/restore_from_journal.py, scripts/seed_db.py, scripts/worker.py |
| 8 | FM23 | HIGH | Phase 6 dependency: `src/orchestrator/agents/models.py` may have moved to `runners/profiles/models.py` | High | Add conditional: if Phase 6 ran, update agents import path |
| 8 | FM24 | MEDIUM | `migrations/env.py` imports both `db.base` and `agents.models` — Task 5 only mentions `db.base` | Medium | Add agents import update to Task 5 if Phase 6 ran first |
| 9 | FM25 | MEDIUM | Phase 6 prerequisite unchecked — `runners/scaffolding/` and `runners/profiles/` may not exist | Medium | Add explicit check at Task 1 start |
| 9 | FM26 | MEDIUM | `runners/__init__.py` template may clobber Phase 6 re-exports | Medium | Read current file first; merge Phase 6 content |
| 9 | FM27 | LOW | Fallback import for `NudgerConfig` uses wrong path | Low | Change to `from orchestrator.config.models import NudgerConfig` |
| 9 | FM28 | LOW | Docstring wording change in `runners/__init__.py` may trigger linting | Low | Preserve existing docstring |
| 10 | FM29 | BLOCKING | Phase 7–9 prerequisite unchecked — workflow may still be flat | Critical | Gate on Phase 7 completion; verify `NoTaskReason` exists in workflow |
| 10 | FM30 | HIGH | `RunWorkflow` location assumed wrong (`signals/runtime.py` vs `workflow/runtime.py`) | High | Audit before attempting rename |
| 10 | FM31 | HIGH | 4 modules already have `__all__` — tasks frame as creation not edit | High | Read current `__all__`; produce diff showing additions/removals |
| 10 | FM32 | MEDIUM | `generate_id` already in `state/__all__` — must remove, not create new | Medium | Edit existing `__all__`, don't recreate |
| 10 | FM33 | MEDIUM | Empty modules need imports added before `__all__` declarations | Medium | Audit callers; add re-exports; then declare `__all__` |
| 10 | FM34 | MEDIUM | 8 backward-compat shims in `runners/` may still exist (Phase 1 incomplete) | Medium | Check if Phase 1 completed; don't include shim symbols in `runners/__all__` |
| 10 | FM35 | MEDIUM | 6 test files import `check_step_progression`/`check_run_completion` directly | Medium | Enumerate all files; update or document explicit imports |

---

## Cross-Step Risk Synthesis

### Critical Dependency Chain

```
Phase 0 (coupling fixes)
  ↓ required for
Phase 1 (dead code deletion)
  ↓ required for
Phase 2 (module absorptions: cache/review/repos → git)
  ↓ required for
Phase 5 (metrics/mcp → api, depends on Step 2 for repos imports)
  ↓ AND
Phase 3 (routines → config)
Phase 4 (artifacts → workflow)
Phase 6 (scaffolding/agents → runners)
  ↓ required for
Phases 7–10 (internal restructuring + interface narrowing)
```

**Execution order is critical:** Steps 0→1→2 must complete before 3–6. Steps 3–6 can proceed in parallel after 2. Steps 7–10 require all of 0–6 complete first.

### Phase Ordering Violations Found

| Violation | Phases | Impact |
|-----------|--------|--------|
| Phase 5 claims independence from Phase 2, but has hidden dependency | 2 ↔ 5 | If executed out of order, `api/mcp/tools.py` gets stale imports |
| Phase 7–10 assume Phases 0–6 complete, but don't verify | 0–6 → 7–10 | Must gate Phase 7 execution on Phase 6 completion |
| Phase 6 assumes Phase 0 (C6 coupling) is complete | 0 → 6 | UserManagedAgent protocol fix required |
| Phase 8 has internal ordering conflict within itself (recovery.py naming) | 8 internal | Must restructure Task 3 to avoid file shadowing |

### Cross-Module Coupling Risks After All Phases

| Coupling | Current Status | Phase Fix | Residual Risk |
|----------|---|---|---|
| `runners/` → `api/` (ConnectionManager type annotation) | Phase 10 defines `BroadcastCallback` protocol | Still TYPE_CHECKING import; only annotation change | LOW — runtime decoupled via DI |
| `runners/` → `workflow/` (NoTaskReason, LoopAction) | Phase 7 moves to workflow/signals | Still low-level import; no circular risk | LOW — one-way dependency |
| `runners/` → `config/` (NudgerConfig) | Phase 0 moves to config/models | Resolves Foundation→Execution coupling | RESOLVED |
| `workflow/` → `api/` (artifact registry lazy import) | Phase 4 move isolates to workflow/artifacts | Still internal; no external coupling | RESOLVED |

### Hardening Gaps Across Phases

| Gap | Phases Affected | Mitigation |
|-----|---|---|
| No explicit prerequisite gating between phase groups | 0→1→2 and 7→10 | Add `test -d /path/exists || exit 1` checks at phase start |
| Consumer list incomplete across multiple phases | 1, 2, 6, 8 | Run `grep -r` audit before each phase; enumerate ALL consumers explicitly |
| Backward-compat shims may survive (Phase 1 not done) | All phases import from runners | Gate Phase 9+ on Phase 1 completion; verify zero shim imports |
| Symbol inventory audits done post-hoc, not pre-implementation | 7, 10 | Require grep output before writing any `__init__.py` files |
| Import path updates in tests may be missed | 1, 2, 3, 5, 6, 8, 9 | Add `tests/` to all grep audits; update conftest files explicitly |

---

## Recommended Plan Changes

### Critical Changes (Blocking Issues)

1. **Phase 0**: Add explicit note that there are TWO `NudgerConfig` classes — update clarifications.md or step documentation with full disambiguation

2. **Phase 1**: Remove "Expected: zero consumers" annotation from OpenHands/Codex tasks; replace with "Verify consumers via grep, update all callers before deletion"

3. **Phase 5**: Remove "independent of all other phases" claim; add explicit "Phase 2 must complete before Phase 5"

4. **Phase 6, Task 4**: Add `src/orchestrator/db/migrations/env.py` explicitly to consumer list with note about Alembic table discovery

5. **Phase 6, Task 2**: Specify explicit fix for `agents/schemas.py` ApiModel import:
   - Option A: Replace `from orchestrator.api.schemas.base import ApiModel` with `from pydantic import BaseModel as ApiModel`
   - Option B: Move `ApiModel` to `config/schemas.py` or `api/shared_models.py` as lower-layer export

6. **Phase 7, Task 3**: Before writing `events/__init__.py`, run comprehensive audit:
   ```bash
   grep "^class \|^[A-Z][A-Z_]* =" src/orchestrator/workflow/events.py | sort
   ```
   Use output to enumerate complete symbol list; template is incomplete

7. **Phase 7, Task 4**: Before writing `signals/__init__.py`, run audit for all imported symbols (includes `SignalQueue`, registry functions)

8. **Phase 7, Task 6**: Explicitly move `LoopAction` dataclass along with `NoTaskReason`; update all import paths

9. **Phase 8, Task 3**: Restructure to avoid naming conflict — either:
   - Delete `db/recovery.py` immediately when creating directory, OR
   - Populate `db/recovery/__init__.py` with full re-exports at creation time

10. **Phase 10**: Gate execution on Phase 7–9 completion verification:
    ```bash
    test -d src/orchestrator/workflow/engine || { echo "STOP: Phase 7 incomplete"; exit 1; }
    ```

### High-Priority Changes (Implementation Guidance)

11. **Phase 2**: Add `tests/unit/repos/test_discovery.py` explicitly to Task 3 consumer list

12. **Phase 3–6**: Clarify that all import-path edits in conftest files must be included; add explicit grep for conftest imports

13. **Phase 7**: Decide bridge policy upfront — document whether intra-module re-export bridges are acceptable or if all external callers must be updated to canonical paths

14. **Phase 8**: Expand Task 6 to explicitly list `scripts/` directory (3 files: restore_from_journal.py, seed_db.py, worker.py)

15. **Phase 8, Task 5**: Add conditional: "If Phase 6 has run, update `import orchestrator.agents.models` → `import orchestrator.runners.profiles.models`"

16. **Phase 9**: Add Phase 6 prerequisite check at Task 1 start; verify `runners/scaffolding/` and `runners/profiles/` exist

17. **Phase 10, All Tasks**: Change language from "add `__all__`" to "create or update `__all__`"; explicitly read existing `__all__` before writing

18. **Phase 10, Task 6**: Clarify that `generate_id` removal is an EDIT to existing `state/__all__`, not creation of new one

19. **Phase 10, Task 8**: Decide scope: is removing symbols from `__all__` also removing them from `__init__.py` re-exports? Document (a) `__all__` only vs (b) also remove re-export

### Lower-Priority Changes (Documentation/Clarity)

20. **All phases**: Add explicit note in step documentation: "Phases are ordered by dependency. Attempting out-of-order execution will cause import failures. Run phases 0→1→2→(3–6 in any order)→7→8→9→10."

21. **All phases**: Replace generic "run full test suite" with explicit test command and known failure list (e.g., "2 openhands module failures expected")

22. **Phase 0, 6, 7, 8**: Add section on "Verification checkpoint: no circular imports" with concrete commands

23. **Phase 10**: Add post-completion integration test: verify that `from orchestrator.<module> import *` works for all 9 modules and that `__all__` accurately reflects what's importable

---

## Implementation Confidence Assessment

| Phase | Confidence | Notes |
|-------|-----------|-------|
| 0 | MEDIUM | Well-designed but many edge cases; tight coupling of fixes |
| 1 | LOW-MEDIUM | Many more consumers than expected; requires careful audit |
| 2 | MEDIUM | Blocking Phase 0; missing one consumer; incomplete exports |
| 3 | HIGH | Straightforward move; low-risk |
| 4 | HIGH | Mechanical, well-specified, low complexity |
| 5 | MEDIUM | Hidden dependency on Phase 2; must be documented |
| 6 | LOW | ApiModel layering violation; missing Alembic consumer |
| 7 | LOW | Symbol audits missing; bridges policy unclear; LoopAction incomplete |
| 8 | LOW | Critical naming conflict; must restructure Task 3 |
| 9 | MEDIUM | Phase 6 prerequisite unchecked; preserving existing content required |
| 10 | LOW | Multiple prerequisites unchecked; existing `__all__` may be clobbered; 6 test files need updates |

**Overall:** Phases 0–6 (40%) confidence; Phases 7–10 (20% confidence). Implementation feasible with hardening actions applied.

---

## Key Assumptions Requiring Verification

Before execution begins, verify:

1. ✓ No other changes to `src/orchestrator/` between now and execution start
2. ✓ All test files at expected locations (no major test refactors since this plan was written)
3. ✓ Alembic migrations in `src/orchestrator/db/migrations/` have structure described (versions, env.py)
4. ✓ No external packages or scripts depend on backward-compat shim imports (e.g., `orchestrator.runners.openhands`)
5. ✓ `git worktree` is used for execution; main project DB (`orchestrator.db`) is never touched
6. ✓ Phases executed sequentially in order 0→10; no parallel execution
7. ✓ Pre-commit hooks in place and passing before starting Phase 0

---

## Next Steps for Execution

1. **Before Phase 0:** Apply all hardening actions from this analysis
2. **Before each phase:** Run prerequisite checks and pre-flight audits specified in hardening actions
3. **During each phase:** Stop and escalate if any verification step fails (don't suppress errors)
4. **After each phase:** Commit changes and tag commit with phase number
5. **After Phase 10:** Review consolidated `__all__` declarations across all 9 modules; document public interfaces

---

**End of Consolidated Dry-Run Analysis**
