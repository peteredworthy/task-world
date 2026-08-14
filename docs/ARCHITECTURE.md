# Architecture Overview

This document provides a high-level overview of the Orchestrator project structure, how to run it, and guidance for navigating the codebase.

## Quick Start

### Running the Application

**Backend API Server (FastAPI):**
```bash
# Start the backend on port 8000
uv run orchestrator serve --reload
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
| Scoped MCP SSE | http://localhost:8000/mcp-scoped/{tools}/sse | MCP endpoint limited to comma-separated orchestrator tool names |
| API Docs | http://localhost:8000/docs | OpenAPI/Swagger docs |

### Environment Setup

1. Copy `.env.example` to `.env`
2. Set required variables:
   - `OPENAI_API_KEY` - Required for OpenHands agents
   - `AUTH_DISABLED=true` - For local development

---

## Cache-authority routine binding

Graph routines may declare `file_state_policy` with bounded `declarations` and
`scan_budget` (`max_entries`, `max_bytes`). Compilation canonicalizes this
policy, stores its versioned preimage and SHA-256 digest only in the routine snapshot,
and copies the digest to every node, lease, and dispatch intent. Runtime
dispatch verifies all copies against the projected snapshot before it accesses
the worktree. Pattern-library learning remains classification-only and cannot
alter this compiled authority. The format is exhaustive: all of version,
preimage, and hash absent is legacy; all present with version
`cache-authority-v1` and a verified digest is new-format; every partial or
unknown-version combination is rejected. V1 built-in tool-cache and secret
detector fields are frozen constants, while routine configuration can supply
only custom declarations and scan budgets. Runtime materializes boundary
policy from the verified snapshot, never from mutable defaults. Older facts
with all three fields absent resolve to `LEGACY_CACHE_AUTHORITY_V1`.

The production `dynamic-graph-feature` routine compiles a 50,000-entry,
1-GiB scan budget so normal ignored frontend dependency trees fit within its
immutable authority. A deterministic cache scan-budget failure before runner
baseline capture is a terminal runtime-configuration failure: the lease is
revoked and the node fails without scheduling a runtime retry.

Runner snapshot boundaries persist `RunnerCacheRoot` objects (`path` plus
`untracked` or `ignored` source kind), not bare path strings. Roots are sorted,
non-overlapping concrete first ancestors derived from actual worktree status;
tracked paths, source-kind mismatches, learned patterns, and broad arbitrary
paths cannot authorize omission. Baseline, staged, final, and recovery-observed
sets remain separately attributable on an execution attempt and recovery uses
their validated union. Hashless string roots are replay-only legacy evidence:
they are grandfathered for their existing attempt under the frozen legacy
policy, while new root facts must be typed and policy-authorized.

---

## Directory Map

```
task-world/
├── src/orchestrator/          # Python backend modules
│   ├── errors.py              # Root-level domain exceptions
│   ├── time_utils.py          # Time utilities (injectable clocks for testing)
│   │
│   ├── api/                   # All external interfaces
│   │   ├── app.py             # Application factory, lifespan, startup recovery
│   │   ├── auth.py            # JWT authentication
│   │   ├── deps.py            # Dependency injection
│   │   ├── errors.py          # Exception handlers
│   │   ├── metrics.py         # Token counting and USD cost estimation
│   │   ├── websocket.py       # WebSocket connection manager
│   │   ├── mcp/               # MCP server (alternative transport to REST)
│   │   │   ├── server.py      # FastMCP SSE server
│   │   │   ├── tools.py       # Tool definitions (ORCHESTRATOR_TOOLS)
│   │   │   └── clarification_tools.py
│   │   ├── routers/           # API endpoints (12 routers)
│   │   │   ├── agents.py      # GET/POST/PUT/DELETE /api/agents
│   │   │   ├── runners.py     # GET /api/agent-runners
│   │   │   ├── model_profiles.py # GET/PUT /api/agent-runners/{type}/model-profile-defaults
│   │   │   ├── routines.py    # /api/routines CRUD + validate
│   │   │   ├── cost_rollup.py # GET /api/runs/cost-rollup graph usage aggregation
│   │   │   ├── runs.py        # /api/runs CRUD + lifecycle
│   │   │   ├── tasks.py       # Task operations, checklist, grades, prompts
│   │   │   ├── repos.py       # /api/repos (repository browser)
│   │   │   ├── config.py      # GET /api/config
│   │   │   ├── clarifications.py
│   │   │   ├── envfiles.py
│   │   │   ├── review.py      # Review & merge workbench (13 endpoints)
│   │   │   └── graph.py       # Graph projections and authorized artifact reads
│   │   └── schemas/           # Pydantic request/response models
│   │       ├── runs.py, tasks.py, steps.py, routines.py
│   │       ├── repos.py, clarifications.py, envfiles.py
│   │       ├── model_profiles.py, activity.py, review.py, cost_rollup.py, base.py
│   │
│   ├── cli/                   # Click CLI commands
│   │   ├── main.py            # Entry point (orchestrator command)
│   │   ├── runs.py, routines.py, agents.py, repos.py
│   │   ├── approve.py         # Human approval commands
│   │   └── db.py              # Database commands
│   │
│   ├── config/                # All configuration: enums, models, routine loading
│   │   ├── enums.py           # RunStatus, TaskStatus, AgentRunnerType, ModelProfile, etc.
│   │   ├── global_config.py   # config.json loader
│   │   ├── loader.py          # Config loading helpers
│   │   ├── models.py          # RoutineConfig, StepConfig, TaskConfig, NudgerConfig, etc.
│   │   └── routines/          # YAML routine loading (absorbed from routines/)
│   │       ├── loader.py      # YAML routine parser
│   │       ├── discovery.py   # Directory scanning
│   │       ├── versioning.py  # Git SHA versioning
│   │       └── errors.py
│   ├── artifacts/             # Durable content-addressed artifact storage
│   │   ├── models.py          # Stored artifact reference model export
│   │   ├── store.py           # ArtifactStore protocol and filesystem CAS
│   │   ├── gc.py              # Typed-reference mark-and-sweep collector
│   │   ├── coordination.py    # Cross-process publish/sweep root locking
│   │   ├── resolution.py      # Run-scoped main-CAS and project-GC composition
│   │   └── errors.py          # Artifact storage errors
│   │
│   ├── db/                    # Persistence: ORM, repositories, event store
│   │   ├── orm/               # SQLAlchemy ORM definitions
│   │   │   ├── base.py        # SQLAlchemy Base class
│   │   │   └── models.py      # Run, Step, Task, Attempt, Event, RoutineMeta ORM models
│   │   ├── access/            # Data access layer
│   │   │   ├── connection.py  # Async engine + session factory
│   │   │   ├── repositories.py # RunRepository, locked JSON merge mechanics, etc.
│   │   │   ├── event_store.py # Legacy event persistence + paginated queries (events table)
│   │   │   ├── event_store_v2.py # SqliteEventStore: event sourcing via events_v2
│   │   │   └── jsonl_outbox.py # JsonlOutboxObserver: post-append JSONL writer
│   │   ├── projections/       # Read-model projections rebuilt from events_v2
│   │   │   ├── registry.py    # ProjectionRegistry: fan-out + rebuild_all
│   │   │   ├── run_state.py   # RunStateProjector → runs projection table
│   │   │   ├── task_state.py  # TaskStateProjector → tasks projection table
│   │   │   └── run_lifecycle.py # RunLifecycleProjector → active-run tracking
│   │   ├── bootstrap.py       # JSONL bootstrap: seeds events_v2 on empty-DB startup
│   │   ├── recovery/          # Backup utilities
│   │   │   └── backup.py      # DB backup / restore helpers
│   │
│   ├── envfiles/              # Environment file management
│   │   ├── models.py, store.py, lifecycle.py
│   │   ├── resolution.py, security.py, cleanup.py, tools.py
│   │
│   ├── git/                   # All git & repository operations
│   │   ├── worktree.py        # Git worktree management + ensure_exists()
│   │   ├── project_init.py    # Project initialization
│   │   ├── utils.py           # Git utility functions
│   │   ├── errors.py          # Git-specific error types
│   │   ├── repos.py           # RepoInfo, BranchInfo, list_repos, get_repo, list_branches
│   │   ├── diff/              # Diff generation (absorbed from diff_ops, cached_diff_ops, cache)
│   │   │   ├── diff_ops.py    # Diff generation (branch/commit/task scopes)
│   │   │   ├── cached_diff_ops.py # LRU-cached diff operations
│   │   │   ├── lru_cache.py   # Generic LRU cache
│   │   │   └── models.py      # Diff domain models (DiffScope, ModifiedFile, etc.)
│   │   ├── ops/               # Branch, conflict, prune operations (absorbed from review)
│   │   │   ├── branch_ops.py  # Branch operations (merge, back-merge)
│   │   │   ├── conflict_ops.py # Merge conflict detection and resolution
│   │   │   └── prune_ops.py   # Selective change removal (file/hunk/line granularity)
│   │   └── testing/           # Async test execution (absorbed from review/test_runner)
│   │       └── test_runner.py # TestRunner with polling and result tracking
│   │
│   ├── graph/                 # Pure dynamic execution graph kernel
│   │   ├── command_bindings.py # Opaque check-command binding resolution
│   │   ├── commands.py        # Command applier and graph event generation
│   │   ├── compiler.py        # Routine-to-graph compiler
│   │   ├── contracts.py       # Typed node/port contract registry
│   │   ├── macros.py          # Planner-facing macro expansion to low-level patch ops
│   │   ├── patch_validator.py # Pure graph patch validation
│   │   ├── projection_collections.py # FrozenMap and persistent update primitives
│   │   ├── projection_models.py # Frozen grouped GraphProjection and canonical record ownership
│   │   ├── projection_queries.py # Public, copy-out projection query boundary
│   │   ├── projection_codec.py # Disposable schema/position/state/checksum checkpoint codec
│   │   ├── projections.py     # Event reducer and projection policy/read models
│   │   └── scheduler.py       # Pure readiness and lease scheduling helpers
│   │
│   ├── graph_runtime/         # Effectful graph runtime bridge
│   │   ├── controller.py      # Applies graph commands and appends events/outbox rows
│   │   ├── dispatch.py        # Outbox-to-runner/controller execution bridge
│   │   ├── prompts.py         # Bounded prompt packets and explicit artifact excerpts
│   │   ├── outbox.py          # Durable side-effect outbox mapping/dispatcher
│   │   └── store.py           # Graph event store and summary read models
│   │
│   ├── runners/               # Agent execution: all runner types, detection, profiles
│   │   ├── interface.py       # AgentRunner protocol definition
│   │   ├── types.py           # ExecutionContext, ExecutionResult, etc.
│   │   ├── agent_factory.py   # Registry-based agent factory; each package self-registers
│   │   ├── agent_detector.py  # Registry-based runner detection (preferred over detector.py)
│   │   ├── errors.py          # Runner-specific error types
│   │   ├── agents/            # Concrete agent implementations
│   │   │   ├── claude_cli/    # CLIAgent + ClaudeCliQuotaAgent (subprocess)
│   │   │   ├── codex/         # CodexServerAgent (stdio/JSON-RPC)
│   │   │   ├── openhands/     # OpenHandsAgent (local) + DockerOpenHandsAgent
│   │   │   └── mock/          # Mock agent for testing
│   │   ├── detection/         # Agent detection + config helpers (absorbed from flat runners/)
│   │   │   ├── detector.py    # Legacy detector; wired to GET /api/agent-runners (TD-02)
│   │   │   ├── config_utils.py
│   │   │   └── profile_resolution.py # Model profile → model string resolution
│   │   ├── execution/         # Shared execution infrastructure
│   │   │   ├── phase_handler.py   # Wires agent callbacks to WorkflowService
│   │   │   ├── attempt_store.py   # Persists attempt metrics and agent metadata
│   │   │   └── event_broadcaster.py # Persists AgentOutputEvent per batch
│   │   ├── parsers/           # Stream parser protocol
│   │   │   ├── base.py        # Parser protocol (implementations live in agents/*/parser.py)
│   │   ├── profiles/          # Agent config CRUD (absorbed from agents/)
│   │   │   ├── models.py      # AgentConfigModel ORM model
│   │   │   ├── schemas.py     # AgentSchema, CreateAgentRequest, UpdateAgentRequest
│   │   │   ├── service.py     # AgentService CRUD + seed_default_agents()
│   │   │   ├── resolution.py  # Cascading agent resolution (task→step→routine→default)
│   │   │   └── errors.py
│   │   ├── runtime/           # Runtime health: monitor, nudger, quota, repetition detection
│   │   │   ├── monitor.py     # Dead runner detection/recovery
│   │   │   ├── nudger.py      # Stuck runner nudging (timeout, nudge, kill)
│   │   │   ├── quota.py       # Agent quota tracking and enforcement
│   │   │   └── repetition_detector.py # Detects agent stuck in output loops
│   │   └── scaffolding/       # Project scaffolding (absorbed from scaffolding/)
│   │       ├── copier.py      # Copier integration
│   │       └── models.py
│   │
│   ├── state/                 # Runtime domain models (in-memory, not persisted by this module)
│   │   ├── models.py          # Run, StepState, TaskState, ActionLog, ActionEntryKind
│   │   ├── factory.py         # Create Run from RoutineConfig
│   │   ├── session.py         # In-memory SessionStateManager
│   │   └── errors.py
│   │
│   └── workflow/              # Workflow engine: state machine, signals, events, prompts
│       ├── service.py         # WorkflowService (async wrapper; owns DB session)
│       ├── completion.py      # Run completion logic
│       ├── dry_run.py         # Dry run execution
│       ├── locks.py           # Task-level pessimistic locking
│       ├── graph_driver.py    # Production driver for graph-mode runs
│       ├── graph_recovery.py  # Startup recovery selection for graph-mode runs
│       ├── agent/             # Agent interaction layer
│       │   ├── prompts.py     # Builder/verifier prompt generation
│       │   ├── templates.py   # Prompt template rendering
│       │   ├── context_builder.py # Build execution context for agents
│       │   ├── auto_verify.py # Automatic verification logic
│       │   ├── clarifications.py # Clarification workflow handling
│       │   └── summary_cache.py # Cached run summaries for activity feed
│       ├── artifacts/         # Artifact tracking (absorbed from artifacts/)
│       │   ├── models.py      # Artifact data models
│       │   └── registry.py    # Registry for generated files
│       ├── engine/            # Pure state machine (no I/O)
│       │   ├── engine.py      # WorkflowEngine: state machine orchestration
│       │   ├── condition_evaluator.py # Step/task condition expression evaluator
│       │   ├── gates.py       # Checklist gate evaluation
│       │   ├── grades.py      # Grade threshold evaluation
│       │   ├── transitions.py # State transition functions
│       │   └── errors.py
│       ├── events/            # Event models + persistence
│       │   ├── types.py       # All WorkflowEvent subclasses
│       │   └── logger.py      # PersistentEventEmitter: event persistence + listener fan-out
│       ├── delegation/        # Delegated-work commands, reducers, and recording helpers
│       │   ├── coordinator.py # Immutable delegation state value object
│       │   ├── recorder.py    # Shared DelegationState recording helper
│       │   ├── fan_out.py     # Fan-out delegation policy and work mapping
│       │   └── super_parent.py # Super-parent child command validation and work mapping
│       └── signals/           # Signal transport + executor loop
│           ├── signals.py     # WorkflowSignal enum, SignalTransport ABC, EventSignalTransport
│           ├── handlers.py    # Typed signal handler dispatch
│           └── runtime.py     # RunWorkflow: executor loop, signal dispatch, phase routing
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
│   ├── restore_from_journal.py # Restore empty DBs from JSONL via events_v2
│   └── seed_db.py             # Obsolete; create seed data through CLI/API lifecycle
├── docker/                    # Docker configuration
│   └── Dockerfile.agent-server
│
├── AGENTS.md                  # Coding agent instructions
├── CLAUDE.md                  # Redirects to AGENTS.md
├── pyproject.toml             # Python project configuration
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

