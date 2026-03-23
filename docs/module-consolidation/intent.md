# Module Consolidation Intent

This document describes the target module structure for `src/orchestrator/`. The goal is not
flattening — it is **coherence**. Each proposed module groups related concerns into a single
logical unit with explicit, narrow public interfaces and well-defined internal sub-groups.

The current state is 19 active modules (plus a dead shim). Several are tiny single-consumer
packages that add navigational overhead without adding meaningful boundaries. The target is
**9 modules**, each internally structured with sub-packages that reflect natural groupings.

---

## Guiding Principles

**Explicit interfaces via `__init__.py`**
Every module's top-level `__init__.py` declares `__all__` explicitly. Symbols not in `__all__`
are considered internal implementation details — callers outside the module must not import them
directly. This makes the public contract machine-checkable.

**Sub-packages for internal grouping, not for external access**
Sub-packages within a module (e.g. `workflow/engine/`) organise related files and may export
upward to the parent `__init__.py`, but external modules should import from the top-level module,
not from internal sub-packages. `from orchestrator.workflow import WorkflowService`, not
`from orchestrator.workflow.service import WorkflowService`.

**Resolve anomalous couplings before moving files**
The import audit found six coupling violations that break clean layering. These must be resolved
as part of any consolidation — moving files without fixing the underlying imports would just
relocate the mess.

---

## Anomalous Couplings to Resolve First

These cross-layer imports need to be fixed regardless of which consolidation moves are made.
They are ordered by ease of resolution.

| # | From | To | Symptom | Fix |
|---|------|----|---------|-----|
| C1 | `config/global_config.py` | `runners.nudger.NudgerConfig` | Foundation layer importing from Execution layer | Move `NudgerConfig` to `config/models.py` or define it locally in `global_config.py` |
| C2 | `git/diff_ops.py` | `review.models` (`CommitInfo`, `FileStatus`, `ModifiedFile`) | Infrastructure importing from Domain | Move those three types to `git/` (they are fundamentally git output types) |
| C3 | `state/models.py` | `runners.action_log.ActionLog` | Domain importing from Execution layer | Move `ActionLog` to `state/` (it is a domain concept representing recorded agent actions) |
| C4 | `state/models.py` | `envfiles.models.EnvFileSpec` | Domain cross-importing from Infrastructure | Move `EnvFileSpec` to `config/models.py` (it is a configuration declaration, not lifecycle logic) |
| C5 | `workflow/service.py` | `api/schemas/runs.RecoverResponse` | Orchestration importing from API layer | Define `RecoverResponse` in `workflow/` or use a plain dataclass; remove the API schema dependency |
| C6 | `runners/agents/user_managed/agent.py` | `workflow.service.WorkflowService` | Execution importing from Orchestration | Pass `WorkflowService` as a protocol/callback into `UserManagedAgent`; remove the direct import |

---

## Target: 9 Modules

```
config/         Foundation: enums, config models, routine loading
state/          Domain: in-memory runtime models
db/             Infrastructure: ORM, repositories, event store, recovery
git/            Infrastructure: worktrees, branch ops, diffs, review types, repo discovery
envfiles/       Infrastructure: env file lifecycle, snapshots, resolution
workflow/       Orchestration: state machine, events, signals, prompts
runners/        Execution: agent protocol, implementations, executor, agent profiles
api/            Interface: FastAPI routers, schemas, MCP server, cost metrics
cli/            Interface: CLI commands
```

---

## Module 1: `config/`

**Absorbs:** `routines/` (loader, discovery, versioning)

