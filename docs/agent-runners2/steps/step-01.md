# Step 1: Rename "Agents" to "Agent Runners" (Backend)

Programmatic rename of all backend Python references from "Agent" to "AgentRunner" using `rope` for Python files + manual find-replace for non-Python files (YAML, docs, SQL). This establishes the naming foundation that all subsequent steps build on.

## Intent Verification
**Original Intent**: Rename the current "agents" concept to "agent-runners" throughout the backend, freeing the "Agent" namespace for the new prompt+profile concept (see `docs/agent-runners2/intent.md`).
**Functionality to Produce**:
- Directory `src/orchestrator/agents/` renamed to `src/orchestrator/runners/`
- All Python classes use `AgentRunner` prefix: `AgentRunnerType`, `AgentRunner` protocol, `AgentRunnerInfo`, `AgentRunnerExecutor`, etc.
- API router serves `GET /api/agent-runners` instead of `GET /api/agents`
- DB columns renamed via Alembic migration: `runner_type`, `runner_config`, `runner_started_at`
- All imports and references updated across the codebase
- Non-Python files (YAML, docs, templates) updated

**Final Verification Criteria**:
- All backend tests pass (330+ unit, 235+ integration)
- `grep -r "AgentType\b" src/` returns no hits (old naming eliminated)
- `GET /api/agent-runners` returns runner list
- Alembic migration applies cleanly

---

## Task 1: Rename Python Classes with Rope

**Description**: Use the `rope` refactoring library to rename all core Python classes from `Agent*` to `AgentRunner*` across the backend source tree. This handles AST-level renames in Python files only.

**Implementation Plan (Do These Steps)**
- [ ] Install rope if not present: `uv add --dev rope`
- [ ] Write a rope refactoring script that renames:
  - `AgentType` -> `AgentRunnerType` in `src/orchestrator/config/enums.py`
  - `Agent` protocol -> `AgentRunner` in `src/orchestrator/agents/interface.py`
  - `AgentInfo` -> `AgentRunnerInfo` in `src/orchestrator/agents/interface.py`
  - `AgentExecutor` -> `AgentRunnerExecutor` in `src/orchestrator/agents/executor.py`
- [ ] Run the rope script and verify all Python imports updated
- [ ] Grep-verify: `grep -rn "class AgentType\b\|class Agent\b\|class AgentInfo\b\|class AgentExecutor\b" src/` returns no hits

**Dependencies**
- None -- this is the first task

**References**
- `docs/agent-runners2/plan.md` -- M1 step 1
- `docs/agent-runners2/architecture.md` -- renamed class names
- Clarification Q2: Use prefixed names (`AgentRunner`, `AgentRunnerType`, `AgentRunnerExecutor`)
- Clarification Q4: Use rope for Python + manual for non-Python
- Current source: `src/orchestrator/agents/`

**Constraints**
- Only rename Python classes in this task. Directory rename and file renames are separate tasks.
- Rope may miss string references -- those are caught in later tasks via grep.

**Functionality (Expected Outcomes)**
- [ ] All `Agent*` Python classes renamed to `AgentRunner*` equivalents
- [ ] All Python import statements updated to use new names
- [ ] No syntax errors in any Python file

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.agents.interface import AgentRunner; print('OK')"` succeeds
- [ ] `uv run python -c "from orchestrator.config.enums import AgentRunnerType; print('OK')"` succeeds
- [ ] `grep -rn "class AgentType\b" src/` returns no hits

---

## Task 2: Rename Directory and Files

**Description**: Rename `src/orchestrator/agents/` to `src/orchestrator/runners/` and rename `routers/agents.py` to `routers/runners.py`. Update all import paths.

**Implementation Plan (Do These Steps)**
- [ ] Rename directory: `git mv src/orchestrator/agents/ src/orchestrator/runners/`
- [ ] Rename router file: `git mv src/orchestrator/api/routers/agents.py src/orchestrator/api/routers/runners.py`
- [ ] Rename schema file if separate: `git mv src/orchestrator/api/schemas/agents.py src/orchestrator/api/schemas/runners.py`
- [ ] Update all import paths from `orchestrator.agents.*` to `orchestrator.runners.*`
- [ ] Update router registration in `app.py` to import from `routers.runners`
- [ ] Grep-verify: `grep -rn "from orchestrator.agents" src/` returns no hits

**Dependencies**
- [ ] Task 1 must be complete (class renames done before file moves)

**References**
- `docs/agent-runners2/architecture.md` -- file structure after refactor
- `docs/agent-runners2/plan.md` -- M1 steps 2-3

**Constraints**
- Use `git mv` to preserve git history
- Only rename files and update import paths. Do not change endpoint URLs yet.

**Functionality (Expected Outcomes)**
- [ ] `src/orchestrator/runners/` directory exists with all runner modules
- [ ] `src/orchestrator/api/routers/runners.py` exists
- [ ] All imports resolve correctly

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.runners.interface import AgentRunner; print('OK')"` succeeds
- [ ] `grep -rn "from orchestrator.agents\." src/` returns no hits

---

## Task 3: Rename Schemas and Update API Endpoints

