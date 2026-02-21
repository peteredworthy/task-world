# Architecture: codex-server

## Contract Source of Truth

> **Normative reference:** [`context/contract-matrix.md`](context/contract-matrix.md)
>
> All binding integration decisions (auth, callbacks, tool scope, compatibility, release gate) are
> locked in the contract matrix. Architectural decisions below must remain consistent with it.
> In the event of any discrepancy between this document and `context/contract-matrix.md`, the
> contract matrix takes precedence. Deviations require a new clarification entry in
> `docs/codex-server/clarifications.md` **before** implementation may proceed.

## Current State

The orchestrator currently supports managed agents through `AgentExecutor` for:
- `cli_subprocess` (`src/orchestrator/agents/cli.py`)
- `openhands_local` (`src/orchestrator/agents/openhands.py`)
- `openhands_docker` (`src/orchestrator/agents/openhands_docker.py`)

Agent availability is exposed via `ToolDetector` (`src/orchestrator/agents/detector.py`) and surfaced by `GET /api/agents` (`src/orchestrator/api/routers/agents.py`). Execution contexts include run/task IDs, prompt, requirements, callback base URL, and optional auth (`src/orchestrator/agents/types.py`).

OpenHands establishes the closest reference architecture: explicit tool registration, callback bridging for checklist/submit/grade, and normalized execution metrics/action logs (`src/orchestrator/agents/openhands_common.py`).

## Proposed Changes

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `CodexServerAgent` | `src/orchestrator/agents/codex_server.py` | Managed local-server execution path, tool/callback wiring, metrics/action normalization |
| `CodexServerRemoteAgent` | `src/orchestrator/agents/codex_server_remote.py` | Managed remote-server execution path with auth/endpoint handling and robust network error mapping |
| `codex_server_common` helpers | `src/orchestrator/agents/codex_server_common.py` | Shared prompt composition, tool schema mapping, callback adapter, and event-to-action-log normalization |

### Modified Components

| Component | Changes |
|----------|---------|
| `src/orchestrator/config/enums.py` | Add `AgentType.CODEX_SERVER` and `AgentType.CODEX_SERVER_REMOTE` |
| `src/orchestrator/agents/detector.py` | Add availability/config detection for both Codex server variants |
| `src/orchestrator/agents/executor.py` | Create/spawn branches for both new agent types |
| `src/orchestrator/agents/monitor.py` | Extend alive/dead checks for Codex server managed processes/sessions if required |
| `src/orchestrator/api/schemas/runs.py` | Add display/icon mapping support for new `AgentType` values |
| `src/orchestrator/api/routers/agents.py` | No route shape changes; returns expanded options via detector |

### Interactions

1. User selects Codex-Server variant from `/api/agents` options.
2. Run starts via existing flow; `AgentExecutor` instantiates new codex server agent class.
3. Agent receives `ExecutionContext` and runs builder/verifier prompt contract.
4. Agent invokes orchestrator callbacks/tools (REST or MCP) to update checklist, grade, submit, and request clarification.
5. Agent events are normalized into existing `ActionLog` model and attempt metrics.
6. Workflow and persistence paths remain unchanged (`WorkflowService`, DB repository/event store).

## Technology Choices

> Choices marked **[Contract §N]** are binding decisions governed by
> [`context/contract-matrix.md`](context/contract-matrix.md). They must not be changed without
> updating the contract matrix first.

| Area | Choice | Rationale / Contract |
|------|--------|---------------------|
| Transport abstraction | Shared adapter module for local and remote Codex server clients | Avoid duplicate protocol handling and keep behavior consistent. |
| Tool integration | Experimental tool features wrapped behind orchestrator-owned adapter API | Contains vendor churn and preserves stable internal contracts. |
| Callback interface | Reuse existing REST/MCP orchestrator callback contract with equal v1 support for both channels | **[Contract §3]** — REST and MCP must be supported equally; neither is optional. |
| Observability | Reuse `ActionLog` schema + parser-normalizer pattern | Keeps UI and analytics compatibility with current event consumers. |
| Failure model | Map transport/tool/auth errors to explicit `Agent*Error` types | Aligns with existing error handling in API/workflow layers. |
| Baseline interface | Codex app server docs (`https://developers.openai.com/codex/app-server/`) | **[Contract §1]** — authoritative integration target for local and remote variants. |
| Remote auth | Static API key via `Authorization: Bearer <token>` | **[Contract §2]** — bearer token from configured secret; token must not appear in logs. |
| Compatibility policy | Latest documented Codex app server only | **[Contract §5]** — explicit support boundary; detector must warn on version mismatch. |
| Release gate | Block release until both `codex_server` and `codex_server_remote` are production-ready | **[Contract §6]** — atomic delivery; no partial launch permitted. |
| v1 tool allow-list | `update_checklist`, `grade`, `submit`, `request_clarification` only | **[Contract §4]** — all other tools (shell, file-edit, repo-browse) are release blockers if enabled. |

