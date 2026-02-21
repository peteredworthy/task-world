# AGENTS.md

This file provides guidance to coding agents working with code in this repository.

## Project Overview

**Orchestrator** coordinates LLM-powered coding agents through structured workflows. It uses a **Routine/Run** model where git-versioned routine templates define multi-step tasks, and runs execute them with a user-selected agent (OpenHands, CLI subprocess, or external MCP). Each task goes through a builder/verifier cycle with fresh LLM context per phase.

Design documentation lives in `docs/intent/`. Implementation follows the phased plan in the slice documents. Phases 1-8 are implemented.

## Run Execution Model (Worktrees + Agents)

- Each run executes in its own git worktree under `worktrees/run-<run-id>/`.
- The selected agent backend (OpenHands, Claude Code via CLI agent, Codex CLI agent, or external MCP/user-managed) operates inside that run worktree, not the main checkout.
- Artifacts created by agents are written inside the run worktree first (for example `worktrees/run-<run-id>/docs/<feature>/...`).
- Auto-verify and verification steps run against the run worktree path.
- Run commits (`start_commit`/`end_commit`) are recorded from the worktree branch (`orchestrator/run-<run-id>`), then merged back according to completion actions.
- If expected files are not visible in the main repo root, check the run worktree before assuming generation failed.

## Quick Navigation

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for:
- **Directory map** - Full project structure with file descriptions
- **How to run** - Backend (port 8000), frontend (port 5173), and all service URLs
- **API routes** - Complete REST endpoint reference
- **CLI commands** - All orchestrator commands
- **Tech stack** - Python/FastAPI backend, React/Vite frontend

## Slice Documents

Always read the relevant slice document before working on a phase. Each slice lists deliverables, architecture constraints, implementation steps, and definition-of-done checklists.

| File | Phase | Slices | Content |
|------|-------|--------|---------|
| `docs/intent/10-SLICES-OVERVIEW.md` | All | — | Master overview, principles, dependency graph |
| `docs/intent/11-SLICES-PHASE-1.md` | 1 | 1.1–1.6 | Foundation: skeleton, config, routines, state, session, history |
| `docs/intent/12-SLICES-PHASE-2.md` | 2 | 2.1–2.5 | Workflow: gates, grades, state machine, prompts, events |
| `docs/intent/13-SLICES-PHASE-3.md` | 3 | 3.1–3.4 | Persistence: SQLite, repository, event store, integrated persistence |
| `docs/intent/14-SLICES-PHASE-4.md` | 4 | 4.1–4.5 | API: FastAPI setup, routine/run/task endpoints, WebSocket |
| `docs/intent/15-SLICES-PHASE-5.md` | 5 | 5.1–5.6 | Agents: interface, tool detector, OpenHands, CLI+nudger, MCP |
| `docs/intent/16-SLICES-PHASE-6.md` | 6 | 6.1–6.4 | Web UI: React/TypeScript/Vite/Tailwind/TanStack Query |
| `docs/intent/17-SLICES-PHASE-7.md` | 7 | 7.1–7.3 | Git: worktrees, routine versioning, completion actions |
| `docs/intent/18-SLICES-PHASE-8.md` | 8 | 8.1–8.3 | CLI & polish: Click commands, error handling, E2E suite |

Other intent docs: `01-PRD.md` through `09-*.md` cover architecture, data models, API design, agent protocols, etc.

### Slice-to-Implementation Map (Phases 3–4)

**Phase 3 – Persistence:**

| Slice | Deliverable | Implementation | Tests |
|-------|------------|----------------|-------|
| 3.1 DB Setup | ORM models, engine, session factory | `db/base.py`, `db/models.py`, `db/connection.py` | `tests/integration/test_database.py` |
| 3.2 Repository | RunRepository (CRUD, ORM↔Pydantic) | `db/repositories.py` | `tests/integration/test_repositories.py` |
| 3.3 Event Store | EventStore, PersistentEventEmitter, recovery | `db/event_store.py`, `workflow/event_logger.py`, `db/recovery.py` | `tests/integration/test_event_recovery.py` |
| 3.4 Integrated | WorkflowService (engine↔repo↔events) | `workflow/service.py` | `tests/integration/test_workflow_service.py`, `test_full_persistence.py` |

**Phase 4 – API:**

| Slice | Deliverable | Implementation | Tests |
|-------|------------|----------------|-------|
| 4.1 App Factory | FastAPI app, DI, error handlers, health | `api/app.py`, `api/deps.py`, `api/errors.py` | `tests/integration/test_api_health.py` |
| 4.2 Routines | GET /api/routines, GET /api/routines/{id} | `api/routers/routines.py`, `api/schemas/routines.py` | `tests/integration/test_api_routines.py` |
| 4.3 Runs | CRUD + start run | `api/routers/runs.py`, `api/schemas/runs.py` | `tests/integration/test_api_runs.py` |
| 4.4 Tasks | Task ops, checklist, grades | `api/routers/tasks.py`, `api/schemas/tasks.py` | `tests/integration/test_api_tasks.py` |
| 4.5 WebSocket | ConnectionManager, per-run subscriptions | `api/websocket.py` | `tests/integration/test_api_websocket.py` |

