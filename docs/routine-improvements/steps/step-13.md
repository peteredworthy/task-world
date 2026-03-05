# Step 13: Task complexity labeling (A16)

**Milestone:** M4 — Schema & Architecture Extensions
**Plan:** [step-13-plan.md](../step-13-plan.md)
**Architecture:** [architecture.md](../architecture.md) §2 (Config Models, A16)
**Intent:** [intent.md](../intent.md) — Completion Criteria #12

## Tasks

### Task 13.1: Add complexity field to TaskConfig

Add `complexity: Literal["simple", "standard"] = "standard"` to `TaskConfig`.
Optionally add `Complexity` enum to `enums.py`. Diagnostic metadata only —
no behavioral changes.

**Files:** `src/orchestrator/config/models.py`, optionally `src/orchestrator/config/enums.py`
**LOC estimate:** ~15
**Verify:** Unit tests — accepts "simple" and "standard"; default is
"standard"; invalid value raises validation error. Existing TaskConfig tests
pass.
