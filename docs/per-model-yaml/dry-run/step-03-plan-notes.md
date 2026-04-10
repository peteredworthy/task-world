# Step S-03 Dry-Run Analysis: Phase Handler Token Extraction (M3)

Generated: 2026-04-08

---

## Pre-Execution State

**Both tasks are already fully implemented.** This is confirmed by direct inspection:

- `phase_handler.py` line 50–113: `_extract_metrics_and_usage()` exists and is complete
- `phase_handler.py` lines 270, 397, 467: `token_usage_by_model=` passed in all three phase methods
- `tests/unit/test_model_token_usage.py` exists with 14 tests covering the extraction logic

The step will succeed immediately on the first attempt with no code changes required.

---

## T-01: Implement per-model extraction in PhaseHandler

### Assumptions

1. `get_model_costs()` is already imported at line 17 — assumption valid.
2. `ModelTokenUsage` is importable from `orchestrator.state.models` — valid.
3. `ActionLog` fields (`agent_model`, `total_*_tokens`, `sub_agents`) match the spec — confirmed.
4. All three phase methods (`_execute_building`, `_execute_verifying`, `_execute_recovering`) use `_extract_metrics_and_usage()` then call `store_attempt_metrics()` — confirmed at lines 263/270, 390/397, 460/467.

### Expected Outputs

All four auto_verify grep checks will pass immediately:
- `_extract_metrics_and_usage` — present at line 50
- `get_model_costs` — imported at line 17
- `token_usage_by_model` — present at lines 270, 397, 467
- `existing_tests_pass` — all tests should pass

### Failure Modes

