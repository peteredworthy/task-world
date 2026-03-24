# Architecture: Module Consolidation

## Current State

`src/orchestrator/` contains 19 active modules plus dead shim files. Modules range from 2 files (~100 LOC) to 15+ files (~2,500 LOC). Several small modules (`cache/`, `artifacts/`, `repos/`, `metrics/`) serve a single consumer and add navigational overhead without meaningful boundaries. Six cross-layer coupling violations break clean layering.

**Current module structure (19 modules):**

| Module | Size | Primary Consumers | Notes |
|--------|------|-------------------|-------|
| `config/` | ~400 LOC | All modules | Foundation: enums, models, global config |
| `state/` | ~550 LOC | workflow, db, api | Domain: runtime models |
| `db/` | ~1,200 LOC | workflow, api, cli | Infrastructure: ORM, repositories |
| `git/` | ~800 LOC | workflow, runners, api | Infrastructure: worktrees, diffs |
| `envfiles/` | ~910 LOC | workflow, runners | Infrastructure: env file lifecycle |
| `workflow/` | ~2,500 LOC | api, runners, cli | Orchestration: engine, events, signals |
| `runners/` | ~1,800 LOC | api, workflow | Execution: agent protocol, executor |
| `api/` | ~2,000 LOC | (entry point) | Interface: routers, schemas |
| `cli/` | ~1,770 LOC | (entry point) | Interface: CLI commands |
| `routines/` | ~400 LOC | config, api, workflow | Routine discovery/loading — belongs in config/ |
| `review/` | ~300 LOC | api, git | Review models/test runner — belongs in git/ |
| `repos/` | ~250 LOC | api | Repo discovery — belongs in git/ |
| `cache/` | ~100 LOC | git | LRU cache — belongs in git/ |
| `artifacts/` | ~200 LOC | workflow, api | Artifact registry — belongs in workflow/ |
| `metrics/` | ~150 LOC | api | Cost calculation — belongs in api/ |
| `mcp/` | ~400 LOC | api | MCP server — belongs in api/ |
| `scaffolding/` | ~200 LOC | runners | Workspace setup — belongs in runners/ |
| `agents/` | ~350 LOC | api | Agent persona CRUD — belongs in runners/ |
| `routers/` | dead shim | none | Dead backward-compat shim — delete |

**6 anomalous couplings:**

```
C1: config/global_config.py → runners.nudger.NudgerConfig     (Foundation → Execution)
C2: git/diff_ops.py → review.models                           (Infrastructure → Domain)
C3: state/models.py → runners.action_log.ActionLog            (Domain → Execution)
C4: state/models.py → envfiles.models.EnvFileSpec             (Domain → Infrastructure)
C5: workflow/service.py → api/schemas/runs.RecoverResponse     (Orchestration → API)
C6: runners/agents/user_managed → workflow.service             (Execution → Orchestration)
```

## Proposed Changes

### Target Structure: 9 Modules

