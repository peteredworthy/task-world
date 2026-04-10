# Step 04 Dry-Run Analysis: Run-Level Aggregation (M4)

Generated: 2026-04-08  
Step YAML: `routines/per-model-yaml/steps/step-04-plan.yaml`

---

## Executive Summary

**T-01 and T-02 are already fully implemented.** The aggregation logic and wiring are present in the codebase. Only T-03 (unit tests for run-level aggregation) is missing and must be written.

---

## T-01: Implement run-level aggregation in RunRepository

**Status: ALREADY IMPLEMENTED** (`repositories.py` lines 842–869)

### Assumptions

- The method `update_latest_attempt()` already accepts `token_usage_by_model: list[ModelTokenUsage] | None = None` as a keyword argument.
- The run model is accessible via `task_model.step.run` within the method.
- `token_usage_by_model` is a SQLAlchemy JSON column that stores a list of dicts.

### Expected Outputs

- Attempt-level: `attempt.token_usage_by_model` accumulates per-model tokens (builder + verifier both contribute to the same attempt record).
- Run-level: `run_model.token_usage_by_model` accumulates across all attempts and phases.
- Both use dict-keyed-by-model merge: same model name → sum token counts, preserve existing rates.

### Verification of R1

Lines 856–869 implement run-level aggregation correctly:
```python
run_usage: dict[str, dict[str, Any]] = {e["model"]: dict(e) for e in existing}
for u in token_usage_by_model:
    if u.model not in run_usage:
        run_usage[u.model] = u.model_dump(mode="json")  # new model: capture rates
    else:
        entry = run_usage[u.model]
        entry["cache_read_tokens"] += u.cache_read_tokens
        ...
run_model.token_usage_by_model = list(run_usage.values())
```
✅ R1 is satisfied: tokens summed, rates preserved from first occurrence, new models appended.

### Verification of R2 (Legacy flat fields)

**Gap identified.** Lines 837–841 populate legacy flat run fields from the `metrics` argument:
```python
task_model.step.run.total_tokens_read += metrics.tokens_read
task_model.step.run.total_tokens_write += metrics.tokens_write
task_model.step.run.total_tokens_cache += metrics.tokens_cache
```

The `metrics` object is NOT re-derived from the merged `run.token_usage_by_model`. Instead it comes from `ExecutionMetrics` passed alongside `token_usage_by_model`. The step plan says flat fields should be "computed as sums across all models in the merged run.token_usage_by_model."

**In practice this is consistent** because `PhaseHandler._extract_metrics_and_usage()` derives both the flat `ExecutionMetrics` and the `list[ModelTokenUsage]` from the same `ActionLog` data. They will match. However, the implementations are decoupled — if `token_usage_by_model` is ever updated without updating `metrics` (or vice versa), the flat and per-model data could diverge.

**Verdict:** Satisfies the spirit of R2 but not strictly the letter. The flat fields are derived from the same source as per-model data (via `_extract_metrics_and_usage`), just not re-summed from `run.token_usage_by_model` at write time. No functional bug exists in current code paths.

**Hardening recommendation:** The dry-run analysis should note this coupling. The unit tests (T-03) should verify that after aggregation, flat field values match the sum of per-model token counts, catching any future divergence.

### Verification of R3

Line 842: `if token_usage_by_model:` — this guards against both `None` and empty list `[]`. Both falsy values skip the per-model block silently. ✅ R3 satisfied.

### Auto-verify Quality Assessment

- `repo_file_exists`: existence-only (test -f) — too weak. Would pass even if file has no aggregation.
- `update_latest_attempt_has_aggregation`: grep-based — could pass if `run.` appears in comments. Slightly better but still surface-level.
- `unit_tests_pass`: `must: false` — won't block if tests fail. Should be `must: true`.

**Hardening recommendation:** The `update_latest_attempt_has_aggregation` check should be a test assertion, not a grep. Consider changing `must: false` on `unit_tests_pass` to `must: true`.

---

## T-02: Wire token_usage_by_model through AttemptStore and PhaseHandler

**Status: ALREADY IMPLEMENTED** — all three files are fully wired.

### Verification of R4

All three phase methods call `_extract_metrics_and_usage(result)` then pass the result to `store_attempt_metrics()` with `token_usage_by_model=token_usage_by_model`:

