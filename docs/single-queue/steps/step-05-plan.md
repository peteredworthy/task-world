# Step 05: Guards and Documentation

This step locks in the signal-queue architecture with automated enforcement and documentation.
The pre-commit guard script prevents regression by catching disallowed imports/calls of registry
functions. The AGENTS.md rules codify the architectural boundaries that the consumer module protects.
Together, these ensure the new invariants remain locked even as the codebase evolves.

## Intent Verification

**Original Intent**: [I-14], [I-15], [I-32], [I-33] from intent.md

**Functionality to Produce**:
- `scripts/check_signal_routing.py` — AST-based pre-commit guard that fails if `has_active_workflow`, `register_active_run`, or `unregister_active_run` are imported or called outside `consumer.py` (and its test file)
- Pre-commit hook entry in `.pre-commit-config.yaml` that runs the guard script on all Python files
- New section in `AGENTS.md` titled "Signal Queue and Runner Isolation" documenting four architectural rules

**Final Verification Criteria**:
- Guard script passes on clean codebase (all existing imports are legal)
- Guard script fails when a test violation (illegal import) is introduced
- Guard script passes again when violation is removed
- AGENTS.md section exists and documents all four rules exactly as specified in the PRD
- Pre-commit hook runs successfully with `pre-commit run check-signal-routing`

---

## Task 1: Create Pre-Commit Guard Script for Signal Routing

**Description**:
Create a new Python script that uses AST analysis to enforce that registry functions
(`has_active_workflow`, `register_active_run`, `unregister_active_run`) are only imported
or called within `consumer.py` and its test file. Model the script after the existing
`scripts/check_module_imports.py` to maintain consistency.

**Implementation Plan (Do These Steps)**:

The guard script will:
1. Parse all Python files using the `ast` module
2. Detect `ImportFrom` statements that import the three forbidden names
3. Detect `Call` nodes that call these functions (e.g., `has_active_workflow(...)`)
4. Report violations with file, line number, and context
5. Support allow-listing via `# noqa: signal-routing` comment on the line above the violation

- [ ] Create new file `scripts/check_signal_routing.py`

