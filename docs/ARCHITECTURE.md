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
│   ├── errors.py              # Root-level error definitions (domain exceptions)
│   ├── time_utils.py          # Time utilities (injectable clocks for testing)
│   ├── executor.py            # Backward-compat shim → runners/executor.py
│   ├── agents/                # Agent configs (prompt + model profile, CRUD)
│   │   ├── errors.py          # AgentNotFoundError, AgentNameConflictError, etc.
│   │   ├── models.py          # AgentConfigModel ORM model
│   │   ├── resolution.py      # Cascading agent resolution (task→step→routine→default)
│   │   ├── schemas.py         # AgentSchema, CreateAgentRequest, UpdateAgentRequest
│   │   └── service.py         # AgentService CRUD + seed_default_agents()
│   ├── runners/               # Agent runner implementations (execution backends)
│   │   ├── interface.py       # AgentRunner protocol definition
│   │   ├── types.py           # ExecutionContext, ExecutionResult, AgentRunnerOption, etc.
│   │   ├── agent_factory.py   # Registry-based agent factory; each package self-registers
│   │   ├── agent_detector.py  # Registry-based runner detection (preferred over detector.py)
│   │   ├── detector.py        # Legacy detector; still used by GET /api/agent-runners (TD-02)
│   │   ├── profile_resolution.py # Model profile → model string resolution
│   │   ├── monitor.py         # Dead runner detection/recovery
│   │   ├── nudger.py          # Stuck runner nudging (timeout, nudge, kill)
│   │   ├── action_log.py      # Structured runner activity log
│   │   ├── quota.py           # Agent quota tracking and enforcement
│   │   ├── repetition_detector.py # Detects agent stuck in output loops
│   │   ├── config_utils.py    # Shared agent config helpers
│   │   ├── errors.py          # Runner-specific error types
│   │   ├── agents/            # Concrete agent implementations (canonical location)
│   │   │   ├── claude_cli/    # CLIAgent: subprocess via stdin/stdout
│   │   │   │   ├── agent.py   # Main CLIAgent; uses Nudger, ClaudeStreamParser
│   │   │   │   ├── config.py  # CLIAgent config schema
│   │   │   │   ├── factory.py # Self-registration with agent_factory
│   │   │   │   └── parser.py  # ClaudeStreamParser: JSON stream → events
│   │   │   ├── claude_sdk/    # In-process Anthropic SDK agent
│   │   │   ├── codex/         # CodexServerAgent: managed `codex app-server` (stdio/JSON-RPC)
│   │   │   ├── openhands/     # OpenHandsAgent (local in-process) + DockerOpenHandsAgent
│   │   │   ├── user_managed/  # UserManagedAgent: passive wait-for-external-signal
│   │   │   └── mock/          # Mock agent for testing
│   │   ├── execution/         # Shared execution infrastructure
│   │   │   ├── phase_handler.py   # Wires agent callbacks to WorkflowService calls
│   │   │   ├── attempt_store.py   # Persists attempt metrics and agent metadata
│   │   │   └── event_broadcaster.py # Persists AgentOutputEvent; one DB session per call
│   │   ├── # Backward-compat shims pointing to agents/ — DO NOT add new code here (TD-01):
│   │   ├── openhands.py, openhands_docker.py, openhands_common.py
│   │   ├── codex_server.py, codex_server_common.py, executor.py
│   │   └── parsers/           # Stream parser protocol + shims
│   │       ├── base.py        # Base stream parser protocol (canonical)
│   │       ├── claude_parser.py, codex_parser.py, openhands_parser.py
│   ├── api/                   # FastAPI REST API
│   │   ├── app.py             # Application factory, lifespan, startup recovery
│   │   ├── auth.py            # JWT authentication
│   │   ├── deps.py            # Dependency injection
│   │   ├── errors.py          # Exception handlers
│   │   ├── websocket.py       # WebSocket connection manager
│   │   ├── routers/           # API endpoints (11 routers)
│   │   │   ├── agents.py      # GET/POST/PUT/DELETE /api/agents (agent CRUD)
│   │   │   ├── runners.py     # GET /api/agent-runners (runner discovery)
│   │   │   ├── model_profiles.py # GET/PUT /api/agent-runners/{type}/profiles
│   │   │   ├── routines.py    # /api/routines CRUD + validate
│   │   │   ├── runs.py        # /api/runs CRUD + lifecycle
│   │   │   ├── tasks.py       # Task operations, checklist, grades, prompts
│   │   │   ├── repos.py       # /api/repos (repository browser)
│   │   │   ├── config.py      # GET /api/config
│   │   │   ├── clarifications.py # Clarification requests
│   │   │   ├── envfiles.py    # Environment file operations
│   │   │   └── review.py      # Review & merge workbench (13 endpoints)
│   │   └── schemas/           # Pydantic request/response models
│   │       ├── runs.py, tasks.py, steps.py, routines.py
│   │       ├── repos.py, clarifications.py, envfiles.py
│   │       ├── model_profiles.py  # Runner profile request/response schemas
│   │       ├── activity.py    # Activity log schemas
│   │       └── review.py      # Review schemas (diff, prune, conflicts, tests, merge)
│   ├── artifacts/             # Artifact tracking (proposed: move to workflow/)
│   │   ├── models.py          # Artifact data models
│   │   └── registry.py        # Registry for generated files
│   ├── cache/                 # LRU cache utility (proposed: move to git/)
│   │   └── lru.py             # Generic LRU cache used by cached_diff_ops
│   ├── cli/                   # Click CLI commands
│   │   ├── main.py            # Entry point (orchestrator command)
│   │   ├── runs.py            # Run management commands
│   │   ├── routines.py        # Routine listing commands
│   │   ├── agents.py          # Agent listing commands
│   │   ├── repos.py           # Repository commands
│   │   ├── approve.py         # Human approval commands
│   │   └── model_profiles.py  # Runner model profile commands
│   ├── config/                # Configuration models
│   │   ├── enums.py           # RunStatus, TaskStatus, AgentRunnerType, ModelProfile, etc.
│   │   ├── global_config.py   # config.json loader
│   │   ├── loader.py          # Config loading helpers
│   │   └── models.py          # RoutineConfig, StepConfig, TaskConfig
│   ├── db/                    # Database layer (SQLAlchemy + SQLite)
│   │   ├── base.py            # SQLAlchemy Base class
│   │   ├── connection.py      # Async engine + session factory
│   │   ├── models.py          # ORM models (Run, Step, Task, Attempt, Event, Signal, Lock…)
│   │   ├── repositories.py    # RunRepository, AttemptRepository, etc.
│   │   ├── event_store.py     # Event persistence + paginated queries
│   │   ├── event_journal.py   # JSONL journal (append-only, recovery source)
│   │   ├── journal_replay.py  # Replay JSONL journal onto DB snapshots
│   │   ├── recovery.py        # State recovery from event history
│   │   ├── backup.py          # DB backup utilities
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
│   │   ├── worktree.py        # Git worktree management + ensure_exists()
│   │   ├── branch_ops.py      # Branch operations (merge, back-merge)
│   │   ├── cached_diff_ops.py # LRU-cached diff operations
│   │   ├── project_init.py    # Project initialization
│   │   ├── utils.py           # Git utility functions
│   │   ├── diff_ops.py        # Diff generation (branch/commit/task scopes)
│   │   ├── prune_ops.py       # Selective change removal (file/hunk/line granularity)
│   │   ├── conflict_ops.py    # Merge conflict detection and resolution
│   │   └── errors.py          # Git-specific error types
│   ├── mcp/                   # MCP server (proposed: move to api/) (TD-01)
│   │   ├── server.py          # FastMCP SSE server
│   │   ├── tools.py           # Tool definitions
│   │   └── clarification_tools.py # Clarification-specific tools
│   ├── metrics/               # Cost tracking (proposed: move to api/) (TD-01)
│   │   └── cost.py            # Token counting and USD pricing
│   ├── repos/                 # Repository management (proposed: move to git/) (TD-01)
│   │   ├── models.py          # RepoInfo, BranchInfo
│   │   ├── discovery.py       # Repository discovery
│   │   └── errors.py          # Repo-specific errors
│   ├── review/                # Review subsystem (proposed: move to git/) (TD-01)
│   │   ├── models.py          # Domain models (DiffScope, ModifiedFile, CommitInfo, FileStatus)
│   │   └── test_runner.py     # Async test execution with result tracking and polling
│   ├── routines/              # Routine loading (proposed: move to config/) (TD-01)
│   │   ├── loader.py          # YAML routine parser
│   │   ├── discovery.py       # Directory scanning
│   │   └── versioning.py      # Git SHA versioning
│   ├── routers/               # Dead shim — pending deletion (TD-01)
│   ├── scaffolding/           # Project scaffolding (proposed: move to runners/) (TD-01)
│   │   ├── copier.py          # Copier integration
│   │   └── models.py          # Scaffolding models
│   ├── state/                 # Runtime state models
│   │   ├── models.py          # Run, StepState, TaskState
│   │   ├── factory.py         # Create Run from RoutineConfig
│   │   └── session.py         # In-memory state manager
│   └── workflow/              # Workflow engine (~8,400 LOC, 22 files)
│       ├── engine.py          # State machine orchestration (pure, no I/O)
│       ├── service.py         # WorkflowService (async wrapper; owns DB session)
│       ├── runtime.py         # RunWorkflow: executor loop, signal dispatch, phase routing
│       ├── signals.py         # WorkflowSignal enum, SignalTransport ABC, DbSignalTransport
│       ├── handlers.py        # Typed signal handler dispatch
│       ├── condition_evaluator.py # Step/task condition expression evaluator
│       ├── gates.py           # Checklist gate evaluation
│       ├── grades.py          # Grade threshold evaluation
│       ├── transitions.py     # State transition functions
│       ├── prompts.py         # Builder/verifier prompts
│       ├── templates.py       # Prompt template rendering
│       ├── context_builder.py # Build execution context for agents
│       ├── auto_verify.py     # Automatic verification logic
│       ├── clarifications.py  # Clarification workflow handling
│       ├── completion.py      # Run completion logic
│       ├── dry_run.py         # Dry run execution
│       ├── summary_cache.py   # Cached run summaries for activity feed
│       ├── events.py          # Event dataclasses + emitter ABC
│       ├── event_logger.py    # PersistentEventEmitter: SQLite + JSONL dual write
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

