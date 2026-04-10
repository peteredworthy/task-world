# Step 5 Dry-Run Analysis: Guards and Documentation

**Date:** 2026-03-26
**Step:** `docs/single-queue-2/steps/step-05-plan.md`
**Status:** Pre-implementation analysis

---

## Pre-Run State Verification

Current codebase state (before Step 5 runs):

| Item | State |
|---|---|
| `scripts/check_signal_routing.py` | Does NOT exist |
| `consumer.py` | Does NOT exist (built in S-02) |
| `test_signal_consumer.py` | Does NOT exist |
| `test_signal_redelivery.py` | Does NOT exist |
| `signals.py` registry functions | Still defined and exported |
| `runtime.py` registry calls | Still present (S-03 not done) |
| `service.py` registry calls | Still present (S-03 not done) |
| `workflow/__init__.py` re-exports | Still present |
| `signals/__init__.py` re-exports | Still present |
| AGENTS.md section | Does NOT exist |
| `.pre-commit-config.yaml` hook | Does NOT exist |

**Critical dependency:** Step 5 has an explicit prerequisite that S-04 is complete.
The clean-codebase check in Task 3 WILL fail if S-04 is incomplete, since `runtime.py`
and `service.py` still call registry functions. This is by design — the step's Task 3
guidance explicitly says: "If violations are found, they indicate S-04 is incomplete —
do not proceed; fix S-04 first."

---

## Task-by-Task Analysis

### Task 1: Create `scripts/check_signal_routing.py`

**Assumptions:**
- `scripts/` directory exists (verified — `check_module_imports.py` is there).
- The guard script will not import from the `orchestrator` package (correct — only uses `ast`, `sys`, `pathlib`).
- `consumer.py` doesn't exist during execution of this step, but the guard still needs to be logically correct for when it does exist.

**Expected outputs:**
- New file `scripts/check_signal_routing.py` with AST-based checking.
- File is executable (`chmod +x`).

**Assumptions about `is_allowed_file()`:**

The function uses only `filepath.name` (the filename, not the full path):
```python
def is_allowed_file(filepath: Path) -> bool:
    name = filepath.name
    if name == "consumer.py":
        return True
    if name.startswith("test_") and "consumer" in name:
        return True
    return False
```

