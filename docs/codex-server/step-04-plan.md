# Step 04 Plan: Remote Codex Server Variant

## Purpose

Implement `CodexServerRemoteAgent` for remote Codex app server execution with explicit endpoint/auth handling and robust transport error mapping, while reusing shared local-agent contracts.

## Prerequisites

- Step 01 complete: remote auth and compatibility policy fixed.
- Step 02 complete: remote agent type/config schema available.
- Step 03 complete: shared codex execution abstractions exist for reuse.

## Functional Contract

### Inputs

- `AgentType.CODEX_SERVER_REMOTE` selection and remote config values:
  - `base_url`/endpoint
  - bearer token source
  - model/session settings
  - callback transport preference (REST/MCP)
  - timeout/retry settings
- `ExecutionContext` for builder/verifier phases.
- Shared codex common helpers from Step 03.

### Outputs

- `src/orchestrator/agents/codex_server_remote.py` implementing remote execution path.
- Remote transport client logic with secure bearer-token header injection and secret-safe logging.
- Retry/timeout and network-error normalization into explicit orchestrator agent errors.

### Errors

- Authentication failure (401/403) -> explicit auth/config error surfaced to user without token leakage.
- Network timeout/unreachable endpoint -> `AgentTimeoutError`/`AgentExecutionError` with retry context.
- Remote API contract mismatch (unexpected payload/tool schema) -> explicit compatibility error aligned with latest-documented policy.

## Tasks

1. Implement remote Codex agent execution path with configuration-driven endpoint/auth behavior.
2. Reuse Step 03 shared helpers for prompt/tool/event contracts; avoid duplicated parsing logic.
3. Add resilient network error handling and secure redaction of secrets in logs/errors.

## Verification

### Auto-Verify

- [ ] Unit tests for remote auth header construction, timeout/retry handling, and error mapping pass.
- [ ] Integration tests validate remote-style execution path can perform checklist update, grade, and submit callbacks.
- [ ] Tests confirm secrets are not logged in failures.

### Manual Verify

- [ ] Execute a remote-agent builder/verifier cycle against a compatible Codex app server and confirm parity with local variant outputs.
- [ ] Force auth and network failures to validate user-facing diagnostics and retry behavior.

## Context & References

- `docs/codex-server/step-01-plan.md`
- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/step-03-plan.md`
- `src/orchestrator/agents/codex_server.py`
- `src/orchestrator/agents/errors.py`