## Commands

```bash
# Package management (ALWAYS use uv, never pip)
uv sync
uv add <package>
uv add --group dev <package>

# Tests
uv run pytest                                              # all tests
uv run pytest tests/unit -v                                # unit only
uv run pytest tests/integration -v                         # integration only
uv run pytest tests/unit/test_workflow.py::test_func       # single test
uv run pytest --cov=orchestrator --cov-report=html         # with coverage

# Type checking and linting
uv run pyright
uv run ruff check .
uv run ruff format .

# Server
uv run orchestrator serve --reload

# CLI
uv run orchestrator routine list
uv run orchestrator run list --status active
uv run orchestrator run create <routine> --project <path> --config '<json>'
uv run orchestrator run agents <run-id>
uv run orchestrator run start <id> --agent <type>
```

## Architecture

### Core Flow

```
User creates Run → Selects Agent → Start (create worktree, acquire lock)
  → Builder Phase (fresh context) → submit → Gates check
  → Verifier Phase (fresh context) → grade each requirement → complete-verification
  → Pass: next task | Revision: back to Builder (fresh context, attempt++)
```

### Key Modules (under `src/orchestrator/`)

| Module | Purpose | Phase |
|--------|---------|-------|
| `config/models.py` | Pydantic models: RoutineConfig, StepConfig, TaskConfig | 1 |
| `config/enums.py` | RunStatus, TaskStatus, ChecklistStatus, Priority, AgentType | 1 |
| `routines/loader.py` | Load and validate YAML routine definitions | 1 |
| `routines/discovery.py` | Discover routines from directories with source tracking | 1/4 |
| `routines/errors.py` | RoutineNotFoundError, RoutineParseError, RoutineValidationError | 1 |
| `state/models.py` | Runtime state: Run, StepState, TaskState, Attempt, ChecklistItem | 1 |
| `state/session.py` | SessionStateManager: in-memory state with JSON file persistence | 1 |
| `state/factory.py` | Factory functions to create Run from RoutineConfig | 1 |
| `state/errors.py` | RunNotFoundError, TaskNotFoundError, ChecklistItemNotFoundError | 1 |
| `workflow/gates.py` | Checklist gate evaluation (pure function) | 2 |
| `workflow/grades.py` | Grade threshold evaluation (pure function) | 2 |
| `workflow/transitions.py` | Pure state transition functions (task status changes) | 2 |
| `workflow/engine.py` | Sync WorkflowEngine: orchestrates state machine via SessionStateManager | 2 |
| `workflow/prompts.py` | Builder/verifier prompt generation (pure functions) | 2 |
| `workflow/events.py` | Event types + BufferingEmitter (sync in-memory event buffer) | 2 |
| `workflow/errors.py` | GateBlockedError, InvalidTransitionError | 2 |
| `db/models.py` | SQLAlchemy ORM: RunModel, StepModel, TaskModel, AttemptModel, EventModel | 3 |
| `db/connection.py` | Async engine + session factory (SQLite via aiosqlite) | 3 |
| `db/repositories.py` | RunRepository: CRUD with ORM↔Pydantic conversion | 3 |
| `db/event_store.py` | EventStore: persist and query workflow events | 3 |
| `workflow/event_logger.py` | PersistentEventEmitter: async event persistence + broadcast | 3 |
| `workflow/service.py` | WorkflowService: async wrapper bridging engine↔repository↔events | 3/4 |
| `api/app.py` | FastAPI app factory with lifespan, DI via app.state | 4 |
| `api/deps.py` | FastAPI Depends: session, repository, event store, service | 4 |
| `api/errors.py` | Domain exception → HTTP status code handlers | 4 |
| `api/websocket.py` | ConnectionManager: per-run WebSocket subscriptions | 4 |
| `api/routers/routines.py` | GET /api/routines, GET /api/routines/{id} | 4 |
| `api/routers/runs.py` | CRUD endpoints for runs | 4 |
| `api/routers/tasks.py` | Task operations, checklist updates, grade submission | 4 |
| `agents/interface.py` | Agent Protocol (execute, cancel, info) | 5 |
| `agents/types.py` | ExecutionContext, ExecutionResult, AgentOption, AgentConfigField | 5 |
| `agents/detector.py` | ToolDetector: detect available agents (including Codex Server variants), config schemas; exposes all options via `GET /api/agents` | 5 |
| `agents/openhands_common.py` | Shared OpenHands code: executors, CallbackRegistry, prompt building | 5 |
| `agents/openhands.py` | OpenHands Local agent (in-process via SDK LocalConversation) | 5 |
| `agents/openhands_docker.py` | OpenHands Docker agent (ephemeral container via DockerWorkspace) | 5 |
| `agents/cli.py` | CLIAgent: subprocess with nudger, REST/MCP callback channels | 5 |
| `agents/codex_server_common.py` | Shared helpers for Codex Server agents: prompt assembly, tool allow-list enforcement (update_checklist/grade/submit/request_clarification only), output normalization | 5 |
| `agents/codex_server.py` | CodexServerAgent: local managed-process variant — launches `codex app-server` via stdio/loopback, no bearer auth required | 5 |
| `agents/codex_server_remote.py` | CodexServerRemoteAgent: remote bearer-authenticated HTTPS variant — connects to a pre-existing `codex app-server` instance; token resolved from constructor arg → env var → `OPENAI_API_KEY` | 5 |
| `agents/user_managed.py` | UserManagedAgent: waits for external submit via REST/MCP | 5 |
| `agents/nudger.py` | Nudger for stuck CLI agents (timeout, nudge, kill) | 5 |
| `agents/errors.py` | AgentExecutionError, AgentNotAvailableError, AgentCancelledError, AgentTimeoutError | 5 |
| `mcp/server.py` | OrchestratorMCPServer: MCP tools via FastMCP (SSE + stdio) | 5 |
| `mcp/tools.py` | MCP tool definitions and ToolHandler | 5 |
| `git/worktree.py` | Git worktree creation/cleanup | 7 |
| `git/branch_ops.py` | Branch operations (merge, back-merge, status) | 7 |
| `git/project_init.py` | Project initialization via git | 7 |
| `agents/action_log.py` | Structured agent activity log | 5 |
| `agents/nudger.py` | Stuck agent nudging (timeout, nudge, kill) | 5 |
| `agents/parsers/*.py` | Per-agent output stream parsers (Claude, Codex, OpenHands) | 5 |
| `artifacts/registry.py` | Artifact tracking for generated files | — |
| `repos/discovery.py` | Repository discovery and metadata | — |
| `repos/models.py` | RepoInfo, BranchInfo models | — |
| `metrics/cost.py` | Token counting and cost tracking | — |
| `scaffolding/copier.py` | Project scaffolding via copier | — |
| `envfiles/resolution.py` | Environment variable resolution | — |
| `envfiles/cleanup.py` | Env file cleanup operations | — |
| `workflow/auto_verify.py` | Automatic verification logic | 2 |
| `workflow/clarifications.py` | Clarification workflow handling | — |
| `workflow/completion.py` | Run completion logic | — |
| `workflow/context_builder.py` | Build execution context for agents | — |
| `workflow/dry_run.py` | Dry run execution | — |
| `api/routers/repos.py` | Repository browser endpoints | — |
| `api/routers/clarifications.py` | Clarification request endpoints | — |
| `api/routers/config.py` | GET /api/config | — |
| `api/routers/envfiles.py` | Environment file endpoints | — |
| `cli/repos.py` | Repository CLI commands | — |
| `cli/approve.py` | Human approval CLI commands | — |