## Testing Strategy

- **Unit Tests:**
  - `detector`: availability branches, config schemas, install hints for local/remote Codex server.
  - `codex_server_common`: prompt/tool mapping, callback payload validation, event normalization.
  - `executor`: `_create_agent` dispatch and spawn allow-list includes new types.

- **Integration Tests:**
  - Managed run start/resume paths with each new agent type configured.
  - Builder phase updates checklist and submits via callback contract.
  - Verifier phase sets grades and completes verification.
  - API `GET /api/agents` returns both options with accurate availability info.

- **E2E/Functional Checks:**
  - Create run with each new type, start, complete at least one builder/verifier cycle, verify persisted metrics/action logs.
  - Recovery and pause/resume behavior remains consistent with other managed agents.

## Security Considerations

- Remote variant must support secure auth/token injection without logging secrets.
- Tool execution scope must remain constrained to worktree/project paths.
- Callback authentication headers/tokens must continue to be honored for REST and MCP paths.
- Experimental tool capabilities must be explicitly allow-listed per phase to avoid over-privileged actions.
- v1 allow-list is limited to orchestrator callback tools only: `update_checklist`, `grade`, `submit`, `request_clarification`.

## Performance Considerations

- Keep streaming/event handling incremental to avoid buffering large outputs.
- Bound retries/timeouts for remote network calls to prevent blocking executor loops.
- Reuse existing metrics collection pipeline; avoid heavy per-event transformations.
- Ensure monitor/executor health checks for new agent types are lightweight and non-blocking.

## Contract Constraints

The following constraints are binding on all architectural and implementation work. Each maps to a
non-go condition in [`context/contract-matrix.md`](context/contract-matrix.md), which is the
normative source of truth.

| Constraint | Non-Go Condition | Contract § |
|-----------|-----------------|-----------|
| All transport/payload/session-lifecycle behaviour must conform to the Codex app server spec at `https://developers.openai.com/codex/app-server/` | Any deviation without a recorded change-request in `clarifications.md` blocks release | §1 |
| `codex_server_remote` must inject `Authorization: Bearer <token>` from a configured secret; local variant (`codex_server`) requires no bearer auth | Shipping without bearer-token injection or logging the raw token blocks release | §2 |
| Both REST and MCP callback channels must be supported and tested equally in v1 | Either channel absent, broken, or untested blocks release | §3 |
| v1 tool allow-list is exactly four tools: `update_checklist`, `grade`, `submit`, `request_clarification`; `codex_server_common` must reject/warn on any invocation outside this list | Enabling shell, file-editing, repo-browsing, or any other Codex experimental tool blocks release | §4 |
| `ToolDetector` must report the supported server version and emit a clear warning (not silent failure) on version mismatch | Silently accepting an undocumented or outdated server version blocks release | §5 |
| Release is a single atomic delivery of both variants; no per-variant feature flags | Releasing with one variant failing or absent blocks release | §6 |

## Mismatch Handling

If any implementation choice is found to conflict with a constraint above, the implementor must:

1. **Stop** — do not implement the conflicting behaviour.
2. **Record** — add a new entry in `docs/codex-server/clarifications.md` describing the conflict
   and the proposed resolution.
3. **Update** — once a new clarification decision is reached, update `context/contract-matrix.md`
   before resuming implementation.
4. **Re-verify** — re-run all affected checklist items with the verifier after the matrix is
   updated.

This procedure applies equally to ambiguities discovered during integration testing, CI failures
related to contract constraints, and any vendor-driven changes to the Codex app server interface.
