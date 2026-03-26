# Step 04: Registry Isolation

**Phase:** 4
**Goal:** Restrict `register_active_run` / `unregister_active_run` / `has_active_workflow` to the consumer module only.

---

## Purpose and Functionality

Move or restrict the active-run registry functions so they are only accessible
from the consumer module. Remove them from the public API surface of
`workflow/signals/signals.py`. This enforces the architectural invariant that
only the consumer manages RunWorkflow lifecycle.

---

## Prerequisites / Dependencies

- **S-03 complete:** All lifecycle methods use signal queue. No callers of registry functions remain outside the consumer module (except possibly stale imports).

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `register_active_run()` | `signals/signals.py` | Currently exported publicly |
| `unregister_active_run()` | `signals/signals.py` | Currently exported publicly |
| `has_active_workflow()` | `signals/signals.py` | Currently exported publicly |

### Outputs

| Output | Description |
|--------|-------------|
| Registry functions moved/restricted | Only importable from `consumer.py` and its test files |
| Public surface cleaned | `signals/signals.py` no longer exports registry functions |
| All external imports removed | No file outside consumer module imports these functions |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Import from wrong module | Code outside consumer tries to import registry functions | Import error or pre-commit hook failure (S-05) |

---

## Verification Strategy

1. **Grep audit:** Confirm no imports of `register_active_run`, `unregister_active_run`, or `has_active_workflow` outside `consumer.py` and its test file.

2. **Module inspection:** Verify `signals/signals.py` `__all__` (or equivalent) does not include registry functions.

3. **Test update:** Any tests that previously imported registry functions from `signals.py` are updated to import from consumer or use consumer-aware helpers.

4. **Regression:** Full test suite passes with updated imports.

---

## Files Changed

- Modify: `src/orchestrator/workflow/signals/signals.py` (remove registry exports)
- Modify: `src/orchestrator/workflow/signals/consumer.py` (own the registry functions)
- Modify: any files that currently import registry functions (update or remove imports)

---

## Traces

[I-04], [I-29], [I-30]
