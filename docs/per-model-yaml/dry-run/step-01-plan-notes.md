# Step 01 Dry-Run Analysis: Core Data Model and Cost Config (M1)

*Simulated 2026-04-08. All commands verified against actual worktree state.*

---

## Executive Summary

**All M1 components already exist and are working.** The step plan largely describes work that has been pre-implemented. However, there is a **critical file-location mismatch** between the plan spec (`config/model_costs.yaml`) and the actual implementation (`model_costs.yaml` at project root), which will cause several auto_verify checks to fail. The plan YAML files need hardening before a builder agent executes them.

---

## Task-by-Task Walkthrough

### T-01: Create config/model_costs.yaml

**Status: File already exists but at wrong path.**

- The plan specifies `config/model_costs.yaml` (a `config/` subdirectory at project root).
- The actual file is `model_costs.yaml` at the project root. No `config/` directory exists.
- The `_find_cost_file()` function in `costs.py` only looks for `model_costs.yaml` (no `config/` subdirectory), so creating `config/model_costs.yaml` without also updating `costs.py` would not be loaded.

**Assumptions made by plan:**
- A `config/` directory will be created if it doesn't exist.
- `costs.py` also reads from `config/model_costs.yaml`.

**Expected output:** `config/model_costs.yaml` created.

**Blockers:**
- `costs.py._find_cost_file()` looks for `model_costs.yaml` at project root, not `config/model_costs.yaml`. Simply creating the file at `config/` would have no effect on the running system.

**Rate discrepancies** (plan architecture vs actual file):

| Model | Field | Plan spec | Actual file |
|-------|-------|-----------|-------------|
| claude-sonnet-4-6 | cache_creation | 3.75 | 6.00 (1h ephemeral tier) |
| claude-haiku-4-5-20251001 | cache_read | 0.08 | 0.10 |
| claude-haiku-4-5-20251001 | cache_creation | 1.00 | 2.00 |
| claude-haiku-4-5-20251001 | input | 0.80 | 1.00 |
| claude-haiku-4-5-20251001 | output | 4.00 | 5.00 |
| claude-opus-4-6 | cache_read | 0.75 | 0.50 |
| claude-opus-4-6 | cache_creation | 9.375 | 10.00 |
| claude-opus-4-6 | input | 7.50 | 5.00 |
| claude-opus-4-6 | output | 37.50 | 25.00 |

The actual file has a comment explaining the cache_creation discrepancy: "1h ephemeral tier (5m tier is $3.75)". The plan's architecture spec was written before this pricing decision was documented.

**Auto-verify quality:**
- `test -f config/model_costs.yaml` — **WILL FAIL** (file is at `model_costs.yaml`)
- Python assertion check on YAML contents — would pass if file exists at correct path, but won't reach this if the first check fails

---

### T-02: Add ModelTokenUsage class and token_usage_by_model fields to state/models.py

**Status: All components already exist and verified working.**

Verified via live execution:
```
ModelTokenUsage(model='test', input_tokens=1_000_000, cost_per_m_input=3.0).total_cost_usd == 3.0  ✓
Attempt(attempt_num=1).token_usage_by_model == []  ✓
'token_usage_by_model' in Run.model_fields  ✓
```

**Assumptions made by plan:**
- `ModelTokenUsage` doesn't yet exist in `state/models.py`. **Incorrect** — it exists already.
- Fields don't yet exist on `Attempt` and `Run`. **Incorrect** — both fields exist.

**Failure mode if plan is executed naively:** An agent doing a "create" or "add" would add duplicate class definitions or duplicate field declarations, breaking imports.

**Auto-verify quality:**
- All three checks are contract-level (import + instantiate + assert property). They would pass on the pre-existing implementation and catch any regression. Good quality.
- The `attempt_field` check asserts `== []` which verifies the default value. Solid.

---

### T-03: Create src/orchestrator/runners/costs.py

**Status: File already exists and fully implemented.**

Verified via live execution:
```
get_model_costs('claude-sonnet-4-6') → cost_per_m_input=3.0, cost_per_m_output=15.0  ✓
get_model_costs('claude-sonnet-4-6-20250514') → cost_per_m_input=3.0  ✓
get_model_costs('totally-unknown-model') → all zeros  ✓
get_model_costs(None) → all zeros  ✓
```

**Assumptions made by plan:**
- `costs.py` doesn't exist yet. **Incorrect** — it's at `src/orchestrator/runners/costs.py`.

**Key difference from plan spec:**
- The plan's `_find_cost_file()` description says "Check up to 4 parent directories" and fall back to `CWD/config/model_costs.yaml`. The actual implementation checks `parent.parent.parent.parent / "model_costs.yaml"` (project root directly) and `CWD / "model_costs.yaml"` — it does **not** look in `config/` subdirectory.

**Auto-verify quality:**
- All four checks are contract-level (import + assert computed value). They pass on the existing implementation. These would also detect regressions in future steps. Good quality.
- Note: the `costs_module` check reads from the project root `model_costs.yaml` (lazy-loaded). If the file is moved to `config/` without updating `_find_cost_file()`, this check would fail because the module would return zeros.

---

### T-04: Write unit tests for ModelTokenUsage and get_model_costs

**Status: Test file already exists with 12 tests, all passing.**