### Cost and Token Telemetry

`ModelTokenUsage` is a frozen, append-oriented **execution × model** fact; it
is not a provider-call trace because the current runners cannot reliably retain
provider-call identity. Its canonical OpenTelemetry GenAI fields are
`gen_ai_usage_input_tokens`, `gen_ai_usage_output_tokens`,
`gen_ai_usage_cache_read_input_tokens`,
`gen_ai_usage_cache_creation_input_tokens`,
`gen_ai_usage_reasoning_output_tokens`, and
`gen_ai_response_finish_reasons`. Cache token components are included in input;
reasoning tokens remain observable but are not charged a second time. Each fact
also preserves `cost_usd`, `latency_ms`, and `rate_missing` at execution time.

Phase 1 persists graph `node_usage_recorded` facts idempotently and exposes only
their graph rollup through `GET /api/runs/cost-rollup`. Provider-billed built-in
runner defaults must resolve to a matched, nonzero rate in `model_costs.yaml`.
Local/no-provider-cost models must instead be represented by an explicit
zero-rate table entry; a missing rate is surfaced as `rate_missing=true`, never
silently classified as local. Runners with no baked-in model default are
classified separately as `no_static_default`, so runtime discovery is not
mistaken for a zero-cost provider. Budget blocking, alert thresholds, and
per-profile effort configuration remain Phase-2 work.