## Event & Signaling System

The system uses two separate mechanisms for communicating about workflow state: **Events** (what happened, immutable history) and **Signals** (what to do next, consumed once).

### Events

Events record every observable state change. All event types inherit from `WorkflowEvent` (`src/orchestrator/workflow/events.py`) and carry `timestamp`, `run_id`, and `event_type`.

**Lifecycle events:**

| Event | When emitted |
|-------|-------------|
| `RunStatusChanged` | Run transitions between DRAFT / ACTIVE / PAUSED / COMPLETED / FAILED; carries `pause_reason` and `last_error` |
| `TaskStatusChanged` | Task transitions between PENDING / BUILDING / VERIFYING / COMPLETED / FAILED; carries `start_commit` and `end_commit` |
| `StepCompleted` | All tasks in a step reach a terminal state |
| `StepSkipped` | Step skipped due to a condition |
| `RunStepBackward` | Run transitions to an earlier step |
| `ChecklistGateEvaluated` | Checklist gate evaluated with pass/fail and blocking items |
| `GradesEvaluated` | Grade thresholds evaluated with per-requirement `GradeDetail` list |
| `AutoVerifyCompleted` | Auto-verify commands finished |

**Agent lifecycle events:**

| Event | When emitted |
|-------|-------------|
| `AgentChangedEvent` | Agent switched on resume |
| `AgentDiedEvent` | Managed agent process exited unexpectedly |
| `AgentOutputEvent` | Batch of stdout lines with `line_offset` for stream reassembly |
| `AgentErrorEvent` | Agent error with type and message |
| `TaskReverted` | Task reverted to phase start during resume |
| `HealthCheckEvent` | Pre-run health check started / completed / failed |

