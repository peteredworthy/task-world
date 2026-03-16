# Step 4: Engine Enhancements (M4 Prerequisites)

Implement two small engine fixes required for fan-out parallelism: two-pass template resolution in `templates.py` and passing run variables to `shared_context` resolution in `executor.py`. These are targeted changes (~13 lines total) that enable per-item context in fan-out prompts.

## Intent Verification
**Original Intent**: Completion criteria #11 (two-pass template resolution) and #12 (shared_context variable passing) from intent.md
**Functionality to Produce**:
- `resolve_template()` resolves plain variables first, then `{{file:...}}` references in a second pass
- `shared_context` entries receive run config variables for path resolution
- Unit tests cover nested variable resolution, plain variables, missing files, edge cases
**Final Verification Criteria**:
- All existing template resolution tests pass (no regression)
- New unit tests pass for two-pass resolution
- `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` resolves correctly with appropriate variables

---

## Task 1: Implement Two-Pass Template Resolution

**Description**: Modify `resolve_template()` in `templates.py` to resolve plain variables first (Pass 1), leaving `{{file:...}}` patterns untouched, then resolve `{{file:...}}` references in a second pass (Pass 2) with variables already substituted in paths.

**Implementation Plan (Do These Steps)**

The current `resolve_template()` uses a single `re.sub()` pass. The regex `\{\{(.+?)\}\}` matches `{{file:docs/{{feature}}` as the first placeholder when nested `{{}}` patterns are present, which breaks fan-out per-item context. Splitting into two passes fixes this.

- [ ] Read `src/orchestrator/workflow/templates.py` to understand the current `resolve_template()` implementation
- [ ] Modify `resolve_template()` to use two passes:

  **⚠️ CRITICAL REGEX ISSUE**: The existing `_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")` with non-greedy matching will match `{{file:docs/{{feature}}` as a single group (key = `file:docs/{{feature`), consuming the inner `{{feature}}`'s closing `}}`. Simply checking `key.startswith("file:")` and returning it as-is in pass 1 will leave `{{feature}}` unresolved because it was consumed as part of the file match.

  **FIX**: Use a different regex for pass 1 that matches ONLY simple (non-nested) variables — patterns whose content contains no `{` character:

  ```python
  _SIMPLE_VAR_RE = re.compile(r"\{\{([^{]+?)\}\}")  # matches {{name}} but NOT {{file:docs/{{name}}

  # Pass 1: resolve plain variables only using the simple-var regex
  def _replace_vars(match):
      key = match.group(1).strip()
      if key.startswith("file:"):
          return match.group(0)  # leave for pass 2
      if key in vars_:
          return vars_[key]
      return match.group(0)

  result = _SIMPLE_VAR_RE.sub(_replace_vars, template)

  # Pass 2: resolve {{file:...}} references using the original regex
  # (paths now have variables substituted, so no more nesting)
  def _replace_files(match):
      key = match.group(1).strip()
      if key.startswith("file:"):
          rel_path = key[len("file:"):]
          full = Path(worktree_path or ".") / rel_path
          try:
              return full.read_text()
          except (FileNotFoundError, IsADirectoryError, OSError):
              return f"[File not found: {rel_path}]"
      return match.group(0)

  return _PLACEHOLDER_RE.sub(_replace_files, result)
  ```

  The key difference: `_SIMPLE_VAR_RE` uses `[^{]+?` instead of `.+?`, so it matches `{{feature}}` and `{{item_stem}}` but skips over `{{file:docs/{{feature}}/...}}` entirely (because the content contains `{`). After pass 1 resolves all simple variables, the `{{file:...}}` patterns contain only literal paths and pass 2 resolves them normally.
