# Codex-Server Integration: Open Risks

**Status:** Active
**Date:** 2026-02-20
**Normative source:** `docs/codex-server/context/contract-matrix.md`

This document lists actionable risks that could block or degrade the Codex server integration. Each entry identifies the trigger condition, the step plans affected, a concrete mitigation, and whether the risk is currently blocking release.

---

## R-01: Payload Drift

**Summary:** The Codex app server payload schema (request or response) diverges from the version targeted during implementation, causing silent failures or incorrect behavior in production.

| Field | Detail |
|-------|--------|
| **Trigger** | OpenAI ships a breaking or additive change to the Codex app server API (new required fields, renamed keys, removed events) between the time step-02 detector metadata is pinned and step-06 release hardening is complete. |
| **Affected step plans** | step-02 (detector version metadata), step-03 (local agent payload parsing), step-04 (remote agent payload parsing), step-06 (integration tests targeting latest documented version) |
| **Mitigation** | 1. Pin the targeted Codex app server version in `ToolDetector` metadata at step-02 and emit an explicit warning (not silent failure) when a mismatch is detected (contract-matrix §5). 2. Implement a version-check assertion in `codex_server_common` that compares the detected server version string against the pinned value on every session start. 3. Expose a dedicated parser normalization error type (already listed in step-03 error contract) so payload mismatches surface immediately rather than producing corrupt `ExecutionResult` objects. 4. Include a schema conformance test in the step-06 suite that asserts the payload structure against the documented spec snapshot used during development. |
| **Blocking?** | **Yes** — a payload mismatch that causes silent data corruption or incorrect checklist updates violates the interface contract (contract-matrix §1) and is a release blocker. A mismatch that produces an explicit error is not a release blocker but must be resolved before shipping. |

---

## R-02: Remote Timeout Behavior

**Summary:** The remote Codex agent (`codex_server_remote`) does not handle network timeouts, hung connections, or slow responses in a way that integrates cleanly with the orchestrator's nudger/monitor lifecycle, causing orphaned attempts or false dead-agent detection.

| Field | Detail |
|-------|--------|
| **Trigger** | The remote Codex endpoint is slow or unresponsive during a builder/verifier phase; the HTTP client blocks past the configured timeout without propagating a structured `AgentTimeoutError`; or the monitor's health-check logic incorrectly classifies a running-but-slow remote session as dead. |
| **Affected step plans** | step-04 (remote transport timeout/retry handling), step-05 (monitor dead-agent detection for remote variant) |
| **Mitigation** | 1. Enforce explicit per-request and per-session connect/read timeouts on the remote HTTP client in step-04; map all `httpx.TimeoutException` and `httpx.NetworkError` variants to `AgentTimeoutError` or `AgentExecutionError` with retry context (step-04 error contract). 2. Ensure the step-05 monitor health-check path for `codex_server_remote` interrogates an explicit session-status endpoint rather than relying on a TCP keepalive; use the same check interval and dead-agent threshold already used for OpenHands Docker. 3. Add unit tests in step-04 that inject timeout exceptions at the transport layer and assert the correct error type and redaction behavior. 4. Add a step-05 integration test that simulates a hung remote session and confirms the monitor triggers cancellation without leaking the task lock. |
| **Blocking?** | **Yes** — an unhandled timeout that leaves a task locked or creates a zombie attempt violates the lifecycle contract (step-05 functional contract) and is a release blocker. A timeout that surfaces a clear `AgentTimeoutError` is not a blocker but must be covered by tests before step-06 completes. |

---

## R-03: Callback Parity

**Summary:** The REST and MCP callback channels do not behave identically for Codex server sessions, violating the contract-matrix §3 requirement that both channels are supported equally in v1.

| Field | Detail |
|-------|--------|
| **Trigger** | A Codex session uses the MCP callback path but `update_checklist`, `grade`, `submit`, or `request_clarification` produce different side-effects, error messages, or authorization failures compared to the equivalent REST path; or phase-aware tool availability differs between the two channels for Codex sessions specifically. |
| **Affected step plans** | step-03 (local agent callback tool registration), step-04 (remote agent callback transport preference), step-05 (executor callback auth propagation), step-06 (integration evidence for both channels) |
| **Mitigation** | 1. During step-03 and step-04, register callback tools via the shared `codex_server_common` adapter so the same tool-invocation logic runs regardless of transport; the adapter dispatches internally to REST or MCP based on the session's configured `callback_transport` field. 2. In step-03 verification, run the builder-phase callback flow once with `callback_transport=rest` and once with `callback_transport=mcp` and assert identical `ExecutionResult` and action-log entries. 3. In step-05, verify that executor auth propagation injects the correct credentials for both REST (HTTP header) and MCP (connection metadata) paths. 4. In step-06, include explicit integration evidence artifacts (test output or action logs) for both callback paths to satisfy the release gate contract (contract-matrix §6). |
| **Blocking?** | **Yes** — absent, broken, or untested support for either callback channel is an explicit release blocker per contract-matrix §3. |