### Graph Planning and Legacy Delegation

Graph-mode runs are the default execution carrier. `GraphRunDriver` seeds a
routine into graph events, drives scheduler ticks, dispatches leased executable
nodes, records file-state boundaries, and bridges terminal graph state back onto
the run read model. Planner-chain support replaces the retired parent/child
oversight carrier: delegated child-style work is represented as graph planner
generations and horizon regions inside one run, not as separate child runs.

The old live parent/child oversight API and UI have been removed. Historical
fields such as `parent_run_id` and `oversight_state` remain read-only so archived
runs and event logs can still be replayed.

The remaining `workflow/delegation/` code is generic fan-out task bookkeeping,
not the super-parent carrier. Delegation command fencing, idempotency records,
result records, and review blockers are recorded through `DelegationRecorder`,
which wraps the immutable `DelegationState` value object.

### Immutable Graph Projection

`GraphProjection` is a schema-14, grouped, deeply immutable read model. Its
root groups and every reachable projection model are frozen; dynamic indexes use
`FrozenMap`, ordered collections use tuples, and reducers make persistent
updates with `model_copy`/`map_set` rather than mutation. `RecordStore.by_id`
is the sole owner of complete canonical accepted/output records; other groups
retain identifiers or summaries. The projection does not maintain a duplicate
projected record/value hierarchy or conversion registry.