- `_execute_building()` line ~269–271 ✅
- `_execute_verifying()` line ~396–398 ✅
- `_execute_recovering()` line ~466–468 ✅

### Verification of R5

`AttemptStore.store_attempt_metrics()` (lines 109–131):
- Accepts `token_usage_by_model: list[ModelTokenUsage] | None = None`
- Passes it to `repo.update_latest_attempt(..., token_usage_by_model=token_usage_by_model)`
✅ R5 satisfied.

### Verification of R6

Aggregation is triggered via `store_attempt_metrics()` called at the end of each phase method. Since each phase runs one attempt completion (build, verify, or recover), the run-level total is updated after each individual phase completes — not only at step/run completion.
✅ R6 satisfied.

### Auto-verify Quality Assessment

- `phase_handler_wired`: grep for `token_usage_by_model` near `store_attempt_metrics` — better than existence check. However: grep pipes can return false positives if both strings appear on adjacent (but not same-call) lines.
- `attempt_store_wired`: counts occurrences, expects ≥1 — would pass even if parameter exists but isn't forwarded.
- `backend_tests_pass`: `must: false` — same concern as T-01.

**Hardening recommendation:** Change `must: false` to `must: true` for test-run verifications. Grep checks are adequate for already-implemented code but brittle for new implementations.

---

## T-03: Unit tests for run-level aggregation

**Status: NOT IMPLEMENTED** — `tests/unit/test_run_aggregation.py` does not exist.

### Assumptions

- Tests should exercise the repository-level aggregation logic without a live DB.
- The repository's `update_latest_attempt()` requires SQLAlchemy ORM models (`RunModel`, `AttemptModel`, etc.) which are DB-backed.
- **Key challenge:** The aggregation logic in `repositories.py` operates on SQLAlchemy ORM objects with eager-loaded relationships (`task_model.step.run`). Testing this without a DB requires either: (a) integration test with in-memory SQLite, or (b) extracting the merge logic into a standalone pure function that can be unit-tested.

### Failure Modes

1. **Testability gap**: The merge logic at lines 842–869 is embedded in `update_latest_attempt()` which requires a full DB session. Pure unit tests (no DB) cannot invoke it directly. The test file must either use in-memory SQLite (integration) or extract/duplicate the merge logic.

   **Recommendation:** Extract the merge dict logic into a module-level helper function (e.g., `_merge_token_usage(existing: list[dict], incoming: list[ModelTokenUsage]) -> list[dict]`) and unit-test that function directly. The repository method then calls this helper.

2. **Legacy flat field verification (R10)**: The flat fields (`total_tokens_read`, etc.) are updated from `metrics`, not from `run.token_usage_by_model`. A test that checks flat fields = sum of per-model values will only pass if the test constructs both `metrics` and `token_usage_by_model` consistently from the same source data (matching what `_extract_metrics_and_usage` does). This could mislead the test author if they set them independently.

   **Recommendation:** R10 tests should construct both `metrics` and `token_usage_by_model` the same way the phase handler does — using `_extract_metrics_and_usage()` — rather than constructing them independently.

3. **Cost rate preservation (R8)**: The current merge logic in `repositories.py` preserves rates from the first occurrence (the `if u.model not in run_usage:` branch sets all fields including rates, while the `else:` branch only adds token counts). Tests must confirm that rates from the second attempt entry for the same model are NOT overwritten.

4. **Auto-verify quality**: The `test_file_exists` check uses `test -f` — existence-only. Would pass if the file exists but all tests are skipped or commented out. The `new_tests_pass` check (`pytest -k 'aggregation or token_usage'`) is better but depends on test naming.

### Required Test Cases Analysis

**R7: Multiple attempts with different models**
- Create two `ModelTokenUsage` objects (different model names), call merge, assert both present with correct token counts.
- If testing via helper function: straightforward.
- If testing via repository: needs in-memory DB setup.

**R8: Same model across attempts (sum correctly, preserve rates)**
- Two calls to merge with same model name. Verify tokens summed, rates match first call.
- Must explicitly check rates are from first occurrence, not overwritten.

**R9: Empty attempts contribute nothing**
- Pass `token_usage_by_model=[]` (falsy) — the `if token_usage_by_model:` guard means the block is skipped entirely. Test that no empty entry is added and no exception raised.

