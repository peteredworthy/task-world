# Step Plan: Rename "Agents" to "Agent Runners" (Backend)

## Purpose

Programmatic rename of all backend Python references from "Agent" to "AgentRunner" using `rope` for Python files + manual find-replace for non-Python files (YAML, docs, SQL). This establishes the naming foundation that all subsequent steps build on.

## Prerequisites

- None -- this is the first step with no dependencies.

## Functional Contract

### Inputs

- Existing codebase with `Agent`, `AgentType`, `AgentExecutor`, `AgentInfo`, `AgentOption`, `AgentQuota` naming throughout `src/orchestrator/agents/`
- Existing API router `routers/agents.py` serving `GET /api/agents`
- Existing DB model with `RunModel.agent_type`, `RunModel.agent_config`, `RunModel.agent_started_at` columns
- Existing enum `AgentType` in `config/enums.py`

### Outputs

- Directory `src/orchestrator/agents/` renamed to `src/orchestrator/runners/`
- All Python classes renamed with `AgentRunner` prefix: `AgentRunnerType`, `AgentRunner` (protocol), `AgentRunnerInfo`, `AgentRunnerExecutor`, `AgentRunnerOption`, `AgentRunnerQuota`, etc.
- API router `routers/runners.py` serving `GET /api/agent-runners`
- DB columns renamed via Alembic migration: `runner_type`, `runner_config`, `runner_started_at`
- Enum `AgentRunnerType` in `config/enums.py`
- All imports and references updated across `executor.py`, `engine.py`, `service.py`, `deps.py`, `app.py`
- Non-Python files (YAML, docs, templates) updated via manual find-replace

### Error Cases

- Rope misses references in strings, YAML, templates -- mitigated by grep verification after each pass
- Alembic migration fails on existing DB -- migration must handle column rename without data loss
- Import cycles introduced by directory rename -- verify all imports resolve correctly

## Tasks

1. Use rope to rename Python classes: `AgentType` -> `AgentRunnerType`, `Agent` protocol -> `AgentRunner`, `AgentInfo` -> `AgentRunnerInfo`, `AgentExecutor` -> `AgentRunnerExecutor`, etc.
2. Rename directory `src/orchestrator/agents/` -> `src/orchestrator/runners/`
3. Rename `routers/agents.py` -> `routers/runners.py`, update endpoint paths to `/api/agent-runners`
4. Rename schemas: `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, etc.
5. Create Alembic migration to rename DB columns: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`, `agent_started_at` -> `runner_started_at`
6. Rename enum values in `config/enums.py`
7. Update all imports in `executor.py`, `engine.py`, `service.py`, `deps.py`, `app.py`
8. Update routine config models (`config/models.py`) -- field names referencing agents
9. Manual find-replace for non-Python files (YAML, templates, docs). Grep-verify after each pass
10. Run full test suite, fix failures

## Verification Approach

### Auto-Verify

- All existing backend tests pass with renamed imports (330+ unit, 235+ integration)
- `grep -r "AgentType\b" src/` returns no hits (old naming eliminated from Python source)
- `grep -r "agent_type" src/orchestrator/db/models.py` returns no hits (DB column renamed)

### Manual Verification

- `GET /api/agent-runners` returns runner list with correct schema
- A run can be created and started using the new API paths
- Alembic migration applies cleanly on existing DB

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M1 specification
- Architecture: `docs/agent-runners2/architecture.md` -- renamed file structure, API changes
- Clarification Q2: Use prefixed names (`AgentRunner`, `AgentRunnerType`, `AgentRunnerExecutor`)
- Clarification Q3: Alembic migrations only (production-grade)
- Clarification Q4: Use rope for Python + manual for non-Python
- Current agents directory: `src/orchestrator/agents/`
- Current router: `src/orchestrator/api/routers/agents.py`
- Current enums: `src/orchestrator/config/enums.py`