```python
#!/usr/bin/env python3
"""
Enforce signal routing isolation: registry functions only in consumer.py.

Registry functions (has_active_workflow, register_active_run, unregister_active_run)
manage the in-process active-run registry. They must only be called from within
src/orchestrator/workflow/signals/consumer.py and its test file
(tests/unit/test_signal_consumer.py, tests/unit/test_signal_redelivery.py).

WRONG: from orchestrator.workflow.signals import has_active_workflow  (in service.py)
RIGHT: called only within consumer.py

WRONG: if has_active_workflow(run_id):  (in executor.py)
RIGHT: consumer.py owns all registry access

Allow-listing: # noqa: signal-routing
"""

import ast
import sys
from pathlib import Path

# Names that must stay isolated to consumer.py
FORBIDDEN_NAMES = {"has_active_workflow", "register_active_run", "unregister_active_run"}

# Files where these names are allowed
ALLOWED_FILES = {
    "src/orchestrator/workflow/signals/consumer.py",
    "tests/unit/test_signal_consumer.py",
    "tests/unit/test_signal_redelivery.py",
    "tests/unit/test_signal_consumer_integration.py",  # for comprehensive testing
}


def normalize_path(filepath: Path) -> str:
    """Normalize path to use / and be relative to project root."""
    try:
        # Find src/orchestrator or tests directory
        parts = filepath.parts
        try:
            src_idx = next(i for i, p in enumerate(parts) if p == "src" or p == "tests")
            return str(Path(*parts[src_idx:]).as_posix())
        except StopIteration:
            # Fallback: return as-is
            return str(filepath.as_posix())
    except Exception:
        return str(filepath.as_posix())


def is_allowed_file(filepath: Path) -> bool:
    """Check if this file is allowed to use registry functions."""
    normalized = normalize_path(filepath)
    return any(normalized.endswith(allowed.replace("/", "/")) for allowed in ALLOWED_FILES)


def has_noqa_suppression(line_before: str) -> bool:
    """Check if previous line has # noqa: signal-routing comment."""
    return "# noqa: signal-routing" in line_before or "# noqa" in line_before


def check_file(filepath: Path, source: str) -> list[tuple[int, str]]:
    """Check a single file for signal routing violations."""
    violations: list[tuple[int, str]] = []

    # Quick fail: allowed files have no violations by definition
    if is_allowed_file(filepath):
        return violations

    try:
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, ValueError):
        return violations

    lines = source.split("\n")

    for node in ast.walk(tree):
        # Check ImportFrom: from orchestrator.workflow.signals import has_active_workflow
        if isinstance(node, ast.ImportFrom):
            if not node.module or "signals" not in node.module:
                continue
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    # Check for noqa on the import line itself or line before
                    noqa_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    noqa_before = lines[node.lineno - 2] if node.lineno > 1 and node.lineno - 1 <= len(lines) else ""
                    if has_noqa_suppression(noqa_line) or has_noqa_suppression(noqa_before):
                        continue
                    violations.append(
                        (node.lineno, f"Import of forbidden function `{alias.name}` (only allowed in consumer.py)")
                    )

        # Check Call: has_active_workflow(...), register_active_run(...), etc.
        elif isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                # This would catch module.has_active_workflow(...) which we also want to block
                func_name = node.func.attr

            if func_name and func_name in FORBIDDEN_NAMES:
                noqa_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                noqa_before = lines[node.lineno - 2] if node.lineno > 1 and node.lineno - 1 <= len(lines) else ""
                if has_noqa_suppression(noqa_line) or has_noqa_suppression(noqa_before):
                    continue
                violations.append(
                    (node.lineno, f"Call to forbidden function `{func_name}` (only allowed in consumer.py)")
                )

    return violations


def main(paths: list[str]) -> int:
    """Check all provided paths for signal routing violations."""
    all_violations: list[tuple[Path, int, str]] = []

    for path_str in paths:
        path = Path(path_str)
        if not path.suffix == ".py" or not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        violations = check_file(path, source)
        for lineno, message in violations:
            all_violations.append((path, lineno, message))

    if all_violations:
        print("Signal routing violations found:", file=sys.stderr)
        for path, lineno, message in sorted(all_violations, key=lambda x: (str(x[0]), x[1])):
            print(f"  {path}:{lineno}: {message}", file=sys.stderr)
        print(
            "\nRegistry functions (has_active_workflow, register_active_run, unregister_active_run) "
            "must only be imported or called within consumer.py.\n"
            "Allowed files: " + ", ".join(ALLOWED_FILES) + "\n"
            "To suppress: add `# noqa: signal-routing` on the line or line before.\n",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] Verify the script exists and has correct shebang

```bash
head -1 scripts/check_signal_routing.py | grep -q "#!/usr/bin/env python3" && echo "OK"
```

- [ ] Make script executable

```bash
chmod +x scripts/check_signal_routing.py
```

