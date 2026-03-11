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

## Working Directory Discipline

**Always use `uv run` for Python commands.** Never use bare `python3` or `python` — they may not resolve the project's virtual environment or `pyproject.toml` correctly, especially in worktrees. Use `uv run python`, `uv run pytest`, etc.

**Never `cd` outside your working directory.** If you are running in a worktree (`worktrees/rNN/`), stay there. Do not `cd` to the main project root, parent directories, or sibling worktrees. All source files, `pyproject.toml`, and dependencies are available in the worktree — use `uv run` to access them.

**Interact with the orchestrator via API calls only.** Do not modify server code, restart the server, or touch `orchestrator.db` directly. Use `curl` to the orchestrator's REST API endpoints.

**Do not run git operations on the main working tree.** Git commands should only operate on the current worktree's branch. Never run `git stash`, `git checkout`, or `git reset` from the main project root.

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
User creates Run → Selects Agent Runner → Start (create worktree, acquire lock)
  → Builder Phase (fresh context) → submit → Gates check
  → Verifier Phase (fresh context) → grade each requirement → complete-verification
  → Pass: next task | Revision: back to Builder (fresh context, attempt++)
```

### Agent Runners

An **Agent Runner** is the execution backend that performs work inside a run's worktree. The user selects a runner when creating (or resuming) a run. Runners are discovered at runtime by `ToolDetector` in `src/orchestrator/runners/detector.py`.

Available runner types (`AgentRunnerType` enum in `src/orchestrator/config/enums.py`):

| Type | Name | Notes |
|---|---|---|
| `openhands_local` | OpenHands (local) | In-process via openhands-ai SDK |
| `openhands_docker` | OpenHands (Docker) | Isolated Docker container |
| `cli_subprocess` | Claude CLI / Codex CLI | Subprocess via stdin/stdout |
| `codex_server` | Codex Server (local) | Managed `codex app-server` process (stdio/JSON-RPC) |
| `claude_sdk` | Claude SDK | In-process via Anthropic Python SDK |
| `user_managed` | User Managed | External agent via REST or MCP; always available |

All runners satisfy the `AgentRunner` protocol (`src/orchestrator/runners/interface.py`): `execute()`, `cancel()`, and optional `get_quota()`.

**API endpoints** (prefix `/api/agent-runners`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/agent-runners` | List available runners with availability and config schema |
| `GET` | `/api/agent-runners/local-models` | Discover models from a local OpenAI-compatible server |
| `GET` | `/api/agent-runners/{type}/profiles` | Get per-profile model defaults for a runner type |
| `PUT` | `/api/agent-runners/{type}/profiles` | Set per-profile model defaults for a runner type |

### Model Profiles

A **Model Profile** is a named cognitive role that maps to a specific model on a given runner. Profiles let routines declare what *kind* of intelligence a task requires without hard-coding a model string.

Four profiles (`ModelProfile` enum in `src/orchestrator/config/enums.py`):

| Profile | Intended use |
|---|---|
| `architect` | High-level planning, design decisions, broad context |
| `designer` | UX/API design, interface contracts |
| `coder` | Implementation, code changes, debugging |
| `summarizer` | Distillation, note-taking, lightweight analysis |

**Per-runner defaults** — each runner stores a `profile → model` mapping in the database (`RunnerProfileDefaultModel`). When a task specifies a profile, resolution proceeds:

1. Runner profile defaults (`GET /api/agent-runners/{type}/profiles`)
2. Runner built-in default model (from `agent_config`)
3. `None` (no model override)

Resolution logic lives in `src/orchestrator/runners/profile_resolution.py`.

### Agents

An **Agent** (distinct from an Agent Runner) is a named configuration combining a **system prompt** and a **model profile**. Agents are stored in the database and selected per-phase in routine YAML. They control *what instructions* the runner receives and *which model profile* applies.

**Factory defaults** (seeded automatically on first startup):

| Name | Profile | Role |
|---|---|---|
| `Planner` | `architect` | Breaks goals into actionable steps |
| `Builder` | `coder` | Implements requirements from the checklist |
| `Verifier` | `coder` | Grades completed work objectively |

