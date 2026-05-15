# 02 - Child Result State Handoff

## Problem

The child evidence handoff told the parent that evidence existed, but the parent
still had to query or infer child run state separately. That separation created
extra calls and confusion between:

- evidence is ready
- child run is terminal
- child can be accepted, rejected, or abandoned

## Proposed Shape

When child evidence is returned to the parent, include a compact state block:

```json
{
  "child_run_id": "2ea5fbe8-...",
  "parent_slice_id": "INV-R-001-pytest-smoke",
  "run_status": "paused",
  "is_terminal": false,
  "evidence_status": "valid",
  "evidence_ready": true,
  "allowed_parent_actions": ["wait", "abandon"],
  "blocked_actions": [
    {
      "action": "create_child_run",
      "reason": "unresolved_child_exists"
    }
  ]
}
```

## Expected Impact

Small to medium token/call reduction. The larger value is correctness: the
parent can distinguish evidence readiness from terminal readiness without
reconstructing state through separate calls.

## Best Fit

Roll this into the state-choice and lifecycle work, especially any changes that
make child concurrency explicit.