**Fan-out events:** `FanOutSpawned`, `ChildSpawned`, `ChildCompleted`, `ChildFailed`, `FanOutCompleted`

**Human interaction events:** `ClarificationRequested`, `ClarificationResponded`, `ApprovalRequested`, `ApprovalDecision`

**Review workbench events:** `PruneApplied`, `TestRunStarted`, `TestRunCompleted`, `ConflictResolved`, `BackMergeCompleted`, `BackMergeReverted`, `AgentFixStarted`, `AgentFixCompleted`

### How Events Flow

```
WorkflowEngine.emit(event)          ← pure, synchronous, no I/O
        ↓
PersistentEventEmitter              (src/orchestrator/workflow/event_logger.py)
        ↓
EventStore.append()                 ← writes to SQLite `events` table
        +
JsonlEventJournal.append()          ← appends to .orchestrator/state/history.jsonl (aiofiles)
        ↓
Registered listeners notified
        ↓
loop.create_task(manager.broadcast_event(event))   ← WebSocket fan-out to all connected UIs
```

**Dual write rationale:** SQLite is the primary store for online queries (`EventStore.get_events_paginated()`). The JSONL journal is a secondary durable log used for recovery when the DB is unavailable or has been corrupted. Journal replay (`db/journal_replay.py`) can reconstruct DB state from the JSONL file.