Only `projection_models.py`, `projection_collections.py`,
`projection_queries.py`, `projection_codec.py`, and `projections.py` may read
physical grouped storage. Modules outside the graph package import query
functions and types from `orchestrator.graph`, never a graph submodule. Query functions own storage
access and return immutable values or fresh public copies.

Checkpoints are disposable accelerators. Complete runtime state lives in the
dedicated `graph_projection_checkpoints` owner with position, projection schema
version, serialized grouped state, and checksum. It is read only when its
metadata, direct Pydantic state validation, and checksum agree. Relationship
correctness remains at event acceptance and reducer/index writes. The
separate `graph_projection_snapshots` owner contains only response-bounded
public fields and is validated by position plus graph read-contract revision;
public packing therefore cannot disable checkpoint-plus-tail execution.
Missing, malformed, stale, or version-mismatched runtime checkpoints are
rebuilt by fixed-batch startup/maintenance replay from the durable event stream,
while request-time recovery remains bounded. The permanent
`graph-projection-boundaries` pre-commit hook rejects storage-boundary and
public-import violations. Executable closure evidence is the canonical event
behavior matrix, every-split incremental and checkpoint-tail replay,
model-derived flexible-JSON checkpoint coverage, and direct performance tests.
The direct performance gate replays each 10,000-event scenario after one warmup,
uses three samples, asserts exact behavior cardinality, and requires a median
under one second.

