# Step Plan: Guards and Documentation

## Purpose

Lock in the new single-queue invariants with an automated pre-commit guard script
and AGENTS.md documentation rules. The guard prevents future code from accidentally
importing registry functions outside the consumer module.

## Prerequisites

- **S-04 complete**: Registry functions isolated to consumer module. No imports
  exist outside consumer and its tests.

## Functional Contract

### Inputs

- Codebase with registry functions only imported in `consumer.py` and its tests.
- Existing `scripts/check_module_imports.py` as structural reference.
- Existing `.pre-commit-config.yaml` or hook configuration.
- Existing `AGENTS.md`.

### Outputs

- **`scripts/check_signal_routing.py`**:
  - Uses `ast` module to parse all Python files.
  - Fails if `has_active_workflow`, `register_active_run`, or `unregister_active_run`
    are imported or called outside `consumer.py` and its test file(s).
  - Supports `# noqa: signal-routing` suppression for edge cases.
  - Same structure as existing `scripts/check_module_imports.py`.
  - Exit code 0 on pass, non-zero on violation.
- **Pre-commit hook** configured to run `check_signal_routing.py`.
- **AGENTS.md** updated with "Signal Queue and Runner Isolation" section containing:
  1. No registry function calls outside consumer.
  2. No process-local state crossing API/executor boundary.
  3. No `app.state` access from RunWorkflow/executor.
  4. All lifecycle transitions via signal queue.

### Error Cases

- Guard script produces false positives on string matches in comments/docstrings —
  mitigated by AST-based parsing (analyzes imports/calls, not raw text).
- Guard blocks a legitimate edge case — `# noqa: signal-routing` suppression available.

## Tasks

1. Create `scripts/check_signal_routing.py` using AST parsing.
2. Add to pre-commit hook configuration.
3. Verify script passes on current codebase.
4. Verify script fails when a test violation is introduced.
5. Add "Signal Queue and Runner Isolation" section to `AGENTS.md`.

## Verification Approach

### Auto-Verify

- `scripts/check_signal_routing.py` exits 0 on clean codebase.
- Script exits non-zero when a file outside consumer imports `register_active_run`.
- `# noqa: signal-routing` suppression works.
- AGENTS.md contains the four rules verbatim.
- Pre-commit hook runs the script.

### Manual Verification

- Add a temporary import of `has_active_workflow` in `service.py`, run the guard,
  confirm failure. Remove the temporary import.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 5 (§5.1, §5.2)
- Architecture: `docs/single-queue-2/architecture.md` — Module Boundaries, Enforced by
- Reference: `scripts/check_module_imports.py` (existing guard for module-import rules)
