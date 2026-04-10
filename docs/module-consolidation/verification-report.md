# Verification Report: Module Consolidation Plan Alignment

**Generated:** 2026-03-23
**Scope:** Cross-check of intent → plan → step files → dry-run notes for mutual consistency and execution readiness.

---

## Overall Status: ✓ Ready

All critical and high-severity dry-run gaps have been applied to step files. No unresolved critical conflicts remain.

---

## R1: Step Files Align with Plan and Intent

**Status: ✓ Pass**

All 11 step files (step-00 through step-10) are present under `docs/module-consolidation/`. Each step file:
- References its corresponding phase in `plan.md`
- Has an Intent Verification section with final verification criteria
- Produces outcomes consistent with the intent document's "Definition of Complete"
- Is ordered to match the documented dependency chain (0→1→2→(3–6)→7→8→9→10)

**Phase ordering (FM11 fixed):** `step-05-plan.md` now explicitly states "Prerequisite: Step 2 (`cache/review/repos → git`) must be complete before this step" with the rationale that `mcp/tools.py` imports from `orchestrator.repos`. The "independent of all other phases" claim has been replaced with the accurate dependency. The footer reference also updated to "Depends on: Step 2."

**Task ordering (FM21 fixed):** `step-08-plan.md` Task 4 now describes the atomic directory-creation approach: populate `db/recovery/__init__.py` with full re-exports at creation time, so the new package directory is a functional replacement before the flat file is deleted. No broken import window remains.

---

## R2: All Critical/Significant Dry-Run Gaps Applied to Step Files

**Status: ✓ Pass** — All 6 previously-failing critical/high gaps are now applied.

The dry-run analysis (`dry-run-notes.md`) identifies 35 failure modes. The table below covers all CRITICAL, BLOCKING, and HIGH severity gaps:

| FM | Severity | Phase | Gap Description | Applied to Step File? | Notes |
|----|----------|-------|-----------------|----------------------|-------|
| FM4 | HIGH | 1 | OpenHands/Codex shims have ~22 active consumers | ✓ YES | Step-01 Tasks 4–5 have "if consumers found, update them" fallback |
| FM7 | HIGH | 2 | `git/diff_models.py` does not exist until Phase 0 completes | ✓ YES | Step-02 Task 4 has explicit Phase 0 preflight check |
| FM11 | HIGH | 5 | Hidden dependency: Step 5 must run after Step 2 | ✓ YES | **Fixed:** step-05-plan.md Prerequisites now explicitly requires Step 2 completion; footer updated to "Depends on: Step 2" |
| FM13 | HIGH | 6 | `agents/schemas.py` imports `ApiModel` from `api/schemas.base` — violates layering | ✓ YES | **Fixed:** step-06-plan.md Task 5 now includes explicit LAYERING FIX instruction: replace `from orchestrator.api.schemas.base import ApiModel` with `from pydantic import BaseModel as ApiModel` |
| FM14 | CRITICAL | 6 | `db/migrations/env.py` imports `orchestrator.agents.models` for Alembic | ✓ YES | **Fixed:** step-06-plan.md Task 6 now pre-lists `db/migrations/env.py` as a known consumer with explicit grep verification command |
| FM16 | HIGH | 7 | `events/__init__.py` template missing 24+ symbols (35 actual vs 11 template) | ✓ YES | Step-07 Task 3 instructs explicit audit with grep before writing `__init__.py` |
| FM17 | HIGH | 7 | `signals/__init__.py` missing `SignalQueue` and registry functions | ✓ YES | Step-07 Task 4 now has "audit with grep first" directive equivalent to Task 3 |
| FM18 | HIGH | 7 | `LoopAction` not moved with `NoTaskReason` — incomplete coupling fix | ✓ YES | Step-07 Task 6 explicitly moves `LoopAction` to `workflow/signals/runtime.py` |
| FM21 | CRITICAL | 8 | `db/recovery.py` and `db/recovery/` cannot coexist — package shadows flat file immediately | ✓ YES | **Fixed:** step-08-plan.md Task 4 now requires populating `db/recovery/__init__.py` with full re-exports at creation time; explicit 5-step sequence provided; flat file deletion only after package is verified functional |
| FM22 | HIGH | 8 | `scripts/` directory callers (restore_from_journal.py, seed_db.py, worker.py) not in Task 6 consumer list | ✓ YES | **Fixed:** step-08-plan.md Task 7 now explicitly lists all three scripts/ files with verification grep command |
| FM23 | HIGH | 8 | Phase 6 moves `agents/models.py` to `runners/profiles/models.py`; Step 8 Task 6 still lists old path | ✓ YES | **Fixed:** step-08-plan.md Task 7 now includes conditional: "If Phase 6 has already run, `agents/models.py` will be at `runners/profiles/models.py`" with detection command |
| FM24 | MEDIUM | 8 | `migrations/env.py` imports both `db.base` AND `agents.models`; Task 5 only updates `db.base` | ✓ YES | **Fixed:** step-08-plan.md Task 8 now explicitly covers both `orchestrator.db.base` and `orchestrator.agents.models` Alembic imports with grep verification command |
| FM29 | BLOCKING | 10 | Phase 7–9 prerequisite unchecked before Phase 10 executes | ✓ YES | Step-10 intro documents dependency; Task 1 includes gate-check command |
| FM30 | HIGH | 10 | `RunWorkflow` location assumed wrong | ✓ YES | Step-10 Task 5 audits with grep before acting |
| FM31 | HIGH | 10 | 4 modules already have `__all__` — tasks frame as creation not edit | ✓ YES | Step-10 Tasks 6–9 all have "Read … to see current exports" before writing, which prevents clobbering; templates are illustrative |

