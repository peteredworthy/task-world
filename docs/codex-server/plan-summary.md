# Plan Summary: codex-server

## Intent Satisfaction Summary

The generated plan satisfies the codex-server intent by defining a complete implementation path for both `codex_server` and `codex_server_remote` agent variants, with:

- Codex app server baseline locked as the required integration target.
- Required remote bearer-token auth model (`Authorization: Bearer <token>`).
- Equal v1 callback-channel support for REST and MCP.
- Strict v1 experimental-tool allow-list (`update_checklist`, `grade`, `submit`, `request_clarification`).
- Lifecycle parity expectations (start/resume/recover/cancel/monitor) with existing managed agents.
- A release gate that blocks shipping until both variants are production-ready.

This aligns with `docs/codex-server/intent.md`, `docs/codex-server/plan.md`, and clarified decisions in `docs/codex-server/clarifications.md`.

## Ordered Step List With Task Counts

Total planned steps: 6  
Total planned tasks: 18 (3 tasks per step)

1. Step 01: Research + Integration Contract (`docs/codex-server/steps/step-01.md`)  
   Task count: 3
2. Step 02: Types and Detector Support (`docs/codex-server/steps/step-02.md`)  
   Task count: 3
3. Step 03: Base Codex Server Agent Implementation (`docs/codex-server/steps/step-03.md`)  
   Task count: 3
4. Step 04: Remote Codex Server Variant (`docs/codex-server/steps/step-04.md`)  
   Task count: 3
5. Step 05: Executor and Monitor Integration (`docs/codex-server/steps/step-05.md`)  
   Task count: 3
6. Step 06: Tests, Documentation, and Release Hardening (`docs/codex-server/steps/step-06.md`)  
   Task count: 3

## Key Decisions

- Baseline interface: Codex app server documentation at `https://developers.openai.com/codex/app-server/`.
- Remote authentication: static API key bearer token.
- Callback policy: REST and MCP supported equally in v1.
- Tool policy: callback tools only in v1; non-callback experimental tools are out of scope.
- Compatibility policy: latest documented Codex app server only.
- Release policy: release blocked until both local and remote variants are production-ready.
- Delivery strategy: OpenHands-aligned architecture and lifecycle parity to minimize behavioral drift.

## Risks And Mitigations

1. Risk: Contract or behavior drift across planning artifacts.  
   Mitigation: keep `intent.md`, `plan.md`, `architecture.md`, and step files aligned; treat clarification decisions as binding.
2. Risk: Missing persistence/API compatibility for new agent enums.  
   Mitigation: explicit run create/read/update round-trip integration tests for both new types.
3. Risk: Callback parity regressions between REST and MCP or builder/verifier phases.  
   Mitigation: required 2x2 parity validation matrix (builder/verifier x REST/MCP) in remote/local execution coverage.
4. Risk: Unsafe or excessive tool exposure.  
   Mitigation: enforce allow-list and include negative tests for disallowed tool invocation.
5. Risk: Remote auth/transport failures causing opaque runtime errors.  
   Mitigation: explicit token-source precedence, retry/timeout policies, and typed/redacted error mapping.
6. Risk: Recovery ambiguity (stale vs healthy sessions).  
   Mitigation: deterministic stale-session conflict rule plus integration tests for both branches.
7. Risk: Release quality gate bypass for one variant.  
   Mitigation: dual-variant production-readiness gate in final validation and release documentation.

## Caveats For Execution

- Stage 9 execution should not start until all previously identified REQUIRED dry-run remediations are present in step tasks (`docs/codex-server/dry-run-notes.md`).
- `docs/codex-server/design-questions.md` and `docs/codex-server/plan-changes.md` are currently absent; this was treated as non-blocking in Stage 7, but any new unresolved design ambiguity should recreate these artifacts or block affected tasks.
- Implementation must preserve repository-wide constraints: no mocking in tests, explicit DI, and runnable state after each atomic task chunk.
- Verification commands must use explicit required test targets where specified (not only broad `-k` filters) to avoid false confidence.
- Documentation updates (`AGENTS.md`, `docs/ARCHITECTURE.md`) must be kept in lockstep with actual implemented modules and API exposure before release sign-off.