```
src/orchestrator/
├── config/          Foundation: enums, config models, routine loading
│   ├── __init__.py
│   ├── enums.py
│   ├── models.py        ← +NudgerConfig (C1), +EnvFileSpec (C4)
│   ├── global_config.py
│   └── routines/        ← absorbed from routines/
│       ├── discovery.py
│       ├── loader.py
│       └── versioning.py
│
├── state/           Domain: in-memory runtime models
│   ├── __init__.py
│   ├── models.py        ← +ActionLog (C3)
│   ├── factory.py
│   ├── session.py
│   └── errors.py
│
├── db/              Infrastructure: ORM, repositories, event store
│   ├── __init__.py
│   ├── orm/
│   │   ├── base.py
│   │   └── models.py
│   ├── access/
│   │   ├── connection.py
│   │   ├── repositories.py
│   │   └── event_store.py
│   └── recovery/
│       ├── event_journal.py
│       ├── journal_replay.py
│       ├── recovery.py
│       └── backup.py
│
├── git/             Infrastructure: worktrees, diffs, repos, review
│   ├── __init__.py
│   ├── worktree.py
│   ├── utils.py
│   ├── project_init.py
│   ├── errors.py
│   ├── ops/             ← branch, conflict, prune operations
│   │   ├── branch_ops.py
│   │   ├── conflict_ops.py
│   │   └── prune_ops.py
│   ├── diff/            ← absorbed from review/ + cache/
│   │   ├── models.py       ← CommitInfo, FileStatus, ModifiedFile (C2)
│   │   ├── diff_ops.py
│   │   ├── cached_diff_ops.py
│   │   └── lru_cache.py    ← absorbed from cache/
│   ├── repos/           ← absorbed from repos/
│   │   ├── models.py
│   │   ├── discovery.py
│   │   └── errors.py
│   └── testing/         ← absorbed from review/
│       └── test_runner.py
│
├── envfiles/        Infrastructure: env file lifecycle (unchanged)
│   ├── __init__.py
│   ├── models.py        ← EnvFileSpec removed (moved to config/)
│   ├── store.py
│   ├── lifecycle.py
│   ├── resolution.py
│   ├── security.py
│   ├── cleanup.py
│   └── tools.py
│
├── workflow/        Orchestration: state machine, events, signals
│   ├── __init__.py
│   ├── service.py       ← RecoveryResult replaces RecoverResponse (C5)
│   ├── locks.py
│   ├── completion.py
│   ├── dry_run.py
│   ├── engine/
│   │   ├── engine.py
│   │   ├── transitions.py
│   │   ├── gates.py
│   │   ├── grades.py
│   │   ├── condition_evaluator.py
│   │   └── errors.py
│   ├── events/
│   │   ├── types.py
│   │   └── logger.py
│   ├── signals/
│   │   ├── signals.py
│   │   ├── handlers.py
│   │   └── runtime.py     ← +NoTaskReason (from runners)
│   ├── agent/
│   │   ├── prompts.py
│   │   ├── templates.py
│   │   ├── context_builder.py
│   │   ├── clarifications.py
│   │   ├── auto_verify.py
│   │   └── summary_cache.py  ← +DEFAULT_SUMMARIZE_MODEL
│   └── artifacts/       ← absorbed from artifacts/
│       ├── models.py
│       └── registry.py
│
├── runners/         Execution: agent protocol, implementations, executor
│   ├── __init__.py
│   ├── interface.py
│   ├── types.py         ← +BroadcastCallback protocol
│   ├── errors.py
│   ├── executor.py      ← uses BroadcastCallback, not ConnectionManager
│   ├── agents/          ← agent implementations (unchanged)
│   │   ├── claude_cli/
│   │   ├── claude_sdk/
│   │   ├── codex/
│   │   ├── openhands/
│   │   ├── user_managed/  ← uses protocol, not WorkflowService (C6)
│   │   └── mock/
│   ├── execution/          ← already exists (no changes needed)
│   │   ├── phase_handler.py
│   │   ├── attempt_store.py
│   │   └── event_broadcaster.py  ← uses BroadcastCallback
│   ├── detection/
│   │   ├── detector.py
│   │   ├── profile_resolution.py
│   │   └── config_utils.py
│   ├── runtime/
│   │   ├── monitor.py
│   │   ├── nudger.py
│   │   ├── quota.py
│   │   └── repetition_detector.py
│   ├── profiles/        ← absorbed from agents/ (persona CRUD)
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── resolution.py
│   │   └── errors.py
│   └── scaffolding/     ← absorbed from scaffolding/
│       ├── copier.py
│       └── models.py
│
├── api/             Interface: FastAPI routers, schemas, MCP
│   ├── __init__.py
│   ├── app.py
│   ├── auth.py
│   ├── deps.py
│   ├── errors.py
│   ├── websocket.py
│   ├── routers/
│   ├── schemas/
│   ├── mcp/             ← absorbed from mcp/
│   │   ├── server.py
│   │   ├── tools.py
│   │   └── clarification_tools.py
│   └── metrics.py       ← absorbed from metrics/
│
└── cli/             Interface: CLI commands (unchanged)
    └── ...
```

### Coupling Resolutions

#### C1: NudgerConfig → config/models.py

**Current:** `config/global_config.py` imports `NudgerConfig` from `runners.nudger` (Foundation importing Execution).

**Fix:** Move `NudgerConfig` Pydantic model definition to `config/models.py`. Update `runners/nudger.py` to import from `config.models`. Update `global_config.py` to import from local `models.py`.

**Files changed:** `config/models.py`, `config/global_config.py`, `runners/nudger.py` (or `runners/runtime/nudger.py` after Phase 10).

#### C2: Review types → git/diff/models.py