---

## R3: No Unresolved Critical Conflicts

**Status: ✓ Pass** — Both previously-failing CRITICAL conflicts are now resolved in step files.

| Conflict | Phase | Description | Step File Status |
|----------|-------|-------------|-----------------|
| FM21 | 8 | `db/recovery.py` + `db/recovery/` coexistence breaks all `from orchestrator.db.recovery import X` calls | **RESOLVED** — step-08-plan.md Task 4 now specifies: populate `db/recovery/__init__.py` with full re-exports at creation time; explicit 5-step sequence ensures no broken import window; flat file deletion is gated on package verification |
| FM14+FM24 | 6+8 | `db/migrations/env.py` Alembic import of `orchestrator.agents.models` — if not updated, Alembic migrations fail post-Phase-6 | **RESOLVED** — step-06-plan.md Task 6 pre-lists `db/migrations/env.py` as a known consumer requiring update during Phase 6; step-08-plan.md Task 8 covers the same file for the `db.base` path update; FM23 conditional in Task 7 handles path changes from Phase 6 execution order |

**FM21 resolution detail:** The atomic approach requires:
1. Read all public symbols from flat `db/recovery.py`
2. Create `db/recovery/` directory + content files
3. Write `db/recovery/__init__.py` with full re-exports simultaneously
4. Verify imports work: `python -c "from orchestrator.db.recovery import replay_events; print('ok')"`
5. Only then delete the flat `db/recovery.py`

This eliminates the broken import window that would occur if a blank `__init__.py` were created first.

---

## R4: Persistence Mapping Audit

**Status: ✓ N/A — No New State Fields**

As documented in `dry-run-notes.md` (§ Persistence Mapping Audit):

> All phases are structural (file moves, import updates, module reorganization). No new database tables, ORM models, or persistent state fields are added or modified.

The only persistence-adjacent change is import path updates in `src/orchestrator/db/migrations/env.py` — these are mechanical path replacements with no schema changes. No persistence mapping table is required, and no cells are MISSING.

---

## R5: Integration Test Step Files Specify Assertion Logic

**Status: ✓ Pass**

Each step file that involves test verification uses concrete assertion commands (grep counts, pytest invocations, Python import smoke tests), not just scenario names. Examples:

- Step-01 Task 6 Final Verification: `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0 + explicit grep commands per deleted path
- Step-02 Task 8: Six specific grep commands that must return zero results + directory existence checks
- Step-06 Task 6: Explicit circular-import grep checks + `ls` directory verification
- Step-08 Task 9: `uv run python -c "from orchestrator.db import RunModel, init_db, RunRepository, EventStore, replay_events; print('ok')"` + `ls src/orchestrator/db/*.py` showing only `__init__.py`

No step file says "test budget exhaustion" or uses vague scenario language without specifying the assertion. All integration test verification criteria meet the assertion-logic standard.

---

## Summary of Changes Applied to Step Files

| Step File | Task | Change Made |
|-----------|------|-------------|
| `step-05-plan.md` | Prerequisites | Replaced "None — this phase is independent" with explicit Step 2 prerequisite and rationale (FM11) |
| `step-05-plan.md` | Footer | Changed "Independent of: All other phases" to "Depends on: Step 2" with explanation (FM11) |
| `step-06-plan.md` | Task 5 | Added LAYERING FIX block: replace `ApiModel` from `api/schemas.base` with `pydantic.BaseModel` alias (FM13) |
| `step-06-plan.md` | Task 6 | Pre-listed `db/migrations/env.py` as known consumer with grep command (FM14) |
| `step-08-plan.md` | Task 4 | Added CRITICAL note explaining `recovery.py`/`recovery/` coexistence issue; specified 5-step atomic creation sequence (FM21) |
| `step-08-plan.md` | Task 7 | Added scripts/ consumer list (restore_from_journal.py, seed_db.py, worker.py) with grep command (FM22); added conditional for Phase 6 path change with detection command (FM23) |
| `step-08-plan.md` | Task 8 | Added FM24 block covering both `db.base` and `agents.models` Alembic imports; added grep verification command (FM24) |

---

*End of verification report*