**Buffering emitter:** `WorkflowEngine` uses a `BufferingEmitter` during synchronous state transitions — it collects events in memory. The caller drains them with `emitter.drain()` and persists in a single batch, keeping the engine itself free of I/O.

**High-frequency output:** `AgentOutputEvent` lines (stdout from running agents) are persisted by `EventBroadcaster` (`runners/execution/event_broadcaster.py`), which opens a fresh DB session per call rather than sharing the long-lived executor session. This trades connection overhead for isolation between agent output and workflow state writes.

### Signals

Signals are **one-time control commands** sent to an active run's executor loop. Unlike events (append-only history), signals are consumed exactly once.

**Signal types** (`WorkflowSignal` enum in `src/orchestrator/workflow/signals.py`):

| Signal | Purpose |
|--------|---------|
| `PAUSE` | Pause the run |
| `RESUME` | Resume a paused run |
| `CANCEL` | Cancel and terminate the run |
| `ACTIVITY_COMPLETED` | Notify that an external activity has completed |
| `ACTIVITY_VERIFIED` | Notify that an external activity has been verified |

**Transport abstraction:** `SignalTransport` ABC with two implementations:
- `DbSignalTransport` — reads/writes the `pending_signals` SQLite table; marks each row with `processed_at` for exactly-once delivery
- `InMemorySignalTransport` — for testing

**Signal flow:**

```
API route (e.g. POST /api/runs/{id}/pause)
        ↓
WorkflowService.pause_run()
        ↓  checks _active_run_ids set
  ┌─────┴──────┐
  │ run active │ → enqueue signal to pending_signals table
  │ run idle   │ → update DB state directly (no executor to notify)
  └────────────┘
        ↓  (on next executor loop tick)
RunWorkflow.on_signal()
        ↓
drain pending_signals → dispatch to @signal_handler(WorkflowSignal.X)
        ↓
handler returns True to stop the loop, False to continue
```

**Active-run registry:** `_active_run_ids` is a module-level `set[str]` in `signals.py`. This is an intentional, documented exception to the "no global state" design constraint — it must survive across API request/response cycles within a single process. The set is **process-local**: it is lost on server restart and does not survive across multiple workers.

### Interaction Between Signals and Agent Runners

Agent runners (`AgentRunner.execute()`) are long-running async tasks. The executor loop drives state transitions between runner invocations; it cannot interrupt a runner mid-execution via signals. The flow is:

```
RunWorkflow._run_loop():
  1. drain pending signals         ← PAUSE/CANCEL detected here, before next agent call
  2. find_next_task()
  3. execute_task() → PhaseHandler → agent.execute()   ← runner runs until it calls back
  4. callbacks (on_submit, on_grade, etc.) → WorkflowService   ← signals state transitions
  5. loop back to step 1
```

Signals received while an agent is executing (step 3) are **queued** in the `pending_signals` table and processed at the next loop iteration (step 1). A running agent cannot be interrupted mid-stream — cancellation takes effect between phases.

Agent runners communicate completion back to the orchestrator through **async closure callbacks** injected by `PhaseHandler`:

| Callback | Phase | Effect |
|----------|-------|--------|
| `on_submit()` | Builder | Calls `WorkflowService.submit_for_verification()` |
| `on_submit()` | Verifier | Calls `WorkflowService.complete_verification()` |
| `on_grade(req_id, grade, reason)` | Verifier | Calls `WorkflowService.set_grade()` |
| `on_checklist_update(req_id, status, note)` | Both | Calls `WorkflowService.update_checklist_item()` |
| `on_escalation(req_id, reason)` | Builder | Calls `WorkflowService.escalate_requirement()` → pauses run |
| `on_output(lines)` | Both | Emits `AgentOutputEvent` via `EventBroadcaster` |
| `on_agent_metadata(metadata)` | Both | Persists PID and other agent metadata |

External agents (REST/MCP) bypass the callback mechanism entirely — they call the orchestrator REST API directly (`POST /tasks/{id}/submit`, `PUT /tasks/{id}/checklist/{req}/grade`, etc.). The `UserManagedAgent` runner waits for an `asyncio.Event` set by `WorkflowService` when the external agent calls in.

---

## Tech Debt

### TD-01: Backward-compat Shims After Module Reorganisation

After agent implementations were moved from `runners/*.py` to `runners/agents/*/`, the original module paths were preserved as one-liner shim files that `import *` from the new location (e.g. `runners/openhands.py`, `runners/codex_server.py`, `runners/parsers/claude_parser.py`). The root-level `orchestrator/executor.py` and `orchestrator/routers/` are similarly stale shims.

