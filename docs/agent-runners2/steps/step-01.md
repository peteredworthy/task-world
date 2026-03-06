# Step 1: Rename "Agents" to "Agent Runners" (Backend)

Programmatic rename of all backend Python references from "Agent" to "AgentRunner" using `rope` for Python files + manual find-replace for non-Python files. This establishes the naming foundation that all subsequent steps build on.

## Intent Verification
**Original Intent**: M1 from `docs/agent-runners2/plan.md` -- rename all backend "Agent" references to "AgentRunner" to free the "Agent" namespace for the new concept.
**Functionality to Produce**:
- Directory `src/orchestrator/agents/` renamed to `src/orchestrator/runners/`
- All Python classes renamed with `AgentRunner` prefix
- API endpoint path changed from `/api/agents` to `/api/agent-runners`
- DB columns renamed via Alembic migration
- All imports and references updated across the codebase
**Final Verification Criteria**:
- All backend tests pass (330+ unit, 235+ integration)
- `grep -r "class AgentType\b" src/` returns no hits
- `GET /api/agent-runners` returns runner list
- Alembic migration applies cleanly

---

## Task 1: Rename Python Classes with Rope

**Description**: Use `rope` to rename core Python classes from Agent* to AgentRunner* across the source tree. This is the bulk mechanical rename.

**Implementation Plan (Do These Steps)**
- [ ] Install rope: `uv add --dev rope`
- [ ] Use rope to rename `AgentType` -> `AgentRunnerType` in `config/enums.py`
- [ ] Use rope to rename `Agent` protocol -> `AgentRunner` in `agents/interface.py`
- [ ] Use rope to rename `AgentInfo` -> `AgentRunnerInfo`
- [ ] Use rope to rename `AgentExecutor` -> `AgentRunnerExecutor` in `agents/executor.py`
- [ ] Use rope to rename `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota` in schemas
- [ ] Run `grep -r "AgentType\b" src/` to verify no old references remain in Python

**Dependencies**
- None -- this is the first task

**References**
- `docs/agent-runners2/step-01-plan.md` -- Tasks 1, 4, 6
- `docs/agent-runners2/architecture.md` -- naming convention
- Clarification Q2: Use prefixed names (`AgentRunner`, `AgentRunnerType`)
- Clarification Q4: Use rope for Python + manual for non-Python

**Constraints**
- Only rename Python classes. Directory and file renames are separate tasks.
- Rope may miss string references -- these are caught in later tasks.

**Functionality (Expected Outcomes)**
- [ ] All Python classes use `AgentRunner` prefix
- [ ] All imports referencing old names are updated

**Final Verification (Proof of Completion)**
- [ ] `grep -rn "class AgentType" src/` returns no hits
- [ ] `grep -rn "class AgentExecutor" src/` returns no hits
- [ ] Python files parse without syntax errors

---

## Task 2: Rename Directory and Files

**Description**: Rename the `src/orchestrator/agents/` directory to `src/orchestrator/runners/` and rename `routers/agents.py` to `routers/runners.py`. Update all import paths.

**Implementation Plan (Do These Steps)**
- [ ] Rename directory: `git mv src/orchestrator/agents/ src/orchestrator/runners/`
- [ ] Rename router file: `git mv src/orchestrator/api/routers/agents.py src/orchestrator/api/routers/runners.py`
- [ ] Rename schema file if separate: `git mv src/orchestrator/api/schemas/agents.py src/orchestrator/api/schemas/runners.py` (if applicable)
- [ ] Update all `from orchestrator.agents.` imports to `from orchestrator.runners.`
- [ ] Update router registration in `app.py` to reference new module path
- [ ] Update endpoint path prefix from `/api/agents` to `/api/agent-runners` in the router

**Dependencies**
- [ ] Task 1 must be complete (class names already renamed)

**References**
- `docs/agent-runners2/step-01-plan.md` -- Tasks 2, 3
- `docs/agent-runners2/architecture.md` -- file structure after refactor

**Constraints**
- Use `git mv` to preserve git history
- Only change directory/file names and import paths, not class names (already done)

**Functionality (Expected Outcomes)**
- [ ] `src/orchestrator/runners/` directory exists with all runner modules
- [ ] `src/orchestrator/agents/` no longer exists
- [ ] Router serves at `/api/agent-runners` path
- [ ] All imports resolve correctly

