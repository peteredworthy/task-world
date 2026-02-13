# Architecture Overview

This document provides a high-level overview of the Orchestrator project structure, how to run it, and guidance for navigating the codebase.

## Quick Start

### Running the Application

**Backend API Server (FastAPI):**
```bash
# Start the backend on port 8000
uv run uvicorn scripts.serve:app --reload --port 8000
```

**Frontend UI (React/Vite):**
```bash
# In a separate terminal
cd ui
npm install   # first time only
npm run dev   # starts on port 5173
```

**Access Points:**
| Service | URL | Description |
|---------|-----|-------------|
| Web UI | http://localhost:5173 | React frontend (Vite dev server) |
| API Server | http://localhost:8000 | FastAPI backend |
| Health Check | http://localhost:8000/health | Server health endpoint |
| WebSocket | ws://localhost:8000/ws/runs/{run_id} | Real-time run updates |
| MCP SSE | http://localhost:8000/mcp/sse | MCP server-sent events |
| API Docs | http://localhost:8000/docs | OpenAPI/Swagger docs |

### Environment Setup

1. Copy `.env.example` to `.env`
2. Set required variables:
   - `OPENAI_API_KEY` - Required for OpenHands agents
   - `AUTH_DISABLED=true` - For local development

---

## Directory Map

