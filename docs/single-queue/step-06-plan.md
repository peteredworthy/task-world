# Step 06: Validation and Cleanup

**Phase:** 6
**Goal:** Final verification that all intent items are satisfied, all tests pass, and dead code is removed.

---

## Purpose and Functionality

Run the full test suite, remove dead code from the old dual-path routing, and
verify traceability of every intent item. This step produces no new functionality
— it confirms correctness and cleans up.

---

## Prerequisites / Dependencies

- **S-01 through S-05 complete:** All functional changes and guards in place.

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Full codebase | After S-01 through S-05 | All signal-queue changes applied |
| Intent items [I-01] through [I-36] | `intent.md` | Every item must be addressed |

### Outputs

| Output | Description |
|--------|-------------|
| All tests pass | Backend (unit + integration), frontend, type checker, linter |
| Dead code removed | Old dual-path branching logic, unused helper functions, unused imports from old routing |
| No-op `handle_resume` log removed | From `RunWorkflow` |
| Traceability verified | Every [I-XX] maps to at least one completed step |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Test failure | Any test fails | Fix before marking step complete |
| Untraced intent item | An [I-XX] has no step coverage | Either add coverage in a prior step or document as NO-REQ with justification |

---

## Verification Strategy

1. **Full backend test suite:** `pytest tests/` — all pass.
2. **Full frontend test suite:** `npm test` in `ui/` — all pass.
3. **Type checker:** `tsc --noEmit` in `ui/` — clean.
4. **Linter:** `eslint` and `ruff` — clean.
5. **Dead code audit:** Grep for old patterns (`has_active_workflow` in service, `spawn_run` in service, `unregister_active_run` in run_workflow) — none found.
6. **Traceability matrix:** Every [I-XX] in intent.md is annotated with the step(s) that address it.

---

## Files Changed

- Modify: various files (remove dead code, unused imports)
- Modify: `src/orchestrator/workflow/run_workflow.py` (remove no-op handle_resume log)
- No new files

---

## Traces

[I-21], [I-34], [I-36]