**CRUD API** (prefix `/api/agents`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/agents` | List all agent configs |
| `POST` | `/api/agents` | Create a new agent config (409 if name exists) |
| `GET` | `/api/agents/{id}` | Get agent by ID |
| `PUT` | `/api/agents/{id}` | Update agent (name, system_prompt, model_profile) |
| `DELETE` | `/api/agents/{id}` | Delete agent |
| `POST` | `/api/agents/{id}/reset-prompt` | Reset system_prompt to default_prompt |

Each agent record has: `id`, `name`, `system_prompt`, `default_prompt`, `model_profile`, `created_at`, `updated_at`.

**Cascading resolution** — when a task needs an agent for a phase, the orchestrator walks this priority chain (first non-`None` wins):

```
task-level builder_agent / verifier_agent
    ↓
step-level builder_agent / verifier_agent
    ↓
routine-level builder_agent / verifier_agent
    ↓
system default ("Builder" / "Verifier")
```

Resolution logic: `src/orchestrator/agents/resolution.py`.

**Routine YAML schema** — agent overrides are optional at every level:

```yaml
# Routine level
builder_agent: "CustomBuilder"     # optional — overrides system default for all tasks
verifier_agent: "CustomVerifier"   # optional

steps:
  - title: "Step 1"
    builder_agent: "StepBuilder"   # optional — overrides routine-level for this step
    verifier_agent: null
    tasks:
      - title: "Task A"
        builder_agent: "TaskBuilder"  # optional — overrides step-level for this task
        verifier_agent: null
```

All three levels (`RoutineConfig`, `StepConfig`, `TaskConfig`) support `builder_agent` and `verifier_agent` string fields (agent name, not ID). Omit or set `null` to inherit from the level above.

## UI/UX Constraints

**No inline confirm/cancel in tight spaces.** Never place confirm/cancel button pairs directly inside a list item, table row, card header, or any compact UI element. These belong in a proper modal dialog with a title, description of consequences, and clearly labelled buttons. Cramming action confirmation into the same visual space as the content being acted on destroys usability and is never acceptable.

**Action menus via three-dot (⋯) button.** When a compact item (task card, list row, etc.) needs contextual actions, use a ⋯ button in the corner that opens a small dropdown menu. The menu items then trigger a proper modal for any destructive or irreversible action.

**Modals for destructive actions.** Any action that deletes, resets, or irreversibly modifies data must open a full overlay modal — centred on screen, dark backdrop, clear title, description of what will happen, optional reason/note field if useful, and Cancel + confirm buttons in the footer.

## Database

**Never delete `orchestrator.db` without an explicit user request.** The database contains run history, events, and state that cannot be recovered. If a schema change causes errors, add an Alembic migration and run `alembic upgrade head` — do not drop and recreate. Even when the user explicitly asks to wipe the database, **back it up first** (`cp orchestrator.db orchestrator.db.bak`).

- Schema migrations: `src/orchestrator/db/migrations/versions/`
- Create a migration: `uv run alembic -c alembic.ini revision -m "description"`
- Apply migrations: `uv run alembic -c alembic.ini upgrade head`
- `init_db()` runs Alembic migrations for file-based DBs, `create_all` only for in-memory (tests)
- `*.db` is in `.gitignore` — database files are never tracked and cannot be restored from git

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

**Validate all inputs at the API boundary.** Every field that represents a constrained value (enums, strategies, modes, grades) must be validated via Pydantic `Literal`, `field_validator`, or `Field(pattern=...)` on the schema — never via bare enum conversion inside the endpoint body. Invalid values must return 422 with a message listing valid options. Free-form string fields used as filesystem paths, URLs, or identifiers must be sanitized against traversal and injection. Query parameters used for enum filtering get the same treatment.

**Pessimistic locking.** Lock tasks when agent starts working, release on completion.

**Event sourcing for recovery.** Log transitions to JSONL first, then update state. Reconstruct from history on startup.

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

## Documentation Maintenance

When adding new modules, API routes, or CLI commands, update `docs/ARCHITECTURE.md` (directory map, API routes table) and the key modules table above in this file. Keep the directory map and route table in sync with the actual codebase.

## Routine Authoring

When writing or reviewing routine YAML files, keep `step_context` short (one or two sentences). It is duplicated into every task prompt in the step, so verbosity multiplies quickly. See **[docs/step-context-guide.md](docs/step-context-guide.md)** for guidance and good/bad examples.