**Rationale:** Routines are the declarative configuration of what the system does. The config
module already defines `RoutineConfig`, `StepConfig`, `TaskConfig` — the schemas. The routines
module loads and discovers instances of those schemas. They answer the same question ("what is
the system configured to do?") and have no business being separate.

### Proposed internal structure

```
config/
├── __init__.py             ← public interface
├── enums.py                ← all runtime enums (unchanged)
├── models.py               ← all Pydantic config models (+ EnvFileSpec from C4)
├── global_config.py        ← GlobalConfig, load_global_config (NudgerConfig removed per C1)
└── routines/               ← absorbed from top-level routines/
    ├── __init__.py         ← re-exports discovery + loader symbols upward
    ├── discovery.py
    ├── loader.py
    └── versioning.py
```

### Public interface (`__all__`)

```python
# Enums
RunStatus, TaskStatus, AgentRunnerType, ModelProfile, Priority, GateType,
ChecklistStatus, MergeStrategy, RoutineSource, PhaseType

# Config models
RoutineConfig, StepConfig, TaskConfig, GateConfig, AutoVerifyConfig,
MCPServerConfig, FanOutConfig, DryRunConfig, ContextSource, EnvFileSpec

# Global config
GlobalConfig, load_global_config

# Routine I/O
discover_routines, discover_routines_in_repo, get_routine_from_repo,
load_routine_from_path, RoutineNotFoundError, RoutineValidationError
```

**Surface area reduction:** `versioning.py` (git SHA tracking for routines) is purely internal
to the loader — it should not be exported. `DEFAULT_SUMMARIZE_MODEL` (currently on
`config.models`) is consumed only by `workflow/summary_cache.py` and should be moved there.

---

## Module 2: `state/`

**No absorptions.** `state/` is already coherent and well-sized (~550 LOC).

**Dependency fix required:** After C3 and C4 are resolved, `state/models.py` will no longer
import from `runners` or `envfiles`. This makes `state` a true pure-domain layer with no
infrastructure dependencies.

### Proposed internal structure

```
state/
├── __init__.py             ← public interface
├── models.py               ← Run, TaskState, StepState, Attempt, ChecklistItem,
│                              HumanApproval, ActionLog (moved here per C3)
├── factory.py              ← create_run_from_routine
├── session.py              ← SessionStateManager
└── errors.py               ← RunNotFoundError, TaskNotFoundError, etc.
```

### Public interface (`__all__`)

```python
# Domain models
Run, TaskState, StepState, Attempt, ChecklistItem, HumanApproval, ActionLog

# Factory
create_run_from_routine

# State management
SessionStateManager

# Errors
RunNotFoundError, TaskNotFoundError, StepNotFoundError,
ChecklistItemNotFoundError, AttemptNotFoundError
```

**Surface area reduction:** `generate_id` is currently imported from `state.models` by
`workflow/service.py`. It is a utility, not a domain concept — move it to `state/_utils.py` or
inline it in `service.py`. `GradeSnapshotItem` is used only by `db/recovery.py`; since recovery
is internal to `db`, define `GradeSnapshotItem` in `db/` instead.

---

## Module 3: `db/`

**No absorptions.** `db/` is coherent as-is; the sub-grouping work is internal reorganisation.

### Proposed internal structure

```
db/
├── __init__.py             ← public interface (narrow — only what callers need)
├── orm/
│   ├── __init__.py
│   ├── base.py             ← SQLAlchemy Base
│   └── models.py           ← all ORM models
├── access/
│   ├── __init__.py
│   ├── connection.py       ← create_engine, create_session_factory, init_db
│   ├── repositories.py     ← RunRepository, AttemptRepository, etc.
│   └── event_store.py      ← EventStore
└── recovery/               ← used only by cli/ — largely internal
    ├── __init__.py
    ├── event_journal.py    ← JsonlEventJournal, resolve_default_journal_path
    ├── journal_replay.py   ← replay_journal_to_repository
    ├── recovery.py         ← state recovery logic (internal to journal_replay)
    └── backup.py           ← create_backup, restore_backup
```

### Public interface (`__all__`)

```python
# Primary data access (used by workflow, runners, api)
RunRepository, AttemptRepository, CheckpointRepository, EventStore

# Connection lifecycle (used by api/app.py and cli)
create_session_factory, init_db

# Recovery tooling (used only by cli commands)
replay_journal_to_repository, resolve_default_journal_path,
create_backup, restore_backup, BackupError
```

**Surface area reduction:** `RunModel`, `StepModel`, `TaskModel`, `AttemptModel`, `PendingSignalModel`,
`ClarificationRequestModel` are ORM internals that leak into callers. Current external consumers
(`runners/executor.py`, `api/routers/repos.py`, `workflow/signals.py`) are using ORM models
where they should be using repositories or domain models. After consolidation, only
`repositories.py` and `event_store.py` should be visible externally — raw ORM models become
`db.orm` sub-package internals.

The `Base` class from `db.base` is currently imported by `agents/models.py`. After the
`agents/` module is absorbed into `runners/`, this will live inside `runners/profiles/` and
can import from `db.orm.base` directly as an internal cross-module access.

`recovery.py` is called only by `journal_replay.py` — it is already effectively internal;
formalise this by placing it in the `recovery/` sub-package without re-exporting it from
`db/__init__.py`.

---

## Module 4: `git/`

**Absorbs:** `repos/`, `review/`, `cache/`

**Rationale:**
- `repos/` answers "what git repositories exist and what branches do they have?" — it is git
  introspection. Its only consumers are the API repo browser, MCP tools, and the CLI.
- `review/models.py` defines `CommitInfo`, `FileStatus`, `ModifiedFile` — types that describe
  the output of git operations. `git/diff_ops.py` already depends on them (coupling C2); moving
  them into `git/` resolves this.
- `review/test_runner.py` runs tests inside a git worktree. It belongs alongside worktree ops.
- `cache/` is an LRU cache used exclusively by `git/cached_diff_ops.py`.

### Proposed internal structure

```
git/
├── __init__.py             ← public interface
├── worktree.py             ← WorktreeManager (broad consumer, stays top-level)
├── utils.py                ← commit_uncommitted_changes, get_head_commit
├── project_init.py         ← project initialisation
├── errors.py               ← all git error types
├── ops/                    ← git write operations (mostly used by review router)
│   ├── __init__.py
│   ├── branch_ops.py       ← back_merge, merge_back, get_branch_status, revert_back_merge
│   ├── conflict_ops.py     ← conflict detection and resolution
│   └── prune_ops.py        ← selective change removal
├── diff/                   ← read-only inspection
│   ├── __init__.py
│   ├── models.py           ← CommitInfo, FileStatus, ModifiedFile, DiffScope (moved from review)
│   ├── diff_ops.py         ← DiffOps, GitDiffOps (resolves coupling C2)
│   ├── cached_diff_ops.py  ← CachedDiffOps
│   └── lru_cache.py        ← LRU cache (absorbed from cache/)
├── repos/                  ← repository discovery (absorbed from repos/)
│   ├── __init__.py
│   ├── models.py           ← RepoInfo, BranchInfo
│   ├── discovery.py        ← list_repos, get_repo, list_branches
│   └── errors.py           ← RepoNotFoundError
└── testing/                ← test execution in worktrees (absorbed from review/)
    ├── __init__.py
    └── test_runner.py      ← TestRunner, TestRunResult, TestRunStatus
```

### Public interface (`__all__`)

```python
# Worktree (broad consumer)
WorktreeManager

# Error types
BranchNotFoundError, DirtyWorkingTreeError, MergeConflictError,
WorktreeNotFoundError, GitCommandError

# Diff inspection
CommitInfo, FileStatus, ModifiedFile, DiffScope, CachedDiffOps

# Branch/merge operations
back_merge, merge_back, get_branch_status, revert_back_merge, BackMergeResult

# Conflict operations
get_conflicts, resolve_conflict_file, ConflictBlock, ConflictFile

# Prune operations
preview_prune, apply_prune, PruneSelection

# Repository discovery
list_repos, get_repo, list_branches, RepoInfo, BranchInfo, RepoNotFoundError

# Test execution
TestRunner, TestRunResult
```

**Surface area reduction:** The `diff/` and `ops/` sub-packages are almost exclusively consumed
by `api/routers/review.py`. A future `ReviewService` (see consolidation plan M11) would absorb
that router logic and become the sole external consumer of `git/ops` and `git/diff` — at that
point those sub-packages could become genuinely internal to git, visible only to the review
service. For now, exposing them from `git/__init__.py` is correct; the narrowing happens when
M11 is executed.

`project_init.py` and `utils.py` should not be exported — they are internal utilities consumed
by `worktree.py` and `workflow/service.py` respectively. After consolidation, `workflow/service.py`
should call `WorktreeManager` instead of `git.utils` directly.

---

## Module 5: `envfiles/`

**No absorptions.** `envfiles/` is already coherent and well-bounded (~910 LOC).

### Proposed internal structure

The files are already logically grouped; the only change is formalising the interface.

```
envfiles/
├── __init__.py             ← public interface
├── models.py               ← (EnvFileSpec moves to config/ per C4)
├── store.py                ← EnvFileStore, snapshot storage
├── lifecycle.py            ← EnvFileLifecycle, run/task hooks
├── resolution.py           ← resolve_env_specs
├── security.py             ← secret filtering (internal)
├── cleanup.py              ← EnvFileCleanup
└── tools.py                ← EnvFileToolExecutor
```

### Public interface (`__all__`)

```python
EnvFileLifecycle, EnvFileStore, EnvFileCleanup,
resolve_env_specs, EnvFileToolExecutor,
SnapshotNotFoundError, EnvFileNotFoundError
```

**Surface area reduction:** `security.py` is an internal implementation detail of `lifecycle.py`
and `store.py`. It should not be importable from `envfiles` directly. `models.py` becomes a
thin re-export shim (or is removed) after `EnvFileSpec` moves to `config/`.

---

## Module 6: `workflow/`

**Absorbs:** `artifacts/`

**Rationale:** `ArtifactRegistry` is produced during the workflow lifecycle and consumed by
`workflow/context_builder.py`. Its only other consumers (`api/routers/tasks.py` and
`runners/executor.py`) access it through the execution context, not as a first-class concept.
Moving it into `workflow/` gives it a natural home.

This is the largest and most complex module. The internal structure must be carefully layered
to keep the state machine logic pure and testable.

### Proposed internal structure

```
workflow/
├── __init__.py             ← public interface
│
├── engine/                 ← pure state machine (no I/O, no DB)
│   ├── __init__.py
│   ├── engine.py           ← WorkflowEngine (pure transitions, uses BufferingEmitter)
│   ├── transitions.py      ← state transition functions
│   ├── gates.py            ← checklist gate evaluation
│   ├── grades.py           ← grade threshold evaluation
│   ├── condition_evaluator.py ← step/task condition expressions
│   └── errors.py           ← GateBlockedError, InvalidTransitionError, etc.
│
├── events/                 ← event types and persistence
│   ├── __init__.py
│   ├── types.py            ← all WorkflowEvent subclasses (renamed from events.py)
│   └── logger.py           ← PersistentEventEmitter, BufferingEmitter (renamed from event_logger.py)
│
├── signals/                ← control plane
│   ├── __init__.py
│   ├── signals.py          ← WorkflowSignal enum, transports, _active_run_ids
│   ├── handlers.py         ← @signal_handler dispatch
│   └── runtime.py          ← RunWorkflow: executor loop
│
├── agent/                  ← agent interaction layer
│   ├── __init__.py
│   ├── prompts.py          ← generate_builder_prompt, generate_verifier_prompt
│   ├── templates.py        ← resolve_template, derive_output_path
│   ├── context_builder.py  ← TaskContextBuilder
│   ├── clarifications.py   ← ClarificationAnswer, ClarificationQuestion
│   ├── auto_verify.py      ← LocalAutoVerifyRunner
│   └── summary_cache.py    ← SummaryCache (DEFAULT_SUMMARIZE_MODEL moved here)
│
├── artifacts/              ← absorbed from top-level artifacts/
│   ├── __init__.py
│   ├── models.py
│   └── registry.py         ← ArtifactRegistry
│
├── service.py              ← WorkflowService — the primary public façade
├── locks.py                ← InMemoryLockManager, LockManager, TaskLockedError
├── completion.py           ← handle_run_completion (internal to service.py)
└── dry_run.py              ← DryRunExecutor (used by api and tests)
```

### Public interface (`__all__`)

```python
# Primary façade (18 external consumers)
WorkflowService

# Event system
WorkflowEvent,
RunStatusChanged, TaskStatusChanged, StepCompleted, StepSkipped, RunStepBackward,
ChecklistGateEvaluated, GradesEvaluated, AutoVerifyCompleted,
AgentChangedEvent, AgentDiedEvent, AgentOutputEvent, AgentErrorEvent,
TaskReverted, HealthCheckEvent,
FanOutSpawned, ChildSpawned, ChildCompleted, ChildFailed, FanOutCompleted,
ClarificationRequested, ClarificationResponded, ApprovalRequested, ApprovalDecision,
PruneApplied, TestRunStarted, TestRunCompleted, ConflictResolved,
BackMergeCompleted, BackMergeReverted, AgentFixStarted, AgentFixCompleted,
PersistentEventEmitter, BufferingEmitter

# Locking
LockManager, InMemoryLockManager, TaskLockedError, LockTimeoutError

# Signals
WorkflowSignal, SignalTransport, DbSignalTransport

# Agent interaction
ClarificationAnswer, ClarificationQuestion, LocalAutoVerifyRunner

# Errors
GateBlockedError, InvalidTransitionError, WorkflowError

# Utilities (dry run, used by api and tests)
DryRunExecutor
```

**Surface area reduction:**

`RunWorkflow` (from `runtime.py`) — currently exported and used by `runners/executor.py`. This
class is an implementation detail of how the executor drives the loop. It should become
`workflow.signals.runtime._RunWorkflow` (private) and the executor should receive it via
injection or a factory function rather than importing the class directly. This removes the
last reason for `runners` to reach inside `workflow/signals/`.

`check_step_progression` / `check_run_completion` from `transitions.py` — currently imported
directly by `api/routers/runs.py` and `runners/executor.py`. These are state machine queries
that belong on `WorkflowService`. Adding `service.get_progression_status()` or equivalent
removes these from the public interface entirely, and `transitions.py` becomes fully internal
to the `engine/` sub-package.

`generate_builder_prompt` / `generate_verifier_prompt` — currently imported by three external
places: `api/routers/tasks.py`, `api/routers/runs.py`, `runners/executor.py`. The API router
uses them to return prompts on `GET /tasks/{id}/prompt`. This is legitimate — prompts are
surfaced to external agents. Keep in `__all__`, but namespace them clearly as
`workflow.generate_builder_prompt`.

`TaskContextBuilder`, `resolve_template`, `derive_output_path` — consumed by
`api/routers/tasks.py` and `runners/executor.py`. The runner usage is fine (it builds context
before calling an agent). The API usage (`tasks.py` router) is worth reviewing — if the router
only calls `TaskContextBuilder.build()` to return context in the prompt response, that logic
belongs in `WorkflowService.get_task_prompt()` and the context builder stays internal.

`completion.py` (`handle_run_completion`) — only called from `service.py`. Make it private
(`_completion.py`) and remove from `__all__`.

---

## Module 7: `runners/`

**Absorbs:** `scaffolding/`, `agents/` (the persona config CRUD module, not `runners/agents/`)

**Rationale:**
- `scaffolding/` is consumed by `runners/executor.py` alone. It sets up the workspace before
  agent execution. It belongs inside the execution pipeline.
- `agents/` (persona config CRUD) manages agent name/prompt/profile records. All its consumers
  are `api/routers/agents.py` and `api/app.py`. After consolidation, this becomes
  `runners/profiles/` — the configuration that says "which instructions and model profile should
  the Builder agent use" sits alongside the runner that actually uses them.

### Proposed internal structure

```
runners/
├── __init__.py             ← public interface
│
├── interface.py            ← AgentRunner protocol (canonical, unchanged)
├── types.py                ← ExecutionContext, ExecutionResult, callbacks, etc.
├── errors.py               ← AgentExecutionError, AgentNotAvailableError, AgentCancelledError
├── executor.py             ← AgentRunnerExecutor (primary public class)
│
├── agents/                 ← agent implementations (already in this location)
│   ├── __init__.py         ← discover(), register()
│   ├── claude_cli/
│   ├── claude_sdk/
│   ├── codex/
│   ├── openhands/
│   ├── user_managed/       ← after C6: no longer imports WorkflowService directly
│   └── mock/
│
├── execution/              ← shared execution infrastructure (already exists)
│   ├── __init__.py
│   ├── phase_handler.py    ← callback wiring
│   ├── attempt_store.py    ← attempt metrics persistence
│   └── event_broadcaster.py
│
├── detection/              ← runner discovery and configuration
│   ├── __init__.py
│   ├── detector.py         ← ToolDetector (consolidates detector.py + agent_detector.py)
│   ├── profile_resolution.py
│   └── config_utils.py
│
├── runtime/                ← lifecycle helpers
│   ├── __init__.py
│   ├── monitor.py          ← AgentRunnerMonitor
│   ├── nudger.py           ← Nudger, NudgerConfig (moves here per C1 fix)
│   ├── quota.py
│   ├── repetition_detector.py
│   └── action_log.py       ← ActionLog (but see note — may move to state/)
│
├── profiles/               ← absorbed from top-level agents/ (persona config CRUD)
│   ├── __init__.py
│   ├── models.py           ← AgentConfigModel ORM model
│   ├── schemas.py          ← AgentSchema, CreateAgentRequest, UpdateAgentRequest
│   ├── service.py          ← AgentService, seed_default_agents
│   ├── resolution.py       ← get_agent_system_prompt, resolve_agent_name
│   └── errors.py
│
└── scaffolding/            ← absorbed from top-level scaffolding/
    ├── __init__.py
    ├── copier.py
    └── models.py
```

**Note on backward-compat shims:** `openhands.py`, `openhands_docker.py`, `openhands_common.py`,
`codex_server.py`, `codex_server_common.py`, and the `parsers/` shims should be deleted as part
of this consolidation. All callers already import from the canonical `runners/agents/` paths.
The shims were introduced as a transition aid and that transition is complete.

`agent_detector.py` (legacy, zero consumers) should also be deleted.

### Public interface (`__all__`)

```python
# Execution
AgentRunnerExecutor, AgentRunnerMonitor

# Protocol and types
AgentRunner, ExecutionContext, ExecutionResult, AgentRunnerOption, AgentQuota

# Discovery
ToolDetector, AGENT_CONFIG_FIELDS, discover

# Errors
AgentExecutionError, AgentNotAvailableError, AgentCancelledError

# Agent profiles (absorbed from agents/)
AgentService, AgentSchema, CreateAgentRequest, UpdateAgentRequest,
seed_default_agents, get_agent_system_prompt, resolve_agent_name
```

**Surface area reduction:**

`ClaudeStreamParser` / `CodexStreamParser` are imported by `api/routers/tasks.py`. This is
unusual — an API router directly importing stream parsers. Investigate why and either remove
the import (likely unused) or move the functionality into `WorkflowService.get_task_prompt()`.

`AGENT_CONFIG_FIELDS` is a dict of field metadata used by `api/routers/runs.py` to expose
agent configuration to the frontend. This is a leaky implementation detail from the detector.
The right fix is an API-level schema (`AgentRunnerOption` already models this) — remove the
raw dict from the public interface.

`NudgerConfig` currently lives in `runners/nudger.py` and is imported by `config/global_config.py`
(coupling C1). After moving `NudgerConfig` to `config/models.py`, `nudger.py` imports it from
`config` instead. This resolves the downward coupling without changing any external callers.

`NoTaskReason` and `resolve_no_task_action` from `executor.py` are imported by
`workflow/runtime.py`. This is `runners` ↔ `workflow` circular coupling. These belong in
`workflow/` — move them to `workflow/signals/runtime.py` and remove from `runners`.

---

## Module 8: `api/`

**Absorbs:** `metrics/`, `mcp/`

**Rationale:** Both are exclusively mounted/used by `api/app.py`. `metrics/` calculates cost
for API responses. `mcp/` is an alternative transport (like WebSocket) for the same
orchestration tools. Both are interface-layer concerns.

### Proposed internal structure

```
api/
├── __init__.py             ← (empty or minimal; api is a consumer, not a provider)
├── app.py                  ← FastAPI factory, lifespan, startup recovery
├── auth.py                 ← JWT authentication
├── deps.py                 ← dependency injection
├── errors.py               ← exception handlers
├── websocket.py            ← ConnectionManager
├── routers/                ← (unchanged; 11 router files)
│   └── ...
├── schemas/                ← (unchanged; 10 schema files)
│   └── ...
├── mcp/                    ← absorbed from top-level mcp/
│   ├── __init__.py
│   ├── server.py           ← OrchestratorMCPServer
│   ├── tools.py
│   └── clarification_tools.py
└── metrics.py              ← absorbed from top-level metrics/ (single file)
```

**Reverse dependency cleanup:**
`runners/executor.py` and `runners/execution/event_broadcaster.py` currently import
`api/websocket.ConnectionManager`. This is a layer violation — the execution layer should not
import from the interface layer. Fix: define a `BroadcastCallback` protocol in `runners/types.py`
and inject the WebSocket manager as an instance at startup via `api/deps.py`. The executor holds
a reference to the protocol, not the concrete class.

`workflow/service.py` imports `api/schemas/runs.RecoverResponse` (coupling C5). Fix: define
a plain dataclass `RecoveryResult` in `workflow/` and translate it to `RecoverResponse` in the
router, keeping the schema concern in `api/`.

---

## Module 9: `cli/`

**No absorptions.** `cli/` is already self-contained and well-scoped (~1,770 LOC).

The CLI is a pure consumer of other modules. No other module imports from `cli/`. No structural
changes needed.

---

## Execution Order

The moves are ordered by risk and dependency:

| Phase | Work | Risk |
|-------|------|------|
| **0** | Resolve couplings C1–C6 (no file moves, import fixes only) | Low — no structural change |
| **1** | Delete dead code: `routers/` shim dir, `agent_detector.py`, `parsers/` shims, `openhands.py` etc. shims | Zero — verified zero consumers |
| **2** | Move `EnvFileSpec` → `config/models.py`; move `ActionLog` → `state/models.py` | Low — mechanical find/replace |
| **3** | Absorb `cache/` + `review/` + `repos/` into `git/` with internal sub-packages | Low — ~3 import paths each |
| **4** | Absorb `routines/` into `config/routines/` | Low — ~14 import paths, mechanical |
| **5** | Absorb `artifacts/` into `workflow/artifacts/` | Low — 3 import paths |
| **6** | Absorb `metrics/` + `mcp/` into `api/` | Low — 1–2 import paths each |
| **7** | Absorb `scaffolding/` + `agents/` (profiles) into `runners/` | Low — 3–5 import paths each |
| **8** | Restructure `workflow/` internals into engine/ events/ signals/ agent/ sub-packages | Medium — internal only, no external import changes |
| **9** | Restructure `db/` internals into orm/ access/ recovery/ sub-packages | Medium — internal only |
| **10** | Restructure `runners/` internals into detection/ runtime/ sub-packages | Medium — internal only |
| **11** | Narrow all `__init__.py` files to explicit `__all__` | Medium — systematic but safe |
| **12** | Extract RunService + ReviewService (reduces api router fan-out) | High — ~800 LOC to extract |

Phases 0–7 change file locations and import paths. Phases 8–11 change nothing externally but
improve internal clarity and enforce interface discipline. Phase 12 is the highest-value
single refactoring and can be done independently of the others.

---

## Interface Contracts Summary

After consolidation, the import discipline is:

```python
# ✓ Correct — import from module top-level
from orchestrator.workflow import WorkflowService, GateBlockedError
from orchestrator.db import RunRepository, init_db
from orchestrator.git import WorktreeManager, back_merge
from orchestrator.runners import AgentRunnerExecutor, ToolDetector

# ✗ Wrong — reaching into sub-packages
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow.engine.engine import WorkflowEngine
from orchestrator.db.orm.models import RunModel
from orchestrator.git.diff.diff_ops import GitDiffOps
```

The only exception is for module-internal imports — files within a module may import from
sibling sub-packages directly. A linting rule (`ruff` or a custom check) can enforce that no
file outside `orchestrator.X` imports from `orchestrator.X.Y` (sub-packages).