**Final Verification (Proof of Completion)**
- [ ] `ls src/orchestrator/runners/` shows all runner modules
- [ ] `grep -rn "from orchestrator.agents" src/` returns no hits
- [ ] `grep -rn "orchestrator.agents" src/` returns no hits (except docs/comments)

---

## Task 3: Create Alembic Migration for DB Column Renames

**Description**: Create an Alembic migration to rename DB columns on the `runs` table: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`, `agent_started_at` -> `runner_started_at`.

**Implementation Plan (Do These Steps)**
- [ ] Generate a new Alembic migration: `alembic revision --autogenerate -m "Rename agent columns to runner"`
- [ ] Edit the migration to use `op.alter_column()` with `new_column_name` for each column rename
- [ ] Update SQLAlchemy model `RunModel` to use new column names: `runner_type`, `runner_config`, `runner_started_at`
- [ ] Update any Pydantic schemas referencing the old column names
- [ ] Test migration: `alembic upgrade head` on a fresh DB

**Dependencies**
- [ ] Task 1 must be complete (enum is already `AgentRunnerType`)

**References**
- `docs/agent-runners2/step-01-plan.md` -- Task 5
- `docs/agent-runners2/architecture.md` -- data model changes
- Clarification Q3: Alembic migrations only (production-grade)

**Constraints**
- Migration must handle column rename without data loss
- Must work on existing databases with data

**Functionality (Expected Outcomes)**
- [ ] Alembic migration file exists and is valid
- [ ] `RunModel` uses `runner_type`, `runner_config`, `runner_started_at` column names
- [ ] Migration applies cleanly on existing DB

**Final Verification (Proof of Completion)**
- [ ] `alembic upgrade head` succeeds
- [ ] `grep -rn "agent_type" src/orchestrator/db/models.py` returns no hits
- [ ] `grep -rn "agent_config" src/orchestrator/db/models.py` returns no hits

---

## Task 4: Update Config Models and Non-Python References

**Description**: Update routine config models (`config/models.py`) field names and all non-Python files (YAML, templates, docs) referencing the old naming.

**Implementation Plan (Do These Steps)**
- [ ] Update field names in `config/models.py` that reference "agent" in the runner sense
- [ ] Update all imports and references in `executor.py`, `engine.py`, `service.py`, `deps.py`, `app.py`
- [ ] Search and replace in YAML routine files: `agent_type` -> `runner_type` where appropriate
- [ ] Update any template strings or error messages referencing old names
- [ ] Run `grep -r "agent_type" src/` to verify no stale Python references remain
- [ ] Run `grep -r "AgentType" src/` to verify no stale enum references remain

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/agent-runners2/step-01-plan.md` -- Tasks 7, 8, 9
- `docs/agent-runners2/architecture.md` -- routine config models

**Constraints**
- Be careful not to rename "agent" references that refer to the new Agent concept (not yet implemented)
- YAML field renames must maintain backward compatibility with existing routine files

**Functionality (Expected Outcomes)**
- [ ] Config models use runner naming
- [ ] No stale "agent" references in the runner context remain in Python source
- [ ] Non-Python files updated

**Final Verification (Proof of Completion)**
- [ ] `grep -rn "agent_type" src/orchestrator/config/` returns no hits
- [ ] `grep -rn "AgentType" src/orchestrator/` returns no hits (except new AgentRunnerType)

---

## Task 5: Fix Tests and Verify Full Suite

**Description**: Run the full backend test suite, fix all failures caused by the rename, and verify everything passes.

**Implementation Plan (Do These Steps)**
- [ ] Run unit tests: `uv run pytest tests/unit/ -x`
- [ ] Fix any import errors or name mismatches in test files
- [ ] Run integration tests: `uv run pytest tests/integration/ -x`
- [ ] Fix any API path or schema mismatches in test files
- [ ] Run the full suite: `uv run pytest`
- [ ] Grep-verify: `grep -rn "AgentType\b" tests/` should only reference `AgentRunnerType`

**Dependencies**
- [ ] Tasks 1-4 must be complete

**References**
- `docs/agent-runners2/step-01-plan.md` -- Task 10
- Test baseline: 330+ unit, 235+ integration tests

**Constraints**
- All existing tests must pass -- no test deletions
- Only fix rename-related failures, don't refactor tests

**Functionality (Expected Outcomes)**
- [ ] All 330+ unit tests pass
- [ ] All 235+ integration tests pass (minus known skips)
- [ ] No stale "Agent" (in runner sense) references in test files

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest` exits with 0 failures
- [ ] `grep -rn "from orchestrator.agents" tests/` returns no hits
