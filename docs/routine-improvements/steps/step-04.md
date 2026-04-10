# Step 4: Verifier model pinning (A10)

**Milestone:** M1 — Gate Fixes & Safety
**Plan:** [step-04-plan.md](../step-04-plan.md)
**Architecture:** [architecture.md](../architecture.md) §1 (Workflow Engine, A10)
**Intent:** [intent.md](../intent.md) — Completion Criteria #4

## Tasks

### Task 4.1: Add verifier_model field to Run state and pin at creation

Add `verifier_model: str | None` to Run state model. Set it at run creation
from the current agent/verifier config. Update executor to pass pinned model
to all verifier invocations, ignoring subsequent config changes.

**Files:** `src/orchestrator/state/models.py`, `src/orchestrator/workflow/engine.py` or `src/orchestrator/agents/executor.py`
**LOC estimate:** ~40
**Verify:** Unit tests — run creation stores verifier model; verifier uses
pinned model not current config; config change after creation has no effect.
Existing run creation tests pass.