**Current:** `git/diff_ops.py` imports `CommitInfo`, `FileStatus`, `ModifiedFile` from `review.models` (Infrastructure importing Domain).

**Fix:** Move the three type definitions to `git/diff/models.py`. Update `review/` consumers and `git/diff_ops.py`. After Phase 3, `review/` no longer exists, so all consumers import from `git`.

**Files changed:** New `git/diff/models.py`, `git/diff_ops.py`, all files that imported from `review.models`.

#### C3: ActionLog → state/models.py

**Current:** `state/models.py` imports `ActionLog` from `runners.action_log` (Domain importing Execution).

**Fix:** Move `ActionLog` class definition to `state/models.py`. Update all `runners.action_log` importers.

**Files changed:** `state/models.py`, `runners/action_log.py` (becomes re-import or is deleted), all `ActionLog` importers.

#### C4: EnvFileSpec → config/models.py

**Current:** `state/models.py` imports `EnvFileSpec` from `envfiles.models` (Domain importing Infrastructure).

**Fix:** Move `EnvFileSpec` to `config/models.py`. Update `envfiles/models.py` and `state/models.py` to import from `config`.

**Files changed:** `config/models.py`, `state/models.py`, `envfiles/models.py`, any other `EnvFileSpec` importers.

#### C5: RecoverResponse → workflow dataclass

**Current:** `workflow/service.py` imports `RecoverResponse` from `api/schemas/runs` (Orchestration importing API).

**Fix:** Define a `RecoveryResult` dataclass in `workflow/service.py` (or `workflow/types.py`). The API router translates `RecoveryResult` → `RecoverResponse` in the response.

**Files changed:** `workflow/service.py`, `api/routers/runs.py`.

#### C6: UserManagedAgent → protocol

**Current:** `runners/agents/user_managed/agent.py` imports `WorkflowService` directly (Execution importing Orchestration).

**Fix:** Define a callback protocol (e.g., `TaskSubmitCallback`) in `runners/types.py`. `UserManagedAgent` depends on the protocol. `WorkflowService` or a thin adapter is injected at startup via `api/deps.py`.

**Files changed:** `runners/types.py`, `runners/agents/user_managed/agent.py`, `api/deps.py` (injection wiring).

### Interface Narrowing (Phase 10)

After restructuring, these symbols become internal:

| Symbol | Current Location | Becomes | Reason |
|--------|-----------------|---------|--------|
| `RunWorkflow` | `workflow/signals/runtime.py` | `_RunWorkflow` (private) | Implementation detail of executor loop |
| `check_step_progression` | `workflow/transitions.py` | Internal to `workflow/engine/` | Expose via `WorkflowService.get_progression_status()` |
| `check_run_completion` | `workflow/transitions.py` | Internal to `workflow/engine/` | Expose via `WorkflowService` |
| `RunModel`, `StepModel`, etc. | `db/models.py` | Internal to `db/orm/` | External callers use repositories |
| `generate_id` | `state/models.py` | `state/_utils.py` | Utility, not domain concept |
| `GradeSnapshotItem` | `state/models.py` | `db/recovery/` | Used only by recovery code |
| `DEFAULT_SUMMARIZE_MODEL` | `config/models.py` | `workflow/agent/summary_cache.py` | Single consumer |
| `project_init.py`, `utils.py` | `git/` | Not in `git/__all__` | Internal utilities |
| `security.py` | `envfiles/` | Not in `envfiles/__all__` | Internal to lifecycle/store |
| `versioning.py` | `config/routines/` | Not in `config/__all__` | Internal to loader |
| `AGENT_CONFIG_FIELDS` | `runners/detector.py` | Not in `runners/__all__` | Leaky implementation detail |
| `ConnectionManager` | `api/websocket.py` | Not imported by `runners/` | Replace with `BroadcastCallback` protocol |

### Interactions

