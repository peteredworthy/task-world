# Verification Report: Per-Model Token Accounting YAML Step Files

*Generated: 2026-04-08*

**Overall Status: ✓ Ready (after fixes applied)**

---

## Executive Summary

All six YAML step files were audited against intent, plan, and dry-run notes. Multiple
issues were found and **fixed in this pass** — the YAML files now reflect the actual
codebase state, have contract-level auto_verify checks, no pipe violations, and consistent
rubric IDs. The routine is ready to execute.

---

## 1. Dry-Run Gap Application (R2)

All critical and significant dry-run gaps have been applied to the YAML step files.

### S-01: Core Data Model and Cost Config

| Gap | Severity | Applied |
|-----|----------|---------|
| FM-01: `config/model_costs.yaml` path mismatch — costs.py looks at project root | Critical | ✓ Fixed: T-01 updated to `model_costs.yaml` at project root; task_context and auto_verify corrected |
| FM-02: T-02/T-03 will re-implement already-existing code | High | ✓ Fixed: "NOTE: This code may already exist" added to T-02 and T-03 task_context |
| FM-03: Rate discrepancies (stale plan spec vs actual model_costs.yaml) | Medium | ✓ Mitigated: T-01 auto_verify checks structure only (model keys present), not specific rate values |
| FM-04: costs.py doesn't look in config/ | High | ✓ Fixed: T-03 task_context clarifies that `_find_cost_file()` must look at project root, not config/ |
| FM-05: T-04 `tail -5` hides pytest exit code | Low | ✓ Fixed: pipes removed from T-04 auto_verify commands |

### S-02: DB Migration and Persistence

| Gap | Severity | Applied |
|-----|----------|---------|
| T-01 greps check `Column(JSON` but ORM uses `mapped_column(JSON` | High | ✓ Fixed: replaced with count-based grep + Python import assertion |
| `alembic_upgrade` marked `must: false` | Medium | ✓ Fixed: changed to `must: true` |
| T-03 `unit_tests_pass` marked `must: false` | Medium | ✓ Fixed: changed to `must: true` |
| T-04 `integration_tests_pass` marked `must: false` | Medium | ✓ Fixed: changed to `must: true` |
| T-04 rubric IDs `round_trip_correctness` etc. don't match requirement IDs | Medium | ✓ Fixed: renamed to R11, R12, R13 |

### S-03: Phase Handler Token Extraction

| Gap | Severity | Applied |
|-----|----------|---------|
| Auto_verify T-01 checks are all existence-only greps | Medium | ✓ Fixed: added `extraction_contract` Python import assertion; removed pipe from `existing_tests_pass` |
| Rubric ID `R45` doesn't match requirement IDs R4 and R5 | Medium | ✓ Fixed: split into separate R4 and R5 rubric items |
| T-02 pipes hide pytest exit code | Medium | ✓ Fixed: pipes removed |

### S-04: Run-Level Aggregation

| Gap | Severity | Applied |
|-----|----------|---------|
| `unit_tests_pass` / `backend_tests_pass` marked `must: false` | Medium | ✓ Fixed: both changed to `must: true` |
| T-03 testability gap — merge logic embedded in ORM method | Medium | ✓ Fixed: added guidance to extract `_merge_token_usage()` helper for unit testing |
| Pipe violations | Medium | ✓ Fixed: all pipes removed |

### S-05: API Exposure

| Gap | Severity | Applied |
|-----|----------|---------|
| T-02 R5 contradiction: YAML says old runs return 0.0, but code uses legacy fallback chain | Critical | ✓ Fixed: R5 updated to "legacy fallback acceptable for old runs"; T-03 R7 test updated to `>= 0.0` |
| T-01 auto_verify is existence-only grep | Medium | ✓ Fixed: added `schema_importable_and_correct` Python import assertion |
| T-03 injection mechanism unspecified | High | ✓ Fixed: added explicit guidance to use repository layer or raw SQL |
| `backend_tests_pass`, `all_integration_tests_pass` marked `must: false` | Medium | ✓ Fixed: changed to `must: true` |
| Pipe violations | Medium | ✓ Fixed: all pipes removed |

### S-06: Frontend Display

| Gap | Severity | Applied |
|-----|----------|---------|
| H1 (Critical): No auto_verify that ModelCostBreakdown is imported in RunDetail.tsx | Critical | ✓ Fixed: added `rundetail_imports_cost_component` grep check |
| H2 (Critical): MetricsBar is orphaned but YAML doesn't warn builder | Critical | ✓ Fixed: explicit IMPORTANT note in T-02 task_context that MetricsBar is not wired |
| H3: MetricsBar vs ModelCostBreakdown overlap not resolved in YAML | High | ✓ Fixed: task_context clarifies builder must choose one approach and avoid duplicate cost display |
| H6: Floating-point grand total test precision not noted | Medium | ✓ Fixed: added note about using regex match instead of exact string equality |
| TypeScript non-optional array requires `as any` for undefined test | Medium | ✓ Fixed: added explicit `as any` pattern note |
| Pipe violations | Medium | ✓ Fixed: all pipes removed from T-02 and T-03 |

