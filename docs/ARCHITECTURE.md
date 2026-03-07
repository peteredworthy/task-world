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
│   ├── agents/                # Agent configs (prompt + model profile, CRUD)
│   │   ├── errors.py          # AgentNotFoundError, AgentNameConflictError, etc.
│   │   ├── models.py          # AgentConfigModel ORM model
│   │   ├── resolution.py      # Cascading agent resolution (task→step→routine→default)
│   │   ├── schemas.py         # AgentSchema, CreateAgentRequest, UpdateAgentRequest
│   │   └── service.py         # AgentService CRUD + seed_default_agents()
│   ├── runners/               # Agent runner implementations (execution backends)
│   │   ├── interface.py       # AgentRunner protocol definition
│   │   ├── types.py           # ExecutionContext, ExecutionResult, AgentRunnerOption, etc.
│   │   ├── executor.py        # Runner lifecycle management
│   │   ├── detector.py        # Detects available runner backends; serves GET /api/agent-runners
│   │   ├── profile_resolution.py # Model profile → model string resolution
│   │   ├── cli.py             # CLI subprocess runner with nudger
│   │   ├── openhands.py       # OpenHands Local runner (in-process)
│   │   ├── openhands_docker.py # OpenHands Docker runner (container)
│   │   ├── openhands_common.py # Shared OpenHands utilities
│   │   ├── codex_server_common.py # Shared helpers for Codex Server runners
│   │   ├── codex_server.py    # CodexServerRunner: local managed-process variant
│   │   ├── claude_sdk.py      # Claude SDK runner (in-process Anthropic API)
│   │   ├── user_managed.py    # External/manual runner
│   │   ├── monitor.py         # Dead runner detection/recovery
│   │   ├── nudger.py          # Stuck runner nudging (timeout, nudge, kill)
│   │   ├── action_log.py      # Structured runner activity log
│   │   ├── mock.py            # Mock runner for testing
│   │   └── parsers/           # Per-runner output stream parsers
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
│   │   │   ├── agents.py      # GET/POST/PUT/DELETE /api/agents (agent CRUD)
│   │   │   ├── runners.py     # GET /api/agent-runners (runner discovery + profile defaults)
│   │   │   ├── routines.py    # /api/routines CRUD + validate
│   │   │   ├── runs.py        # /api/runs CRUD + lifecycle
│   │   │   ├── tasks.py       # Task operations, checklist, grades
│   │   │   ├── repos.py       # /api/repos (repository browser)
│   │   │   ├── config.py      # GET /api/config
│   │   │   ├── clarifications.py # Clarification requests
│   │   │   ├── envfiles.py    # Environment file operations
│   │   │   └── review.py      # Review & merge workbench (13 endpoints)
│   │   └── schemas/           # Pydantic request/response models
│   │       ├── routines.py, runs.py, tasks.py, steps.py
│   │       ├── repos.py, clarifications.py, envfiles.py
│   │       ├── activity.py    # Activity log schemas
│   │       └── review.py      # Review schemas (diff, prune, conflicts, tests, merge)
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
│   │   ├── utils.py           # Git utility functions
│   │   ├── diff_ops.py        # Diff generation (branch/commit/task scopes)
│   │   ├── prune_ops.py       # Selective change removal (file/hunk/line granularity)
│   │   ├── conflict_ops.py    # Merge conflict detection and resolution
│   │   └── errors.py          # Git-specific error types
│   ├── review/                # Review subsystem
│   │   ├── models.py          # Domain models (DiffScope, ModifiedFile, CommitInfo, FileStatus)
│   │   └── test_runner.py     # Async test execution with result tracking and polling
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
│   │   │   ├── client.ts      # Core API client (runs, tasks, routines, etc.)
│   │   │   └── reviewClient.ts # Review API client (diff, prune, conflicts, tests, merge)
│   │   ├── components/        # React components
│   │   │   ├── dashboard/     # Run list, filters, create modal, timeline
│   │   │   ├── detail/        # Run detail, task cards, inspector, logs
│   │   │   ├── guidance/      # Agent guidance panel
│   │   │   ├── routines/      # Routine cards
│   │   │   ├── run/           # Run control (resume dialog)
│   │   │   ├── review/        # Review & merge workbench (22 components)
│   │   │   │   ├── ReviewMergeTab.tsx          # Master container; coordinates all sub-panels
│   │   │   │   ├── FileListSection.tsx          # Changed file list with stats
│   │   │   │   ├── DiffViewer.tsx               # Unified diff renderer (binary + large diff support)
│   │   │   │   ├── DiffDialog.tsx               # Modal diff viewer with expand/collapse
│   │   │   │   ├── HistoryPanel.tsx             # Commit history list for the run branch
│   │   │   │   ├── TaskFilesPanel.tsx           # Per-task file attribution and diff links
│   │   │   │   ├── BranchStatusSection.tsx      # Ahead/behind indicator + back-merge option
│   │   │   │   ├── MergeReadinessBar.tsx        # Four-gate merge readiness display
│   │   │   │   ├── BackMergeBanner.tsx          # Back-merge status and revert button
│   │   │   │   ├── BackMergeModal.tsx           # Trigger back-merge with conflict preview
│   │   │   │   ├── MergeConfirmModal.tsx        # Final merge confirmation dialog
│   │   │   │   ├── ConflictFileList.tsx         # Conflict file sidebar with keyboard nav
│   │   │   │   ├── ConflictResolverDialog.tsx   # Per-block conflict resolution dialog
│   │   │   │   ├── ConflictBlock.tsx            # Single conflict block renderer
│   │   │   │   ├── AgentResolveConflictsModal.tsx # Dispatch agent to fix conflicts
│   │   │   │   ├── TestPanel.tsx                # Test execution UI with run/results
│   │   │   │   ├── TestLogsDrawer.tsx           # Scrollable test output log drawer
│   │   │   │   ├── AgentFixTestsModal.tsx       # Dispatch agent to fix failing tests
│   │   │   │   ├── PruneModeProvider.tsx        # Context provider for prune selection state
│   │   │   │   ├── PruneToolbar.tsx             # Preview/Apply/Cancel prune actions
│   │   │   │   ├── PrunePreviewModal.tsx        # Shows resulting diff before applying prune
│   │   │   │   └── PruneGutter.tsx              # Clickable gutter for hunk/line selection
│   │   │   └── *.tsx          # Shared UI (Layout, Sidebar, StatusBadge, etc.)
│   │   ├── context/           # React contexts (create-run, settings)
│   │   ├── hooks/             # Custom React hooks
│   │   │   ├── useReview.ts                     # TanStack Query hooks for all review operations
│   │   │   ├── useReviewKeyboardShortcuts.ts    # Keyboard shortcuts (j/k/[/]/Shift+P/t)
│   │   │   └── (other hooks)
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
| GET | `/api/agent-runners` | List available agent runner backends as `AgentRunnerOption[]`; includes OpenHands (local/Docker), CLI (claude/codex), Codex Server (local), Codex Server Remote, and User Managed |
| GET | `/api/agent-runners/local-models` | Discover models from a local OpenAI-compatible LLM server |
| GET | `/api/agent-runners/{type}/profiles` | Get per-profile model defaults for a runner type |
| PUT | `/api/agent-runners/{type}/profiles` | Set per-profile model defaults for a runner type |
| GET | `/api/agents` | List all agent configs (name + system_prompt + model_profile) |
| POST | `/api/agents` | Create an agent config |
| GET | `/api/agents/{id}` | Get agent config by ID |
| PUT | `/api/agents/{id}` | Update agent config |
| DELETE | `/api/agents/{id}` | Delete agent config |
| POST | `/api/agents/{id}/reset-prompt` | Reset system_prompt to default_prompt |

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