- [ ] Run script on itself (should pass — it's not a consumer file, but it has no imports)

```bash
uv run python scripts/check_signal_routing.py scripts/check_signal_routing.py
```

**Dependencies**:
- Python 3.10+
- `ast` module (standard library)
- `pathlib` module (standard library)

**References**:
- `scripts/check_module_imports.py` — Similar AST-based guard script (existing codebase pattern)
- intent.md [I-14], [I-15], [I-32], [I-33]

**Constraints**:
- Script must not import any orchestrator modules (keep it self-contained)
- Must match the structure of `check_module_imports.py` for consistency
- Allow-list must cover exactly the files specified: `consumer.py` and its test files

**Side Effects**:
- None. This is a new script with no runtime side effects.

**Functionality (Expected Outcomes)**:
- [ ] Script parses Python files without errors
- [ ] Script correctly identifies forbidden imports in non-allowed files
- [ ] Script correctly identifies forbidden function calls in non-allowed files
- [ ] Script respects `# noqa: signal-routing` suppression comments
- [ ] Script outputs human-readable violation messages with file and line number

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run script on entire `src/` directory — should pass (no violations in clean codebase)

```bash
uv run python scripts/check_signal_routing.py src/orchestrator/**/*.py
```

- [ ] Verify exit code is 0 on clean codebase

```bash
uv run python scripts/check_signal_routing.py src/orchestrator/**/*.py; test $? -eq 0 && echo "PASS"
```

---

## Task 2: Integrate Guard Script into Pre-Commit Hooks

**Description**:
Add a new hook entry to `.pre-commit-config.yaml` that runs the signal routing guard on all
Python files during pre-commit. Follow the pattern of the existing `module-imports` hook.

**Implementation Plan (Do These Steps)**:

- [ ] Open `.pre-commit-config.yaml` and locate the `local` hooks section (should already exist)

- [ ] Add new hook entry after the `module-imports` hook:

```yaml
      - id: check-signal-routing
        name: check-signal-routing
        entry: uv run python scripts/check_signal_routing.py
        language: system
        types: [python]
        pass_filenames: true
```

The complete hook block in `.pre-commit-config.yaml` should now look like:

```yaml
  - repo: local
    hooks:
      - id: pyright
        name: pyright
        entry: uv run pyright
        language: system
        types: [python]
        pass_filenames: false
      - id: pytest
        name: pytest
        entry: uv run pytest -x --timeout=30
        language: system
        pass_filenames: false
        stages: [pre-commit]
      - id: module-imports
        name: module-imports
        entry: uv run python scripts/check_module_imports.py
        language: system
        types: [python]
        pass_filenames: true
      - id: check-signal-routing
        name: check-signal-routing
        entry: uv run python scripts/check_signal_routing.py
        language: system
        types: [python]
        pass_filenames: true
      - id: ui-lint
        ...
```

- [ ] Verify YAML syntax is valid

```bash
uv run python -c "import yaml; yaml.safe_load(open('.pre-commit-config.yaml'))" && echo "YAML OK"
```

**Dependencies**:
- `.pre-commit-config.yaml` file must exist (it does)
- `pre-commit` framework already installed in project

**References**:
- `.pre-commit-config.yaml` — existing hook config file
- Pre-commit framework documentation: https://pre-commit.com/

**Constraints**:
- Hook entry must use `types: [python]` to filter only .py files
- Must use `uv run` to ensure correct Python environment
- Must use `pass_filenames: true` to pass the list of changed files

**Side Effects**:
- Pre-commit hook will now run on every commit that touches Python files
- May block commits if signal routing violation is detected (desired behavior)

**Functionality (Expected Outcomes)**:
- [ ] Hook entry exists in `.pre-commit-config.yaml`
- [ ] Hook uses `uv run python scripts/check_signal_routing.py`
- [ ] Hook has `types: [python]` and `pass_filenames: true`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run pre-commit hook manually on clean codebase — should pass

```bash
pre-commit run check-signal-routing --all-files
```

- [ ] Verify exit code is 0

```bash
pre-commit run check-signal-routing --all-files; test $? -eq 0 && echo "PASS"
```

---

## Task 3: Add Signal-Queue Rules to AGENTS.md

**Description**:
Add a new section to `AGENTS.md` documenting the signal-queue architecture and its
four core isolation rules. This makes the architectural boundary explicit to anyone
reading the project guide.

**Implementation Plan (Do These Steps)**:

- [ ] Open `AGENTS.md` and locate the "Architecture" section (around line 70)

- [ ] Add a new subsection after the "Agent Runners" section and before any other architecture detail. Insert the following text (find a good placement after existing sections):

```markdown
## Signal Queue and Runner Isolation

The single-queue signal model separates signal production (API/services) from signal consumption
(agent executor) via the `pending_signals` table. This architecture enforces four core rules:

### Rule 1: No Registry Function Calls Outside Consumer Module

The active-run registry (`register_active_run()`, `unregister_active_run()`, `has_active_workflow()`)
is owned solely by `src/orchestrator/workflow/signals/consumer.py`. No other module may import or call
these functions. Enforcement: `scripts/check_signal_routing.py` (pre-commit hook).

```python
# WRONG — in service.py or any other module
if has_active_workflow(run_id):
    ...

# RIGHT — called only from consumer.py
```

### Rule 2: No Process-Local State Crossing API/Executor Boundary

The in-memory registry and active `RunWorkflow` instances exist only in the executor process.
The API router and `WorkflowService` must never access these directly. Instead, they enqueue
signals unconditionally and return immediately (202 Accepted).

```python
# WRONG — service reaching into executor's process-local state
executor.active_runs[run_id]

# RIGHT — always enqueue and return
enqueue_signal(run_id, "PAUSE")
return 202 Accepted
```

### Rule 3: No `app.state` Access From RunWorkflow or Executor

The FastAPI app state (`app.state`) is tied to a single server process. Executor processes
(which may be separate in a distributed setup) cannot access it. If executor code needs a
resource, it must be passed as a constructor argument or fetched via API calls.

```python
# WRONG — in executor.py or run_workflow.py
config = app.state.config

# RIGHT — pass as argument or fetch via API
executor = AgentRunnerExecutor(config=config, ...)
```

### Rule 4: All Lifecycle Transitions via Signal Queue

Every run lifecycle transition (DRAFT→ACTIVE, ACTIVE→PAUSED, etc.) is driven by a signal
enqueued to `pending_signals`. There are no direct DB updates or in-memory state mutations
bypassing the signal queue.

```python
# WRONG — direct DB state change
run.status = "PAUSED"
db.commit()

# RIGHT — enqueue signal
enqueue_signal(run_id, "PAUSE", reason="manual_pause")
# consumer will transition the state
```

These rules are enforced by:
- Pre-commit hook `check-signal-routing.py` catches forbidden imports/calls
- Code review: verify all lifecycle changes go through signals
- Architecture tests: verify consumer is the sole transition handler
```

- [ ] Verify the section is properly formatted Markdown

```bash
grep -A 50 "## Signal Queue and Runner Isolation" AGENTS.md | head -60
```

**Dependencies**:
- `AGENTS.md` file must exist (it does)
- Markdown editor or text editor

**References**:
- intent.md [I-14], [I-15], [I-32], [I-33]
- `docs/single-queue/intent.md` — Full signal-queue design

**Constraints**:
- Do not modify any other sections of `AGENTS.md`
- Rules must match exactly the four rules from the PRD (intent.md)
- Code examples must be realistic and match actual codebase patterns

**Side Effects**:
- None. This is documentation only.

**Functionality (Expected Outcomes)**:
- [ ] New section "Signal Queue and Runner Isolation" exists in `AGENTS.md`
- [ ] Section contains all four rules
- [ ] Each rule has a description and code example
- [ ] Section explains enforcement mechanisms (pre-commit hook, code review, tests)

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Section exists and is readable

```bash
grep -A 5 "## Signal Queue and Runner Isolation" AGENTS.md
```

- [ ] All four rules are present (search for "Rule 1", "Rule 2", "Rule 3", "Rule 4")

```bash
for i in 1 2 3 4; do
  grep -q "### Rule $i:" AGENTS.md && echo "Rule $i: OK" || echo "Rule $i: MISSING"
done
```

- [ ] Section mentions `check_signal_routing.py`

```bash
grep -q "check-signal-routing.py" AGENTS.md && echo "Enforcement reference: OK"
```

---

## Task 4: Validate Guard Script with Negative Test

**Description**:
Create an integration test that verifies the guard script correctly fails when a signal routing
violation is introduced, then passes when the violation is removed. This confirms the guard
actually detects violations.

**Implementation Plan (Do These Steps)**:

- [ ] Create a temporary test file that violates the rule:

```bash
cat > /tmp/test_violation.py << 'EOF'
# Intentional violation: import forbidden function outside consumer.py
from orchestrator.workflow.signals import has_active_workflow

def some_function():
    if has_active_workflow("run-123"):
        print("active")
EOF
```

- [ ] Run guard script on the violation file — should fail (exit code 1)

```bash
uv run python scripts/check_signal_routing.py /tmp/test_violation.py
TEST_RESULT=$?
if [ $TEST_RESULT -eq 1 ]; then
  echo "PASS: Guard correctly detected violation"
else
  echo "FAIL: Guard did not detect violation (exit code: $TEST_RESULT)"
  exit 1
fi
```

- [ ] Verify error message is clear and mentions the forbidden function

```bash
uv run python scripts/check_signal_routing.py /tmp/test_violation.py 2>&1 | grep -q "has_active_workflow" && echo "Error message OK"
```

- [ ] Create a version of the file with a valid suppression comment:

```bash
cat > /tmp/test_suppressed.py << 'EOF'
# noqa: signal-routing
from orchestrator.workflow.signals import has_active_workflow

def some_function():
    # noqa: signal-routing
    if has_active_workflow("run-123"):
        print("active")
EOF
```

- [ ] Run guard script on the suppressed file — should pass (exit code 0)

```bash
uv run python scripts/check_signal_routing.py /tmp/test_suppressed.py
TEST_RESULT=$?
if [ $TEST_RESULT -eq 0 ]; then
  echo "PASS: Guard respects noqa suppression"
else
  echo "FAIL: Guard did not respect noqa (exit code: $TEST_RESULT)"
  exit 1
fi
```

- [ ] Clean up temporary files

```bash
rm /tmp/test_violation.py /tmp/test_suppressed.py
```

- [ ] Run guard script on entire project — should pass (no violations in codebase)

```bash
uv run python scripts/check_signal_routing.py src/**/*.py tests/**/*.py
TEST_RESULT=$?
if [ $TEST_RESULT -eq 0 ]; then
  echo "PASS: No violations in codebase"
else
  echo "FAIL: Unexpected violations in codebase"
  exit 1
fi
```

**Dependencies**:
- `scripts/check_signal_routing.py` must exist (created in Task 1)
- `uv` must be installed and working

**References**:
- Task 1 implementation

**Constraints**:
- Use temporary files in `/tmp/` to avoid polluting the repo
- Must clean up temporary files after test
- All checks must use actual execution, not just file presence checks

**Side Effects**:
- Temporary files created and deleted (no persistent side effects)
- No changes to actual codebase

**Functionality (Expected Outcomes)**:
- [ ] Guard script correctly identifies violations in test file
- [ ] Guard script respects noqa suppression comments
- [ ] Guard script passes on clean codebase
- [ ] All error messages are human-readable and actionable

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] All four guard script test checkpoints above passed (violation detection, suppression, clean codebase)

