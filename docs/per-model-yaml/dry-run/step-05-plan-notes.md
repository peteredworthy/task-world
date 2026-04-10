# Step 05 Dry-Run Analysis: API Exposure (M5)

Generated: 2026-04-08

---

## Summary: What Already Exists

Before any work is done, the following are **fully implemented**:

| Symbol | Location | Status |
|--------|----------|--------|
| `ModelTokenUsageSchema` (10 fields, `total_cost_usd` as plain float) | `api/schemas/tasks.py:81-91` | ✅ Complete |
| `AttemptSchema.token_usage_by_model: list[ModelTokenUsageSchema] = []` | `api/schemas/tasks.py:109` | ✅ Complete |
| `RunResponse.token_usage_by_model: list[ModelTokenUsageSchema] = []` | `api/schemas/runs.py:159` | ✅ Complete |
| `_run_to_response()` builds per-model schemas with `total_cost_usd=round(u.total_cost_usd, 6)` | `api/routers/runs.py:176-194` | ✅ Complete |
| `estimated_cost_usd` uses per-model sum when data present | `api/routers/runs.py:200-203` | ✅ Complete |
| Integration tests for `token_usage_by_model` | `tests/integration/` | ❌ Missing |

---

## Task-by-Task Analysis

### T-01: Add ModelTokenUsageSchema and update AttemptSchema

**Status: Already complete.**

Both `ModelTokenUsageSchema` and `AttemptSchema.token_usage_by_model` already exist exactly as specified. The builder agent must read the file first (as instructed) and confirm no-op — adding nothing.

**Assumptions:**
- Step plan was written before M1–M4 implementation completed and these were added as part of an earlier step.
- The builder will confirm no changes needed.

**Expected output:** No file changes; R1/R2 marked done by inspection.

**Failure modes:**
- **Builder re-adds the class**: If the builder doesn't read the file carefully, it might insert a duplicate `ModelTokenUsageSchema` class, causing an `ImportError` or Pydantic schema conflict. Mitigation: the task context says "Read the current file first — these may already be present. Only add what is missing." This is correct guidance.

**Auto_verify quality:**
- `grep -q 'class\\|ModelTokenUsageSchema'` is **existence-only**. Would pass even if the class were a stub with no fields. Does NOT verify that all 10 fields are present or that `total_cost_usd` is a plain `float` (not `@property`).
- Hardening needed: add a Python import check: `python -c "from orchestrator.api.schemas.tasks import ModelTokenUsageSchema; s = ModelTokenUsageSchema(model='x'); assert hasattr(s, 'total_cost_usd') and isinstance(s.total_cost_usd, float)"`

---

### T-02: Update RunResponse and _run_to_response() builder

**Status: Mostly complete — one deviation from plan.**

`RunResponse.token_usage_by_model` is present. `_run_to_response()` correctly:
1. Iterates `run.token_usage_by_model` and builds `ModelTokenUsageSchema` entries with `total_cost_usd=round(u.total_cost_usd, 6)`.
2. Uses the per-model sum for `estimated_cost_usd` when data is present.

**Deviation — R5 partial failure:** The task context says:

> For old runs with empty token_usage_by_model, return estimated_cost_usd=0.0 (not the flat gpt-4o fallback).

The current implementation at `runs.py:204-237` does NOT do this. When `token_usage_schemas` is empty, it falls through to:
1. Sum of `action_log.total_cost_usd` across attempts (if > 0)
2. `estimate_cost()` with gpt-4o pricing (flat fallback)

The flat fallback is still active for old runs. This is **more useful** behavior than returning 0.0, but it contradicts R5 and the plan's explicit wording.

**Decision required:** Does R5 intend to strip the flat estimate entirely, or is the more informative fallback acceptable? The plan intent is to avoid the "27% undercount" from sub-agent exclusion — the flat estimate was the _old_ inaccurate path. For runs where action_log has `total_cost_usd > 0`, that's actually _more_ accurate than 0.0. The verifier needs to decide whether to accept the current behavior or require strict 0.0 for empty per-model lists.

**Assumptions:**
- Builder will read the file and note the flat fallback still exists.
- Builder might incorrectly mark R5 done without addressing this deviation.

**Wiring check:** `_run_to_response()` is already called from all response-building routes (confirmed at lines 396, 433, 443, 458, 477, 496, 534, 996, 1137, 1156, 1170). No wiring gap.

**Auto_verify quality:**
- `router_builds_schemas`: checks that `token_usage_by_model` or `token_usage_schemas` appears in the router file. **Existence-only.** Would pass even if the schemas were built but not included in the response object.
- Hardening: a functional test (T-03) is the real verification — without it, R4/R5 cannot be confirmed.

---

### T-03: Integration tests for API exposure

**Status: Not implemented. Must be built from scratch.**

No `tests/integration/test_api_token_usage.py` exists. No `token_usage_by_model` appears anywhere in `tests/`. This is the only substantive work in Step 05.

**Assumptions being made by the plan:**
1. The test fixture pattern from `test_api_full_lifecycle.py` works: in-memory SQLite with `StaticPool`, `AsyncClient` against the FastAPI app.
2. Token data can be "injected" directly — the test must find a way to get `token_usage_by_model` onto a run without actually running an agent. This likely means:
   - Creating a run via the API
   - Directly updating the DB via the repository (bypassing the executor), OR
   - Using `update_latest_attempt()` in the repository to store the data