### Entity Hierarchy

```
Project → Run → Routine (git-versioned) → Step → Task → Attempt (tokens, duration)
```

### Status Enums

- **Run**: DRAFT → ACTIVE ↔ PAUSED → COMPLETED/FAILED
- **Task**: PENDING → BUILDING → VERIFYING → COMPLETED/FAILED

## UI/UX Constraints

**No inline confirm/cancel in tight spaces.** Never place confirm/cancel button pairs directly inside a list item, table row, card header, or any compact UI element. These belong in a proper modal dialog with a title, description of consequences, and clearly labelled buttons. Cramming action confirmation into the same visual space as the content being acted on destroys usability and is never acceptable.

**Action menus via three-dot (⋯) button.** When a compact item (task card, list row, etc.) needs contextual actions, use a ⋯ button in the corner that opens a small dropdown menu. The menu items then trigger a proper modal for any destructive or irreversible action.

**Modals for destructive actions.** Any action that deletes, resets, or irreversibly modifies data must open a full overlay modal — centred on screen, dark backdrop, clear title, description of what will happen, optional reason/note field if useful, and Cancel + confirm buttons in the footer.

## Non-Negotiable Design Constraints

**No mocking in tests.** Never use `patch`, `MagicMock`, or monkeypatching. Use real objects with dependency injection -- real git repos, real SQLite (in-memory), real files.

**No global state.** All dependencies injected explicitly. Time is a dependency (inject clocks for testing).

**Fresh context per phase.** Builder and verifier never share LLM context. Each phase gets a clean prompt.