---

## Event & Signaling System

The system uses two separate mechanisms for communicating about workflow state: **Events** (what happened, immutable history) and **Signals** (what to do next, consumed once).

### Events

Events record every observable state change. All event types inherit from `WorkflowEvent` (`src/orchestrator/workflow/events/types.py`) and carry `timestamp`, `run_id`, and `event_type`.

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

Workflow transitions emit immutable events to `events_v2`, and event-backed read-model updates are applied through projectors. Some read-model tables still have compatibility mutation paths for migration-era utilities and tests, so the system is event-backed but not purely event-sourced.

```
API call → command handler (WorkflowService)
        ↓
WorkflowEngine.emit(event)          ← pure, synchronous, no I/O
        ↓
PersistentEventEmitter              (src/orchestrator/workflow/events/logger.py)
        ↓
SqliteEventStore.append()           ← writes to events_v2 table (primary store)
        ↓
ProjectionRegistry                  ← fan-out to registered projectors
  ├── RunStateProjector             → updates runs read-model table
  ├── TaskStateProjector            → updates tasks read-model table
  └── RunLifecycleProjector         → tracks active-run lifecycle state
        ↓
JsonlOutboxObserver                 ← appends to .orchestrator/state/history.jsonl
        ↓
loop.create_task(manager.broadcast_event(event))   ← WebSocket fan-out to all connected UIs
```

**Empty-DB bootstrap:** On first startup, if `events_v2` is empty, `bootstrap_from_jsonl()` reads `history.jsonl`, seeds `events_v2`, and calls `projection_registry.rebuild_all()` to restore read-model tables from history.

**Buffering emitter:** `WorkflowEngine` uses a `BufferingEmitter` during synchronous state transitions — it collects events in memory. The caller drains them with `emitter.drain()` and persists in a single batch, keeping the engine itself free of I/O.

