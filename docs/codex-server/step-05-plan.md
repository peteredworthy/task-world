# Step 05 Plan: Executor and Monitor Integration

## Purpose

Wire both Codex server agents into orchestrator execution lifecycle so run start/resume/recovery, cancellation, and dead-agent monitoring behave identically to existing managed agents.

## Prerequisites

- Step 03 complete: local Codex agent available.
- Step 04 complete: remote Codex agent available.

## Functional Contract

### Inputs

- `AgentType.CODEX_SERVER` and `AgentType.CODEX_SERVER_REMOTE` run selections.
- Existing executor/monitor lifecycle implementation:
  - `src/orchestrator/agents/executor.py`
  - `src/orchestrator/agents/monitor.py`
- Existing callback auth/channel configuration in execution context.

### Outputs

- `AgentExecutor._create_agent` dispatch supports both new types.
- Spawn/start/resume/recovery flows can manage Codex local/remote executions.
- Cancellation and dead-agent detection logic covers both new managed types.
- Callback instruction/auth propagation remains correct for REST and MCP channels.

### Errors

- Missing executor branch for a new type -> runtime `unsupported agent type` failure.
- Monitor health-check incompatibility -> false dead-agent detection or leaked running sessions.
- Lifecycle state mismatch during resume/recovery -> orphaned attempts or duplicate execution starts.

## Tasks

1. Add executor creation/spawn branches for both Codex agent types.
2. Extend monitor/lifecycle handling for health checks, cancellation, and recovery semantics.
3. Validate callback channel/auth propagation through executor paths for both variants.

## Verification

### Auto-Verify

- [ ] Unit tests for `_create_agent` dispatch and spawn allow-list pass for both Codex variants.
- [ ] Integration tests for run start/pause/resume/cancel/recover pass with both variants.
- [ ] Dead-agent monitor tests cover Codex local/remote behavior.

### Manual Verify

- [ ] Start and cancel runs using each Codex variant; confirm state transitions and attempt records are correct.
- [ ] Simulate interrupted run recovery and confirm no duplicate execution and no task lock leaks.

## Context & References

- `docs/codex-server/step-03-plan.md`
- `docs/codex-server/step-04-plan.md`
- `src/orchestrator/agents/executor.py`
- `src/orchestrator/agents/monitor.py`
