# Step 04: Engine Enhancements (M4 Prerequisites)

## Purpose

Implement two small engine fixes required for fan-out parallelism (Step 05): two-pass template resolution in `templates.py` and passing run variables to `shared_context` resolution in `executor.py`. These are targeted changes (~13 lines total) that enable per-item context in fan-out prompts.

## Prerequisites

- Understanding of `src/orchestrator/workflow/templates.py` `resolve_template()` function
- Understanding of `src/orchestrator/runners/executor.py` fan-out execution flow (~line 1206)

## Dependencies

- **No dependencies on Steps 01-03** (engine changes are independent of routine YAML)
- **Step 05 depends on this step** (fan-out conversion requires both engine fixes)

## Functional Contract

### Change 0a: Two-Pass Template Resolution

**File:** `src/orchestrator/workflow/templates.py`

**Input:** A template string containing mixed placeholders, e.g.:
```
{{file:docs/{{feature}}/{{item_stem}}-plan.md}}
```
Plus a `variables` dict (e.g., `{"feature": "myproject", "item_stem": "step-01"}`) and optional `worktree_path`.

**Output:** File contents of the resolved path (e.g., contents of `docs/myproject/step-01-plan.md`).

**Behavior:**
- Pass 1: Resolve all non-`file:` placeholders (plain variable lookups). `{{file:...}}` patterns are left untouched.
- Pass 2: Resolve `{{file:...}}` placeholders (paths now have variables substituted).

**Error cases:**
- Missing variable in Pass 1: placeholder left as-is (existing behavior)
- Missing file in Pass 2: returns `[File not found: <rel_path>]` (existing behavior)
- Variable value containing `{{file:...}}`: would be processed in Pass 2 (documented risk, unlikely in practice)

### Change 0b: Shared Context Variable Resolution

**File:** `src/orchestrator/runners/executor.py`

**Input:** `shared_context` entries containing variable placeholders, e.g.:
```
docs/{{feature}}/intent.md
```
Plus the run config variables dict.

**Output:** Correctly resolved file paths with variables substituted before file reading.

**Behavior:** Build a `config_vars` dict from `run.config` before the shared_context resolution loop, pass it as `variables=variables` to the `resolve_template()` call.

**Error cases:**
- If `run.config` has no variables, empty dict is passed (no change from current behavior)
- If variable is missing from config, placeholder left as-is (existing behavior)

## Changes

| File | Change |
|------|--------|
| `src/orchestrator/workflow/templates.py` | Split `resolve_template()` into two passes: variables first, then `{{file:...}}` references (~10 lines) |
| `src/orchestrator/runners/executor.py` | Pass run config variables to `shared_context` `resolve_template()` call (~3 lines) |
| `tests/unit/test_templates.py` | Add unit tests for two-pass resolution: nested variables, plain variables, missing files, edge cases |

## Verification Strategy

1. **Unit tests for two-pass resolution:**
   - `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` with variables `feature=myproject`, `item_stem=step-01` -> reads `docs/myproject/step-01-plan.md`
   - Plain variables resolve correctly (Pass 1 only, no regression)
   - `{{file:...}}` without nested variables still works (Pass 2 only)
   - Missing file returns `[File not found: ...]`
2. **Existing tests pass:** All current template resolution tests continue to pass (no regression)
3. **Manual smoke test:** Create a test fan-out task with `shared_context` containing `{{feature}}` and verify it resolves