**Blocker:** There is no public API endpoint to inject `token_usage_by_model` data. The data is set by `AttemptStore.store_attempt_metrics()` which is only called from the executor. The test must either:
   - Use the repository layer directly (accessing the DB), or
   - Use internal test utilities to set the data on the run before calling `GET /api/runs/{id}`.

The plan says "inject/simulate token_usage_by_model data on the run" without specifying how. This is an implementation gap — the builder must figure out the injection mechanism. Looking at `test_api_full_lifecycle.py` for patterns is the right approach.

**Failure modes:**
1. **Injection mechanism unclear**: Builder may mock at wrong layer or not be able to set `token_usage_by_model` at all via the public API. If they use `db.run_repository.update_run()` directly, they'll need to import and use `update_latest_attempt()` — this is internal but feasible.
2. **R5 deviation not tested**: If the flat fallback for old runs is kept (see T-02), test R7 ("old runs return `estimated_cost_usd=0.0`") may fail because old runs actually return a flat estimate, not 0.0. The test must be written to match actual behavior, not planned behavior.
3. **AttemptSchema test (R8)**: `GET /api/runs/{run_id}/tasks/{task_id}` returns a `TaskDetailResponse` containing `attempts: list[AttemptSchema]`. The test needs to verify `token_usage_by_model` on the attempt object. The builder needs to check how this endpoint populates attempts and whether `token_usage_by_model` is included.

**Auto_verify quality:**
- `integration_test_file_exists`: `test -f tests/integration/test_api_token_usage.py || grep -l 'token_usage_by_model' tests/integration/test_api_full_lifecycle.py` — **existence-only**. Would pass if the file exists but contains only stubs.
- `integration_tests_pass`: `uv run pytest tests/integration/ -x -q -k 'token_usage' 2>&1 | tail -10` — **contract-level IF the tests assert on values**. This is the right check, but depends on the tests being substantive.

**Hardening for T-03:**
- After test file creation, verify tests assert on actual field values, not just presence: e.g., `assert response["token_usage_by_model"][0]["model"] == "claude-sonnet-4-6"` not just `assert "token_usage_by_model" in response`.
- Test R7 should assert `estimated_cost_usd == 0.0` only if the code is changed to return 0.0 for old runs — otherwise the test should assert the fallback behavior that actually exists.

---

## Cross-Cutting Observations

### The T-02/R5 tension

The plan says "For old runs with empty per-model data return `estimated_cost_usd=0.0`." The code instead falls back to action log cost or a flat estimate. The T-03 test for R7 says "old runs return `estimated_cost_usd=0.0`." If the test is written as specified but the code isn't changed, R7 will **fail**. Either:
- The code must be updated to remove the flat fallback (T-02 incomplete), or
- The test must be written to match the actual (more useful) behavior, and R5 re-scoped.

**Recommendation:** Treat the existing fallback chain as acceptable — it's more useful than returning 0.0. Update R5 to say "accurate per-model sum used when data present; legacy fallback (action log cost, then flat estimate) applies for old runs." Update R7 test to verify the actual behavior.

### Component wiring: complete

All response-building routes call `_run_to_response()` which already builds the per-model schemas. No new wiring required.

### Task detail endpoint (AttemptSchema)

`GET /api/runs/{run_id}/tasks/{task_id}` returns `TaskDetailResponse` which contains `attempts: list[AttemptSchema]`. `AttemptSchema.token_usage_by_model` is already defined. The builder must verify the router populates this field when building the `TaskDetailResponse` — confirm that `attempt.token_usage_by_model` is serialized from the domain model.

Check: in `api/routers/tasks.py`, the attempt conversion must map `domain_attempt.token_usage_by_model` → `AttemptSchema.token_usage_by_model`. If the router uses `.model_dump()` / `AttemptSchema.model_validate()` it may work automatically; if it constructs `AttemptSchema` field-by-field, the field may be missing. This needs explicit verification before writing the T-03 test for R8.

---

## Summary of Actions Required

| Task | Action |
|------|--------|
| T-01 | No code changes. Verify by inspection, mark R1/R2 done. |
| T-02 | Clarify R5 intent (0.0 vs. fallback chain). If strict 0.0 required, remove `estimate_cost()` fallback block. Otherwise mark R3/R4 done; flag R5 deviation. |
| T-03 | Write integration tests from scratch. Check task detail endpoint populates `token_usage_by_model` on attempts. Align R7 test with actual `estimated_cost_usd` behavior. |

---

## Hardening Actions

1. **T-01 auto_verify**: Replace grep-only check with Python import assertion that validates all 10 fields are present and `total_cost_usd` is a plain float field.

2. **T-02 R5**: Explicitly decide whether to remove the flat fallback. Document the decision in the step notes. Update T-03 R7 test to match.

3. **T-03 injection mechanism**: Specify exactly how `token_usage_by_model` data gets onto a run in tests — recommend direct repository call via `update_latest_attempt()` with `token_usage_by_model=[...]` parameter.

4. **T-03 AttemptSchema wiring**: Before writing R8 test, verify `api/routers/tasks.py` serializes `attempt.token_usage_by_model` into `AttemptSchema`. If not, this is a bug that must be fixed in T-02 or T-03.

5. **T-03 value assertions**: Tests must assert on specific field values (model name, token counts, cost rate fields) not just that the array is non-empty.