```
task-world/
├── src/orchestrator/          # Python backend (main application)
│   ├── errors.py              # Root-level error definitions
│   ├── agents/                # Agent implementations
│   │   ├── interface.py       # Agent protocol definition
│   │   ├── types.py           # ExecutionContext, ExecutionResult, AgentOption
│   │   ├── executor.py        # Agent lifecycle management
│   │   ├── detector.py        # Detects available agent tools
│   │   ├── cli.py             # CLI subprocess agent with nudger
│   │   ├── openhands.py       # OpenHands Local agent (in-process)
│   │   ├── openhands_docker.py # OpenHands Docker agent (container)
│   │   ├── openhands_common.py # Shared OpenHands utilities
│   │   ├── user_managed.py    # External/manual agent
│   │   ├── monitor.py         # Dead agent detection/recovery
│   │   ├── nudger.py          # Stuck agent nudging (timeout, nudge, kill)
│   │   ├── action_log.py      # Structured agent activity log
│   │   ├── mock.py            # Mock agent for testing
│   │   └── parsers/           # Per-agent output stream parsers
│   │       ├── base.py        # Base stream parser protocol
│   │       ├── claude_parser.py
│   │       ├── codex_parser.py
│   │       └── openhands_parser.py
│   ├── api/                   # FastAPI REST API
│   │   ├── app.py             # Application factory, lifespan
│   │   ├── auth.py            # JWT authentication
│   │   ├── deps.py            # Dependency injection
│   │   ├── errors.py          # Exception handlers
│   │   ├── websocket.py       # WebSocket connection manager
│   │   ├── routers/           # API endpoints
│   │   │   ├── agents.py      # GET /api/agents
│   │   │   ├── routines.py    # /api/routines CRUD + validate
│   │   │   ├── runs.py        # /api/runs CRUD + lifecycle
│   │   │   ├── tasks.py       # Task operations, checklist, grades
│   │   │   ├── repos.py       # /api/repos (repository browser)
│   │   │   ├── config.py      # GET /api/config
│   │   │   ├── clarifications.py # Clarification requests
│   │   │   └── envfiles.py    # Environment file operations
│   │   └── schemas/           # Pydantic request/response models
│   │       ├── routines.py, runs.py, tasks.py, steps.py
│   │       ├── repos.py, clarifications.py, envfiles.py
│   │       └── activity.py    # Activity log schemas
│   ├── artifacts/             # Artifact tracking
│   │   ├── models.py          # Artifact data models
│   │   └── registry.py        # Registry for generated files
│   ├── cli/                   # Click CLI commands
│   │   ├── main.py            # Entry point (orchestrator command)
│   │   ├── runs.py            # Run management commands
│   │   ├── routines.py        # Routine listing commands
│   │   ├── agents.py          # Agent listing commands
│   │   ├── repos.py           # Repository commands
│   │   └── approve.py         # Human approval commands
│   ├── config/                # Configuration models
│   │   ├── enums.py           # RunStatus, TaskStatus, AgentType
│   │   ├── global_config.py   # config.json loader
│   │   └── models.py          # RoutineConfig, StepConfig, TaskConfig
│   ├── db/                    # Database layer (SQLAlchemy + SQLite)
│   │   ├── base.py            # SQLAlchemy Base class
│   │   ├── connection.py      # Async engine + session factory
│   │   ├── models.py          # ORM models
│   │   ├── repositories.py    # RunRepository (CRUD)
│   │   ├── event_store.py     # Event persistence
│   │   ├── recovery.py        # State recovery from events
│   │   └── migrations/        # Alembic migrations
│   ├── envfiles/              # Environment file management
│   │   ├── models.py          # Env file data models
│   │   ├── store.py           # Snapshot storage
│   │   ├── lifecycle.py       # Run/task lifecycle hooks
│   │   ├── resolution.py      # Variable resolution
│   │   ├── security.py        # Secret filtering
│   │   ├── cleanup.py         # Cleanup operations
│   │   └── tools.py           # Env file management tools
│   ├── git/                   # Git operations
│   │   ├── worktree.py        # Git worktree management
│   │   ├── branch_ops.py      # Branch operations (merge, back-merge)
│   │   ├── project_init.py    # Project initialization
│   │   └── utils.py           # Git utility functions
│   ├── mcp/                   # MCP server (tool protocol)
│   │   ├── server.py          # FastMCP SSE server
│   │   ├── tools.py           # Tool definitions
│   │   └── clarification_tools.py # Clarification-specific tools
│   ├── metrics/               # Performance and cost tracking
│   │   └── cost.py            # Token counting and pricing
│   ├── repos/                 # Repository management
│   │   ├── models.py          # RepoInfo, BranchInfo
│   │   ├── discovery.py       # Repository discovery
│   │   └── errors.py          # Repo-specific errors
│   ├── routines/              # Routine loading and discovery
│   │   ├── loader.py          # YAML routine parser
│   │   ├── discovery.py       # Directory scanning
│   │   └── versioning.py      # Git SHA versioning
│   ├── scaffolding/           # Project scaffolding
│   │   ├── copier.py          # Copier integration
│   │   └── models.py          # Scaffolding models
│   ├── state/                 # Runtime state models
│   │   ├── models.py          # Run, StepState, TaskState
│   │   ├── factory.py         # Create Run from RoutineConfig
│   │   └── session.py         # In-memory state manager
│   └── workflow/              # Workflow engine
│       ├── engine.py          # State machine orchestration
│       ├── service.py         # WorkflowService (async wrapper)
│       ├── gates.py           # Checklist gate evaluation
│       ├── grades.py          # Grade threshold evaluation
│       ├── transitions.py     # State transition functions
│       ├── prompts.py         # Builder/verifier prompts
│       ├── context_builder.py # Build execution context for agents
│       ├── auto_verify.py     # Automatic verification logic
│       ├── clarifications.py  # Clarification workflow handling
│       ├── completion.py      # Run completion logic
│       ├── dry_run.py         # Dry run execution
│       ├── events.py          # Event types + emitter
│       ├── event_logger.py    # Persistent event logging
│       └── locks.py           # Task-level pessimistic locking
│
├── ui/                        # React frontend
│   ├── src/
│   │   ├── App.tsx            # Root component + routes
│   │   ├── main.tsx           # Entry point
│   │   ├── api/               # API client functions
│   │   ├── components/        # React components
│   │   │   ├── dashboard/     # Run list, filters, create modal, timeline
│   │   │   ├── detail/        # Run detail, task cards, inspector, logs
│   │   │   ├── guidance/      # Agent guidance panel
│   │   │   ├── routines/      # Routine cards
│   │   │   ├── run/           # Run control (resume dialog)
│   │   │   └── *.tsx          # Shared UI (Layout, Sidebar, StatusBadge, etc.)
│   │   ├── context/           # React contexts (create-run, settings)
│   │   ├── hooks/             # Custom React hooks
│   │   ├── lib/               # Utilities (formatting, etc.)
│   │   ├── pages/             # Page components
│   │   └── types/             # TypeScript type definitions
│   ├── tests/                 # Vitest tests
│   ├── vite.config.ts         # Vite configuration + API proxy
│   └── package.json           # npm dependencies
│
├── tests/                     # Python tests
│   ├── unit/                  # Pure function tests (fast)
│   ├── integration/           # Real DB/file tests
│   ├── e2e/                   # End-to-end tests
│   └── fixtures/              # Test data
│       └── routines/          # Sample routine YAML files
│
├── routines/                  # Production routine definitions (YAML)
├── examples/routines/         # Example routine templates
├── docs/                      # Documentation
│   ├── ARCHITECTURE.md        # This file
│   ├── intent/                # Design documents (PRD, slices)
│   ├── ui/                    # UI-specific documentation
│   ├── planner/               # Planner system documentation
│   └── plan-runner/           # Plan runner documentation
├── scripts/                   # Development scripts
│   ├── serve.py               # Server entry point
│   └── seed_db.py             # Database seeding
├── docker/                    # Docker configuration
│   └── Dockerfile.agent-server
│
├── AGENTS.md                  # Coding agent instructions
├── CLAUDE.md                  # Redirects to AGENTS.md
├── pyproject.toml             # Python project configuration
├── alembic.ini                # Database migration config
└── config.json                # Global app configuration
```

