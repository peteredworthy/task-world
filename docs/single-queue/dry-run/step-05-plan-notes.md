# Step 05 Dry-Run Analysis: Guards and Documentation

**Step:** 05 (Guards and Documentation)
**Date:** 2026-03-26
**Scope:** Pre-commit guard script + AGENTS.md documentation
**Phase:** 5 (Lock-in constraints via automation and docs)

---

## Overview

Step 05 introduces two enforcement mechanisms:
1. **`scripts/check_signal_routing.py`** — AST-based pre-commit hook that prevents registry function (`has_active_workflow`, `register_active_run`, `unregister_active_run`) usage outside `consumer.py`
2. **AGENTS.md section** — Documents four signal-queue isolation rules

This step has NO runtime behavior changes (it's enforcement + docs). However, it depends heavily on Steps 1-4 being complete. This analysis identifies risks during implementation.

---

## Task 1: Create Pre-Commit Guard Script

### Assumptions

| Assumption | Risk | Mitigation |
|-----------|------|-----------|
| `scripts/check_module_imports.py` exists and is a good pattern to follow | Low | Script exists (verified). Pattern is sound: AST parsing, path normalization, TYPE_CHECKING guard, suppression mechanism. |
| All Python syntax is valid for `ast.parse()` | Medium | Some files may have syntax errors during editing. Script already wraps parse in try/except. |
| The three forbidden function names are exactly: `has_active_workflow`, `register_active_run`, `unregister_active_run` | Low | Verified against intent.md and prior steps. |
| Allowed files are fixed: `consumer.py`, `test_signal_consumer.py`, `test_signal_redelivery.py`, and optionally `test_signal_consumer_integration.py` | Medium | New test files may be created later. Hardcoded list requires manual updates. |
| Path normalization works for all project paths | Medium | Script tries to find `src/orchestrator` or `tests` in path parts. Relative vs. absolute paths may normalize differently. |
| No existing code outside `consumer.py` calls these functions | **CRITICAL** | If Steps 1-4 didn't fully remove disallowed calls, the script will fail on clean codebase. This must be verified. |

### Expected Outputs

- [ ] Script file at `scripts/check_signal_routing.py` with proper shebang
- [ ] Script returns exit code 0 on clean codebase
- [ ] Script returns exit code 1 with clear error messages on violation
- [ ] Script parses and validates all Python files without crashes
- [ ] `# noqa: signal-routing` comments suppress violations

### Failure Mode 1: Path Normalization Edge Cases

**Scenario:** The script's `normalize_path()` function assumes `Path.parts` will contain `src` or `tests` as a directory component. If a file is passed with a relative path that doesn't traverse through `src/` or `tests/`, normalization may fail.

**Evidence:**
```python
# In check_signal_routing.py
def normalize_path(filepath: Path) -> str:
    try:
        parts = filepath.parts
        try:
            src_idx = next(i for i, p in enumerate(parts) if p == "src" or p == "tests")
            return str(Path(*parts[src_idx:]).as_posix())
        except StopIteration:
            return str(filepath.as_posix())  # Fallback
```

If a file is at `scripts/check_signal_routing.py` (no `src` or `tests` in path), it falls back to returning the full path as-is. The `is_allowed_file()` function then checks if any allowed file pattern (which start with `src/` or `tests/`) matches the returned path. This will always fail for `scripts/` files.

**Impact:** Scripts in `scripts/` directory (including this one) won't be recognized as non-allowed, so they won't be checked. However, this is actually correct behavior — scripts don't contain forbidden imports by definition. The real concern is if a legitimate source file uses a relative path starting from `scripts/` level.

**Hardening Action:**
1. Test the script with absolute and relative paths:
   ```bash
   # Absolute path
   python scripts/check_signal_routing.py /full/path/to/src/orchestrator/api/routers.py

   # Relative path
   python scripts/check_signal_routing.py src/orchestrator/api/routers.py

   # From different CWD
   cd src && python ../scripts/check_signal_routing.py orchestrator/api/routers.py
   ```
2. Document that relative paths should be from project root for consistent normalization.

---

### Failure Mode 2: Function Name Collision

**Scenario:** The script flags ALL calls to functions named `has_active_workflow`, `register_active_run`, or `unregister_active_run`, regardless of whether they're the forbidden ones from `signals` module.

**Example:**
```python
# In some_user_module.py
def has_active_workflow(some_param):  # User-defined function with same name
    """My custom implementation."""
    return True

result = has_active_workflow(run_id)  # Script will flag this as a violation!
```

**Evidence:** The script checks `ast.Call` nodes and looks for matching function names:
```python
elif isinstance(node, ast.Call):
    func_name = None
    if isinstance(node.func, ast.Name):
        func_name = node.func.id
    # ... later ...
    if func_name and func_name in FORBIDDEN_NAMES:
        violations.append(...)
```

This is overly broad. It doesn't verify that the function was actually imported from `signals` module.

**Impact:** False positives. If a user defines their own `has_active_workflow()` function, the script will incorrectly flag calls to it.

**Hardening Action:**
1. Refine the script to track imports and only flag calls to imported functions:
   ```python
   # Build a set of "dangerous imports" (imports of forbidden names from signals module)
   dangerous_names = set()
   for node in ast.walk(tree):
       if isinstance(node, ast.ImportFrom):
           if node.module and "signals" in node.module:
               for alias in node.names:
                   if alias.name in FORBIDDEN_NAMES:
                       # Track what name it's imported as
                       local_name = alias.asname or alias.name
                       dangerous_names.add(local_name)

   # Only flag calls to tracked names
   for node in ast.walk(tree):
       if isinstance(node, ast.Call):
           func_name = get_func_name(node.func)
           if func_name in dangerous_names:
               # This is actually a call to a forbidden import
               violations.append(...)
   ```
2. Add a test case: user defines `has_active_workflow()` in their own code, script should NOT flag calls to it.

---

### Failure Mode 3: Attribute Access Pattern

**Scenario:** Code imports the signals module and calls functions via attribute access (e.g., `signals.has_active_workflow(...)`). The current script checks `ast.Attribute` nodes, but the check may be incomplete.

**Code patterns not caught:**
```python
# Pattern 1: Import module, call function
import orchestrator.workflow.signals as signals
signals.has_active_workflow(run_id)  # Does script catch this?

# Pattern 2: Star import
from orchestrator.workflow.signals import *
has_active_workflow(run_id)  # This pattern is already caught

# Pattern 3: Nested attribute
from orchestrator.workflow import signals as sig
sig.signals.has_active_workflow(...)  # Nested imports
```

**Evidence:** The script looks for `ast.Attribute` nodes:
```python
elif isinstance(node.func, ast.Attribute):
    func_name = node.func.attr
    if func_name in FORBIDDEN_NAMES:
        violations.append(...)
```

This catches `signals.has_active_workflow(...)` because `node.func` is an `Attribute` with `attr='has_active_workflow'`. However, it doesn't verify that `signals` is actually the signals module — it just checks the function name.

**Impact:** Same as Failure Mode 2 — false positives if someone has an object named `signals` with a method `has_active_workflow()`.

**Hardening Action:**
1. Same solution as Failure Mode 2: track imports and only flag calls to imported names.
2. Add a test case:
   ```python
   # This should NOT be flagged
   class FakeSignals:
       def has_active_workflow(self): return True

   signals = FakeSignals()
   signals.has_active_workflow()  # User's own object, not the forbidden one
   ```

---

### Failure Mode 4: Allowed Files Don't Exist Yet

**Scenario:** The script lists allowed files in `ALLOWED_FILES`, including `tests/unit/test_signal_consumer.py` and `tests/unit/test_signal_redelivery.py`. These test files don't exist yet; they will be created later (in Phase 6 verification or when tests are written).

**Expected behavior:** The script runs on the codebase and allows these files to use registry functions. If the files don't exist, the script won't check them (which is correct). But if new test files are created with different names, they must be added to `ALLOWED_FILES` manually.

**Impact:** Low during Step 05 (files don't exist, so script doesn't need to allow them). Medium risk post-Step 05 (if new test files are created with different names, the guard script won't recognize them as allowed, and commits will fail).

**Hardening Action:**
1. Add a TODO comment in the script:
   ```python
   # TODO: After test files are created, verify they appear in ALLOWED_FILES
   ALLOWED_FILES = {
       "src/orchestrator/workflow/signals/consumer.py",
       "tests/unit/test_signal_consumer.py",  # Created in Phase 6
       "tests/unit/test_signal_redelivery.py",  # Created in Phase 6
       "tests/unit/test_signal_consumer_integration.py",
   }
   ```
2. Add a pre-commit validation step to check that all test files matching `test_signal_*.py` in `tests/unit/` are in `ALLOWED_FILES`.

---

### Failure Mode 5: Comment-Based Suppression Format

**Scenario:** The script checks for `# noqa: signal-routing` or generic `# noqa` comments to suppress violations. The check looks at the line containing the violation and the line before it.

**Code patterns:**
```python
# Pattern 1: Comment on same line
from orchestrator.workflow.signals import has_active_workflow  # noqa: signal-routing

# Pattern 2: Comment on line before
# noqa: signal-routing
from orchestrator.workflow.signals import has_active_workflow

# Pattern 3: Comment on line after (NOT checked)
from orchestrator.workflow.signals import has_active_workflow
# noqa: signal-routing

# Pattern 4: Generic noqa (should work)
# noqa
from orchestrator.workflow.signals import has_active_workflow
```

**Evidence:** The script checks:
```python
noqa_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
noqa_before = lines[node.lineno - 2] if node.lineno > 1 and node.lineno - 1 <= len(lines) else ""
if has_noqa_suppression(noqa_line) or has_noqa_suppression(noqa_before):
    continue
```

This covers patterns 1, 2, and 4. Pattern 3 (comment after) is not supported.

**Impact:** Low. Comment placement is controllable and documented. Users can suppress violations.

**Hardening Action:**
1. Document in the script's docstring:
   ```python
   """
   Allow-listing: Place `# noqa: signal-routing` on the same line or line before the violation

   CORRECT:
   # noqa: signal-routing
   from orchestrator.workflow.signals import has_active_workflow

   ALSO CORRECT:
   from orchestrator.workflow.signals import has_active_workflow  # noqa: signal-routing

   NOT CHECKED:
   from orchestrator.workflow.signals import has_active_workflow
   # noqa: signal-routing
   """
   ```
2. Test all three valid patterns to ensure they work.

---

### Failure Mode 6: Clean Codebase Assumption

**Scenario:** The script is run on the codebase after Step 05 is implemented. If Steps 1-4 didn't fully remove disallowed function calls, the script will report violations on the "clean" codebase.

**Critical question:** Are we certain that Steps 1-4 have removed ALL calls to `has_active_workflow()`, `register_active_run()`, and `unregister_active_run()` from everywhere except `consumer.py`?

**Evidence:** Need to grep the codebase:
```bash
grep -r "has_active_workflow\|register_active_run\|unregister_active_run" \
  src/orchestrator --exclude-dir=__pycache__ | grep -v "consumer.py"
```

If this returns any matches, Steps 1-4 are incomplete.

**Impact:** CRITICAL. If Steps 1-4 are incomplete, Task 1 will fail at "Verify exit code is 0 on clean codebase".

**Hardening Action:**
1. **BEFORE implementing Task 1:** Run the grep above to confirm no disallowed usage exists.
2. **BEFORE running final validation:** Re-run the grep to ensure nothing was re-introduced.
3. If any matches are found, identify which step (1-4) needs to be revisited.

---

### Failure Mode 7: Script Self-Invocation

**Scenario:** Task 4 runs "Run script on itself (should pass — it's not a consumer file, but it has no imports)". The script is at `scripts/check_signal_routing.py`, which doesn't contain the forbidden function names, so it should pass.

**Expected behavior:** Exit code 0 (no violations).

**Potential issue:** If the script imports these functions (to document what to forbid), it will flag itself as a violation.

**Evidence:** The script's docstring mentions the function names but doesn't import them. However, the line:
```python
FORBIDDEN_NAMES = {"has_active_workflow", "register_active_run", "unregister_active_run"}
```
Just defines strings, so there's no import.

**Impact:** Low. The script is self-contained and has no imports.

**Hardening Action:**
1. Run Task 4 validation step: `uv run python scripts/check_signal_routing.py scripts/check_signal_routing.py`
2. Verify exit code is 0.

---

## Task 2: Integrate Guard Script into Pre-Commit Hooks

### Assumptions

| Assumption | Risk | Mitigation |
|-----------|------|-----------|
| `.pre-commit-config.yaml` exists and is valid YAML | Low | File exists (verified). YAML is syntactically correct. |
| The `local` hooks section exists in the config | Low | Verified: repo `local` exists with multiple hooks (pyright, pytest, module-imports). |
| The hook entry follows the same pattern as `module-imports` | Low | Pattern is clear and consistent. New entry follows structure. |
| `uv run` is available in the pre-commit environment | Low | Pre-commit uses `language: system`, so it runs in current environment. `uv` must be in PATH. |
| Hook filtering with `types: [python]` works correctly | Low | This is a standard pre-commit feature. Same as existing hooks. |

### Expected Outputs

- [ ] New hook entry in `.pre-commit-config.yaml` under `local` section
- [ ] Hook ID is `check-signal-routing`
- [ ] Hook runs `uv run python scripts/check_signal_routing.py`
- [ ] Hook filters to Python files via `types: [python]`
- [ ] Hook passes filenames via `pass_filenames: true`
- [ ] YAML syntax is valid

### Failure Mode 1: YAML Syntax Error

**Scenario:** The new hook entry is malformed YAML, breaking the entire config file.

**Common mistakes:**
```yaml
# WRONG: incorrect indentation (4 spaces instead of 2)
    - id: check-signal-routing
        name: check-signal-routing
        entry: uv run python scripts/check_signal_routing.py

# WRONG: missing spaces after colons
      - id:check-signal-routing

# WRONG: incorrect list syntax (missing dash)
      id: check-signal-routing
```

**Impact:** High. If YAML is broken, pre-commit won't load the config, and all pre-commit hooks fail.

**Hardening Action:**
1. Validate YAML syntax after edit:
   ```bash
   uv run python -c "import yaml; yaml.safe_load(open('.pre-commit-config.yaml')); print('YAML OK')"
   ```
2. Use a YAML linter:
   ```bash
   yamllint .pre-commit-config.yaml
   ```
3. Visually verify indentation matches adjacent hooks (2-space indentation for all keys under `hooks`).

---

### Failure Mode 2: Hook Entry Location

**Scenario:** The new hook is added in the wrong place in the config, either outside the `local` section or in the wrong order.

**Example of wrong location:**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    ...
  - id: check-signal-routing  # WRONG: hook entry, not repo entry
    name: check-signal-routing
    ...
```

**Impact:** Medium. Pre-commit might ignore the hook or raise an error.

**Hardening Action:**
1. Verify the hook is indented under `local` → `hooks`, at the same level as `module-imports`:
   ```yaml
   - repo: local
     hooks:
       - id: pyright
         ...
       - id: pytest
         ...
       - id: module-imports
         ...
       - id: check-signal-routing  # ← Same indentation level
         ...
   ```
2. Run `pre-commit run --help` to verify structure (or check against pre-commit docs).

---

### Failure Mode 3: Hook Execution

**Scenario:** The hook is added to the config, but when running `pre-commit run check-signal-routing --all-files`, it fails to execute.

**Common causes:**
- `uv run` is not in PATH
- `scripts/check_signal_routing.py` doesn't exist (Task 1 not complete)
- Script is not executable (missing shebang or no execute permission)
- File filtering `types: [python]` excludes all files

**Impact:** High if Task 1 isn't complete. Medium if environment issue.

**Hardening Action:**
1. Ensure Task 1 is complete: `ls -la scripts/check_signal_routing.py`
2. Check script has execute permission: `ls -la scripts/check_signal_routing.py | grep ^-r.x`
3. Verify `uv` is in PATH: `which uv`
4. Run hook manually to debug:
   ```bash
   pre-commit run check-signal-routing --all-files --verbose
   ```

---

### Failure Mode 4: File Filtering

**Scenario:** The hook has `types: [python]` and `pass_filenames: true`. If no Python files are staged/modified, the hook may run with an empty file list or skip entirely.

**Expected behavior:** Hook should pass (nothing to check) if no Python files are modified.

**Impact:** Low. This is expected behavior.

**Hardening Action:**
1. Test with a modified Python file:
   ```bash
   echo "# comment" >> src/orchestrator/api/routers/runs.py
   pre-commit run check-signal-routing
   # Should run and report no violations
   git checkout src/orchestrator/api/routers/runs.py
   ```

---

## Task 3: Add Signal-Queue Rules to AGENTS.md

### Assumptions

| Assumption | Risk | Mitigation |
|-----------|------|-----------|
| AGENTS.md exists and is valid Markdown | Low | File exists (verified). Markdown is well-formed. |
| The four rules match intent.md [I-14], [I-15], [I-32], [I-33] exactly | Medium | Rules must be transcribed correctly. Wording matters. |
| Insertion point doesn't break document flow | Low | New section goes after "Agents" and before "UI/UX Constraints" — logical placement. |
| Code examples are realistic and match actual codebase | Medium | Examples must reflect actual patterns (e.g., `app.state`, import paths, function signatures). |
| Markdown formatting is correct (code blocks, lists, emphasis) | Low | Standard Markdown syntax, easy to verify. |

### Expected Outputs

- [ ] New section "## Signal Queue and Runner Isolation" in AGENTS.md
- [ ] Four subsections: "Rule 1", "Rule 2", "Rule 3", "Rule 4"
- [ ] Each rule has a description and code examples (WRONG / RIGHT)
- [ ] Section references enforcement mechanisms (pre-commit hook, code review, tests)
- [ ] Markdown is syntactically valid and renders correctly
- [ ] Inserted at logical location (after "Agents", before other sections)

### Failure Mode 1: Rule Wording Mismatch

**Scenario:** The four rules are transcribed from intent.md, but the wording is paraphrased or shortened, making the documented rule different from the intent.

**Intent.md Rules (from docs):**
1. No registry function calls outside consumer module
2. No process-local state crossing API/executor boundary
3. No `app.state` access from RunWorkflow or executor
4. All lifecycle transitions via signal queue

**Risk if wording is different:**
- Readers might interpret the rules differently
- Code review feedback might reference the intended rule, but docs say something else
- Future agents might not enforce the exact intent

**Impact:** Medium. Rules are guidance, not code, so exact wording is important but not critical.

**Hardening Action:**
1. Cross-check each rule against intent.md [I-14], [I-15], [I-32], [I-33] word-for-word.
2. Include citations in the AGENTS.md section:
   ```markdown
   ### Rule 1: No Registry Function Calls Outside Consumer Module

   **From intent.md [I-04], [I-29], [I-30]:**
   The active-run registry (`register_active_run()`, `unregister_active_run()`, `has_active_workflow()`)
   is owned solely by `src/orchestrator/workflow/signals/consumer.py`. ...
   ```
3. Have a human reviewer compare the final text against intent.md before committing.

---

### Failure Mode 2: Code Examples Don't Match Codebase

**Scenario:** The WRONG/RIGHT code examples use module paths, class names, or function signatures that don't match the actual codebase.

**Examples that could be wrong:**
```python
# WRONG example might use old module path
from orchestrator.workflow.service import has_active_workflow  # But it's actually in signals.py

# RIGHT example might reference non-existent class/method
executor = AgentRunnerExecutor(config=config, ...)  # But the class might have different params
```

**Impact:** Medium. Code examples are illustrative, but if they're wrong, they mislead readers.

**Hardening Action:**
1. Before writing Task 3, verify actual code:
   ```bash
   grep -r "class AgentRunnerExecutor" src/
   grep -r "def __init__" src/orchestrator/executor.py | head -5
   grep -r "class WorkflowService" src/
   ```
2. Copy actual code patterns from the codebase (don't invent examples).
3. Use realistic imports that actually work:
   ```python
   # RIGHT: from orchestrator.workflow.signals.consumer import register_active_run
   register_active_run(run_id, workflow)
   ```
4. Have a human verify that copy-pasted code examples are actual patterns in the codebase.

---

### Failure Mode 3: Markdown Formatting Errors

**Scenario:** The new section has Markdown syntax errors (unclosed code blocks, wrong list formatting, etc.).

**Common mistakes:**
```markdown
# WRONG: unclosed code block
### Rule 1
```python
def foo():

Rule 1 description continues...  # This is still inside the code block!

# WRONG: incorrect list indentation
1. First point
2. Second point
   - Sub-point (4 spaces, but may need alignment)

# WRONG: emphasis syntax
**Bold text (correct)
_Italic_ (correct with underscores)
**Bold and italic** (this is just bold, not both)
```

**Impact:** Medium. Markdown rendering may break, making the section hard to read.

**Hardening Action:**
1. Preview the Markdown after edit:
   ```bash
   # Use a Markdown linter
   markdownlint AGENTS.md
   # Or view in GitHub/editor with preview
   ```
2. Verify code blocks are closed properly:
   ```bash
   grep -n "^[`]{3}" AGENTS.md | tail -20  # Should have even count
   ```
3. Visually check lists and emphasis in editor before committing.

---

### Failure Mode 4: Insertion Point Disrupts Document Flow

**Scenario:** The new section is inserted at a location that breaks the logical flow or disrupts an existing section.

**Example:** If the insertion point is mid-section (e.g., in the middle of the "Agents" section), it will split the section into two parts.

**Impact:** Low if insertion point is between major sections. High if insertion point is mid-section.

**Hardening Action:**
1. Identify the exact insertion point:
   ```bash
   grep -n "### Model Profiles\|### Agents\|## UI/UX Constraints" AGENTS.md
   ```
   Example output:
   ```
   107:### Model Profiles
   128:### Agents
   186:## UI/UX Constraints
   ```
   The new section should be inserted between line 184 and 186 (after "Agents" section ends).

2. Verify the insertion point is between two complete sections:
   ```bash
   sed -n '180,190p' AGENTS.md  # View context around insertion point
   ```
3. Insert the section at the right indentation level (## for section, not ### for subsection, unless it's a subsection).

---

### Failure Mode 5: Missing or Incomplete Rules

**Scenario:** The implementation misses one of the four rules, or a rule is incomplete (missing description or code examples).

**Risk:** Requirements not met. Verification step will fail:
```python
for i in 1 2 3 4; do
  grep -q "### Rule $i:" AGENTS.md && echo "Rule $i: OK" || echo "Rule $i: MISSING"
done
```

**Impact:** CRITICAL. Requirement [I-33] explicitly specifies all four rules.

**Hardening Action:**
1. Before Task 3, create a checklist of four rules with expected content:
   ```
   - [ ] Rule 1: No Registry Function Calls (description + WRONG/RIGHT examples)
   - [ ] Rule 2: No Process-Local State Crossing (description + examples)
   - [ ] Rule 3: No `app.state` Access (description + examples)
   - [ ] Rule 4: All Lifecycle Transitions via Signal Queue (description + examples)
   ```
2. After writing Task 3, verify each rule is present and complete:
   ```bash
   grep -A 2 "### Rule 1:" AGENTS.md | wc -l  # Should have at least 3 lines (header + description)
   ```
3. Have the verification step from Task 3 confirm all four rules.

---

## Task 4: Validate Guard Script with Negative Test

### Assumptions

| Assumption | Risk | Mitigation |
|-----------|------|-----------|
| Temporary files can be created in `/tmp/` | Low | `/tmp/` is writable on all Unix systems. |
| Shell script with exit code checking works correctly | Low | Standard bash pattern. |
| Script is deterministic (same input always produces same output) | Low | AST parsing is deterministic. |
| Cleanup removes temporary files | Low | Explicit `rm` commands. |

### Expected Outputs

- [ ] Guard script detects violation in test file (exit code 1)
- [ ] Guard script respects suppression comment (exit code 0)
- [ ] Guard script passes on clean codebase (exit code 0)
- [ ] Error messages are clear and actionable

### Failure Mode 1: Temporary File Path Normalization

**Scenario:** Temporary test files are created in `/tmp/test_violation.py`, but the script's path normalization expects paths relative to project root or containing `src/orchestrator` or `tests/`.

**Script path normalization logic:**
```python
def normalize_path(filepath: Path) -> str:
    try:
        parts = filepath.parts
        try:
            src_idx = next(i for i, p in enumerate(parts) if p == "src" or p == "tests")
            return str(Path(*parts[src_idx:]).as_posix())
        except StopIteration:
            return str(filepath.as_posix())
```

If `/tmp/test_violation.py` is passed:
- `parts = ('/', 'tmp', 'test_violation.py')`
- No `src` or `tests` found → returns `/tmp/test_violation.py` as fallback
- `is_allowed_file('/tmp/test_violation.py')` checks if any ALLOWED_FILES pattern matches → NO
- File is NOT in allowed list → violations will be flagged ✓

Expected behavior: The temporary file is NOT allowed, so violations should be flagged. This is correct!

**Impact:** Low. The script behaves as expected for non-project files.

**Hardening Action:**
1. Verify the script handles `/tmp/` paths correctly:
   ```bash
   cat > /tmp/test_violation.py << 'EOF'
   from orchestrator.workflow.signals import has_active_workflow
   EOF

   python scripts/check_signal_routing.py /tmp/test_violation.py
   # Should exit with code 1 (violation found)
   ```
2. If the script passes a non-violation test, update the test to use absolute paths and verify the error message is clear.

---

### Failure Mode 2: Exit Code Not Propagated

**Scenario:** The test script runs the guard script but doesn't properly capture or check the exit code.

**Example of wrong test:**
```bash
uv run python scripts/check_signal_routing.py /tmp/test_violation.py
# Forgot to check $?
TEST_RESULT=$?  # This is correct
if [ $TEST_RESULT -eq 1 ]; then
  echo "PASS"
fi
```

**Expected behavior:** Each guard script invocation should be followed by `echo $?` or stored in a variable.

**Impact:** Medium. If exit codes aren't checked, tests might pass even though the script failed.

**Hardening Action:**
1. Always capture exit code immediately after command:
   ```bash
   uv run python scripts/check_signal_routing.py /tmp/test_violation.py
   RESULT=$?

   if [ $RESULT -eq 1 ]; then
     echo "PASS: Violation detected"
   else
     echo "FAIL: Exit code was $RESULT, expected 1"
     exit 1
   fi
   ```
2. Use explicit `[ $? -eq X ]` checks in the task steps.

---

### Failure Mode 3: Glob Pattern Issues in Final Test

**Scenario:** The final validation step uses `uv run python scripts/check_signal_routing.py src/**/*.py tests/**/*.py`, which relies on shell glob expansion. This may not work as expected in all shells.

**Potential issue:** If glob doesn't expand, the script receives literal strings like `src/**/*.py` instead of file paths.

**Impact:** Medium. The test might fail on some shells or environments.

**Hardening Action:**
1. Replace glob with `find` for reliability:
   ```bash
   uv run python scripts/check_signal_routing.py $(find src tests -name "*.py" -type f)
   ```
2. Or use explicit `set -o globstar` in bash:
   ```bash
   shopt -s globstar
   uv run python scripts/check_signal_routing.py src/**/*.py tests/**/*.py
   ```
3. Test on both bash and zsh to ensure compatibility.

---

### Failure Mode 4: Suppression Comment Format Validation

**Scenario:** Task 4 creates a test file with `# noqa: signal-routing` suppression, but the comment format doesn't match what the script expects.

**Script checks:**
```python
def has_noqa_suppression(line_before: str) -> bool:
    return "# noqa: signal-routing" in line_before or "# noqa" in line_before
```

**Test creates:**
```python
cat > /tmp/test_suppressed.py << 'EOF'
# noqa: signal-routing
from orchestrator.workflow.signals import has_active_workflow
EOF
```

This should work because the comment is on the line before the import.

**But what if:**
```python
cat > /tmp/test_suppressed.py << 'EOF'
from orchestrator.workflow.signals import has_active_workflow
# noqa: signal-routing
EOF
```

Comment is on the line AFTER the import. Script WON'T suppress because it only checks current and previous lines.

**Impact:** Low. The task correctly places the comment before the violation. But if someone later uses the wrong format, it won't work.

**Hardening Action:**
1. Document the comment placement requirement in the task:
   ```bash
   # Comment must be on same line or line BEFORE the violation
   # noqa: signal-routing
   from orchestrator.workflow.signals import has_active_workflow
   ```
2. Test both valid placements:
   ```bash
   # Test 1: Comment on line before
   cat > /tmp/test_before.py << 'EOF'
   # noqa: signal-routing
   from orchestrator.workflow.signals import has_active_workflow
   EOF

   # Test 2: Comment on same line
   cat > /tmp/test_same.py << 'EOF'
   from orchestrator.workflow.signals import has_active_workflow  # noqa: signal-routing
   EOF

   # Both should pass (exit code 0)
   ```

---

## Cross-Cutting Risks

### Risk 1: Steps 1-4 Incomplete

**Issue:** Step 05 assumes Steps 1-4 (Schema → Consumer → Sender → Registry) are fully complete. If any of these steps is incomplete, Step 05 will fail.

**Critical verification:**
1. Consumer module exists and handles all signal types
2. WorkflowService methods enqueue signals (not direct spawns)
3. `register_active_run()` and `unregister_active_run()` are ONLY called from `consumer.py`
4. No existing code calls disallowed registry functions

**Test:**
```bash
# Verify no disallowed calls exist
grep -r "has_active_workflow\|register_active_run\|unregister_active_run" \
  src/orchestrator --exclude-dir=__pycache__ | grep -v "consumer.py" | grep -v test_

# Should return NOTHING
```

**Mitigation:** Before Task 1, run the grep above. If it returns matches, identify which step needs completion.

---

### Risk 2: Component Wiring Not Verified

**Issue:** Task 1 creates the guard script, but doesn't verify that the guard script is actually USED by anything. The script could be perfect, but if no one runs it, the invariants aren't enforced.

**Missing verification:**
1. Is the script added to pre-commit (Task 2)? ✓
2. Will developers run pre-commit before committing? (Depends on setup)
3. Is there a CI/CD check that runs the script? (Not mentioned in Step 05)

**Mitigation:**
1. Verify Task 2 (pre-commit integration) is complete
2. Verify developers are running pre-commit (check `.git/hooks/pre-commit` or `git hooks` config)
3. Consider adding the script to CI/CD pipeline (GitHub Actions, etc.) if it's not already there

---

### Risk 3: AGENTS.md Not Read/Updated by Developers

**Issue:** Task 3 adds rules to AGENTS.md, but there's no guarantee developers read it or follow the rules. Documentation is guidance, not enforcement.

**Enforcement hierarchy:**
1. Code enforcement (pre-commit guard script) ← Task 1, 2
2. Documentation (AGENTS.md rules) ← Task 3
3. Code review (human judgment)

**Mitigation:**
1. The pre-commit guard script (Task 1) is the primary enforcement mechanism
2. AGENTS.md is secondary (guidance for developers)
3. Add a link to AGENTS.md from the pre-commit guard script error message:
   ```python
   print(
       "\nFor more information, see AGENTS.md → 'Signal Queue and Runner Isolation'\n",
       file=sys.stderr,
   )
   ```

---

### Risk 4: Test Coverage for Guard Script

**Issue:** Task 4 includes negative tests (intentional violations), but these are one-off manual tests, not permanent unit tests.

**Problem:** If the guard script is later modified and a bug is introduced, there's no permanent test to catch it.

**Mitigation:**
1. Add permanent unit tests to `tests/unit/test_check_signal_routing.py`:
   ```python
   def test_detects_import_violation(tmp_path):
       """Guard script detects imports of forbidden names."""
       test_file = tmp_path / "bad_module.py"
       test_file.write_text("from orchestrator.workflow.signals import has_active_workflow")

       result = subprocess.run(
           ["python", "scripts/check_signal_routing.py", str(test_file)],
           capture_output=True
       )
       assert result.returncode == 1
       assert "has_active_workflow" in result.stderr

   def test_respects_suppression(tmp_path):
       """Guard script respects noqa suppression."""
       test_file = tmp_path / "suppressed.py"
       test_file.write_text(
           "# noqa: signal-routing\n"
           "from orchestrator.workflow.signals import has_active_workflow"
       )

       result = subprocess.run(
           ["python", "scripts/check_signal_routing.py", str(test_file)],
           capture_output=True
       )
       assert result.returncode == 0
   ```
2. Run these tests in pre-commit or CI/CD to catch regressions.

---

## Summary of Hardening Actions

| Failure Mode | Hardening Action | Priority |
|---|---|---|
| Path normalization edge cases (Task 1.1) | Test with absolute/relative paths from different CWDs | Medium |
| Function name collision (Task 1.2) | Improve detection to track imports, not just names | High |
| Allowed files don't exist yet (Task 1.4) | Add TODO comment, plan for future test files | Low |
| YAML syntax error (Task 2.1) | Validate with yaml.safe_load() and yamllint | High |
| Hook entry location (Task 2.2) | Visually verify indentation matches adjacent hooks | Medium |
| Hook execution fails (Task 2.3) | Debug with `pre-commit run --verbose` | Medium |
| Rule wording mismatch (Task 3.1) | Cross-check against intent.md, include citations | Medium |
| Code examples don't match codebase (Task 3.2) | Copy actual patterns from source, have human verify | High |
| Markdown formatting errors (Task 3.3) | Use markdownlint, verify code blocks are closed | Low |
| Missing or incomplete rules (Task 3.5) | Create checklist before implementation, verify after | High |
| Temporary file path normalization (Task 4.1) | Use absolute paths, verify exit codes are correct | Low |
| Exit code not propagated (Task 4.2) | Always capture $? immediately after command | Medium |
| Glob pattern issues (Task 4.3) | Use find instead of glob for reliability | Low |
| Steps 1-4 incomplete (Cross-cutting) | Run grep to verify no disallowed calls exist | **CRITICAL** |
| Component wiring not verified (Cross-cutting) | Verify pre-commit integration and CI/CD checks | High |
| AGENTS.md not read by developers (Cross-cutting) | Add link in guard script error message | Low |
| No permanent tests for guard script (Cross-cutting) | Add unit tests to test suite | Medium |

---

## Dependency Verification Checklist

Before implementing Step 05, verify:

- [ ] Step 1 complete: Schema changes (STOPPING status, signal table PK)
- [ ] Step 2 complete: Consumer module exists and handles all signals
- [ ] Step 3 complete: WorkflowService methods enqueue signals only
- [ ] Step 4 complete: Registry functions isolated to consumer.py
- [ ] No disallowed registry function calls in codebase:
  ```bash
  grep -r "has_active_workflow\|register_active_run\|unregister_active_run" \
    src/orchestrator --exclude-dir=__pycache__ | grep -v "consumer.py" | grep -v test_
  ```
- [ ] `.pre-commit-config.yaml` exists and is valid YAML
- [ ] `AGENTS.md` exists and is well-formed Markdown
- [ ] `scripts/check_module_imports.py` exists (for reference pattern)
- [ ] All developers have pre-commit installed: `pre-commit --version`

---

## Final Verification Criteria (From Step Plan)

| Criterion | Verification Command | Expected Result |
|-----------|----------------------|-----------------|
| Guard script passes on clean codebase | `python scripts/check_signal_routing.py src/**/*.py tests/**/*.py` | Exit code 0 |
| Guard script detects violations | `echo "from orchestrator.workflow.signals import has_active_workflow" \| python scripts/check_signal_routing.py /dev/stdin` | Exit code 1 |
| Pre-commit hook is configured | `grep -q "check-signal-routing" .pre-commit-config.yaml` | Match found |
| AGENTS.md has new section | `grep -q "## Signal Queue and Runner Isolation" AGENTS.md` | Match found |
| All four rules documented | `for i in 1 2 3 4; do grep -q "### Rule $i:" AGENTS.md \|\| exit 1; done` | All 4 rules present |
| Pre-commit hook runs | `pre-commit run check-signal-routing --all-files` | Exit code 0 (no violations) |

---

## Notes for Implementation

1. **Start with dependency verification:** Before Task 1, confirm Steps 1-4 are complete by running the grep for disallowed calls.

2. **Implement in order:** Task 1 (create script) → Task 2 (integrate hook) → Task 3 (docs) → Task 4 (validate). Each task depends on previous ones.

3. **Function name collision issue:** The current script design will produce false positives if user code defines functions with the same names. This should be fixed before Task 1 is considered complete.

4. **Test file placement:** The script lists allowed test files that don't exist yet. Document this assumption so future test creation doesn't surprise developers.

5. **AGENTS.md insertion point:** Insert new section after line 184 (end of "Agents" section), before line 186 ("## UI/UX Constraints").

6. **Commit together:** Commit Tasks 1, 2, 3 together (guard script, hook config, docs) so they arrive in the codebase at the same time. This prevents a state where the hook is configured but the script doesn't exist.