### Review & Merge Workbench

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs/{id}/review/diff` | Unified diff (scope: aggregate/commit/task; optional ref, context_lines) |
| GET | `/api/runs/{id}/review/diff/files` | Modified files with change stats (scope: aggregate/task) |
| GET | `/api/runs/{id}/review/commits` | Commit history from source-branch merge-base to HEAD |
| POST | `/api/runs/{id}/review/prune/preview` | Preview prune selection (no worktree change) |
| POST | `/api/runs/{id}/review/prune/apply` | Apply prune and create audit commit |
| POST | `/api/runs/{id}/review/revert-file` | Revert single file to base-branch state |
| POST | `/api/runs/{id}/review/test` | Start async test run; returns test_run_id (202) |
| GET | `/api/runs/{id}/review/test/{test_run_id}` | Poll test status and results |
| GET | `/api/runs/{id}/review/conflicts` | List conflict files with structured blocks |
| POST | `/api/runs/{id}/review/conflicts/agent-resolve` | Dispatch agent to resolve conflicts |
| POST | `/api/runs/{id}/review/conflicts/{file_path}/resolve` | Apply per-block resolutions for a file |
| GET | `/api/runs/{id}/review/merge-readiness` | Evaluate 4 merge gates (clean_merge, no_unresolved_conflicts, tests_pass, no_active_jobs) |
| POST | `/api/runs/{id}/review/revert-back-merge` | Revert last back-merge commit (HEAD must be merge commit) |

**Review Schemas** (`src/orchestrator/api/schemas/review.py`):
- `DiffResponse`, `DiffFileEntry` — diff text and file change stats
- `CommitEntry` — commit metadata (sha, short_sha, message, author, timestamp)
- `FilePrune`, `PruneSelection`, `LineRange` — prune request bodies
- `PrunePreviewResponse`, `PruneApplyResponse` — prune results with stats
- `ConflictBlock`, `ConflictFile` — conflict file/block structure
- `BlockResolution`, `ConflictResolutionRequest`, `ConflictResolutionResponse` — resolution inputs/outputs
- `TestRunRequest`, `TestRunResponse`, `TestRunResult`, `TestSummary` — test execution lifecycle
- `BackMergeResponse`, `Gate`, `MergeReadiness` — merge readiness evaluation

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

## Production Release Gate — Codex Server Variants

> **BLOCKED** — neither `codex_server` (local) nor `codex_server_remote` may be enabled in production until all conditions below are resolved.

Both Codex Server agent variants (`codex_server.py` and `codex_server_remote.py`) are present in the codebase and exposed through `GET /api/agent-runners`. They are **not production-ready**. The following runtime risk items from `docs/codex-server/context/open-risks.md` remain open and are blocking:

| Risk ID | Description | Blocking Variant |
|---------|-------------|-----------------|
| R-01 | Payload drift — Codex API response shape may change without notice | Both |
| R-02 | Remote timeout/retry behaviour under network partition not validated | Remote |
| R-03 | REST and MCP callback parity not fully confirmed across both variants | Both |
| R-04 | Tool allow-list enforcement not tested end-to-end (only unit-level) | Both |
| R-05 | Bearer token leakage risk in error paths not audited | Remote |
| R-06 | Codex CLI version compatibility detection may fail silently | Local |

**Promotion criteria:** All six risk items must be resolved, associated integration tests merged to `main`, and a follow-up release-readiness document signed off before either variant is enabled as a production default. Static checks (ruff, pyright, pre-commit) passing is a necessary but not sufficient condition.

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
| Review API routes | `src/orchestrator/api/routers/review.py` |
| Review schemas | `src/orchestrator/api/schemas/review.py` |
| Git diff/prune/conflict ops | `src/orchestrator/git/diff_ops.py`, `prune_ops.py`, `conflict_ops.py` |
| Review domain models | `src/orchestrator/review/models.py` |
| Async test runner | `src/orchestrator/review/test_runner.py` |
| Review frontend components | `ui/src/components/review/ReviewMergeTab.tsx` |
| Review API client | `ui/src/api/reviewClient.ts` |
| Review hooks | `ui/src/hooks/useReview.ts`, `ui/src/hooks/useReviewKeyboardShortcuts.ts` |

### Review Workflow Events

The following event types (`src/orchestrator/workflow/events.py`) are emitted by review operations and persisted to the activity log:

| Event | Trigger | Key Fields |
|-------|---------|------------|
| `PruneApplied` | Prune apply completes | commit_sha, files_affected, hunks_removed, lines_removed |
| `TestRunStarted` | Test run begins | test_run_id |
| `TestRunCompleted` | Test run finishes | test_run_id, status, duration_ms |
| `ConflictResolved` | Conflict file resolved | file_path, remaining_conflicts |
| `BackMergeReverted` | Back-merge undone | reverted_commit, new_head |
| `AgentFixStarted` | Agent dispatched for conflict/test fix | job_id, agent_type |
