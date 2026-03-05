# Step 10: Agent escalation for unfulfillable requirements (A11)

## Milestone
M3: Safety Guards

## Purpose
Allow builder/verifier agents to flag a requirement as "cannot be fulfilled in this environment" and escalate to the human. This prevents agents from spinning on impossible tasks and gives humans a structured way to intervene.

## Prerequisites / Dependencies
- None directly. Independent of M1/M2 steps.

## Functional Contract

### Inputs
- **API endpoint:** `POST /api/runs/{run_id}/tasks/{task_id}/escalate`
- **Request body:**
  ```json
  {
    "requirement_id": "R1",
    "reason": "OpenHands not installed in this environment"
  }
  ```

### Outputs
- **Success (200):** Requirement marked as `escalated`, run paused with `pause_reason="requirement_escalated"`
- **After human intervention:** Human can modify the requirement, mark it `not_applicable`, or provide environment guidance and resume

### Errors
- **404:** Run or task not found
- **400:** Invalid requirement_id
- **409:** Run not in a state that allows escalation (already completed/cancelled)

### State Changes
- Requirement status set to `escalated`
- Run paused with descriptive reason

## Files Modified
- `src/orchestrator/agents/interface.py` — new `EscalationCallback` protocol
- `src/orchestrator/routers/tasks.py` — new escalation endpoint
- `src/orchestrator/workflow/engine.py` — handle escalation (pause run, mark requirement)

## Verification Strategy
- **Integration test:** POST escalation -> requirement marked escalated, run paused with correct reason.
- **Integration test:** Human modifies requirement after escalation -> run can resume.
- **Unit test:** Engine handles escalation correctly (state transitions).
- **Error test:** Escalation on completed run returns 409.
- **Regression:** Existing task and run API tests pass.
