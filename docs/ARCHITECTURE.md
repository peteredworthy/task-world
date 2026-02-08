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
│   ├── agents/                # Agent implementations
│   │   ├── cli.py             # CLI subprocess agent with nudger
│   │   ├── detector.py        # Detects available agent tools
│   │   ├── executor.py        # Agent lifecycle management
│   │   ├── interface.py       # Agent protocol definition
│   │   ├── monitor.py         # Dead agent detection/recovery
│   │   ├── openhands.py       # OpenHands Local agent
│   │   ├── openhands_docker.py # OpenHands Docker agent
│   │   ├── user_managed.py    # External/manual agent
│   │   └── types.py           # ExecutionContext, ExecutionResult
│   ├── api/                   # FastAPI REST API
│   │   ├── app.py             # Application factory, lifespan
│   │   ├── auth.py            # JWT authentication
│   │   ├── deps.py            # Dependency injection
│   │   ├── errors.py          # Exception handlers
│   │   ├── websocket.py       # WebSocket connection manager
│   │   ├── routers/           # API endpoints
│   │   │   ├── agents.py      # GET /api/agents
│   │   │   ├── routines.py    # GET /api/routines
│   │   │   ├── runs.py        # CRUD /api/runs
│   │   │   ├── tasks.py       # Task operations
│   │   │   └── ...
│   │   └── schemas/           # Pydantic request/response models
│   ├── cli/                   # Click CLI commands
│   │   ├── main.py            # Entry point (orchestrator command)
│   │   ├── runs.py            # Run management commands
│   │   ├── routines.py        # Routine listing commands
│   │   └── agents.py          # Agent listing commands
│   ├── config/                # Configuration models
│   │   ├── enums.py           # RunStatus, TaskStatus, AgentType
│   │   ├── global_config.py   # config.json loader
│   │   └── models.py          # RoutineConfig, StepConfig, TaskConfig
│   ├── db/                    # Database layer (SQLAlchemy + SQLite)
│   │   ├── connection.py      # Async engine + session factory
│   │   ├── models.py          # ORM models
│   │   ├── repositories.py    # RunRepository (CRUD)
│   │   ├── event_store.py     # Event persistence
│   │   └── migrations/        # Alembic migrations
│   ├── envfiles/              # Environment file management
│   │   ├── store.py           # Snapshot storage
│   │   ├── lifecycle.py       # Run/task lifecycle hooks
│   │   └── security.py        # Secret filtering
│   ├── git/                   # Git operations
│   │   ├── worktree.py        # Git worktree management
│   │   ├── branch_ops.py      # Branch operations
│   │   └── project_init.py    # Project initialization
│   ├── mcp/                   # MCP server (tool protocol)
│   │   ├── server.py          # FastMCP SSE server
│   │   └── tools.py           # Tool definitions
│   ├── routines/              # Routine loading and discovery
│   │   ├── loader.py          # YAML routine parser
│   │   ├── discovery.py       # Directory scanning
│   │   └── versioning.py      # Git SHA versioning
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
│       ├── events.py          # Event types + emitter
│       └── locks.py           # Task-level pessimistic locking
│
├── ui/                        # React frontend
│   ├── src/
│   │   ├── App.tsx            # Root component + routes
│   │   ├── main.tsx           # Entry point
│   │   ├── api/               # API client functions
│   │   ├── components/        # React components
│   │   │   ├── dashboard/     # Run list, filters, create modal
│   │   │   ├── detail/        # Run detail, task cards, inspector
│   │   │   ├── guidance/      # Agent guidance panel
│   │   │   └── routines/      # Routine cards
│   │   ├── context/           # React contexts (WebSocket, settings)
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
│   ├── intent/                # Design documents (PRD, slices)
│   └── ui/                    # UI-specific documentation
├── scripts/                   # Development scripts
│   ├── serve.py               # Server entry point
│   └── seed_db.py             # Database seeding
├── docker/                    # Docker configuration
│   └── Dockerfile.agent-server
│
├── CLAUDE.md                  # AI assistant instructions
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

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/routines` | List available routines |
| GET | `/api/routines/{id}` | Get routine details |
| GET | `/api/runs` | List all runs |
| POST | `/api/runs` | Create a new run |
| GET | `/api/runs/{id}` | Get run details |
| PATCH | `/api/runs/{id}` | Update run |
| DELETE | `/api/runs/{id}` | Delete run |
| POST | `/api/runs/{id}/start` | Start run execution |
| POST | `/api/runs/{id}/pause` | Pause run |
| POST | `/api/runs/{id}/resume` | Resume run |
| GET | `/api/runs/{id}/tasks/{task_id}` | Get task details |
| POST | `/api/runs/{id}/tasks/{task_id}/submit` | Submit builder work |
| POST | `/api/runs/{id}/tasks/{task_id}/verify` | Submit verification grades |
| GET | `/api/agents` | List available agents |
| GET | `/health` | Health check |

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

---

## Key Files for New Contributors

| Purpose | File(s) |
|---------|---------|
| Understand the domain | `docs/intent/01-PRD.md`, `docs/intent/10-SLICES-OVERVIEW.md` |
| API structure | `src/orchestrator/api/app.py`, `api/routers/*.py` |
| Core workflow logic | `src/orchestrator/workflow/engine.py`, `workflow/service.py` |
| Data models | `src/orchestrator/state/models.py`, `config/models.py` |
| Database schema | `src/orchestrator/db/models.py` |
| Agent implementations | `src/orchestrator/agents/*.py` |
| Frontend entry | `ui/src/App.tsx`, `ui/src/pages/*.tsx` |
| Test examples | `tests/unit/*.py`, `tests/integration/*.py` |