---

## Core Concepts

### Routine/Run Model

- **Routine**: A git-versioned YAML template defining a multi-step workflow
- **Run**: An execution instance of a routine against a specific project
- **Step**: A group of related tasks within a run
- **Task**: An individual unit of work (building, verifying)
- **Attempt**: A single try at completing a task (tracks tokens, duration)

### Workflow States

**Run Status:** `DRAFT` → `ACTIVE` ↔ `PAUSED` → `COMPLETED`/`FAILED`

**Task Status:** `PENDING` → `BUILDING` → `VERIFYING` → `COMPLETED`/`FAILED`

### Builder/Verifier Cycle

Each task goes through:
1. **Builder Phase** - Agent implements the task (fresh LLM context)
2. **Gates Check** - Verify checklist items are complete
3. **Verifier Phase** - Agent grades each requirement (fresh LLM context)
4. **Pass/Fail** - Either proceed to next task or retry with revision

---

## API Routes

### Core

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/config` | Global configuration |
| GET | `/api/agents` | List available agent backends |

### Routines

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/routines` | List available routines |
| GET | `/api/routines/{id}` | Get routine details |
| POST | `/api/routines/validate` | Validate a routine YAML |

### Repositories

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/repos` | List all repositories |
| GET | `/api/repos/{name}` | Repository details |
| GET | `/api/repos/{name}/branches` | List branches |
| GET | `/api/repos/{name}/routines` | List routines in a repo |
| GET | `/api/repos/{name}/routines/{id}` | Get routine from a repo |

### Runs

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs` | Create a new run |
| GET | `/api/runs` | List runs (filterable) |
| GET | `/api/runs/{id}` | Get run details |
| DELETE | `/api/runs/{id}` | Delete run |
| POST | `/api/runs/{id}/start` | Start run execution |
| POST | `/api/runs/{id}/pause` | Pause run |
| POST | `/api/runs/{id}/resume` | Resume run |
| POST | `/api/runs/{id}/cancel` | Cancel run |
| GET | `/api/runs/{id}/activity` | Activity log (paginated) |
| GET | `/api/runs/{id}/activity/stream` | Activity SSE stream |
| GET | `/api/runs/{id}/guidance` | Aggregate guidance for agents |
| GET | `/api/runs/{id}/branch-status` | Branch ahead/behind status |
| POST | `/api/runs/{id}/back-merge` | Pull source branch into run |
| POST | `/api/runs/{id}/merge-back` | Merge run branch into source |
| POST | `/api/runs/{id}/steps/{step_id}/approve` | Approve a step gate |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs/{id}/tasks/{tid}` | Get task with checklist |
| POST | `/api/runs/{id}/tasks/{tid}/start` | Start building |
| POST | `/api/runs/{id}/tasks/{tid}/submit` | Submit for verification |
| POST | `/api/runs/{id}/tasks/{tid}/complete-verification` | Complete verification |
| GET | `/api/runs/{id}/tasks/{tid}/prompt` | Get builder/verifier prompt |
| PATCH | `/api/runs/{id}/tasks/{tid}/checklist/{req}` | Update checklist item |
| PUT | `/api/runs/{id}/tasks/{tid}/checklist/{req}/grade` | Set grade |
| POST | `/api/runs/{id}/tasks/{tid}/approve` | Human approves task |
| POST | `/api/runs/{id}/tasks/{tid}/reject` | Human rejects task |

### Clarifications

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs/{id}/tasks/{tid}/clarifications` | Submit questions |
| GET | `/api/runs/{id}/tasks/{tid}/clarifications/pending` | Get pending request |
| POST | `/api/runs/{id}/tasks/{tid}/clarifications/{rid}/respond` | Answer questions |
| GET | `/api/runs/{id}/pending-actions` | List pending user actions |