```
                    ┌──────────┐
                    │   cli/   │
                    └────┬─────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         ┌────▼────┐          ┌────▼────┐
         │  api/   │          │workflow/│
         │ +mcp    │◄────────►│+artifacts│
         │ +metrics│          └────┬────┘
         └────┬────┘               │
              │              ┌─────┴─────┐
              │              │           │
         ┌────▼────┐   ┌────▼────┐ ┌───▼───┐
         │runners/ │   │  git/   │ │  db/  │
         │+scaffold│   │+review  │ │       │
         │+profiles│   │+repos   │ │       │
         │         │   │+cache   │ │       │
         └────┬────┘   └────┬────┘ └───┬───┘
              │              │          │
         ┌────▼────┐   ┌────▼────┐     │
         │envfiles/│   │ state/  │◄────┘
         └─────────┘   └────┬────┘
                             │
                        ┌────▼────┐
                        │ config/ │
                        │+routines│
                        └─────────┘

Arrows show primary dependency direction (imports flow downward).
api/ and workflow/ have a bidirectional relationship (api calls workflow;
workflow events are consumed by api for WebSocket broadcasting).
```

**Layering rules after consolidation:**
- `config/`, `state/` — Foundation/Domain. No upward imports.
- `db/`, `git/`, `envfiles/` — Infrastructure. Import from config/, state/ only.
- `workflow/` — Orchestration. Imports from infrastructure + foundation.
- `runners/` — Execution. Imports from workflow/, infrastructure, foundation.
- `api/`, `cli/` — Interface. Import from everything below.
- No layer imports from a layer above it (enforced by `__all__` + code review, future lint rule).

## Technology Choices

| Choice | Option Selected | Alternatives Considered | Rationale |
|--------|----------------|------------------------|-----------|
| Migration strategy | Phase-by-phase with full test suite after each | Big-bang single commit; automated codemods | Phases are independently verifiable; easier to bisect failures; lower risk |
| Shim policy | Zero tolerance — delete completely | Deprecation period with re-export shims | Intent explicitly requires no stubs; shims mask incomplete migrations |
| `__all__` enforcement | Manual declaration + code review | Runtime `__all__` generator; import linter | Manual is simplest; linter is a follow-up |
| BroadcastCallback | Protocol in `runners/types.py` | ABC; duck typing; direct injection | Protocol is Pythonic for structural subtyping; no inheritance required |
| Sub-package access | Top-level module imports only | Allow sub-package imports with deprecation warnings | Cleaner boundary; `__all__` makes the contract explicit |
| RunService/ReviewService extraction | Deferred | Include in this consolidation | ~800 LOC extraction is high risk; consolidation should stabilize first |

## Testing Strategy

### Per-Phase Verification

Every phase must pass all of the following before proceeding:

1. **`uv run pytest tests/unit/ -v`** — All unit tests pass
2. **`uv run pytest tests/integration/ -v`** — All integration tests pass
3. **`cd ui && npx vitest run`** — All frontend tests pass
4. **`cd ui && npx tsc --noEmit`** — TypeScript type check clean
5. **`cd ui && npx eslint src/`** — ESLint clean
6. **`cd ui && npx vite build`** — Frontend build passes
7. **`uv run pre-commit run --all-files`** — Pre-commit hooks pass
8. **Import verification** — `grep -r "from orchestrator.{deleted_module}" src/ tests/` returns zero results for any module deleted in that phase

### Completeness Verification (Critical)

After each phase, verify no stubs remain:

- **No re-export shims:** No file exists solely to `from new_location import X` and re-export it
- **No empty `__init__.py` with comments:** No `# moved to ...` comments in place of real code
- **No dead import paths:** `grep -rn "from orchestrator\." src/ tests/ | sort -u` shows only valid current paths
- **No orphan files:** `git status` shows deleted files for old locations, no untracked files in old locations
- **No `TODO: remove shim` or similar markers:** `grep -r "shim\|stub\|backward.compat\|deprecated" src/orchestrator/` returns zero matches (beyond legitimate uses)

### Regression Safety

- Tests that import from moved modules must be updated in the same phase as the source move
- Alembic migration files must be checked for stale imports (`grep -r "from orchestrator" alembic/`)
- `scripts/` directory must be checked for stale imports
- Conftest files must be checked for stale imports and fixtures

## Security & Performance Considerations

### Security

- No behavioral changes — consolidation is purely structural
- Import path changes don't affect runtime behavior
- `__all__` narrowing reduces the attack surface by hiding internal implementation details
- `BroadcastCallback` protocol prevents runners from accessing arbitrary WebSocket methods

### Performance

- No runtime performance impact — Python import resolution happens once at startup
- Reducing module count from 19 to 9 marginally reduces import graph complexity
- `__all__` has no runtime cost (it's only consulted by `from module import *`)
- Sub-package structure adds negligible import overhead (one extra `__init__.py` per level)
