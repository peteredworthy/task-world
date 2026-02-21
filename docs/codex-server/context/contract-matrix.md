# Codex-Server Integration Contract Matrix

**Status:** Baseline locked
**Date:** 2026-02-20
**Sources:** `docs/codex-server/clarifications.md`, `docs/codex-server/architecture.md`, `docs/codex-server/intent.md`, `docs/codex-server/plan.md`

This document converts every resolved clarification into an enforceable contract artifact. Each row
names the decision, states the binding rule, records the clarification reference that authorised it,
and lists the non-go condition that would block a release.

---

## 1. Interface Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | The authoritative integration baseline is the Codex app server interface documented at `https://developers.openai.com/codex/app-server/`. All transport, payload structure, and session-lifecycle behaviour must conform to that specification. |
| **Variants** | `codex_server` (local managed process) and `codex_server_remote` (remote HTTP endpoint) |
| **Reference architecture** | OpenHands local/docker split — same `AgentExecutor` dispatch pattern, same `ActionLog` schema |
| **Clarification source** | Clarification 1 → Q1: user answered `https://developers.openai.com/codex/app-server/` |
| **Non-go condition** | Any implementation that deviates from the Codex app server spec without a recorded change-request in `clarifications.md` is a release blocker. |

---

## 2. Authentication Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | `codex_server_remote` MUST authenticate using a static API key injected as `Authorization: Bearer <token>`. The token value MUST come from a configured secret/env-var and MUST NOT appear in logs, action-log entries, or API responses. |
| **Local variant** | `codex_server` (local process) requires no bearer auth; trusted network is assumed for the loopback transport. |
| **Config field** | `api_key` (secret field) on the `codex_server_remote` config schema |
| **Clarification source** | Clarification 1 → Q2 (research delegated) resolved by Clarification 2 → Q1: "Static API key via Authorization: Bearer `<token>`" |
| **Non-go condition** | Shipping `codex_server_remote` without bearer-token injection, or logging the raw token value anywhere, is a release blocker. |

---

## 3. Callback Channel Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | Both REST and MCP callback channels MUST be supported equally in v1. Neither channel is optional or degraded. A Codex server session may use either channel to call `update_checklist`, `grade`, `submit`, and `request_clarification`. |
| **REST path** | Existing orchestrator REST endpoints (`PATCH /api/runs/{id}/tasks/{id}/checklist/{req_id}`, `POST /api/runs/{id}/tasks/{id}/submit`, etc.) |
| **MCP path** | `OrchestratorMCPServer` tools (`src/orchestrator/mcp/server.py`, `src/orchestrator/mcp/tools.py`) |
| **Phase awareness** | Callback availability must be phase-aware: builder-phase tools differ from verifier-phase tools consistent with existing prompt contract. |
| **Clarification source** | Clarification 1 → Q3: "Support both equally in v1" |
| **Non-go condition** | If either REST or MCP callback path is absent, broken, or untested for a Codex server session, the integration MUST NOT be released. |

---

## 4. Tool Allow-List Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | The v1 experimental tool allow-list is limited to exactly four orchestrator callback tools. No other tools may be injected into Codex server sessions without a new clarification and a documented change to this matrix. |
| **v1 allow-list** | `update_checklist`, `grade`, `submit`, `request_clarification` |
| **Enforcement point** | `codex_server_common` adapter MUST reject or ignore any tool invocation outside this list and log a warning to the action log. |
| **Clarification source** | Clarification 1 → Q4: "Only orchestrator callback tools (update_checklist, grade, submit, request_clarification)" |
| **Non-go condition** | Enabling shell/file-editing tools, repository-browsing tools, or any other Codex experimental capabilities in v1 sessions is a release blocker. See §7 for explicit out-of-scope items. |

---

