# Step Plan: Validation and Cleanup

## Purpose

Final verification that all intent items are satisfied, all tests pass, and any
dead code from the old dual-path routing is removed. This step confirms the
implementation is complete and clean.

## Prerequisites

- **S-01 through S-05 complete**: All schema changes, consumer, sender rewiring,
  registry isolation, guards, and documentation in place.

## Functional Contract

### Inputs

- Full codebase after steps S-01 through S-05.
- Intent items [I-01] through [I-36] from `docs/single-queue-2/intent.md`.

### Outputs

- **All backend tests pass** (unit + integration).
- **All frontend tests pass**.
- **Type checker and linter clean**.
- **Dead code removed**:
  - Unused branching logic from old dual-path routing.
  - Unused helper functions or imports that were part of the old model.
  - No-op `handle_resume` log message from `RunWorkflow`.
- **Traceability verified**: Every [I-XX] item addressed by at least one step.

### Error Cases

- Test failures discovered at validation — fix in this step or escalate if they
  indicate a design problem from a prior step.
- Dead code removal breaks something — the code wasn't actually dead; restore and
  investigate.

## Tasks

1. Run full backend test suite (unit + integration).
2. Run full frontend test suite.
3. Run type checker (`mypy` or equivalent) and linter.
4. Grep for and remove dead code:
   - `has_active_workflow` calls in non-consumer code (should be none after S-04).
   - Old branching patterns in service.py (should be none after S-03).
   - No-op `handle_resume` log in `run_workflow.py`.
5. Verify every [I-XX] intent item is covered (traceability check).
6. Fix any remaining test failures or type errors.

## Verification Approach

### Auto-Verify

- `pytest tests/unit/ tests/integration/` — all pass.
- Frontend test suite — all pass.
- Type check and lint — clean.
- `grep -rn "has_active_workflow" src/orchestrator/workflow/service.py` — no hits.
- `grep -rn "has_active_workflow" src/orchestrator/api/` — no hits.
- Every [I-XX] in intent.md has a step annotation.

### Manual Verification

- Review diff of all changes across S-01–S-06 for completeness.
- Confirm no backward-compatibility stubs remain.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 6 (§6.1, §6.2, §6.3)
- Intent: `docs/single-queue-2/intent.md` — all [I-XX] items
- Architecture: `docs/single-queue-2/architecture.md` — full target architecture