**Description**: Rename Pydantic schema classes (`AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, etc.) and update endpoint paths from `/api/agents` to `/api/agent-runners`.

**Implementation Plan (Do These Steps)**
- [ ] Rename schema classes in `schemas/runners.py`: `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, `AgentConfigField` -> `AgentRunnerConfigField`
- [ ] Update endpoint prefix in `routers/runners.py` from `/api/agents` to `/api/agent-runners`
- [ ] Update all references to these schemas in service, deps, and router files
- [ ] Update `CreateRunRequest` / `RunResponse` schemas: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`

**Dependencies**
- [ ] Task 2 must be complete (files renamed)

**References**
- `docs/agent-runners2/architecture.md` -- API changes table, schema definitions
- `docs/agent-runners2/plan.md` -- M1 steps 3-4

**Constraints**
- Keep backward-compatible JSON field names if needed via Pydantic `alias` (evaluate whether external consumers exist)

**Functionality (Expected Outcomes)**
- [ ] `AgentRunnerOption`, `AgentRunnerQuota` schemas exist and are importable
- [ ] API endpoints respond at `/api/agent-runners` path
- [ ] Old `/api/agents` path no longer responds (or returns 404)

**Final Verification (Proof of Completion)**
- [ ] `grep -rn "class AgentOption\b\|class AgentQuota\b" src/` returns no hits
- [ ] `grep -rn '"/api/agents"' src/` returns no hits (only `/api/agent-runners`)

---

## Task 4: Create Alembic Migration for DB Column Renames

**Description**: Create an Alembic migration to rename columns on the `runs` table: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`, `agent_started_at` -> `runner_started_at`.

**Implementation Plan (Do These Steps)**
- [ ] Generate Alembic migration: `uv run alembic revision --autogenerate -m "Rename agent columns to runner"`
- [ ] Edit the migration to use `op.alter_column()` with `new_column_name` for each rename
- [ ] Update SQLAlchemy model `RunModel` in `db/models.py`: rename column definitions
- [ ] Test migration: `uv run alembic upgrade head` on a fresh DB
- [ ] Test downgrade: `uv run alembic downgrade -1` reverses the renames

**Dependencies**
- [ ] Tasks 1-3 should be complete so model references match new column names

**References**
- `docs/agent-runners2/plan.md` -- M1 step 4
- `docs/agent-runners2/architecture.md` -- modified tables section
- Clarification Q3: Alembic migrations only (production-grade)

**Constraints**
- Migration must be reversible (downgrade support)
- No data loss -- column rename only, not drop+create

**Functionality (Expected Outcomes)**
- [ ] Alembic migration file exists in `alembic/versions/`
- [ ] `runs` table columns renamed: `runner_type`, `runner_config`, `runner_started_at`
- [ ] Migration applies and reverses cleanly

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` completes without error
- [ ] `uv run alembic downgrade -1` completes without error
- [ ] `grep -rn "agent_type\|agent_config\|agent_started_at" src/orchestrator/db/models.py` returns no hits

---

## Task 5: Update Config Models, Engine, and Non-Python Files

**Description**: Update routine config models field names, engine/service/executor references, and manually find-replace "agent" references in non-Python files (YAML, docs, templates).

**Implementation Plan (Do These Steps)**
- [ ] Update `config/models.py`: rename any fields referencing `agent_type` or `agent_config` in routine config
- [ ] Update `engine.py`, `service.py`, `deps.py`, `app.py` -- any remaining `agent` references in variable names, log messages, comments
- [ ] Manual find-replace in YAML files (routines, examples): `agent_type` -> `runner_type` where applicable
- [ ] Update documentation files that reference old naming
- [ ] Grep-verify: `grep -rn "agent_type\|AgentType\|AgentExecutor\|AgentInfo" src/` returns no hits

**Dependencies**
- [ ] Tasks 1-4 must be complete

**References**
- `docs/agent-runners2/plan.md` -- M1 steps 6-9
- Current config: `src/orchestrator/config/models.py`
- Current engine: `src/orchestrator/engine.py`

**Constraints**
- Do not rename fields that will be used by the new "Agent" concept in M5
- Preserve any public API field names that external consumers depend on (use aliases if needed)

**Functionality (Expected Outcomes)**
- [ ] No orphaned `Agent` references (in the runner sense) remain in source
- [ ] Routine YAML files parse correctly with updated field names
- [ ] All log messages use "runner" terminology

**Final Verification (Proof of Completion)**
- [ ] `grep -rn "AgentType\b\|AgentExecutor\b\|AgentInfo\b" src/` returns no hits
- [ ] `uv run pytest tests/ -x --timeout=120` -- all tests pass
- [ ] A run can be created and started via API

---

## Task 6: Run Full Test Suite and Fix Failures

**Description**: Run the complete backend test suite, fix any failures caused by the rename, and verify the system is fully functional.

**Implementation Plan (Do These Steps)**
- [ ] Run unit tests: `uv run pytest tests/unit/ -v --timeout=60`
- [ ] Run integration tests: `uv run pytest tests/integration/ -v --timeout=120`
- [ ] Fix any import errors, assertion mismatches, or fixture references
- [ ] Verify API smoke test: start server, hit `GET /api/agent-runners`
- [ ] Final grep verification: no orphaned old naming in `src/` or `tests/`

**Dependencies**
- [ ] Tasks 1-5 must be complete

**References**
- `docs/agent-runners2/plan.md` -- M1 step 10, verification section
- Test baseline: 330+ unit, 235+ integration tests

**Constraints**
- All existing tests must pass (not just new ones)
- Do not skip or delete tests that fail due to rename -- fix them

**Functionality (Expected Outcomes)**
- [ ] All backend tests pass
- [ ] `GET /api/agent-runners` returns runner list
- [ ] A run can be created and started

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/ -v` -- all pass
- [ ] `uv run pytest tests/integration/ -v` -- all pass (except known openhands skip)
- [ ] `grep -rn "AgentType\b" src/ tests/` returns no hits
