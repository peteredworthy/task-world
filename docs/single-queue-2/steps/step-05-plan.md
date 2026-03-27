# Step 5: Guards and Documentation

Lock in the single-queue invariants with an automated pre-commit guard script and
AGENTS.md documentation. The guard prevents future code from accidentally importing
registry functions outside the consumer module. Once S-04 is complete, no source file
outside `consumer.py` (and its tests) imports `has_active_workflow`,
`register_active_run`, or `unregister_active_run` — this step makes that an enforced,
checked invariant rather than a social convention.

## Intent Verification
**Original Intent**: [I-14], [I-15], [I-32], [I-33] — Automated check prevents registry
functions from escaping consumer module; AGENTS.md documents the four signal-queue rules.

**Functionality to Produce**:
- `scripts/check_signal_routing.py` exists, uses AST parsing, exits 0 on clean codebase,
  exits non-zero when any Python file outside `consumer.py` (and its tests) imports or
  calls `has_active_workflow`, `register_active_run`, or `unregister_active_run`
- `# noqa: signal-routing` comment on an import/call line suppresses the violation
- Pre-commit hook entry `signal-routing` runs the script on every commit
- `AGENTS.md` contains a "Signal Queue and Runner Isolation" section with the four rules

**Final Verification Criteria**:
- `uv run python scripts/check_signal_routing.py $(git ls-files '*.py')` exits 0
- Introducing a test violation (temporary import in `service.py`) causes the script to
  exit non-zero and print the offending file/line
- `grep "signal-routing" .pre-commit-config.yaml` returns a match
- `grep "Signal Queue and Runner Isolation" AGENTS.md` returns a match

---

## Task 1: Create `scripts/check_signal_routing.py`

**Description**:
Create the guard script using Python's `ast` module. The script accepts a list of file
paths (same interface as `check_module_imports.py` so pre-commit can pass changed files),
parses each file, and reports violations if `has_active_workflow`, `register_active_run`,
or `unregister_active_run` are imported or called outside the allowed files.

**Implementation Plan (Do These Steps)**

The allowed files are `consumer.py` and any test file whose name contains `consumer`
(e.g. `test_signal_consumer.py`, `test_signal_redelivery.py`). The script uses `ast.walk`
to detect:
1. `ast.ImportFrom` nodes where the imported names include a restricted symbol.
2. `ast.Name` nodes (bare calls) matching a restricted symbol — catches `register_active_run(...)`.

`# noqa: signal-routing` on the **same source line** as the import or call suppresses
the violation. Extract the line from `source.splitlines()` and check for the suppression
comment before appending to violations.

- [ ] Create `scripts/check_signal_routing.py` with the following structure:

```python
#!/usr/bin/env python3
"""
Enforce signal-routing isolation: registry functions must only be used in consumer.py.

has_active_workflow, register_active_run, and unregister_active_run must not be
imported or called outside src/orchestrator/workflow/signals/consumer.py and its
test files.

Suppression: add  # noqa: signal-routing  to the offending line to silence a violation.

NOTE (F-3): For multi-line parenthesized imports, the suppression comment must go on
the `from ... import (` line, NOT on the individual alias line within the parens.
This is because ast.ImportFrom.lineno points to the `from` line.
"""

import ast
import sys
from pathlib import Path

RESTRICTED_NAMES = {
    "has_active_workflow",
    "register_active_run",
    "unregister_active_run",
}


def is_allowed_file(filepath: Path) -> bool:
    """Return True if this file is allowed to use registry functions."""
    name = filepath.name
    # The consumer module itself (require signals/ path to avoid false exemptions)
    if name == "consumer.py" and "signals" in str(filepath):
        return True
    # Test files covering the consumer or crash-recovery redelivery (F-1 fix)
    # test_signal_redelivery.py calls has_active_workflow() to verify crash recovery state
    if name.startswith("test_") and any(kw in name for kw in ("consumer", "redelivery")):
        return True
    return False


def check_file(filepath: Path) -> list[str]:
    """Return violation strings for the given file."""
    if is_allowed_file(filepath):
        return []

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        return []

    lines = source.splitlines()
    violations: list[str] = []

    def is_suppressed(lineno: int) -> bool:
        """Return True if the source line carries a # noqa: signal-routing comment."""
        line = lines[lineno - 1] if lineno <= len(lines) else ""
        return "# noqa: signal-routing" in line

    for node in ast.walk(tree):
        # Detect: from X import has_active_workflow [, ...]
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in RESTRICTED_NAMES and not is_suppressed(node.lineno):
                    violations.append(
                        f"{filepath}:{node.lineno}: "
                        f"import of restricted registry function `{alias.name}`; "
                        f"only consumer.py may use registry functions. "
                        f"Add `# noqa: signal-routing` to suppress."
                    )
        # Detect: register_active_run(...)  or  has_active_workflow(run_id)
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in RESTRICTED_NAMES and not is_suppressed(node.lineno):
                violations.append(
                    f"{filepath}:{node.lineno}: "
                    f"call to restricted registry function `{name}`; "
                    f"only consumer.py may call registry functions. "
                    f"Add `# noqa: signal-routing` to suppress."
                )

    return violations