**Pure functions for logic.** Separate logic from I/O. Caller handles I/O, passes data to pure functions.

**Pydantic for all data.** Validation at boundaries, type-safe models throughout.

**Async by default.** No blocking I/O operations.

**Explicit error types.** Domain-specific exceptions (e.g., `RoutineNotFoundError`), never generic `Exception`.

**Simplified YAML schema.** No `ref:` or `use:` inheritance in routine definitions. Everything explicit.

**User selects agent.** Never auto-select. Detect available tools, present options, user chooses.

**Git-versioned routines.** Routines must be committed (warn if dirty). Record git SHA as version.

**Pessimistic locking.** Lock tasks when agent starts working, release on completion.

**Event sourcing for recovery.** Log transitions to JSONL first, then update state. Reconstruct from history on startup.

## Implementation Order

Follow slices sequentially -- each builds on previous. Never skip ahead.

1. **Phase 1** (1.1-1.6): Foundation -- project skeleton, config models, routine loading, state models, session, history
2. **Phase 2** (2.1-2.5): Workflow engine -- checklist/grade gates, state machine, prompt generation
3. **Phase 3** (3.1-3.4): Persistence -- SQLite, repository pattern, session persistence, recovery
4. **Phase 4** (4.1-4.5): API server -- FastAPI, REST endpoints, WebSocket
5. **Phase 5** (5.1-5.6): Agent integration -- interface, tool detector, OpenHands, CLI+nudger, MCP
6. **Phase 6** (6.1-6.4): Web UI -- React/TypeScript/Vite/Tailwind/TanStack Query
7. **Phase 7** (7.1-7.3): Git integration -- worktrees, routine versioning, completion actions
8. **Phase 8** (8.1-8.3): CLI & polish -- Click commands, error handling, full E2E suite

Read the current slice document completely before coding. Run the full test suite after each slice.

## Testing

Three strict levels:

| Level | Dependencies | Speed |
|-------|-------------|-------|
| Unit | None (pure functions, injected deps) | <1s per test |
| Integration | Real DB/files, mocked externals | <10s per test |
| E2E | Full running system | <60s per test |

Integration tests requiring credentials use `@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No OPENAI_API_KEY")`. OpenHands tests also require a running server.

Key test fixtures: `tmp_dir` (temp directory), `fixed_time` (deterministic datetime), `in_memory_db` (SQLite `:memory:`), `routine_repo` (git repo with test routines).

## Environment Variables

Store secrets in `.env` at project root (never committed -- protected by `.gitignore`). See `.env.example` for the template.

### WARNING: Do Not Touch ~/.codex/auth.json

**DO NOT write an API key into `~/.codex/auth.json`.** This file is managed by the Codex Desktop app and the Codex CLI. Writing an API key there breaks the ChatGPT subscription auth that `gpt-5.3-codex` requires — the Desktop app will not automatically recover it, and you will lose access to the model entirely.

If you need to supply credentials to a `codex app-server` subprocess, use the `OPENAI_API_KEY` environment variable or the `account/login/start` JSON-RPC method. Never touch `~/.codex/auth.json` directly.

| Variable | Purpose | Required |
|----------|---------|----------|
| `OPENAI_API_KEY` | LLM provider key used by OpenHands agent | For Phase 5 agent tests |

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0, Pydantic v2, GitPython, httpx, Click
- **Frontend**: React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query, React Router 7
- **Dev tools**: uv (package mgmt), pytest + pytest-asyncio, pyright, ruff, Vitest

## Production Release Gate

**BLOCKED until both Codex Server variants are production-ready.**

The following conditions MUST all be satisfied before either Codex Server variant is enabled in production:

| Condition | Variant | Status |
|-----------|---------|--------|
| Runtime payload-drift tests pass (R-01) | Both | Required |
| Remote timeout/retry behaviour validated (R-02) | Remote | Required |
| REST and MCP callback parity confirmed (R-03) | Both | Required |
| Tool allow-list enforcement tested end-to-end (R-04) | Both | Required |
| Token leakage audit complete in error paths (R-05) | Remote | Required |
| Codex CLI version compatibility detection verified (R-06) | Local | Required |

Neither `codex_server` (local) nor `codex_server_remote` may be promoted to a production-enabled default agent until **all** rows above are marked resolved and the corresponding integration tests are merged to `main`. Static-analysis gates alone (ruff, pyright, pre-commit) are not sufficient — runtime risk items R-01 through R-05 are blocking. Track progress in `docs/codex-server/context/open-risks.md`.

## Documentation Maintenance

When adding new modules, API routes, or CLI commands, update `docs/ARCHITECTURE.md` (directory map, API routes table) and the key modules table above in this file. Keep the directory map and route table in sync with the actual codebase.
