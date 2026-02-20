# Intent: codex-server

## Original Request

I want to add a pair of new agents: Codex-Server and Codex-Server Remote. The integration should be researched and wired similarly to OpenHands, including support for experimental tool features.

## Goal

Add two first-class managed agent backends that let runs execute through a Codex server transport (local server and remote server), while preserving the existing orchestrator workflow contract: checklist updates, verification submission, grading, activity logging, recovery, and run lifecycle controls.

The integration baseline is the Codex app server interface documented at
`https://developers.openai.com/codex/app-server/`.

## Scope

### In Scope

- Introduce new agent options for `codex_server` and `codex_server_remote` in detection and API surfaces.
- Define concrete integration approach for both variants, aligned with existing OpenHands local/docker separation.
- Wire runtime creation/spawn paths so both new agent types run through `AgentExecutor`.
- Define how orchestrator callbacks/tools are exposed to Codex server sessions with equal v1 support for REST and MCP callback channels, including phase-aware tool availability.
- Restrict v1 experimental tool support to orchestrator callback tools only: `update_checklist`, `grade`, `submit`, and `request_clarification`.
- Define observability and parsing strategy so action logs and metrics remain compatible with existing UI and persistence.
- Define test strategy across unit, integration, and E2E with no mocking and real dependencies where applicable.
- Define compatibility and release policy: support the latest documented Codex app server version only, and block release until both `codex_server` and `codex_server_remote` are production-ready.

### Out of Scope

- Implementing additional non-Codex agent types.
- Redesigning workflow state machine semantics, gates, or checklist grading rules.
- Reworking existing OpenHands or CLI agent behavior beyond shared abstractions needed for Codex server support.
- Shipping new UI workflows unrelated to agent selection/configuration.

## Definition of Complete

- [ ] `AgentType` and API schemas support selecting `codex_server` and `codex_server_remote` without regressions to existing agents.
- [ ] Tool detection reports availability and config schema for both new agents with actionable install/connection guidance.
- [ ] `AgentExecutor` can create and spawn both new agents, and run lifecycle behavior matches managed-agent expectations (start, pause, resume, recovery).
- [ ] Codex server sessions can complete builder and verifier phases using orchestrator callback contract (checklist update, submit, grade, clarification where applicable).
- [ ] Action log and metrics remain populated in a format compatible with existing activity/UI views.
- [ ] Automated tests cover core logic and integration points, and `uv run pre-commit run --all-files` plus targeted test suites pass.