**High-frequency output:** `AgentOutputEvent` lines (stdout from running agents) are persisted by `EventBroadcaster` (`runners/execution/event_broadcaster.py`), which opens a fresh DB session per call rather than sharing the long-lived executor session.

### Signals

Signals are **one-time control commands** sent to an active run's executor loop. Unlike events (append-only history), signals are consumed exactly once.

**Signal types** (`WorkflowSignal` enum in `src/orchestrator/workflow/signals/signals.py`):

| Signal | Purpose |
|--------|---------|
| `PAUSE` | Pause the run |
| `RESUME` | Resume a paused run |
| `CANCEL` | Cancel and terminate the run |
| `ACTIVITY_COMPLETED` | Notify that an external activity has completed |
| `ACTIVITY_VERIFIED` | Notify that an external activity has been verified |

**Transport abstraction:** `SignalTransport` ABC with two implementations:
- `EventSignalTransport` — stores `SignalEnqueued` / `SignalProcessed` events in `events_v2`
- `InMemorySignalTransport` — for testing

**Signal flow:**

```
API route (e.g. POST /api/runs/{id}/pause)
        ↓
WorkflowService.pause_run()
        ↓
EventSignalTransport.enqueue()      ← writes SignalEnqueued event to events_v2
        ↓  (on next executor loop tick)
RunWorkflow.on_signal()
        ↓
EventSignalTransport.drain()        → dispatch to @signal_handler(WorkflowSignal.X)
        ↓
handler returns True to stop the loop, False to continue
```

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

Signals received while an agent is executing (step 3) are **queued** in `events_v2` via `EventSignalTransport` and processed at the next loop iteration (step 1). A running agent cannot be interrupted mid-stream — cancellation takes effect between phases.

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

External clients may call the orchestrator REST/MCP APIs directly, but this is
not an active agent-runner backend.

---

## Module Import Discipline

The codebase is organized into exactly **9 canonical modules**:

`api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, `workflow`

Each canonical module exposes its public surface via its `__init__.py`. **Never reach into a module's sub-packages from outside that module.** If a symbol you need isn't exported yet, add it to the relevant `__init__.py` rather than importing from the internal sub-path.

```python
# ✓ correct — import from module top-level
from orchestrator.runners import CLIAgent, CodexServerAgent