```bash
# Recap: run all negative/positive tests in sequence
echo "Testing violation detection..."
uv run python scripts/check_signal_routing.py /tmp/test_violation.py 2>&1 | grep -q "has_active_workflow" && echo "✓ Violation detected" || (echo "✗ Failed"; exit 1)

echo "Testing suppression..."
uv run python scripts/check_signal_routing.py /tmp/test_suppressed.py 2>&1; [ $? -eq 0 ] && echo "✓ Suppression works" || (echo "✗ Failed"; exit 1)

echo "Testing clean codebase..."
uv run python scripts/check_signal_routing.py src/**/*.py 2>&1; [ $? -eq 0 ] && echo "✓ No violations" || (echo "✗ Failed"; exit 1)

echo "All tests passed!"
```

---

## Summary

After all four tasks are complete:

1. **`scripts/check_signal_routing.py`** enforces registry function isolation via pre-commit
2. **`.pre-commit-config.yaml`** runs the guard on every commit
3. **`AGENTS.md`** documents the four signal-queue isolation rules
4. **Validation tests** prove the guard catches violations and respects suppression

The guard script and AGENTS.md rules together lock in the signal-queue invariants that Step 04
(Registry Isolation) established, preventing regression as the codebase evolves.

**Traces**:
- [I-14]: "Add rules to AGENTS.md" ← Task 3
- [I-15]: "Pre-commit guard script for registry isolation" ← Task 1
- [I-32]: "Pre-commit guard prevents disallowed imports outside consumer" ← Task 1, 4
- [I-33]: "Rules are documented in AGENTS.md" ← Task 3
