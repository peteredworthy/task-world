# Plan: codex-server

## Contract Source of Truth

> **Normative reference:** [`context/contract-matrix.md`](context/contract-matrix.md)
>
> All integration decisions (auth, callbacks, tool scope, compatibility, release gate) are locked in
> the contract matrix. The sections below summarise those decisions for planning purposes only.
> In the event of any discrepancy between this document and `context/contract-matrix.md`, the
> contract matrix takes precedence. Deviations require a new clarification entry in
> `docs/codex-server/clarifications.md` **before** implementation may proceed.

## Overview

Implement Codex-Server in iterative milestones that de-risk unknowns first: transport/tooling research, domain model updates, agent runtime implementation, orchestrator wiring, and verification hardening. The plan keeps the system runnable after each step and mirrors proven OpenHands patterns where possible.

## Milestones

### Milestone 1: Discovery and Contract Lock

- Confirm Codex server SDK/API surface for local and remote session execution.
- Confirm experimental tool feature requirements and map them to orchestrator tool contract.
- Produce integration contract for prompts, callbacks, tool registration, and event parsing.
- Record finalized decisions from human clarification:
  - Baseline interface: Codex app server docs (`https://developers.openai.com/codex/app-server/`)
  - Remote auth: static API key via `Authorization: Bearer <token>`
  - Callback channel policy: support REST and MCP equally in v1
  - Experimental tool scope: callback tools only (`update_checklist`, `grade`, `submit`, `request_clarification`)
  - Compatibility: latest documented Codex app server only
  - Release gate: block release until both variants are production-ready

### Milestone 2: Domain and Detection Foundations

- Add new `AgentType` enum values and keep schema compatibility across state/API layers.
- Extend `ToolDetector` with availability checks and config schemas for both Codex server variants.
- Define new config fields (endpoint/base URL, auth/token source, model, tool set, timeouts, transport).

### Milestone 3: Agent Runtime Implementation

- Add `CodexServerAgent` (local server integration) and `CodexServerRemoteAgent` (remote endpoint integration).
- Implement prompt/callback bridging with phase-aware builder/verifier behavior.
- Implement execution result normalization (success/error, metrics, output lines, action log entries).

### Milestone 4: Executor and Workflow Wiring

- Extend `AgentExecutor._create_agent` and spawn support for both new managed types.
- Ensure lifecycle parity with existing managed agents (start/resume/recovery, cancellation, dead-agent monitoring).
- Ensure MCP/REST callback instructions and auth handling remain correct for Codex server execution contexts.

### Milestone 5: Verification and Rollout Hardening

- Add/extend tests for detector behavior, agent execution contract, executor branching, and API agent listing.
- Run focused integration scenarios for builder and verifier phases.
- Update docs (`AGENTS.md`, `docs/ARCHITECTURE.md`) with new modules/routes/config where introduced.

## Implementation Order

1. **Step 1: Research + integration contract**
   - Prerequisites: None
   - Deliverables: Documented Codex server capability matrix, tool/callback mapping, explicit open questions, and architecture deltas.

2. **Step 2: Types and detector support**
   - Prerequisites: Step 1
   - Deliverables: `AgentType` additions, detector options/config schemas, API serialization compatibility for new types.

3. **Step 3: Base Codex server agent implementation**
   - Prerequisites: Step 2
   - Deliverables: `CodexServerAgent` with execution contract parity to existing managed agents.

4. **Step 4: Remote variant implementation**
   - Prerequisites: Step 3
   - Deliverables: `CodexServerRemoteAgent` transport/auth differences, shared parser/adapter abstractions, resilient error handling.

5. **Step 5: Executor/monitor integration**
   - Prerequisites: Steps 3-4
   - Deliverables: `AgentExecutor` creation/spawn paths and monitor handling for both new types.

6. **Step 6: Tests and docs completion**
   - Prerequisites: Steps 2-5
   - Deliverables: Unit/integration coverage, updated architecture docs, and checklist-driven verification evidence.

## Key Decisions

> Decisions in this table are derived from and governed by the binding contract in
> [`context/contract-matrix.md`](context/contract-matrix.md). The contract matrix is the normative
> record; this table is a convenience summary only.

| Decision | Choice | Contract Section |
|----------|--------|-----------------|
| Agent topology | Two dedicated managed agent types (`codex_server`, `codex_server_remote`) | §1 Interface Contract |
| Integration baseline | Reuse OpenHands-style contract boundaries (prompt builder, callback bridge, action normalization) | §1 Interface Contract |
| Baseline server contract | Codex app server at `https://developers.openai.com/codex/app-server/` | §1 Interface Contract |
| Remote auth model | Static API key bearer token (`Authorization: Bearer <token>`) | §2 Authentication Contract |
| Callback channel policy | Support REST and MCP equally in v1 | §3 Callback Channel Contract |
| Experimental tool scope | Callback tools only (`update_checklist`, `grade`, `submit`, `request_clarification`) | §4 Tool Allow-List Contract |
| Compatibility target | Latest documented Codex app server only | §5 Compatibility Policy Contract |
| Rollout/release gate | Block release until both `codex_server` and `codex_server_remote` are production-ready | §6 Release Gate Contract |

## Contract Constraints and Mismatch Handling

The following constraints are binding on all implementation work in this plan. Each constraint
maps to a non-go condition in [`context/contract-matrix.md`](context/contract-matrix.md).

| Constraint | Non-Go Condition | Contract Section |
|-----------|-----------------|-----------------|
| All transport/payload/session-lifecycle behaviour must conform to the Codex app server spec | Any deviation without a recorded change-request in `clarifications.md` blocks release | §1 |
| `codex_server_remote` must inject `Authorization: Bearer <token>` from a configured secret; token must not appear in logs | Shipping without bearer-token injection or logging the raw token blocks release | §2 |
| Both REST and MCP callback channels must be supported and tested equally | Either channel absent, broken, or untested blocks release | §3 |
| v1 tool allow-list is exactly: `update_checklist`, `grade`, `submit`, `request_clarification` | Enabling any out-of-scope tool (shell, file-edit, repo-browse) blocks release | §4 |
| Detector must report the supported version and warn on mismatch (no silent failure) | Silently accepting an undocumented or outdated server version blocks release | §5 |
| Release is a single atomic delivery of both variants; no partial launch | Releasing with one variant failing or absent blocks release | §6 |

**Mismatch handling procedure:** If an implementation choice conflicts with any contract constraint
listed above, the implementor must:

1. **Stop** — do not implement the conflicting behaviour.
2. **Record** — add a new clarification entry in `docs/codex-server/clarifications.md` describing
   the conflict and proposed resolution.
3. **Update** — once a new clarification decision is reached, update `context/contract-matrix.md`
   before resuming implementation.
4. **Re-verify** — re-run all affected checklist items with the verifier after the matrix update.

## References

- **`docs/codex-server/context/contract-matrix.md`** ← normative contract source of truth
- `docs/codex-server/clarifications.md`
- `docs/plan-runner/idea_to_plan_stripped.md`
- `docs/plan-runner/idea_to_plan_detailed.md`
- `docs/planner/templates/intent.md`
- `docs/planner/templates/plan.md`
- `docs/planner/templates/architecture.md`
- `src/orchestrator/config/enums.py`
- `src/orchestrator/agents/detector.py`
- `src/orchestrator/agents/executor.py`
- `src/orchestrator/agents/openhands.py`
- `src/orchestrator/agents/openhands_docker.py`
- `src/orchestrator/agents/cli.py`
- `src/orchestrator/mcp/server.py`
- `src/orchestrator/mcp/tools.py`
- `tests/unit`
- `tests/integration`