Test file: `tests/unit/test_model_costs.py`
- `_reset_cost_table` autouse fixture present ✓
- Tests for `load_cost_table` (5 tests: known model, multiple models, empty section, missing fields, reload) ✓
- Tests for `get_model_costs` (7 tests: exact match, prefix-versioned, haiku, unknown, None, copy-not-reference, empty-table) ✓
- All 12 tests pass in 4.83s ✓

Note: A separate `tests/unit/test_model_token_usage.py` also exists for `ModelTokenUsage.total_cost_usd` and `PhaseHandler._extract_metrics_and_usage` — this covers the `total_cost_usd` cases specified in T-04's task_context.

**Auto-verify quality:**
- `test -f tests/unit/test_model_costs.py` — existence-only, passes even if tests are stubs. Paired with `tests_pass` makes it adequate.
- `python3 -m pytest tests/unit/test_model_costs.py -v --tb=short -q 2>&1 | tail -5` — contract-level (must pass). Good.
- `python3 -m pytest tests/unit/ -q --tb=short 2>&1 | tail -5` — regression guard against all unit tests. Good.

**Verifier rubric quality:** The rubric checks for `_ZERO_COSTS` copy semantics (not mutating internal state) and bidirectional prefix matching. The `test_returns_copy_not_reference` test covers the copy requirement. Bidirectional prefix is tested implicitly via haiku (`claude-haiku-4-5-20251001` matches YAML key `claude-haiku-4-5`).

---

## Failure Modes Summary

### FM-01: T-01 auto_verify WILL FAIL due to path mismatch
**Severity: Critical**  
`test -f config/model_costs.yaml` checks for a file in a `config/` subdirectory that doesn't exist.  
**Hardening action:** Change T-01 auto_verify to check `test -f model_costs.yaml` (project root). OR, if the decision is to move to `config/`, update `costs.py._find_cost_file()` in the same task to look in `config/model_costs.yaml`.

### FM-02: T-02/T-03 will re-implement already-existing code
**Severity: High**  
A naive agent will add duplicate `ModelTokenUsage` class, duplicate fields on `Attempt`/`Run`, and overwrite `costs.py`. This would either fail (duplicate symbols) or silently replace working code with potentially incorrect code.  
**Hardening action:** Add a note to T-02 and T-03 task_context stating that these files already exist and the task is to VERIFY correctness only — not to re-create. Alternatively, replace with verification tasks that run the auto_verify checks and report as done.

### FM-03: Rate discrepancy in architecture spec vs. actual YAML
**Severity: Medium**  
If T-01 is executed to create `config/model_costs.yaml`, it will write the rates from the plan spec (which are stale). The haiku rates differ materially (e.g. output: 4.00 in plan vs 5.00 in actual).  
**Hardening action:** Update the rate values in T-01 task_context to match `model_costs.yaml`. Add a comment about the 1h vs 5m ephemeral cache tier for `cache_creation` rates.

### FM-04: `costs.py._find_cost_file()` doesn't look in `config/`
**Severity: High**  
If `config/model_costs.yaml` is created but `costs.py` isn't updated to look there, the cost table will silently remain loaded from the project-root file (or be empty if the root file is deleted).  
**Hardening action:** Either keep the file at project root and update T-01 to reflect the actual path, OR add a T-03 sub-task to update `_find_cost_file()` to also check `config/model_costs.yaml`. Given the existing implementation works correctly with the project root location, the former is simpler.

### FM-05: T-04 auto_verify `tail -5` may not show pass/fail clearly
**Severity: Low**  
If pytest outputs warnings or other content, `tail -5` might show build info instead of the final pass/fail count. This is unlikely to cause a real failure but could confuse an agent reading output.  
**Hardening action:** Change to `2>&1 | grep -E "passed|failed|error" | tail -3`.

---

## Component Wiring Analysis

**T-01 through T-03 are pure additive infrastructure** — no active code path is changed. `get_model_costs()` is not called by any code in M1; it's a library function that M3 (phase_handler.py) will wire in. No wiring issues for this step.

The new fields on `Attempt` and `Run` are purely additive — existing serialization/deserialization in `repositories.py` already handles them (confirmed in the discovery doc). No ORM model changes are needed for M1 (the `token_usage_by_model` JSON columns and the migration already exist).

---

## Recommended Plan Hardening

1. **T-01 auto_verify**: Fix `test -f config/model_costs.yaml` → `test -f model_costs.yaml` **OR** decide to move the file to `config/` and update both the YAML path spec and `_find_cost_file()` in T-03.

2. **T-01 rate values**: Update to match the actual `model_costs.yaml` (sonnet cache_creation=6.00, haiku rates, opus rates). Document the 1h vs 5m ephemeral tier decision.

3. **T-02 and T-03 task_context**: Add "NOTE: This code already exists. Verify it matches the spec rather than re-implementing." Prevents a builder from duplicating or overwriting working code.

4. **T-04 coverage note**: Mention that `test_model_token_usage.py` also covers `ModelTokenUsage.total_cost_usd` — tests don't need to be duplicated.

5. **Overall**: Consider adding a "status: implemented" field to T-01/T-02/T-03 so the orchestrator can skip to verification, or restructure as a single verification task that runs all auto_verify checks.