### Environment Files

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs/{id}/env-files` | List managed env files |
| GET | `/api/runs/{id}/env-files/snapshots` | List snapshot points |
| POST | `/api/runs/{id}/env-files/revert` | Revert to snapshot |
| POST | `/api/runs/{id}/env-files/copy-back` | Copy files to target dir |

### WebSocket / MCP

| Protocol | Path | Description |
|----------|------|-------------|
| WebSocket | `/ws/runs/{id}` | Real-time run updates |
| SSE | `/mcp/sse` | MCP server-sent events |
| HTTP | `/mcp/messages` | MCP message endpoint |

---

## CLI Commands

```bash
# Routine management
orchestrator routine list

# Run management
orchestrator run list --status active
orchestrator run create <routine> --project <path> --config '<json>'
orchestrator run start <id> --agent <type>
orchestrator run agents <run-id>

# Development server
orchestrator serve --reload
```

---

## Technology Stack

### Backend
- Python 3.12+
- FastAPI (async web framework)
- SQLAlchemy 2.0 (async ORM)
- SQLite + aiosqlite (database)
- Pydantic v2 (validation)
- GitPython (git operations)
- Click (CLI)
- uvicorn (ASGI server)
- httpx (async HTTP client)

### Frontend
- React 19 + TypeScript
- Vite 7 (build tool)
- TailwindCSS 4 (styling)
- TanStack Query (data fetching)
- React Router 7 (routing)

### Development
- uv (package management)
- pytest + pytest-asyncio (testing)
- pyright (type checking)
- ruff (linting/formatting)
- Vitest (frontend testing)

### Documentation Maintenance

When adding new modules, API routes, or CLI commands, update this file and `AGENTS.md` to reflect the changes. The directory map above and the API routes table should stay in sync with the codebase.

---

## Key Files for New Contributors

| Purpose | File(s) |
|---------|---------|
| Understand the domain | `docs/intent/03-PRD.md`, `docs/intent/10-SLICES-OVERVIEW.md` |
| API structure | `src/orchestrator/api/app.py`, `api/routers/*.py` |
| Core workflow logic | `src/orchestrator/workflow/engine.py`, `workflow/service.py` |
| Data models | `src/orchestrator/state/models.py`, `config/models.py` |
| Database schema | `src/orchestrator/db/models.py` |
| Agent implementations | `src/orchestrator/agents/*.py` |
| Frontend entry | `ui/src/App.tsx`, `ui/src/pages/*.tsx` |
| Test examples | `tests/unit/*.py`, `tests/integration/*.py` |