This means:
- **Any file named `consumer.py` in any directory** would be exempted. If another module (e.g., `api/consumer.py`) happens to be created later, it would be incorrectly exempted from the registry function checks. Risk is low since the restricted function names are unique, but it's a brittle guarantee.
- **`test_signal_redelivery.py` is NOT exempted.** The plan (Phase 2, Step 2.3) explicitly creates `tests/unit/test_signal_redelivery.py` and its purpose is to test crash recovery. Such tests will almost certainly call `has_active_workflow()` to assert whether a run is active before/after redelivery. The guard would flag this file as a violation, blocking commits.
- `test_signal_consumer.py` IS exempted (contains "consumer" in name). OK.
- `test_check_signal_routing.py` (mentioned in the architecture doc's testing strategy) does NOT contain "consumer", so it would NOT be exempted. This file likely tests the guard script itself, not the consumer, so it probably won't import registry functions. Low risk.

**Blocker — `test_signal_redelivery.py` false positive:** This is the most likely real failure mode in Step 5. When S-02 creates `test_signal_redelivery.py` and that test calls `has_active_workflow()` to verify state, the guard immediately blocks commits. The `is_allowed_file()` logic needs to also exempt files with "redelivery" in the name, OR the guard should use a path-based check (e.g., `"signals/consumer" in str(filepath)`) alongside a more inclusive test-file rule.

**Minor gap — multiline parenthesized imports:** Python allows:
```python
from orchestrator.workflow.signals import (
    register_active_run,  # noqa: signal-routing  ← suppression on WRONG line
)
```
`ast.ImportFrom.lineno` points to the `from` line, not the individual alias lines. The `is_suppressed(node.lineno)` call checks the `from` line for the suppression comment, not the line where the specific name appears. This means `# noqa: signal-routing` placed on the alias line (not the `from` line) would NOT suppress the violation. Low risk (imports with parentheses are uncommon for this pattern), but worth documenting.

**Detection correctness:**
- `from X import register_active_run as rr` → `alias.name` is still `register_active_run` → correctly detected. ✓
- `obj.register_active_run()` → `func.attr == "register_active_run"` → correctly detected. ✓
- `fn = register_active_run; fn()` → NOT detected (indirect call). Acceptable; this is an obscure pattern.

### Task 2: Add Pre-Commit Hook

**Assumptions:**
- `.pre-commit-config.yaml` exists with a `local` repo block (verified — contains `module-imports` at line 29).

**Proposed YAML to insert:**
```yaml
      - id: signal-routing
        name: signal-routing
        entry: uv run python scripts/check_signal_routing.py
        language: system
        types: [python]
        pass_filenames: true
```

This exactly matches the format of `module-imports` (lines 29-34 of the current YAML). Placement "immediately after module-imports" means between the `pass_filenames: true` line of `module-imports` and the `- id: ui-lint` line. The YAML indentation is consistent. ✓

**No blockers.** Straightforward insertion.

### Task 3: Verify Script Passes on Clean Codebase

**Assumptions:**
- S-04 is complete. All registry function imports/calls removed from `runtime.py`, `service.py`, and both `__init__.py` files.

**Current violations that MUST be resolved by S-04 for this task to pass:**

| File | Lines | Functions |
|---|---|---|
| `signals/runtime.py` | 38-39, 176, 183, 195, 205, 286, 310+ | `register_active_run`, `unregister_active_run` |
| `workflow/service.py` | 318, 321, 435, 438, 481, 484, 1100, 1112 | `has_active_workflow` |
| `signals/__init__.py` | 10-12 (import lines), 38-39, 42 | all three (import + re-export) |
| `workflow/__init__.py` | 106-107, 110 (import lines), 264-265, 268 | all three (import + re-export) |

**Note on `__init__.py` cleanup:** S-04 is expected to remove these from `__all__`. However, if S-04 removes them from `__all__` but leaves the bare `import` statements in the file body, the guard WILL flag the `__init__.py` files. Task 3 correctly catches this as an S-04 incompleteness issue.

**This task is purely verification — no files changed.** If the guard exits 0, S-04 is confirmed complete from the guard's perspective.

### Task 4: Verify Script Catches Violations

**Assumptions:**
- Guard script exists (Task 1 complete).
- Temp file written to `/tmp/test_violation.py`.

**Logic check for the temp file:**
```python
from orchestrator.workflow.signals import register_active_run  # violation

def allowed():
    from orchestrator.workflow.signals import register_active_run  # noqa: signal-routing
```

- Line 1: `ast.ImportFrom` with `alias.name == "register_active_run"`. `is_suppressed(1)` checks `lines[0]` which is `from orchestrator... import register_active_run  # violation` — no `# noqa: signal-routing` → violation reported. ✓
- Line 4: `ast.ImportFrom` with same alias. `is_suppressed(4)` checks `lines[3]` which contains `# noqa: signal-routing` → suppressed. ✓

**Expected: exactly 1 violation on line 1, exit code 1.** Logic is correct.

**Note:** The temp file path `/tmp/test_violation.py` matches the sandbox whitelist (`/tmp` is writable). ✓

**Note:** `/tmp/test_violation.py` starts with `test_` but does NOT contain "consumer". So `is_allowed_file()` returns False (both conditions required: `startswith("test_")` AND `"consumer" in name`). The violation will be reported. ✓

### Task 5: Add "Signal Queue and Runner Isolation" to AGENTS.md

**Assumptions:**
- `AGENTS.md` exists (verified — it's a long document with module boundary, testing, and other architectural sections).
- The step says to place it "near other architectural rules (e.g., near the module boundary or testing sections)" but NOT inside an existing subsection. This is slightly vague.
- The auto-verify grep checks for exact section heading: `## Signal Queue and Runner Isolation`.

**No functional blockers.** The content to add is explicitly provided in the step. The placement guidance is vague but the verification only checks that the section exists and specific phrases appear — not the exact location.

**File modification scope:** Only `AGENTS.md`. ✓

---

## Failure Modes

### F-1: `test_signal_redelivery.py` NOT exempted by `is_allowed_file()` [HIGH]

**Description:** The `is_allowed_file()` function exempts test files containing "consumer" in the name. `test_signal_redelivery.py` (created in S-02) does not contain "consumer", so it is NOT exempted. When this test file calls `has_active_workflow()` to assert crash recovery behavior (its primary purpose), the guard flags a violation. This would block all commits once S-02 is complete and this test file exists.

**Evidence:** Plan §2.3 explicitly creates `tests/unit/test_signal_redelivery.py` as a test for "unhandled signals on startup". Such tests must call `has_active_workflow()` to verify pre/post state. Architecture doc §Testing Strategy lists `test_signal_redelivery.py` as a test file for the consumer area.

**Hardening Action:** Add `"redelivery" in name` as an additional exemption condition in `is_allowed_file()`:
```python
if name.startswith("test_") and ("consumer" in name or "redelivery" in name):
    return True
```
Or more robustly, use a configurable allow list that matches all test files in the same test directory as the consumer tests.

### F-2: `is_allowed_file()` is name-only, not path-scoped [LOW]

**Description:** Any file named `consumer.py` in any directory is exempted from the guard. If a future module happens to create `api/consumer.py`, that file would be silently exempted from registry function checks.

**Evidence:** The function checks `filepath.name`, not the full path. A path check like `"signals/consumer" in str(filepath)` would be more precise.

**Hardening Action:** Add a path-scope requirement for the `consumer.py` exemption:
```python
if name == "consumer.py" and "signals" in str(filepath):
    return True
```

### F-3: Multiline import `# noqa` suppression lands on wrong line [LOW]

**Description:** For parenthesized multi-line imports, `ast.ImportFrom.lineno` points to the `from` keyword line. If a suppression comment is placed on the specific alias line inside the parens (not the `from` line), `is_suppressed()` checks the wrong line and does not suppress the violation.

**Evidence:** Python AST: `ast.ImportFrom.lineno` is the first line of the statement. The `is_suppressed()` function checks `lines[lineno - 1]` which is the `from` line.

**Impact:** Low — multi-line imports of restricted functions are unusual. The workaround is to place `# noqa: signal-routing` on the `from` line.

**Hardening Action:** Document in the script's docstring that the suppression comment must appear on the `from ... import` line, not on individual alias lines within parentheses. No code change needed.

### F-4: Guard script not yet testable against `consumer.py` during this step [INFO]

**Description:** The step's "Functionality (Expected Outcomes)" includes "Script exits 0 when passed only `consumer.py` as input, even though it contains calls to restricted functions." However, `consumer.py` doesn't exist during Step 5 (created in S-02). The final verification checklist does NOT include this test — it only tests the script against itself and a temp violation file. This gap means the consumer.py exemption is not verified until S-02 creates the file.

**Impact:** Informational only. The exemption logic is correct and will work when the file is created. No runtime failure from this.

**Hardening Action:** Add to Step 5's final verification: once `consumer.py` exists (in S-02 or later), run `uv run python scripts/check_signal_routing.py path/to/consumer.py` and confirm exit 0. This can be noted as a deferred verification rather than blocking Step 5 completion.

### F-5: `__init__.py` import lines may survive S-04 cleanup [MEDIUM]

**Description:** S-04 is expected to remove registry functions from `__init__.py` exports. If S-04 removes them from `__all__` but leaves the `import` lines in `__init__.py`, the guard in Task 3 will report violations in `signals/__init__.py` and `workflow/__init__.py`. These are NOT `consumer.py` or consumer test files, so they will correctly be flagged.

**Impact:** Medium — this is a valid guard catch. The behavior is correct (Task 3 instructions say to fix S-04 if violations are found). No false logic issue.

**Hardening Action:** Add explicit note to Step 5 Task 3: "If violations appear in `__init__.py` files, S-04 must fully remove the import lines (not just remove from `__all__`)."

### F-6: Component wiring — guard is self-contained, no active code path wiring [INFO]

**Description:** Step 5 introduces a pre-commit guard script. Unlike consumer handlers or service rewiring, this component doesn't require wiring into the running application. The script is invoked by the pre-commit framework, not by the server process. No "old code path still used" risk.

**Evidence:** The hook is registered in `.pre-commit-config.yaml` with `pass_filenames: true`, which is how pre-commit passes staged file paths. The script's `main(sys.argv[1:])` matches this interface. ✓

### F-7: AGENTS.md placement vagueness may produce awkward section location [LOW]

**Description:** The step says "Place it near other architectural rules... Do not place it inside an existing subsection." The AGENTS.md is a long document with many sections. Without a specific anchor point (e.g., "after the Non-Negotiable Constraints section"), an implementer might place the section in an awkward location.

**Impact:** Low — the auto-verify only checks that the section heading and four rule headings exist, not their location.

**Hardening Action:** Specify the exact insertion point in AGENTS.md, e.g., "after the 'Non-Negotiable Constraints' section" or "before the 'Agent Runners' section."

---

## Summary Table

| Failure Mode | Severity | Probability | Action |
|---|---|---|---|
| F-1: `test_signal_redelivery.py` not exempted | HIGH | HIGH | Add "redelivery" to `is_allowed_file()` exemptions |
| F-2: Name-only allow check in `is_allowed_file()` | LOW | LOW | Add path scope check |
| F-3: Multi-line import suppression on wrong line | LOW | LOW | Document in script docstring |
| F-4: Consumer.py exemption unverified during step | INFO | N/A | Defer verification to S-02 |
| F-5: `__init__.py` import lines survive S-04 | MEDIUM | MEDIUM | Task 3 catches this; clarify in notes |
| F-6: No component wiring risk | INFO | N/A | No action needed |
| F-7: AGENTS.md placement vagueness | LOW | LOW | Specify exact insertion anchor |

---

## Overall Assessment

Step 5 is structurally sound. The guard script logic is correct for the common cases.
The AST-based approach is well-designed (avoids false positives from comments/strings).
The pre-commit hook format matches the existing pattern exactly.

**One hardening action is critical before implementation:**

**F-1 must be fixed before the guard script is finalized.** `test_signal_redelivery.py`
is a planned test file (S-02, Step 2.3) that will call registry functions legitimately.
The `is_allowed_file()` function must be expanded to exempt it. Without this fix, the
guard will block commits the moment S-02 is complete, requiring a follow-up patch to
the guard script — defeating the purpose of doing the dry-run analysis.

**Recommended fix for `is_allowed_file()`:**

```python
def is_allowed_file(filepath: Path) -> bool:
    name = filepath.name
    # The consumer module itself (require signals path to avoid false exemptions)
    if name == "consumer.py" and "signals" in str(filepath):
        return True
    # Test files covering the consumer (consumer, redelivery)
    if name.startswith("test_") and any(kw in name for kw in ("consumer", "redelivery")):
        return True
    return False
```

All other tasks (pre-commit hook, AGENTS.md update, verification tasks) are
straightforward and will execute correctly given S-04 completion.
