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
User creates Run → Selects Agent → Start (create worktree, acquire lock)
  → Builder Phase (fresh context) → submit → Gates check
  → Verifier Phase (fresh context) → grade each requirement → complete-verification
  → Pass: next task | Revision: back to Builder (fresh context, attempt++)
```

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