**R10: Legacy flat fields match aggregated data**
- Given caveats above: construct `ExecutionMetrics` whose token totals equal the sum of per-model tokens. After calling both flat-field update and per-model update, verify consistency.

### Hardening Actions

1. **Extract merge helper**: Add `_merge_token_usage(existing: list[dict], incoming: list[ModelTokenUsage]) -> list[dict]` as a module-level function in `repositories.py`. Point `update_latest_attempt()` at it. Test the helper directly in unit tests.

2. **Use existing test patterns**: Follow `test_model_token_usage.py` — use `_reset_cost_table` fixture and construct `ModelTokenUsage` objects directly (not via DB).

3. **Name tests with "aggregation"**: The auto-verify grep runs `pytest -k 'aggregation or token_usage'` — test class/function names must include one of these strings.

4. **Test file name**: Use `tests/unit/test_run_aggregation.py` (the auto-verify also checks for `test_model_token_usage.py` with `||` — either works, but a dedicated file is cleaner).

---

## Cross-Cutting Failure Modes

### COMPONENT WIRING

All T-01 and T-02 components are already wired into the active code path:
- `phase_handler.py` calls `_extract_metrics_and_usage()` → `store_attempt_metrics(token_usage_by_model=...)`
- `attempt_store.py` delegates to `repo.update_latest_attempt(token_usage_by_model=...)`
- `repositories.py` performs the aggregation in the same `update_latest_attempt()` that handles all other attempt updates

No orphaned implementations. No old code paths that bypass the new logic.

### PERSISTENCE LAYER

- DB columns `token_usage_by_model` (JSON, nullable) exist on both `attempts` and `runs` (confirmed in ORM models and migration `p1a2b3c4d5e6_add_token_usage_by_model.py`).
- Serialization: `model_dump(mode="json")` on `ModelTokenUsage` domain objects.
- Deserialization: `_to_domain()` in repositories.py converts JSON list of dicts → `list[ModelTokenUsage]`.

### WILL EXISTING TESTS BREAK?

No. T-01 and T-02 add no new code; they're already in place. T-03 adds new test file only. Existing 330 unit tests and 235 integration tests unaffected.

---

## Summary Table

| Task | Requirement | Status | Notes |
|------|-------------|--------|-------|
| T-01 | R1: Run-level merge by model name | ✅ DONE | Lines 856–869 |
| T-01 | R2: Legacy flat fields from per-model data | ⚠ PARTIAL | Derived from metrics (consistent but not re-summed from run totals) |
| T-01 | R3: Empty/None handled gracefully | ✅ DONE | `if token_usage_by_model:` guard |
| T-02 | R4: PhaseHandler passes token_usage_by_model | ✅ DONE | All 3 phase methods wired |
| T-02 | R5: AttemptStore accepts + forwards | ✅ DONE | Lines 109–131 |
| T-02 | R6: Triggered per-attempt (real-time) | ✅ DONE | Called at end of each phase |
| T-03 | R7: Multi-model test | ❌ MISSING | test_run_aggregation.py not created |
| T-03 | R8: Same-model sum test | ❌ MISSING | test_run_aggregation.py not created |
| T-03 | R9: Empty attempt test | ❌ MISSING | test_run_aggregation.py not created |
| T-03 | R10: Legacy flat fields test | ❌ MISSING | test_run_aggregation.py not created |

---

## Recommended Plan Hardening Actions

1. **T-03 task context**: Add guidance that the merge logic should be extracted into a standalone `_merge_token_usage()` helper to enable pure unit testing without DB. This is not currently mentioned.

2. **T-01 auto_verify**: Change `unit_tests_pass` from `must: false` to `must: true`.

3. **T-02 auto_verify**: Change `backend_tests_pass` from `must: false` to `must: true`.

4. **T-03 auto_verify**: `test_file_exists` is existence-only — add a stronger check (e.g., count test functions inside the file).

5. **R2 clarification**: The verifier rubric's "A" grade says flat fields "are computed as sums across all models in the merged run.token_usage_by_model." The actual implementation uses `metrics` (which is derived from the same source). The verifier should accept this approach as equivalent if tests confirm consistency.
