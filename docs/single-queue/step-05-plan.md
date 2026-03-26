# Step 05: Guards and Documentation

**Phase:** 5
**Goal:** Lock in the new invariants with automated checks and documentation.

---

## Purpose and Functionality

Create a pre-commit guard script that enforces registry function isolation via
AST analysis, and add signal-queue and runner-isolation rules to AGENTS.md.
These guard against regression as the codebase evolves.

---

## Prerequisites / Dependencies

- **S-04 complete:** Registry functions are already isolated to the consumer module. The guard script codifies this as an automated check.

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| All Python source files | `src/`, `scripts/`, `tests/` | Scanned by guard script |
| PRD rules | intent.md [I-15] | Four signal-queue and runner-isolation rules |

### Outputs

| Output | Description |
|--------|-------------|
| `scripts/check_signal_routing.py` | AST-based pre-commit guard. Fails if `has_active_workflow`, `register_active_run`, or `unregister_active_run` are imported or called outside `consumer.py` (and its test file). Same structure as existing `scripts/check_module_imports.py`. |
| Pre-commit hook entry | Guard script added to `.pre-commit-config.yaml` or equivalent |
| AGENTS.md section | "Signal Queue and Runner Isolation" with four rules: (1) No registry calls outside consumer. (2) No process-local state crossing API/executor boundary. (3) No `app.state` access from RunWorkflow/executor. (4) All lifecycle transitions via signal queue. |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Guard script failure | Disallowed import/call detected | Pre-commit hook fails with file + line number |
| Guard script false positive | Legitimate use flagged | Allow-list mechanism in script (e.g., `# noqa: signal-routing`) |

---

## Verification Strategy

1. **Guard script positive test:** Script passes on clean codebase.
2. **Guard script negative test:** Introduce a test violation (e.g., import `has_active_workflow` in `service.py`), confirm script fails.
3. **AGENTS.md review:** Section exists and matches the four rules from the PRD.
4. **Pre-commit integration:** Run `pre-commit run check-signal-routing` and confirm it executes.

---

## Files Changed

- New: `scripts/check_signal_routing.py`
- Modify: `.pre-commit-config.yaml` or equivalent hook config
- Modify: `AGENTS.md`

---

## Traces

[I-14], [I-15], [I-32], [I-33]
