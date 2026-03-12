# Gap Analyzer Clarifications

## Status: No Open Questions

After reviewing intent.md, plan.md, and architecture.md, no design questions were found that require human input. All major decisions are already documented:

- **spawn_fix implementation**: Bespoke minimal (create TaskState directly); Option D deferred
- **JSON parsing failure**: Treat as `fail` verdict; log raw output
- **retry_task eligibility**: COMPLETED tasks only (not failed)
- **Fan-out path**: Leave existing executor path untouched; step verifier applies to explicitly-configured steps only
- **Manual re-verification API**: Out of scope for MVP
- **Verifier agent type**: Same run-level agent as tasks in the step
- **max_iterations on limit**: Auto-fail; prevents infinite loops

## Consistency Fix Applied

One inconsistency was found between plan.md and architecture.md and resolved:

**Issue**: plan.md stated that `check_step_progression()` in transitions.py would "signal the engine to call start_step_verification()". However, the architecture.md interaction diagram (the more detailed and authoritative description) shows the executor manages the entire verification loop directly — `check_step_progression()` is only called in the NO step_verifier path to advance `current_step_index`.

**Resolution**: The executor manages the step verification loop end-to-end:
1. Executor detects all tasks terminal and step_verifier configured → calls `start_step_verification()` directly
2. Runs verifier, calls `complete_step_verification()` with gap report
3. If retry/fix actions: executor task loop re-runs newly-PENDING tasks; when terminal, executor re-enters verification
4. `check_step_progression()` is NOT modified; it is only called (as today) when no step_verifier is configured

Both plan.md and architecture.md have been updated to reflect this consistently.
