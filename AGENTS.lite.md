# AGENTS.lite.md

## Project

Orchestrator coordinates LLM agents through structured workflows. Routine/Run model: git-versioned YAML templates define multi-step tasks, runs execute them via agent backend (OpenHands, CLI, Codex, SDK, user-managed). Builder/verifier cycle, fresh context per phase. Docs: `docs/intent/`, `docs/ARCHITECTURE.md`.

## Working Directory Rules

- **Always `uv run`** for Python. Never bare `python3`.
- **Stay in your worktree** (`worktrees/rNN/`). Never `cd` to main project root or siblings.
- **API only** for orchestrator interaction. No direct DB edits, no server restarts.
- **No git ops on main tree.** No `git stash/checkout/reset` from project root.

Artifacts in `worktrees/rNN/docs/<feature>/...`. Check worktree before assuming generation failed.

## Commands

```bash
uv sync / uv add <pkg> / uv add --group dev <pkg>
uv run pytest / pytest tests/unit -v / pytest tests/integration -v
uv run pyright / ruff check . / ruff format .
uv run orchestrator serve --reload
uv run orchestrator routine list
uv run orchestrator run list --status active
uv run orchestrator run create <routine> --project <path> --config '<json>'
uv run orchestrator run start <id> --agent <type>
```

## Architecture

```
Run → Agent Runner → worktree
  Builder (fresh ctx) → submit → Gates
  Verifier (fresh ctx) → grade reqs → complete-verification
  Pass: next task | Fail: back to Builder (attempt++)
```

**Runners** (`AgentRunnerType`): `openhands_local`, `openhands_docker`, `cli_subprocess`, `codex_server`, `claude_sdk`, `user_managed`. Discovered via `src/orchestrator/runners/agent_detector.py`. All implement `execute()`, `cancel()`, `get_quota()`.

**Model Profiles**: `architect` (planning), `designer` (UX/API), `coder` (impl), `summarizer` (distill). Resolution: task → step → routine → system default. Logic: `src/orchestrator/runners/profile_resolution.py`.

**Agents** = named config (system prompt + profile). Factory defaults: `Planner/architect`, `Builder/coder`, `Verifier/coder`. Cascade: task → step → routine → system default. Logic: `src/orchestrator/agents/resolution.py`.

Agent runner API: `GET/PUT /api/agent-runners`, `GET/PUT /api/agent-runners/{type}/profiles`.
Agent CRUD: `GET/POST /api/agents`, `GET/PUT/DELETE /api/agents/{id}`, `POST /api/agents/{id}/reset-prompt`.

## Design Constraints (non-negotiable)

- No mocks. Real DI: real git repos, real SQLite in-memory, real files.
- No global state. Inject all deps including time.
- Fresh context per phase. Builder/verifier never share LLM context.
- Pure functions for logic. Separate from I/O.
- Pydantic everywhere. Validate at boundaries.
- Async by default.
- Domain exceptions (`RoutineNotFoundError`, etc.), never bare `Exception`.
- No `ref:`/`use:` in YAML. Everything explicit.
- User selects agent. Never auto-select.
- Git-versioned routines. Warn if dirty. Record SHA.
- Validate all inputs at API boundary via Pydantic `Literal`/`field_validator`/`Field(pattern=...)`. 422 with valid options on failure. Sanitize path/URL/identifier fields.
- Pessimistic locking. Lock on start, release on complete.
- Event sourcing: log to JSONL first, then update state.
- Imports from module top-level only. 9 modules: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, `workflow`. CORRECT: `from orchestrator.config import X`. WRONG: `from orchestrator.config.routines.discovery import X`.

## UI Constraints

- No confirm/cancel in compact elements (list rows, cards). Use modal dialogs.
- Three-dot (⋯) for contextual actions → modal for destructive ops.

## Database

Never delete `orchestrator.db` without explicit user request. Migrations only, never drop/recreate.

```bash
uv run alembic -c alembic.ini revision -m "description"
uv run alembic -c alembic.ini upgrade head
```

`init_db()` runs Alembic for file DBs, `create_all` for in-memory (tests only). `*.db` in `.gitignore`.

**NEVER touch `~/.codex/auth.json`.** Use `OPENAI_API_KEY` env var for Codex credentials.

## Pre-commit / Errors

Every failing check is your responsibility. Fix it.

**NEVER `--no-verify`.** NEVER `# noqa`/`# type: ignore` to silence errors you introduced. NEVER delete failing tests.

## Testing

Run tests with foreground Bash (never background Tasks). Suite completes in <60s.

| Level | Deps | Speed |
|-------|------|-------|
| Unit | None (pure, injected) | <1s |
| Integration | Real DB/files | <10s |
| E2E | Full system | <60s |

Fixtures: `tmp_dir`, `fixed_time`, `in_memory_db`, `routine_repo`.

**Unit tests** (`tests/unit/`) MUST NOT import: `create_app`, `TestClient`, `StaticPool`. May use real in-memory SQLAlchemy sessions and call domain objects directly.

**Integration tests** (`tests/integration/`) may use all of the above.

## Debugging a Run

```bash
curl -s http://localhost:8000/api/runs/<id> | python3 -m json.tool
curl -s http://localhost:8000/api/runs/<id>/tasks | python3 -m json.tool
curl -s http://localhost:8000/api/runs/<id>/activity | python3 -m json.tool
grep <id> .orchestrator/state/history.jsonl | python3 -m json.tool
git -C <worktree_path> status --porcelain
git -C <worktree_path> log --oneline -5
```

Key fields: `status`, `pause_reason`, `last_error`, `worktree_path`, `agent_type`.

## Signal Queue Rules

Enforced by `scripts/check_signal_routing.py` (pre-commit hook).

1. `register_active_run`/`unregister_active_run`/`has_active_workflow` — only `consumer.py` and its tests may call these.
2. No in-memory shared state crossing API/executor boundary. Use constructor injection or `Depends`.
3. `RunWorkflow`/`AgentRunnerExecutor` must not access `app.state`. All deps injected via constructors.
4. All lifecycle transitions (`start`/`pause`/`resume`/`cancel`) via `SignalQueue`. `WorkflowService` must not directly mutate run status.

## Tech Stack

Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Pydantic v2, GitPython, httpx, Click
Frontend: React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query, React Router 7
Dev: uv, pytest+pytest-asyncio, pyright, ruff, Vitest

## Routine Authoring

`step_context`: one or two sentences max. Duplicated into every task prompt in step — verbosity multiplies. See `docs/step-context-guide.md`.

## Graphify (Codebase Knowledge Graph)

Pre-built index available. Use bash command directly — NOT the `/graphify` skill syntax.

```bash
graphify query "your question" --graph /Users/peter/code/task-world/graphify-out/graph.json --budget 500
```

Examples:
```bash
graphify query "What are the main API endpoints?" --graph /Users/peter/code/task-world/graphify-out/graph.json --budget 300
graphify query "How does WorkflowEngine process steps?" --graph /Users/peter/code/task-world/graphify-out/graph.json --budget 500
```

Rules: ask specific questions, each returns 300-500 tokens of focused context, query multiple times for different aspects, prefer this over reading source files directly.