These shims exist solely for backward compatibility and should be removed once all internal imports reference the canonical `agents/` paths. New code must never be added to shim files.

**Affected files:** `runners/cli.py`, `runners/openhands.py`, `runners/openhands_docker.py`, `runners/openhands_common.py`, `runners/codex_server.py`, `runners/codex_server_common.py`, `runners/claude_sdk.py`, `runners/user_managed.py`, `runners/mock.py`, `runners/executor.py`, `runners/parsers/claude_parser.py`, `orchestrator/executor.py`, `orchestrator/routers/`.

---

### TD-02: Duplicate Agent Detection Systems

Two agent detection systems coexist:
- `runners/detector.py` — original; still wired to `GET /api/agent-runners`
- `runners/agent_detector.py` — newer registry-based design; each agent package self-registers

Both systems must be kept in sync when adding a new runner type. `detector.py` should be replaced by `agent_detector.py` once the API route is updated.

---

### TD-03: Process-Local Active-Run Registry

`_active_run_ids` in `signals.py` is a module-level `set[str]`. It is lost on server restart and is incompatible with multi-worker deployments. Runs paused by server shutdown are recovered via the `server_shutdown` pause reason, but if a run is mid-transition when the process dies, the registry state is gone.

**Impact today:** Low — single-process, single-worker deployment. Becomes a correctness problem if the deployment model changes.

---

### TD-04: `StepSkipped` Dual-Field Inconsistency

`StepSkipped` carries both `skip_reason` (canonical) and `reason` (legacy alias), kept manually in sync in `__init__`. Recovery code (`db/recovery.py`) contains a matching fallback comment. This is a backward-compatibility wart for events already written to the JSONL journal and SQLite store.

**Resolution path:** Once events older than the `skip_reason` introduction date have aged out of production journals, remove `reason` and the sync code.

---

### TD-05: `scheduled_resume_at` Is a Stub

`RunWorkflow._scheduled_resume_check()` reads the `scheduled_resume_at` DB column but only logs `"auto-resume pending (stub, not yet implemented)"` — no action is taken. The column exists and the migration is applied, but the feature is not functional.

---

### TD-06: `InMemoryLockManager` Does Not Raise `LockTimeoutError`

`LockTimeoutError` is defined but `InMemoryLockManager` never raises it — locks simply expire passively (no contention detection). This means the pessimistic locking contract is not enforced in practice. Tests document this as a known gap.

---

### TD-07: Unimplemented Planning Phase

`PhaseType` enum includes `plan`, `gap_check`, `summarize`, `human_review`, and `auto_verify` alongside the active `build` and `verify` phases. `RoutineConfig`, `StepConfig`, and `TaskConfig` all carry a `planner_agent` field. Neither the planner agent field nor the additional phase types are read by the executor — planning was designed but never implemented.

---

### TD-08: Dead Codex HTTP-Era Code

`runners/agents/codex/common.py` contains `create_session_payload()`, marked `"""Deprecated — HTTP-era session payload builder. Do not use."""` and tagged `# pragma: no cover`. It is never called. This is dead code from a previous HTTP-based Codex integration.

---

### TD-09: `EventBroadcaster` Opens a New DB Session Per Output Line

`EventBroadcaster.emit_log_event()` opens a fresh `async_sessionmaker` session for each batch of agent output lines. Under high-throughput agents (many lines/second) this creates a large number of short-lived DB connections. The module docstring acknowledges this as a known trade-off to preserve the original semantics when the code was extracted from `AgentRunnerExecutor`.

**Resolution path:** Batch output events or reuse a dedicated session with a short-lived transaction.

---

### TD-10: `repos/discovery.py` Deprecated Parameter

The `include_remote` parameter in `repos/discovery.py` is marked `deprecated, use local_only` in the docstring but remains in the function signature. Callers that still pass `include_remote=True` receive the old (now incorrect) behaviour silently.

---

### TD-11: `RunWorkflow` Constructor Arity

`RunWorkflow.__init__` accepts 15+ mostly-optional keyword-only `Callable | None` parameters — bound references to private methods of `AgentRunnerExecutor`. This exists to avoid `reportPrivateUsage` type-checker errors. The correct fix is a small interface or dataclass that `AgentRunnerExecutor` constructs and passes to `RunWorkflow`.

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
orchestrator runs replay-journal --since 2026-03-09T10:00:00Z

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
