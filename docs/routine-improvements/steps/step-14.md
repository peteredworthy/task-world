# Step 14: Multi-file routine definitions (A17)

**Milestone:** M4 — Schema & Architecture Extensions
**Plan:** [step-14-plan.md](../step-14-plan.md)
**Architecture:** [architecture.md](../architecture.md) §2 (Config Models, A17) and §3 (Config Loader, A17)
**Intent:** [intent.md](../intent.md) — Completion Criteria #11
**Clarification:** Q7 in [clarifications.md](../clarifications.md) — no overlap allowed, fail validation

## Tasks

### Task 14.1: Add file field to StepConfig with overlap validation

Add `file: str | None = None` to `StepConfig`. Add model_validator: if `file`
is set AND other step fields (name, tasks, etc.) are also set, raise
`ValueError` — no overlap allowed per clarification decision.

**Files:** `src/orchestrator/config/models.py`
**LOC estimate:** ~25
**Verify:** Unit tests — file field accepted; overlap with other fields raises
error; inline steps (no file) unchanged.

### Task 14.2: Implement multi-file resolution in loader

Update `loader.py` to:
1. Parse root routine.yaml
2. For each step with `file`, resolve path relative to routine directory
3. Validate referenced file exists (raise `RoutineValidationError` if missing)
4. Load referenced YAML as complete step definition
5. Assemble final RoutineConfig

**Files:** `src/orchestrator/config/loader.py`
**LOC estimate:** ~60
**Verify:** Unit tests — resolves step file references; missing file raises
RoutineValidationError; inline steps work. Integration test — full multi-file
routine load.

### Task 14.3: Multi-file loader tests

Comprehensive tests in a dedicated test file for multi-file loading scenarios.

**Files:** `tests/unit/test_loader_multifile.py` (new)
**LOC estimate:** ~80
**Verify:** Tests cover: file resolution, missing file error, overlap
validation, inline steps, mixed inline + file steps. Existing loader tests pass.
