# Step 10: Agent escalation for unfulfillable requirements (A11)

**Milestone:** M3 — Safety Guards
**Plan:** [step-10-plan.md](../step-10-plan.md)
**Architecture:** [architecture.md](../architecture.md) §5 (Agent Interface, A11)
**Intent:** [intent.md](../intent.md) — Completion Criteria #7

## Tasks

### Task 10.1: Add EscalationCallback protocol and engine handling

Define `EscalationCallback` protocol in `interface.py`. Add engine method to
handle escalation: mark requirement as `escalated`, pause run with
`pause_reason="requirement_escalated"`.

**Files:** `src/orchestrator/agents/interface.py`, `src/orchestrator/workflow/engine.py`
**LOC estimate:** ~50
**Verify:** Unit test — engine handles escalation correctly (requirement marked,
run paused with correct reason).

### Task 10.2: Add escalation API endpoint

Add `POST /api/runs/{run_id}/tasks/{task_id}/escalate` endpoint. Request body:
`{"requirement_id": "R1", "reason": "..."}`. Returns 200 on success, 404 if
not found, 400 for invalid requirement, 409 if run not in escalatable state.

**Files:** `src/orchestrator/routers/tasks.py`
**LOC estimate:** ~40
**Verify:** Integration tests — POST escalation → requirement escalated, run
paused; escalation on completed run → 409; invalid requirement → 400.

### Task 10.3: Integration tests for escalation flow

Test full escalation lifecycle: agent escalates → run pauses → human modifies
requirement → run resumes.

**Files:** `tests/integration/` (new or existing test file)
**LOC estimate:** ~60
**Verify:** Tests pass covering the complete escalation and recovery flow.