# ✗ wrong — reaching into sub-packages
from orchestrator.runners.agents.claude_cli.agent import CLIAgent
```

Note: importing from a root-level `.py` file within a module (e.g., `from orchestrator.config.models import NudgerConfig`) is fine — the rule only applies to sub-package directories (directories with their own `__init__.py`).

A pre-commit hook (`scripts/check_module_imports.py`) enforces this rule and will fail if any file imports directly from a sub-package of a module it doesn't own.

---

## Tech Debt

### ~~TD-01: Backward-compat Shims After Module Consolidation~~ — RESOLVED

All backward-compat shim files have been removed as part of module consolidation phase 3 (commit `38102b4`). Removed: `runners/openhands.py`, `runners/openhands_docker.py`, `runners/openhands_common.py`, `runners/codex_server.py`, `runners/codex_server_common.py`, and the root-level `orchestrator/executor.py`. The parser shims (`runners/parsers/claude_parser.py`, `codex_parser.py`, `openhands_parser.py`) were also removed — parsers now live in their respective agent sub-packages (`agents/*/parser.py`) and are lazy-loaded via `runners/parsers/__init__.py`. Note: `runners/executor.py` is the real executor implementation (1600+ LOC), not a shim.

---

### ~~TD-02: Duplicate Agent Detection Systems~~ — RESOLVED

`runners/detection/detector.py` has been deleted. `ToolDetector` now lives solely in `runners/agent_detector.py`. The `detection/` sub-package re-exports from `agent_detector.py` for backward compatibility. The API route (`GET /api/agent-runners`) imports from `agent_detector.py` directly.

---

### ~~TD-03: Process-Local Active-Run Registry~~ — RESOLVED

`RunLifecycleProjector` now tracks active-run state in the `events_v2` projection layer. Active-run state is derived from `RunStatusChanged` events and survives server restarts through the projection rebuild path.

---

### ~~TD-04: `StepSkipped` Dual-Field Inconsistency~~ — RESOLVED

The legacy `reason` alias has been removed from `StepSkipped`; only `skip_reason` remains.

---

### ~~TD-05: `scheduled_resume_at` Is a Stub~~ — RESOLVED

The stub `_scheduled_resume_check()` method has been removed from `workflow/signals/runtime.py`. The `scheduled_resume_at` DB column remains for future use but the dead stub code is gone.

---

### TD-06: `InMemoryLockManager` Does Not Raise `LockTimeoutError`

`LockTimeoutError` is defined but `InMemoryLockManager` never raises it — locks simply expire passively (no contention detection). This means the pessimistic locking contract is not enforced in practice. Tests document this as a known gap.

---

### ~~TD-07: Unimplemented Task Phase Schema~~ — RESOLVED

The unused `PhaseType` enum, `PhaseConfig` model, `TaskConfig.phases` field, planner-agent routine override fields, and phase validator path have been removed. Fresh databases are created directly from the current ORM schema, so no historical phase columns remain.

---

### TD-08: Dead Codex HTTP-Era Code

RESOLVED: `create_session_payload()` has been removed from `runners/agents/codex/common.py`. It was dead code from a previous HTTP-based Codex integration.

---

### TD-09: `EventBroadcaster` Opens a New DB Session Per Output Line

`EventBroadcaster.emit_log_event()` opens a fresh `async_sessionmaker` session for each batch of agent output lines. Under high-throughput agents (many lines/second) this creates a large number of short-lived DB connections. The module docstring acknowledges this as a known trade-off to preserve the original semantics when the code was extracted from `AgentRunnerExecutor`.

**Resolution path:** Batch output events or reuse a dedicated session with a short-lived transaction.

---

### ~~TD-10: `git/repos.py` Deprecated Parameter~~ — RESOLVED

The deprecated `include_remote` parameter has been removed from `list_branches()` in `git/repos.py`. All callers have been updated to use `local_only` instead.

---

### ~~TD-11: `RunWorkflow` Constructor Arity~~ — RESOLVED

The 15+ callback parameters have been consolidated into an `ExecutorCallbacks` dataclass in `workflow/signals/runtime.py`. `AgentRunnerExecutor` constructs an `ExecutorCallbacks` instance and passes it as a single `callbacks` parameter to `RunWorkflow`.

---

## API Routes

### Core

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/config` | Global configuration |
| GET | `/api/agent-runners` | List the four selectable backends as `AgentRunnerOption[]`: OpenHands local/Docker, CLI subprocess, and Codex Server |
| GET | `/api/agent-runners/local-models` | Discover models from a local OpenAI-compatible LLM server |
| GET | `/api/agent-runners/{type}/model-profile-defaults` | Get Agent Runner Model Defaults for a runner type |
| PUT | `/api/agent-runners/{type}/model-profile-defaults` | Set Agent Runner Model Defaults for a runner type |
| GET | `/api/agents` | List all agent configs (name + system_prompt + model_profile) |
| POST | `/api/agents` | Create an agent config |
| GET | `/api/agents/{id}` | Get agent config by ID |
| PUT | `/api/agents/{id}` | Update agent config |
| DELETE | `/api/agents/{id}` | Delete agent config |
| POST | `/api/agents/{id}/reset-prompt` | Reset system_prompt to default_prompt |

### Routines

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/routines` | List available routines (supports `?include_archived=true`) |
| GET | `/api/routines/{id}` | Get routine details |
| POST | `/api/routines/validate` | Validate a routine YAML |
| POST | `/api/routines/{id}/archive` | Archive a routine (hidden from listings) |
| POST | `/api/routines/{id}/unarchive` | Unarchive a routine |

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
| GET | `/api/runs/cost-rollup` | Aggregate canonical graph `node_usage_recorded` facts by day, node kind, model, profile, and/or run |
| GET | `/api/runs/{id}` | Get run details |
| DELETE | `/api/runs/{id}` | Delete run |
| POST | `/api/runs/{id}/start` | Start run execution |
| POST | `/api/runs/{id}/pause` | Pause run |
| POST | `/api/runs/{id}/resume` | Resume run |
| POST | `/api/runs/{id}/cancel` | Cancel run |
| GET | `/api/runs/{id}/evidence` | Return structured `run.evidence.v1` bundles from the run worktree |
| GET | `/api/runs/{id}/evidence-digest?max_nodes=3&include_node_evidence=true` | Bounded run digest from normalized graph read models; it never decodes a projection checkpoint or replays history. `graph_facts_status=partial` identifies facts unavailable from the compact model; per-node `evidence_status=partial` means the fixed evidence window omitted additional facts. |
| GET | `/api/runs/{id}/trace` | Run trace data with attempts, phases, action logs, and token usage |
| GET | `/api/runs/{id}/activity` | Activity log (paginated, compact `payload_mode=summary` by default; use `payload_mode=full` for transcript payloads) |
| GET | `/api/runs/{id}/activity/stream` | Activity SSE stream (compact `payload_mode=summary` by default; use `payload_mode=full` for transcript payloads) |
| GET | `/api/runs/{id}/guidance` | Aggregate guidance for agents |
| GET | `/api/runs/{id}/artifacts/{sha256_hex}?offset=0&limit=65536` | Authenticated, run-referenced byte range after complete blob verification (`0 <= offset`, `1 <= limit <= 1,048,576`) |
| GET | `/api/runs/{id}/graph/events` | Graph event log for a run |
| GET | `/api/runs/{id}/graph/health` | Bounded graph health snapshot: scheduler, lease, blocker, patch, verifier, and pending-gate facts; no raw event payloads |
| GET | `/api/runs/{id}/graph/scheduler` | Graph scheduler buckets and leases |
| GET | `/api/runs/{id}/graph/decisions` | Graph human decisions, appeals, and review readiness |
| GET | `/api/runs/{id}/graph/patches` | Graph patch proposal/result readback |
| GET | `/api/runs/{id}/graph/topology` | Byte- and count-bounded archival topology page |
| GET | `/api/runs/{id}/graph/final-blockers` | Byte- and count-bounded final-invariant blocker page |
| GET | `/api/runs/{id}/graph/regions` | Byte- and count-bounded task-region and blocker page |
| GET | `/api/runs/{id}/graph/file-state` | Bounded, cursor-paged graph file-state boundary report (`from_position`, `limit`, `path_limit`) |
| GET | `/api/runs/{id}/graph/nodes/{node_id}` | Graph node detail with inputs, outputs, callbacks, and file-state facts |
| GET | `/api/runs/{id}/branch-status` | Branch ahead/behind status |
| POST | `/api/runs/{id}/back-merge` | Pull source branch into run |
| POST | `/api/runs/{id}/merge-back` | Merge run branch into source |
| POST | `/api/runs/{id}/steps/{step_id}/approve` | Approve a step gate |

The topology, final-blocker, and region routes share one archival publication
position. Graph appends mark that generation dirty; background maintenance
publishes all three owners atomically. While maintenance is catching up, reads
return a structured retryable 503 and never replay history. Clients may pass
`expected_position`; a different current position returns a structured
retryable 409 so the complete three-view read can restart from a new anchor.

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
| SSE | `/mcp-scoped/{tools}/sse` | MCP server-sent events with a comma-separated orchestrator tool allowlist |
| HTTP | `/mcp-scoped/{tools}/messages` | MCP message endpoint for the scoped MCP server |

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
| Agent implementations | `src/orchestrator/runners/agents/*/` |
| Frontend entry | `ui/src/App.tsx`, `ui/src/pages/*.tsx` |
| Test examples | `tests/unit/*.py`, `tests/integration/*.py` |
| Review API routes | `src/orchestrator/api/routers/review.py` |
| Review schemas | `src/orchestrator/api/schemas/review.py` |
| Git diff/prune/conflict ops | `src/orchestrator/git/diff/diff_ops.py`, `git/ops/prune_ops.py`, `git/ops/conflict_ops.py` |
| Review diff domain models | `src/orchestrator/git/diff/models.py` |
| Async test runner | `src/orchestrator/git/testing/test_runner.py` |
| Review frontend components | `ui/src/components/review/ReviewMergeTab.tsx` |
| Review API client | `ui/src/api/reviewClient.ts` |
| Review hooks | `ui/src/hooks/useReview.ts`, `ui/src/hooks/useReviewKeyboardShortcuts.ts` |

### Review Workflow Events

The following event types (`src/orchestrator/workflow/events/types.py`) are emitted by review operations and persisted to the activity log:

| Event | Trigger | Key Fields |
|-------|---------|------------|
| `PruneApplied` | Prune apply completes | commit_sha, files_affected, hunks_removed, lines_removed |
| `TestRunStarted` | Test run begins | test_run_id |
| `TestRunCompleted` | Test run finishes | test_run_id, status, duration_ms |
| `ConflictResolved` | Conflict file resolved | file_path, remaining_conflicts |
| `BackMergeReverted` | Back-merge undone | reverted_commit, new_head |
| `AgentFixStarted` | Agent dispatched for conflict/test fix | job_id, agent_runner_type |