def main(paths: list[str]) -> int:
    all_violations: list[str] = []
    for path_str in paths:
        path = Path(path_str)
        if path.suffix == ".py" and path.exists():
            all_violations.extend(check_file(path))

    if all_violations:
        print("Signal routing violations found:", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nRegistry functions (has_active_workflow, register_active_run, "
            "unregister_active_run) must only be used in consumer.py and its tests. "
            "See AGENTS.md §'Signal Queue and Runner Isolation'.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] Make the script executable: `chmod +x scripts/check_signal_routing.py`

**References**
- `scripts/check_module_imports.py` — existing guard script used as structural reference
- `docs/single-queue-2/plan.md` §5.1

**Constraints**
- Only `scripts/check_signal_routing.py` is created in this task. No other files.
- Script must not import from `orchestrator` package (it runs before the package is
  installed in the pre-commit environment).

**Functionality (Expected Outcomes)**
- [ ] `uv run python scripts/check_signal_routing.py scripts/check_signal_routing.py` exits 0 (script does not violate its own rules).
- [ ] Script exits 0 when passed only `consumer.py` as input, even though it contains calls to restricted functions.
- [ ] Script exits non-zero and prints the offending line when passed a file containing `from orchestrator.workflow.signals import register_active_run`.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `test -f scripts/check_signal_routing.py` succeeds.
- [ ] `uv run python scripts/check_signal_routing.py scripts/check_signal_routing.py` exits 0.
- [ ] Create a temp file with a restricted import, run the script against it, confirm exit code 1 and a violation message, then delete the temp file.

---

## Task 2: Add Pre-Commit Hook

**Description**:
Register the guard script as a pre-commit hook in `.pre-commit-config.yaml` using the
same `local` repo block that already hosts `module-imports`, `pyright`, and `pytest`.

**Implementation Plan (Do These Steps)**

- [ ] Open `.pre-commit-config.yaml`.
- [ ] Locate the `local` hooks block (currently contains `pyright`, `pytest`,
  `module-imports`, `ui-lint`, `ui-typecheck`).
- [ ] Add a new hook entry immediately after `module-imports`:

```yaml
      - id: signal-routing
        name: signal-routing
        entry: uv run python scripts/check_signal_routing.py
        language: system
        types: [python]
        pass_filenames: true
```

The `pass_filenames: true` flag makes pre-commit pass only the staged Python files to
the script, matching the interface of `check_module_imports.py`.

**Constraints**
- Only `.pre-commit-config.yaml` is modified in this task.
- Do not change any other hook entries.

**Functionality (Expected Outcomes)**
- [ ] `.pre-commit-config.yaml` contains an entry with `id: signal-routing`.
- [ ] The entry uses `pass_filenames: true` so it receives staged file paths.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "signal-routing" .pre-commit-config.yaml` returns at least two matches (the `id:` and `name:` lines).
- [ ] `pre-commit run signal-routing --all-files` exits 0 on the clean codebase.

---

## Task 3: Verify Script Passes on Clean Codebase

**Description**:
Confirm the guard produces no violations when run against the full Python source tree
as it stands after S-04. This task is a validation checkpoint — no file changes are made.

**Implementation Plan (Do These Steps)**

- [ ] Run the script against all Python source files:

```bash
uv run python scripts/check_signal_routing.py $(git ls-files '*.py')
```

- [ ] Confirm exit code is 0 and no violation lines appear in stderr.
- [ ] If violations are found, they indicate either:
  1. S-04 is incomplete (stale imports still exist) — do not proceed; fix S-04 first.
  2. An allowed file was not correctly identified — fix `is_allowed_file()` in the script.

**Constraints**
- No file changes in this task. This is verification only.

**Functionality (Expected Outcomes)**
- [ ] Zero violations reported across all Python files in the repository.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python scripts/check_signal_routing.py $(git ls-files '*.py'); echo "exit:$?"` prints `exit:0`.

---

## Task 4: Verify Script Catches Violations

**Description**:
Confirm the guard correctly catches a deliberate violation and that `# noqa: signal-routing`
suppresses it. This is behavioral verification of the guard's detection logic.

**Implementation Plan (Do These Steps)**

- [ ] Create a temporary Python file at `/tmp/test_violation.py` with the content:

```python
from orchestrator.workflow.signals import register_active_run  # violation

def allowed():
    from orchestrator.workflow.signals import register_active_run  # noqa: signal-routing
```

- [ ] Run the script against the temp file:

```bash
uv run python scripts/check_signal_routing.py /tmp/test_violation.py
echo "exit:$?"
```

- [ ] Confirm:
  1. Exit code is **1** (non-zero).
  2. Exactly **one** violation is reported (line 1), not two (line 4 is suppressed).
  3. The violation message names `register_active_run` and includes the file/line.

- [ ] Delete the temp file:

```bash
rm /tmp/test_violation.py
```

**Constraints**
- No project files are modified. Temp file is created in `/tmp` only.

**Functionality (Expected Outcomes)**
- [ ] Script exit code is 1 when a restricted import exists.
- [ ] `# noqa: signal-routing` suppresses the violation on the annotated line.
- [ ] Violation message includes the file path, line number, and restricted function name.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Running the script against the temp file produces exactly one violation on line 1 and exits 1.
- [ ] Running the script against a file containing only the suppressed form exits 0.

---

## Task 5: Add "Signal Queue and Runner Isolation" Section to AGENTS.md

**Description**:
Document the four invariants enforced by the single-queue model in `AGENTS.md`. These
rules are the human-readable complement to the automated guard. Future contributors
must be able to understand *why* the guard exists, not just that it fails.

**Implementation Plan (Do These Steps)**

- [ ] Open `AGENTS.md` and find an appropriate location for the new section. Place it
  near other architectural rules (e.g., near the module boundary or testing sections).
  Do not place it inside an existing subsection.

- [ ] Add the following section verbatim (the four rules must appear exactly as written
  because the auto-verify step checks for the section heading):

```markdown
## Signal Queue and Runner Isolation

The following rules are enforced by `scripts/check_signal_routing.py` (pre-commit hook).

1. **No registry function calls outside `consumer.py`**: `has_active_workflow`,
   `register_active_run`, and `unregister_active_run` must not be imported or called
   from any module other than `src/orchestrator/workflow/signals/consumer.py` and its
   test files. The consumer is the sole owner of the active-run registry.

2. **No process-local state crossing the API/executor boundary**: State that lives only
   in the executor process (e.g., in-memory RunWorkflow instances, the active-run registry)
   must not be read or modified from the API layer. The API communicates with the executor
   exclusively through the database (signal queue, run status columns).

3. **No `app.state` access from RunWorkflow or executor**: `RunWorkflow` and executor code
   must not import from or reference `app.state`. Dependencies (session factory, config,
   broadcaster) must be injected at construction time.

4. **All lifecycle transitions via signal queue**: Run lifecycle operations (start, pause,
   resume, cancel) must be initiated by enqueueing a signal into `pending_signals`. Direct
   calls to `engine.start_run()`, `engine.pause_run()`, etc. from the service layer are
   not permitted after the single-queue migration.
```

**Constraints**
- Only `AGENTS.md` is modified in this task.
- The section heading must be exactly `## Signal Queue and Runner Isolation` (used by
  auto-verify grep).
- Do not reword the four numbered rules — the auto-verify check looks for the section
  heading; content may be validated manually.

**Functionality (Expected Outcomes)**
- [ ] `AGENTS.md` contains a `## Signal Queue and Runner Isolation` section.
- [ ] All four numbered rules are present with their exact headings.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "Signal Queue and Runner Isolation" AGENTS.md` returns a match.
- [ ] `grep "No registry function calls outside" AGENTS.md` returns a match.
- [ ] `grep "No process-local state crossing" AGENTS.md` returns a match.
- [ ] `grep "No \`app.state\` access" AGENTS.md` returns a match.
- [ ] `grep "All lifecycle transitions via signal queue" AGENTS.md` returns a match.