- [ ] Ensure the existing single-pass behavior for non-nested patterns is preserved (no regression)
- [ ] Read existing tests in `tests/unit/test_templates.py`
- [ ] Add unit tests for two-pass resolution:
  - `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` with variables `feature=myproject`, `item_stem=step-01` → reads `docs/myproject/step-01-plan.md`
  - Plain variables resolve correctly (Pass 1 only, no regression)
  - `{{file:...}}` without nested variables still works (Pass 2 only)
  - Missing file returns `[File not found: ...]`
  - Variables containing `{{file:...}}` pattern (edge case — document behavior: pass 2 WILL expand file references injected by variable substitution)
  - **CRITICAL**: Test that the `_SIMPLE_VAR_RE` regex correctly skips nested patterns. Verify: `resolve_template("{{file:docs/{{feature}}/readme.md}}", variables={"feature": "test"})` where `docs/test/readme.md` exists → reads the file content. This confirms pass 1 resolves `{{feature}}` inside the file path before pass 2 reads the file.
  - Test that existing `test_no_recursive_resolution` still passes (plain variable substitution results are not re-expanded in pass 1)
  - Compile-time check: `_SIMPLE_VAR_RE` must be a module-level constant (same as `_PLACEHOLDER_RE`), not recreated per call

**Dependencies**
- [ ] Understanding of `src/orchestrator/workflow/templates.py` `resolve_template()` function
- [ ] Understanding of `_PLACEHOLDER_RE` regex pattern used

**References**
- Step plan: `docs/planning-routine-improvements/step-04-plan.md`
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 5 (two-pass template resolution), includes implementation sketch
- Intent: `docs/planning-routine-improvements/intent.md` — completion criterion #11

**Constraints**
- Only modify `resolve_template()` function — do not change other functions in templates.py
- Preserve existing behavior for all current template patterns (plain variables, `{{file:...}}` without nesting)
- Change should be ~10 lines of code