**FM-1: Zero-token edge case uses only `input_tokens or output_tokens` as the guard**
- Line 65: `if al.total_input_tokens or al.total_output_tokens:`
- A run with only cache tokens (`total_cache_read_tokens > 0`, but `total_input_tokens == 0`) would skip parent model extraction and return `[]`.
- This is unlikely in practice (cache-only runs don't occur without input tokens), but the condition is not documented as intentional.
- **Severity**: Low — cache-only token scenarios are hypothetical.
- **Hardening**: Add a code comment explaining why cache-only is excluded, or widen the guard to `al.total_input_tokens or al.total_output_tokens or al.total_cache_read_tokens or al.total_cache_creation_tokens`.

**FM-2: Sub-agent parent tokens may double-count**
- If the parent `ActionLog.total_input_tokens` already includes sub-agent tokens (some runners aggregate sub-agent usage into parent totals), the parent entry would double-count sub-agent work.
- Whether runners produce overlapping vs. disjoint parent/sub-agent totals is not verified by any test or assert.
- **Severity**: Medium — depends on runner behavior, silent if wrong.
- **Hardening**: Add a comment documenting the expected contract (parent totals are disjoint from sub-agent totals), and add an integration test or fixture that verifies total cost matches expectations for a known input.

**FM-3: `num_actions` computation is brittle**
- Line 110: `num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use")`
- This depends on `ActionLogEntry.kind` being an enum with `.value == "tool_use"`. If `kind` uses a different string (e.g., `"tool_call"`) or is a plain string, `num_actions` silently becomes 0.
- **Severity**: Low — `num_actions` is a legacy display metric, not used in cost calculation.
- **Hardening**: The existing test `test_legacy_metrics_built_from_parent_tokens` verifies `num_actions == 2` using `_make_tool_use_entry()` helpers, which confirms the enum value is correct. No change needed, but the brittle dependency on `.value` is worth noting.

**FM-4: Auto_verify checks are mostly existence-only**
- `extract_method_exists`, `get_model_costs_used`, `token_usage_by_model_passed` are all `grep -q` — they pass for a stub implementation.
- Only `existing_tests_pass` (`uv run pytest tests/`) is contract-level.
- **Severity**: Medium — but since `existing_tests_pass` is the last check and requires all tests to pass, this is acceptable. The grep checks serve as fast pre-flight indicators.
- **Hardening**: Consider replacing the three grep checks with a single targeted test run: `uv run pytest tests/unit/test_model_token_usage.py -q` which exercises all extraction logic.

**FM-5: Wiring is complete — no gap**
- The step asks whether `_extract_metrics_and_usage()` is called from all three phase methods. Confirmed: lines 263, 390, 460. The step also asks if `store_attempt_metrics` is called with `token_usage_by_model=` in all three. Confirmed: lines 270, 397, 467.
- No old code path exists that bypasses the extraction.

---

## T-02: Unit tests for extraction scenarios

### Assumptions

1. `tests/unit/test_model_token_usage.py` does not exist yet — **assumption is WRONG**. File already exists with 14 test functions.
2. Cost file fixture writes YAML to `tmp_path` — confirmed, `cost_file` fixture at lines ~30–65.

### Coverage vs. Requirements

The step requires 5 scenarios:

| Required Scenario | Test Function | Status |
|---|---|---|
| 1. Parent-only (no sub-agents) | `test_parent_only_action_log` (line 137) | ✓ Covered |
| 2. Parent + sub-agents, different models | `test_sub_agents_added_as_separate_usage_entries` (line 180) | ✓ Covered |
| 3. Multiple sub-agents, same model (merge) | `test_sub_agents_with_same_model_are_grouped` (line 206) | ✓ Covered |
| 4. Unknown model (zero rates) | `test_unknown_model_in_sub_agent_gets_zero_rates` (line 305) | ⚠ Partial |
| 5. Null action_log | `test_no_action_log_returns_result_metrics` (line 126) | ✓ Covered |

### Failure Mode

**FM-6: Scenario 4 tests unknown SUB-AGENT model only, not unknown PARENT model**
- `test_unknown_model_in_sub_agent_gets_zero_rates` uses `agent_model="claude-sonnet-4-6"` (a known model) and only sets the sub-agent to `"gpt-unknown"`.
- The requirement specifies "ActionLog with `agent_model` not in model_costs.yaml" — meaning the parent model is unknown.
- **Gap**: No test verifies that an unknown parent model gets zero rates and that the parent entry appears with `model="<unknown-name>"` and `cost_per_m_* == 0.0`.
- The implementation handles this correctly (`get_model_costs()` returns `_ZERO_COSTS` for unknown models), but the test gap means a regression could go undetected.
- **Severity**: Low — implementation is correct, but the coverage gap violates R6 exactly as stated.
- **Hardening**: Add `test_unknown_parent_model_gets_zero_rates` with `agent_model="gpt-unknown-parent"`, asserting that the parent `ModelTokenUsage` has zero rates and `total_cost_usd == 0.0`.

**FM-7: Auto_verify `unit_tests_pass` shows only `tail -15` of output**
- If a test fails mid-suite, the tail may not show the failing test name. Use `-v` flag (already present) which helps, but the `tail -15` truncation may hide the failure cause.
- **Severity**: Very low — informational only.

---

## Summary of Hardening Actions

| Priority | Action | Target |
|---|---|---|
| Medium | Add `test_unknown_parent_model_gets_zero_rates` test to cover R6 fully | `tests/unit/test_model_token_usage.py` |
| Medium | Document or widen the zero-token guard to handle cache-only token scenarios | `phase_handler.py` line 65 |
| Low | Add a comment documenting that parent and sub-agent totals are expected to be disjoint | `phase_handler.py` line 82 |
| Low | Consider replacing 3 grep auto_verify checks with a single targeted pytest call | `step-03-plan.yaml` T-01 auto_verify |

---

## Overall Assessment

The step is **already complete**. Both tasks are fully implemented with correct logic and adequate test coverage. The only notable gap is test scenario 4 (FM-6), which tests unknown sub-agent but not unknown parent model. The implementation handles the case correctly, making this a pure coverage gap rather than a behavioral bug. The plan is sound and the step should pass verification immediately.
