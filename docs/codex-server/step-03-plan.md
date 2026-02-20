# Step 03 Plan: Base Codex Server Agent Implementation

## Purpose

Implement `CodexServerAgent` for managed local-server execution with behavior parity to existing managed agents (phase prompts, callback tools, normalized results, and action logging).

## Prerequisites

- Step 01 complete: contract baseline fixed.
- Step 02 complete: agent type and detector plumbing available.

## Functional Contract

### Inputs

- `AgentType.CODEX_SERVER` selection from run configuration.
- `ExecutionContext` fields (run/task IDs, phase, prompt, requirements, callback metadata, optional auth).
- Shared callback/tool contract and action-log normalization patterns from OpenHands implementation.

### Outputs

- `src/orchestrator/agents/codex_server.py` implementing agent protocol (`execute`, `cancel`, `info`).
- Optional shared helpers in `src/orchestrator/agents/codex_server_common.py` for:
  - Prompt assembly per phase
  - Callback tool registration
  - Event/output normalization to `ExecutionResult` and `ActionLog`
- Consistent success/failure result mapping with metrics and structured errors.

### Errors

- Local Codex session startup failure -> `AgentNotAvailableError` or `AgentExecutionError` with actionable message.
- Callback tool invocation failure (REST/MCP) -> surfaced as execution failure with preserved context.
- Unexpected event/output schema from Codex server -> parser normalization error mapped to explicit agent error type.

## Tasks

1. Implement managed local Codex agent runtime using shared execution contracts from existing managed agents.
2. Add shared helper abstractions for prompt/tool/event normalization to minimize duplication with remote variant.
3. Ensure cancellation and partial-output handling match existing managed-agent expectations.

## Verification

### Auto-Verify

- [ ] Unit tests for local agent execution success, failure, cancellation, and output normalization pass.
- [ ] Unit tests validate only allow-listed callback tools are exposed.
- [ ] Integration scenario confirms builder-phase checklist updates and submit flow through callbacks.

### Manual Verify

- [ ] Run a local Codex-backed builder attempt and confirm action logs, metrics, and artifacts match established managed-agent behavior.
- [ ] Trigger a controlled callback error and confirm explicit error mapping and diagnostics are preserved.

## Context & References

- `docs/codex-server/step-01-plan.md`
- `docs/codex-server/step-02-plan.md`
- `src/orchestrator/agents/interface.py`
- `src/orchestrator/agents/types.py`
- `src/orchestrator/agents/openhands_common.py`