**Side Effects**
- If a resolved variable value itself contains `{{file:...}}`, the second pass would process it. This is unlikely in practice (variable values come from run config and fan-out metadata) but is a documented risk.
- The existing test `test_no_recursive_resolution` tests that `{{outer}}` resolving to `"has {{inner}}"` does NOT expand `{{inner}}`. This test SHOULD still pass because pass 1 uses `_SIMPLE_VAR_RE` (which won't match already-resolved output), and pass 2 only matches `{{file:...}}` patterns. However, if a variable resolves to `"has {{file:secret.txt}}"`, pass 2 WILL read that file. Add a test documenting this edge case behavior.

**Functionality (Expected Outcomes)**
- [ ] `resolve_template("{{file:docs/{{feature}}/{{item_stem}}-plan.md}}", variables={"feature": "myproject", "item_stem": "step-01"})` reads the correct file
- [ ] `resolve_template("Hello {{name}}", variables={"name": "world"})` returns `"Hello world"` (existing behavior preserved)
- [ ] `resolve_template("{{file:docs/readme.md}}")` reads the file (existing behavior preserved)
- [ ] `resolve_template("{{file:docs/missing.md}}")` returns `"[File not found: docs/missing.md]"` (existing behavior preserved)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/test_templates.py -v` — all tests pass (existing + new)
- [ ] New tests specifically cover nested variable resolution in `{{file:...}}` paths
- [ ] No other test files fail: `uv run pytest tests/unit/ -x -q` passes

---

## Task 2: Pass Run Variables to shared_context Resolution

**Description**: Modify the fan-out execution path in `executor.py` to pass run config variables to `resolve_template()` when resolving `shared_context` entries, enabling `{{feature}}` in shared_context file paths.

**Implementation Plan (Do These Steps)**

Currently `shared_context` entries are resolved via `resolve_template(ctx_entry, worktree_path=worktree_path)` without passing the `variables` dict. This means `{{feature}}` in shared_context paths is left unresolved.

- [ ] Read `src/orchestrator/runners/executor.py` and locate the fan-out execution flow (~line 1206) where `shared_context` is resolved
- [ ] Identify where the `variables` dict (containing run config values like `feature`) is constructed
- [ ] Build a `config_vars` dict from `run.config` before the shared_context resolution loop (or ensure the existing variables dict is available at that point)
- [ ] Pass `variables=config_vars` to the `resolve_template()` call for shared_context entries:
  ```python
  # Before (broken):
  resolve_template(ctx_entry, worktree_path=worktree_path)

  # After (fixed):
  resolve_template(ctx_entry, variables=config_vars, worktree_path=worktree_path)
  ```

**Dependencies**
- [ ] Task 1 (two-pass template resolution) must be complete — the variables parameter must work correctly

**References**
- Step plan: `docs/planning-routine-improvements/step-04-plan.md`
- Architecture: `docs/planning-routine-improvements/architecture.md` — section 6 (shared context variable resolution)
- Intent: `docs/planning-routine-improvements/intent.md` — completion criterion #12

**Constraints**
- Change should be ~3 lines of code
- Do not modify the fan-out execution flow beyond adding the variables parameter
- If `run.config` has no variables, an empty dict should be passed (no change from current behavior)

**⚠️ IMPORTANT: shared_context entries must use `{{file:...}}` format**

`resolve_template()` only reads file contents for `{{file:path}}` patterns. A bare path like `"docs/myproject/plan.md"` is returned as the literal string, not the file contents. This means shared_context entries in the routine YAML must be wrapped:

```yaml
# WRONG — produces the string "docs/myproject/plan.md" in the prompt
shared_context:
  - "docs/{{feature}}/plan.md"

# CORRECT — reads the file and injects its contents
shared_context:
  - "{{file:docs/{{feature}}/plan.md}}"
```

This is enforced in step-05.md's fan_out configurations. The two-pass resolution from Task 1 handles the nested `{{feature}}` inside `{{file:...}}`.

**⚠️ CRITICAL: Variable construction ordering**

In `executor.py`, the shared_context resolution loop (lines 1203-1207) runs BEFORE the `variables` dict is built (lines 1210-1218). You must build `config_vars` from `run.config` BEFORE the shared_context loop — do NOT try to reuse the `variables` dict that is constructed later:

```python
# Build config_vars BEFORE shared_context resolution (lines ~1203)
config_vars = {k: str(v) for k, v in run.config.items() if v is not None}

# Resolve shared_context entries (existing loop)
shared_parts: list[str] = []
for ctx_entry in fan_out.shared_context:
    resolved = resolve_template(ctx_entry, variables=config_vars, worktree_path=worktree_path)
    shared_parts.append(resolved)
```

**Integration Test Assertions for shared_context Fix**

Add a test (in `tests/unit/test_templates.py` or a new `tests/unit/test_executor_fanout.py`) that verifies the end-to-end behavior:

1. **Assertion: shared_context with `{{file:...}}` and variables resolves to file contents**
   - Setup: Create a temp file at `{tmp}/docs/test-proj/plan.md` with content `"# Plan\nBuild the thing"`
   - Call: `resolve_template("{{file:docs/test-proj/plan.md}}", variables={"feature": "test-proj"}, worktree_path=str(tmp))`
   - Assert: result == `"# Plan\nBuild the thing"` (file contents, not path string)

2. **Assertion: shared_context with nested variables resolves after two-pass**
   - Setup: Create temp file at `{tmp}/docs/myproj/plan.md`
   - Call: `resolve_template("{{file:docs/{{feature}}/plan.md}}", variables={"feature": "myproj"}, worktree_path=str(tmp))`
   - Assert: result contains file contents (requires Task 1's two-pass fix)

3. **Assertion: bare path without `{{file:...}}` returns literal string (regression guard)**
   - Call: `resolve_template("docs/{{feature}}/plan.md", variables={"feature": "myproj"})`
   - Assert: result == `"docs/myproj/plan.md"` (path string, NOT file contents)

**Functionality (Expected Outcomes)**
- [ ] `shared_context` entries containing `{{feature}}` resolve to actual file paths when run config has `feature` set
- [ ] `shared_context` entries without variables continue to work as before
- [ ] Fan-out execution with `shared_context: ["{{file:docs/{{feature}}/intent.md}}"]` reads the correct file (note the `{{file:...}}` wrapper)
- [ ] `config_vars` is built from `run.config` BEFORE the shared_context loop, not reusing the later `variables` dict

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ -x -q` — all unit tests pass
- [ ] `uv run pytest tests/integration/ -x -q --ignore=tests/integration/test_openhands*.py` — all integration tests pass (excluding openhands which requires uninstalled module)
- [ ] Manually inspect the `executor.py` diff to confirm only the variables parameter was added to the shared_context resolve_template call
- [ ] New test assertions (shared_context with file refs, nested vars, bare path regression) all pass