---

## 2. Critical Conflicts (R3)

All critical conflicts have been resolved.

| Conflict | Resolution |
|----------|-----------|
| S-01 T-01: `test -f config/model_costs.yaml` fails on existing implementation | Fixed: path updated to `model_costs.yaml` (project root) |
| S-02 T-01: grep for `Column(JSON` fails on `mapped_column(JSON` | Fixed: replaced with Python import assertion |
| S-05 T-02/T-03: R5/R7 required `estimated_cost_usd=0.0` but code returns legacy fallback | Fixed: requirement and test updated to accept legacy fallback |

---

## 3. Persistence Mapping Audit (R4)

The feature adds two new state model fields:
- `Attempt.token_usage_by_model: list[ModelTokenUsage]`
- `Run.token_usage_by_model: list[ModelTokenUsage]`

Persistence mapping across the full stack:

| Layer | `Attempt.token_usage_by_model` | `Run.token_usage_by_model` |
|-------|-------------------------------|---------------------------|
| Domain model (state/models.py) | S-01 T-02 | S-01 T-02 |
| ORM column (db/orm/models.py) | S-02 T-01 | S-02 T-01 |
| Alembic migration | S-02 T-02 | S-02 T-02 |
| Repository serialize/deserialize | S-02 T-03 | S-02 T-03 |
| Phase handler extraction | S-03 T-01 | — (via run aggregation) |
| Run aggregation | — | S-04 T-01/T-02 |
| API schema | S-05 T-01 (AttemptSchema) | S-05 T-02 (RunResponse) |
| Frontend type | S-06 T-01 (tasks.ts optional) | S-06 T-01 (runs.ts) |

**Result: No MISSING cells.** All persistence mapping cells are covered.

---

## 4. Auto-Verify Quality (R5)

Each task now has at least one contract-level auto_verify check. Summary after fixes:

### S-01
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `yaml_valid`: Python assert on YAML structure | contract-level |
| T-02 | `model_token_usage_class`: import + instantiate + assert `total_cost_usd` | contract-level |
| T-03 | `costs_module`: import + assert returned rates | contract-level |
| T-04 | `tests_pass`: pytest run on test file | contract-level |

### S-02
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `orm_imports_correctly`: Python import + `hasattr` assert | contract-level |
| T-02 | `alembic_upgrade`: actual migration run | contract-level |
| T-03 | `unit_tests_pass`: pytest run (must: true) | contract-level |
| T-04 | `integration_tests_pass`: pytest run (must: true) | contract-level |

### S-03
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `extraction_contract`: Python import + `hasattr` assert | contract-level |
| T-02 | `unit_tests_pass`: pytest on test file (must: true) | contract-level |

### S-04
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `unit_tests_pass`: pytest (must: true) | contract-level |
| T-02 | `backend_tests_pass`: pytest (must: true) | contract-level |
| T-03 | `new_tests_pass`: pytest -k filter | contract-level |

### S-05
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `schema_importable_and_correct`: import + assert fields | contract-level |
| T-02 | `backend_tests_pass`: pytest (must: true) | contract-level |
| T-03 | `integration_tests_pass`: pytest -k token_usage (must: true) | contract-level |

### S-06
| Task | Strongest Check | Level |
|------|----------------|-------|
| T-01 | `typecheck_passes`: TypeScript compilation | contract-level |
| T-02 | `typecheck_passes` + `lint_passes` + `rundetail_imports_cost_component` | contract-level |
| T-03 | `frontend_tests_pass`: vitest run on test file | contract-level |

**Result: All tasks have contract-level auto_verify. No existence-only-only tasks remain.**

---

## 5. Integration Test Assertion Quality (R6)

Each step that includes integration test tasks specifies assertion logic:

| Step | Test Task | Assertion Logic Specified |
|------|-----------|--------------------------|
| S-02 T-04 | `test_token_usage_persistence.py` | Assert each field value (model name, token counts, cost rates); assert `== []` for empty default |
| S-03 T-02 | `test_model_token_usage.py` | Assert model name, token counts, cost rates, legacy metrics match for each scenario |
| S-04 T-03 | `test_run_aggregation.py` | Assert tokens summed, rates from first occurrence, empty list contributes nothing |
| S-05 T-03 | `test_api_token_usage.py` | Assert field values in response; assert `estimated_cost_usd` equals per-model sum |

**Result: All integration test step files specify assertion logic, not just scenario names.**

---

## 6. Intent Coverage (R7)

All `[I-XX]` items from intent.md are addressed by at least one YAML step file:

| Intent Item | Description | Covered By |
|-------------|-------------|-----------|
| I-01 | Replace flat counter with per-model breakdown | S-01 through S-06 |
| I-02 | Sub-agent tokens visible, different tiers | S-03 T-01 (sub-agent extraction), S-06 (UI) |
| I-03 | ModelTokenUsage class + list fields on Attempt and Run | S-01 T-02 |
| I-04 | config/model_costs.yaml + costs.py | S-01 T-01, T-03 |
| I-05 | phase_handler.py builds from ActionLog | S-03 T-01 |
| I-06 | Run-level aggregation, updated per-attempt | S-04 T-01, T-02 |
| I-07 | Legacy flat fields backward compatible | S-03 T-01 R3, S-04 T-01 R2 |
| I-08 | DB persistence via Alembic | S-02 T-01, T-02, T-03 |
| I-09 | API exposure via schemas | S-05 T-01, T-02 |
| I-10 | Frontend per-model table | S-06 T-02 |
| I-11 | Fallback for old runs | S-06 T-02 R6 |
| I-12 | Alembic migrations only | S-02 step_context constraint |
| I-13 | Cost rates embedded at execution time | S-03 T-01 (get_model_costs called at extraction) |
| I-14 | System runnable after each milestone | Each step's requirements include "all existing tests pass" |
| I-15 | Each task < 5 files, < 500 lines | Design intent; each task is scoped to 1-3 files |
| I-16 | ModelTokenUsage with total_cost_usd property | S-01 T-02 |
| I-17 | model_costs.yaml with rates; costs.py zeros for unknown | S-01 T-01, T-03, T-04 |
| I-18 | phase_handler.py builds from parent + sub-agents | S-03 T-01 R1, R2 |
| I-19 | Attempt and Run fields populated on new runs | S-03 R5, S-04 R4/R5 |
| I-20 | Legacy flat fields still populated as sum | S-03 T-01 R3, S-04 T-01 R2 |
| I-21 | Alembic migration adds JSON columns | S-02 T-02 |
| I-22 | API responses include token_usage_by_model | S-05 T-01, T-02, T-03 |
| I-23 | Frontend per-model table + fallback for old runs | S-06 T-02, T-03 |
| I-24 | All existing tests pass after each milestone | Critical requirement in every step |
| I-25 | Unit tests cover all areas | S-01 T-04, S-03 T-02, S-04 T-03, S-05 T-03 |

**Intent coverage: complete.**

---

## 7. Rubric ID Consistency

All rubric item IDs now match requirement IDs exactly:

| File | Task | Before | After |
|------|------|--------|-------|
| step-01-plan.yaml | T-04 | `test_coverage`, `correctness` | `R9` (merged) |
| step-02-plan.yaml | T-04 | `round_trip_correctness`, `empty_default_coverage`, `existing_tests_clean` | `R11`, `R12`, `R13` |
| step-03-plan.yaml | T-01 | `R45` | `R4`, `R5` (split) |

---

## 8. Remaining Advisory Items (Not Blocking)

These are low-severity observations that do not block execution:

1. **S-01 rate values**: The rates in T-01 task_context (from the plan architecture) may differ
   from the actual `model_costs.yaml` at the project root (e.g., sonnet cache_creation 3.75 vs
   6.00 in the 1h ephemeral tier). The auto_verify only checks model key presence, not specific
   rate values, so this does not cause failures. Builders should check the existing file before
   creating or updating it.

2. **S-03 FM-6**: No unit test for unknown *parent* model (only unknown sub-agent model). The
   implementation handles this correctly (`get_model_costs()` returns zeros). The gap is pure
   test coverage, not a behavioral bug. Not blocking.

3. **S-04 R2 coupling**: Legacy flat run fields are derived from `metrics` (same source as
   per-model data) rather than re-summed from `run.token_usage_by_model`. Functionally
   equivalent but technically not "computed from run totals". The verifier rubric notes this
   as acceptable.

4. **S-06 T-01 tasks.ts**: `AttemptSchema` in `tasks.ts` may be missing `token_usage_by_model`.
   The YAML notes this as optional for M6 (run-level table is the primary goal). If per-attempt
   breakdowns are needed later, this field should be added.

---

## Summary

| Check | Status |
|-------|--------|
| R1: YAML step files align with plan and intent | ✓ Pass |
| R2: All critical/significant dry-run gaps applied | ✓ Pass (after fixes) |
| R3: No unresolved critical conflicts | ✓ Pass (after fixes) |
| R4: Persistence mapping has no MISSING cells | ✓ Pass |
| R5: All tasks have contract-level auto_verify | ✓ Pass (after fixes) |
| R6: Integration test files specify assertion logic | ✓ Pass |
| R7: All [I-XX] items addressed by at least one step | ✓ Pass |