## 5. Compatibility Policy Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | The orchestrator MUST support the latest documented Codex app server version only. No backward-compatibility shims for previous minor or patch versions are required or permitted in v1. |
| **Detection** | `ToolDetector` MUST report the supported version in the availability check result and emit a clear warning (not silent failure) if the detected server version does not match. |
| **CI coverage** | Integration tests MUST run against the latest documented server version. Testing against prior versions is not required. |
| **Clarification source** | Clarification 2 → Q2: "Latest documented Codex app server only" |
| **Non-go condition** | Shipping detector or integration code that silently accepts or targets an undocumented or outdated server version is a release blocker. |

---

## 6. Release Gate Contract

| Attribute | Value |
|-----------|-------|
| **Binding rule** | Release is blocked until BOTH `codex_server` AND `codex_server_remote` are independently verified as production-ready. A partial release (one variant only) is not permitted. |
| **Definition of production-ready** | All definition-of-done criteria in `docs/codex-server/intent.md` pass for the variant, targeted integration tests pass, and the verifier has graded all checklist items `done`. |
| **Feature flags** | Feature flags per variant are not used; the release is a single atomic delivery of both variants. |
| **Clarification source** | Clarification 2 → Q3: "Block release until both codex_server and codex_server_remote are production-ready" |
| **Non-go condition** | Marking a release as complete with one variant still failing or absent is a release blocker. |

---

## 7. Out-of-Scope v1 Items

The following capabilities are explicitly excluded from v1. They may be considered in future tasks
but MUST NOT be implemented or enabled in v1 sessions without a new clarification decision recorded
in `clarifications.md`.

| Item | Reason excluded |
|------|----------------|
| Repository browsing tools (e.g. file-tree listing, diff viewers via Codex tools) | Not in the Q4 allow-list; would expand the tool surface beyond the callback contract. |
| Shell / file-editing tools exposed via Codex experimental tool API | Explicitly ruled out by Q4 answer; creates over-privileged execution scope. |
| Full Codex experimental toolset | Q4 selected the narrowest option; broad tool enablement deferred to a future scope decision. |
| OAuth / OIDC access tokens for remote auth | Q2 (Clarification 2) selected bearer API key; OAuth deferred. |
| mTLS client certificate auth | Q2 (Clarification 2) selected bearer API key; mTLS deferred. |
| Support for multiple simultaneous auth methods on remote variant | Q2 (Clarification 2) selected a single required auth method for v1. |
| Backward-compatible support for prior Codex app server versions | Q2 (Clarification 2) scoped compatibility to latest version only. |
| Per-variant feature flags / partial rollout | Q3 (Clarification 2) selected atomic release; feature flags deferred. |
| Redesigning workflow state machine, gates, or grading rules | Listed as out of scope in `intent.md`. |
| New UI workflows unrelated to agent selection/configuration | Listed as out of scope in `intent.md`. |
| New non-Codex agent types | Listed as out of scope in `intent.md`. |
| Reworking existing OpenHands or CLI agent behaviour | Listed as out of scope in `intent.md` (shared abstractions only where necessary). |

---

## Traceability Summary

| Contract Area | Clarification File Reference | Decision Date |
|---------------|------------------------------|---------------|
| Interface | Clarification 1 → Q1 | 2026-02-20T14:03:44Z |
| Authentication | Clarification 1 → Q2 + Clarification 2 → Q1 | 2026-02-20T14:03:44Z / 14:12:29Z |
| Callback channels | Clarification 1 → Q3 | 2026-02-20T14:03:44Z |
| Tool allow-list | Clarification 1 → Q4 | 2026-02-20T14:03:44Z |
| Compatibility policy | Clarification 2 → Q2 | 2026-02-20T14:12:29Z |
| Release gate | Clarification 2 → Q3 | 2026-02-20T14:12:29Z |
| Out-of-scope v1 items | Clarification 1 → Q4 + `intent.md` | 2026-02-20T14:03:44Z |

All clarifications are recorded with timestamps and user attribution in
`docs/codex-server/clarifications.md`. Any change to the decisions in this matrix requires a new
clarification entry before the implementation may proceed.