---

## R-04: Allow-List Enforcement Gap

**Summary:** The `codex_server_common` adapter fails to reject tool invocations outside the v1 allow-list (`update_checklist`, `grade`, `submit`, `request_clarification`), allowing unintended tool calls to reach the orchestrator.

| Field | Detail |
|-------|--------|
| **Trigger** | A future Codex app server payload includes additional tool invocations beyond the four allow-listed callbacks (e.g., a new experimental tool or a shell command), and the adapter forwards them rather than rejecting and logging a warning. |
| **Affected step plans** | step-03 (allow-list enforcement in common adapter), step-04 (same enforcement on remote path), step-06 (unit test coverage for reject/warn behavior) |
| **Mitigation** | 1. Implement the allow-list check as an explicit guard at the earliest point in the tool-invocation path in `codex_server_common` (step-03 task 2). 2. On rejection, log a structured warning to the action log (not a silent drop) and return a well-formed tool-error response so the Codex session does not hang. 3. Add a unit test in step-03 that sends an out-of-list tool name and asserts the warning entry and rejection response. 4. Include the allow-list enforcement test in the step-06 regression suite. |
| **Blocking?** | **Yes** — enabling shell/file-editing or other non-allow-listed tools in a v1 session is a release blocker per contract-matrix §4. A gap in enforcement that is caught by tests and fixed before step-06 completes is not itself a blocker. |

---

## R-05: Token Leakage in Error Paths

**Summary:** The bearer token for `codex_server_remote` is exposed in error messages, action-log entries, or API responses due to incomplete secret redaction in transport error handling.

| Field | Detail |
|-------|--------|
| **Trigger** | An authentication failure (401/403) or network error in the remote transport includes the raw `Authorization` header value in the exception message, which is then propagated to `AgentExecutionError`, the action log, or the API error response. |
| **Affected step plans** | step-04 (secret-safe logging in remote transport), step-06 (test that confirms secrets are not logged on failure) |
| **Mitigation** | 1. Wrap the bearer token at construction time in step-04 using the same secret-field pattern used in the `api_key` config field (contract-matrix §2). 2. Ensure all exception catches in the remote transport client replace any stringified header map with a redacted placeholder before constructing `AgentExecutionError`. 3. Add a step-04 unit test that triggers a 401 response and asserts the token string is absent from the resulting error message and action-log entry. 4. Include the token-redaction assertion in the step-06 test suite to prevent regression. |
| **Blocking?** | **Yes** — logging or surfacing the raw bearer token is an explicit release blocker per contract-matrix §2. |

---

## R-06: Compatibility Version Detection Failure

**Summary:** `ToolDetector` silently accepts a detected Codex server version that does not match the supported version, violating the compatibility policy contract.

| Field | Detail |
|-------|--------|
| **Trigger** | The Codex app server version endpoint returns an unexpected format or version string; `ToolDetector` treats the result as valid rather than emitting a clear warning; the unsupported server version appears as a valid target to the user. |
| **Affected step plans** | step-02 (detector version metadata and warning logic), step-06 (CI integration test against latest documented version) |
| **Mitigation** | 1. Implement the version check in `ToolDetector` at step-02 as a strict equality match against the pinned supported version string, with a fallback to a clear warning (not silent pass) for any non-matching or unparseable response (contract-matrix §5). 2. Add a unit test that injects a mismatched version string and asserts the warning is present in the availability result. 3. In step-06 CI, run the detector against the latest documented server version to confirm the pinned version string remains current. |
| **Blocking?** | **No** — a version mismatch that surfaces a warning is not a blocker, but shipping detector code that silently accepts an unsupported version is a release blocker per contract-matrix §5. |

---

## Risk Summary

| ID | Name | Affected Steps | Blocking? |
|----|------|---------------|-----------|
| R-01 | Payload drift | step-02, step-03, step-04, step-06 | Yes |
| R-02 | Remote timeout behavior | step-04, step-05 | Yes |
| R-03 | Callback parity | step-03, step-04, step-05, step-06 | Yes |
| R-04 | Allow-list enforcement gap | step-03, step-04, step-06 | Yes |
| R-05 | Token leakage in error paths | step-04, step-06 | Yes |
| R-06 | Compatibility version detection failure | step-02, step-06 | No (unless silent) |

All five blocking risks must be mitigated and covered by tests before the release gate (contract-matrix §6) can be satisfied.
