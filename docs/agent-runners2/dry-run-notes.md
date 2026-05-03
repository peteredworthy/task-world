# Dry-Run Simulation Notes

Simulation of execution across all 8 steps. For each step, we walk through tasks in order capturing assumptions, expected outputs, blockers, and failure modes.

---

## Per-Step Simulation Results

### Step 1: Rename "Agents" to "Agent Runners" (Backend)

#### Task 1: Rename Python Classes with Rope

**Assumptions:**
- `rope` is not currently installed (confirmed: `uv run pip show rope` returns nothing)
- `rope` can handle renaming a Protocol class (`Agent` in `interface.py`) and an Enum class (`AgentType` in `enums.py`)
- Rope's rename scope covers all files under `src/`

**Expected Outputs:**
- All `Agent*` classes renamed to `AgentRunner*` in Python source
- Import statements auto-updated by rope

**Blockers & Mitigation:**
- **`Agent` is a very common token.** Rope renames at the AST level so it should only rename the specific class, but if any file uses `Agent` as a local variable or string, rope may either miss it (good) or incorrectly rename it (bad). **Mitigation:** The task includes grep verification.
- **Rope may not handle Protocol classes well.** Protocol is a structural typing concept; rope may not trace all usages since they don't inherit from Agent. **Mitigation:** Manual grep after rope to catch stragglers.
- **`rope` compatibility with Python 3.12.** The project likely uses Python 3.12+. Rope has had issues with newer Python versions. **Mitigation:** Add an early environment check: `uv run python -c "import rope; print(rope.VERSION)"` after install.

#### Task 2: Rename Directory and Files

**Assumptions:**
- `git mv` will preserve history
- No circular imports will be introduced
- There are ~30+ files importing from `orchestrator.agents`

**Expected Outputs:**
- `src/orchestrator/runners/` exists with all modules
- All import paths updated

**Blockers & Mitigation:**
- **Massive import update.** 30+ files import from `orchestrator.agents.*`. Agent must update every one. **Mitigation:** Use `grep -rn "from orchestrator.agents" src/` to enumerate all, then find-replace.
- **`__pycache__` artifacts.** Old `.pyc` files under `agents/__pycache__` may confuse Python. **Mitigation:** Add `find . -name __pycache__ -exec rm -rf {} +` after directory rename.
- **`parsers/` subdirectory.** The `agents/parsers/` subdirectory has its own `__init__.py` with internal imports. All must be updated. Task instructions don't explicitly mention this subdirectory. **Gap identified.**

#### Task 3: Rename Schemas and Update API Endpoints

**Assumptions:**
- Schema classes like `AgentOption`, `AgentQuota`, `AgentConfigField` exist in `agents/types.py` (confirmed)
- `CreateRunRequest` and `RunResponse` have `agent_type`/`agent_config` fields (confirmed in `schemas/runs.py`)

**Expected Outputs:**
- All schema classes renamed, endpoint prefix changed

**Blockers & Mitigation:**
- **Frontend still calls `/api/agents`.** At this point frontend hasn't been updated yet, so the running system is broken until Step 2. **Mitigation:** This is expected per the milestone design -- system works at API level but UI needs Step 2.
- **JSON field name changes.** `agent_type` -> `runner_type` in request/response bodies is a breaking API change. The task mentions evaluating Pydantic aliases but doesn't mandate it. **Gap: Need to decide if we use aliases for backward compatibility or accept the breaking change.**

#### Task 4: Create Alembic Migration for DB Column Renames

**Assumptions:**
- Alembic is set up (confirmed: `alembic.ini` exists, migrations directory has 10 existing versions)
- SQLite supports `ALTER TABLE ... RENAME COLUMN` (supported since SQLite 3.25.0, 2018)
- Alembic's `--autogenerate` will detect column renames as renames, not drop+create

**Expected Outputs:**
- Migration file in `src/orchestrator/db/migrations/versions/`
- Column renames applied cleanly

**Blockers & Mitigation:**
- **Alembic autogenerate does NOT detect column renames.** It sees a dropped column + new column instead. The task says to use `--autogenerate` then edit, but an agent may not know this. **Critical gap: Task must explicitly state to write the migration manually with `op.alter_column(... new_column_name=...)` rather than relying on autogenerate.**
- **SQLite `alter_column` limitations.** Alembic's `op.alter_column` with `new_column_name` on SQLite requires batch mode (`with op.batch_alter_table()`). Standard ALTER TABLE RENAME COLUMN works in raw SQLite, but Alembic's abstraction may not use it directly. **Gap: Task should specify using `batch_alter_table` for SQLite compatibility.**
- **`agent_type` appears in TWO tables.** `db/models.py` grep shows `agent_type` in `RunModel` and possibly another model. The task only mentions `runs` table. **Gap: Need to verify all tables with `agent_type` columns.**
- **Async SQLAlchemy driver.** The project uses `sqlite+aiosqlite`. Alembic migrations may need async config. **Mitigation:** Check existing migrations to see how they handle this.

#### Task 5: Update Config Models, Engine, and Non-Python Files

**Assumptions:**
- `config/models.py` has fields like `agent_type` that need renaming
- YAML routines reference `agent_type` in their configs
- Docs files have "agent" references

**Expected Outputs:**
- All remaining references cleaned up

**Blockers & Mitigation:**
- **Routine YAML `agent_type` is a user-facing field.** Renaming it to `runner_type` in YAML files changes the routine schema. Existing user routines would break. **Gap: Need backward compatibility -- either support both field names or don't rename in YAML.**
- **"agent" appears in many legitimate contexts.** For example `agent_metadata`, `on_agent_metadata` callback, `AgentMetadataCallback`. These should NOT be renamed because they refer to the generic concept, not the specific class. The task's grep patterns are too broad. **Gap: Need explicit exclusion list for terms that should NOT be renamed.**

#### Task 6: Run Full Test Suite and Fix Failures

**Assumptions:**
- After all renames, many tests will have broken imports
- Test files reference old class names and import paths

**Expected Outputs:**
- All 330+ unit and 235+ integration tests pass

**Blockers & Mitigation:**
- **Test fixtures and factories.** Tests likely create `Agent` objects or use `AgentType` enum values. All need updating. The volume of changes may be large (hundreds of occurrences across test files). **Mitigation:** Bulk find-replace in test directory.
- **Conftest files.** Shared fixtures in `conftest.py` files may reference old names. **Mitigation:** Include conftest files in the rename sweep.

---

### Step 2: Rename "Agents" to "Agent Runners" (Frontend)

#### Task 1: Rename Types and Utility Files

**Assumptions:**
- `ui/src/types/agents.ts` contains all agent-related type definitions
- `agentConfigUtils.ts` is in `ui/src/components/` (confirmed), not `ui/src/lib/` as the task says

**Expected Outputs:**
- `agentRunners.ts` type file, `agentRunnerConfigUtils.ts` utils file

**Blockers & Mitigation:**
- **File path mismatch.** Task says `ui/src/lib/agentConfigUtils.ts` but the actual file is at `ui/src/components/agentConfigUtils.ts`. **Gap: Task references wrong path. Agent will fail the `git mv` and need to locate the correct file.**
- **Component co-location.** Some agent components may be defined inline within the Agents page, not as separate files. The plan assumes separate files. **Mitigation:** Agent should check actual file structure first.

#### Task 2: Rename Page and Components

**Assumptions:**
- Page is at `ui/src/pages/Agents.tsx`
- Components may or may not be in separate files

**Expected Outputs:**
- Renamed page and components

**Blockers & Mitigation:**
- **Components may be inline.** Looking at the codebase, `AgentCard` doesn't appear as a standalone file -- it may be defined inside `Agents.tsx`. Similarly for `AgentQuotaBadge`, `AgentGuidancePanel`. The task assumes separate files to `git mv`. **Gap: If components are inline, the task needs different instructions (rename within file, not rename file).**
- **React Fast Refresh.** Per project memory, utility exports must be in separate files from components. Renaming may trigger Fast Refresh warnings if not careful. **Mitigation:** Already documented in MEMORY.md.

#### Task 3: Update Routes, API URLs, and UI Labels

**Assumptions:**
- Router config is likely in `App.tsx` or a dedicated router file
- API URLs are string literals throughout component files

**Expected Outputs:**
- Route at `/agent-runners`, API calls to `/api/agent-runners`

**Blockers & Mitigation:**
- **API URL in multiple places.** The agents API is called from the Agents page, CreateRunModal, AgentFixTestsModal, and potentially other review components. All must be updated. **Mitigation:** Grep for `/api/agents` across all frontend files.
- **`agent_type` in response types.** The frontend has `run.agent_type`, `run.agent_icon`, `run.agent_config` in RunCard and other components. These field names come from the API response, which was renamed in Step 1. **Gap: Frontend must update all field name references to match renamed API response fields (`runner_type`, `runner_config`).**

#### Task 4: Run Frontend Tests and Fix Failures

**Assumptions:**
- 221+ frontend tests exist, many will have broken imports after rename

**Expected Outputs:**
- All tests, TypeScript, ESLint, build pass

**Blockers & Mitigation:**
- **Snapshot tests.** If any tests use snapshot matching, the renamed strings will cause snapshot failures. **Mitigation:** Update snapshots.
- **Mock data.** Test fixtures likely include `agent_type` field names. Must update to `runner_type`. **Mitigation:** Grep test files for old field names.

---

### Step 3: Model Profiles (Backend + DB)

#### Task 1: Define ModelProfile Enum and DB Model

**Assumptions:**
- `enums.py` exists and can accept new enum (confirmed: `config/enums.py` doesn't exist as a separate file -- it's at `src/orchestrator/config/enums.py`)
- The project uses SQLAlchemy 2.0 mapped_column style (confirmed)

**Expected Outputs:**
- `ModelProfile` enum with 4 values
- `AgentRunnerModelProfileDefaultModel` SQLAlchemy model

**Blockers & Mitigation:**
- **Enum storage in SQLite.** SQLAlchemy's Enum type doesn't always work well with SQLite. May need to store as String and validate. **Mitigation:** Check how existing `AgentType` enum is stored in the DB model -- it uses `String`, not `Enum`.
- No significant blockers. This is straightforward additive work.

#### Task 2: Create Alembic Migration and Pydantic Schemas

**Assumptions:**
- Autogenerate will detect the new table correctly
- Alembic is properly configured for async

**Expected Outputs:**
- Migration file, Pydantic schemas

**Blockers & Mitigation:**
- **Alembic autogenerate may not detect Enum columns on SQLite.** If we use a native Enum type, autogenerate may produce incorrect DDL for SQLite. **Mitigation:** Use String type for enum columns as the existing models do.

#### Task 3: Create API Endpoints for Profiles

**Assumptions:**
- Router pattern follows existing codebase conventions

**Expected Outputs:**
- `GET /api/model-profiles`, `GET/PUT /api/agent-runners/{type}/model-profile-defaults`

**Blockers & Mitigation:**
- **Runner type path parameter validation.** The `{type}` parameter must match `AgentRunnerType` enum values. Need to validate and return 422 for invalid types. **Mitigation:** Task specifies this.
- **Session/dependency injection.** Must follow existing patterns for DB session injection. **Mitigation:** Reference existing routers.

#### Task 4: Wire Profiles into Execution and Write Tests

**Assumptions:**
- Execution context is modifiable to include profile resolution
- The current execution flow passes a model string; this needs to be changed to resolve through profiles

**Expected Outputs:**
- Profile-resolved model in execution context, new tests

**Blockers & Mitigation:**
- **Execution context changes ripple to all runners.** Changing how models are resolved affects `CLIRunner`, `OpenHandsRunner`, `ClaudeSdkRunner`, etc. Each must handle the new resolution path. **Gap: Task doesn't enumerate which runner implementations need changes. Should list them explicitly.**
- **Backward compatibility.** Runners that don't have profile defaults set must still work with their existing default model. **Mitigation:** Task specifies fallback to built-in default.

---

### Step 4: Model Profiles (Frontend)

#### Task 1: Add Profile Section to Runner Card

**Assumptions:**
- AgentRunnerCard exists after Step 2 rename
- Model selector component pattern exists in codebase

**Expected Outputs:**
- Profile configuration UI on each runner card

**Blockers & Mitigation:**
- **No existing model selector/combobox component.** The task says "match existing model selector patterns" but this may not exist. The Agents page may use a simple text input or dropdown. **Gap: Need to verify what UI components exist for model selection and whether a combobox is already available or needs to be created.**
- **State management complexity.** Each runner card needs to fetch, display, edit, and save 4 profile mappings. This is significant new UI state. **Mitigation:** Use TanStack Query with mutations.

#### Task 2: Write Frontend Tests for Profile UI

**Assumptions:**
- Test infrastructure supports mocking API calls (likely using MSW or similar)

**Expected Outputs:**
- Tests for profile section rendering and API interactions

**Blockers & Mitigation:**
- No significant blockers. Standard test writing.

---

### Step 5: Agents Concept (Backend + DB)

#### Task 1: Create AgentConfig DB Model and Migration

**Assumptions:**
- `src/orchestrator/agents/` directory was renamed to `runners/` in Step 1, so `agents/` is free to use for the new concept
- Alembic will correctly detect the new table

**Expected Outputs:**
- `AgentConfigModel` in `src/orchestrator/agents/models.py`
- Migration creating `agent_configs` table

**Blockers & Mitigation:**
- **Directory naming collision.** The original `agents/` was renamed to `runners/` in Step 1, but git may still have cached references or `.pyc` files. **Mitigation:** Clean `__pycache__` before creating new directory.
- **Unique constraint on `name`.** Need to handle case sensitivity (should "Builder" and "builder" be different agents?). **Gap: Task doesn't specify case sensitivity for agent names.**

#### Task 2: Create Schemas and CRUD Service

**Assumptions:**
- Standard CRUD patterns exist in codebase to follow

**Expected Outputs:**
- Pydantic schemas, CRUD service

**Blockers & Mitigation:**
- **Service transaction management.** Need to ensure DB sessions are properly managed. **Mitigation:** Follow existing service patterns.

#### Task 3: Create API Router and Seed Defaults

**Assumptions:**
- The new `GET /api/agents` endpoint won't conflict with the old one (old one was renamed to `/api/agent-runners` in Step 1)
- Seed script exists and can be extended

**Expected Outputs:**
- CRUD router, 3 seeded default agents

**Blockers & Mitigation:**
- **Seed script idempotency.** Running seed script multiple times should not create duplicate default agents. **Gap: Task doesn't specify idempotent seeding. Should use `INSERT OR IGNORE` or check-then-create pattern.**
- **Factory default prompts.** The task says to store default prompts but doesn't provide the actual prompt text. **Gap: Need to either provide prompt text or reference where to find it.**

#### Task 4: Write Tests for Agent CRUD

**Assumptions:**
- Test infrastructure supports async DB operations

**Expected Outputs:**
- Unit and integration tests for agent CRUD

**Blockers & Mitigation:**
- No significant blockers.

---

### Step 6: Routine Schema Update

#### Task 1: Add Agent Fields to Config Models

**Assumptions:**
- `config/models.py` uses Pydantic models for routine config (need to verify if these are Pydantic or dataclass)
- Fields are truly optional and won't break existing YAML parsing

**Expected Outputs:**
- 3 new optional fields at each level (routine, step, task)

**Blockers & Mitigation:**
- **YAML parser strictness.** If the YAML parser validates strictly against the model, unknown fields might error. Adding fields is fine but need to ensure no strict validation rejects them. **Mitigation:** Pydantic models with optional fields handle this naturally.

#### Task 2: Implement Cascading Resolution

**Assumptions:**
- Resolution is a pure function (no DB access) as specified
- Phase names are "build" and "verify"

**Expected Outputs:**
- `resolve_agent()` function with full cascade

**Blockers & Mitigation:**
- **Phase naming mismatch.** The existing codebase may use different phase names (e.g., "building", "verifying", "BUILDING", "VERIFYING"). **Gap: Need to verify exact phase name strings used in the codebase and match them in the resolution function.**

#### Task 3: Update Prompt Generation and Write Integration Tests

**Assumptions:**
- `GET /api/tasks/{id}/prompt` endpoint exists and can be modified
- The prompt endpoint has access to routine/step/task config

**Expected Outputs:**
- Agent-prefixed prompts, integration tests

**Blockers & Mitigation:**
- **DB access in prompt endpoint.** The resolution function returns an agent name, but looking up the agent's system_prompt requires a DB query. The prompt endpoint must gain DB session access if it doesn't have it. **Mitigation:** Check existing endpoint implementation.
- **Circular dependency.** Agent concept (Step 5) depends on Model Profiles (Step 3), and prompt generation depends on both. Need to ensure no import cycles. **Mitigation:** Keep agent resolution logic in a separate module.

---

### Step 7: Agents UI

#### Task 1: Create Agent Types and API Module

**Assumptions:**
- `ui/src/types/agents.ts` path is now free (was renamed to `agentRunners.ts` in Step 2)

**Expected Outputs:**
- TypeScript types and API module

**Blockers & Mitigation:**
- No significant blockers.

#### Task 2: Create Agents Page and Agent Components

**Assumptions:**
- Standard React patterns with TanStack Query
- Textarea sufficient for prompt editing (no need for code editor like Monaco)

**Expected Outputs:**
- Full Agents page with CRUD, prompt editor, profile selector

**Blockers & Mitigation:**
- **Prompt editing UX.** System prompts can be long (hundreds of lines). A basic textarea may have poor UX. **Gap: Should specify minimum textarea height and whether to use a code editor component.**
- **Profile selector options.** The dropdown needs to show ModelProfile enum values. These must be fetched from `GET /api/model-profiles`. **Mitigation:** Wire to the API created in Step 3.

#### Task 3: Add Route and Navigation, Write Tests

**Assumptions:**
- Router and sidebar components are modifiable

**Expected Outputs:**
- `/agents` route, sidebar link, tests

**Blockers & Mitigation:**
- **Sidebar ordering.** "Agent Runners" and "Agents" are similar names. Users may confuse them. **Gap: Consider adding subtitles or grouping in the sidebar (e.g., under a "Configuration" section).**

---

### Step 8: Integration Testing and Polish

#### Task 1: Write E2E Tests

**Assumptions:**
- All prior steps are complete and working
- E2E tests can create routines, runs, and verify prompt content programmatically

**Expected Outputs:**
- E2E tests for agent overrides and backward compatibility

**Blockers & Mitigation:**
- **E2E test environment setup.** Tests on non-default ports (8001/5174) need proper configuration. **Mitigation:** Task specifies ports.
- **Agent execution in E2E.** Full run lifecycle requires an actual agent runner to be available. If only USER_MANAGED is available, the E2E test needs to simulate the external agent callback. **Gap: Task doesn't specify which runner to use for E2E tests or how to handle agent execution.**

#### Task 2: Browser Verification with Playwright MCP

**Assumptions:**
- Playwright MCP is available and working
- Backend and frontend can be started on alternative ports

**Expected Outputs:**
- Visual verification of UI

**Blockers & Mitigation:**
- **Server startup timing.** Starting backend and frontend takes time. Agent needs to wait for services to be ready before navigating. **Gap: Add health check polling before browser verification.**
- **VITE_API_PORT environment variable.** The task assumes this env var configures the Vite proxy target. Need to verify this is actually implemented in `vite.config.ts`. **Gap: Verify Vite config supports this env var.**
- **Headless browser issues.** Playwright in headless mode may render differently. CSS/layout issues may not be caught. **Mitigation:** Task uses `--headless` flag as specified.

#### Task 3: Update Documentation

**Assumptions:**
- `AGENTS.md` and `docs/ARCHITECTURE.md` exist and need updates

**Expected Outputs:**
- Updated documentation reflecting the refactored architecture

**Blockers & Mitigation:**
- No significant blockers. Straightforward documentation update.

---

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Impact | Hardening Action |
|------|-------------|------------|--------|------------------|
| S1-T1 | `rope` incompatible with Python 3.12+ or fails on Protocol class | Medium | High (blocks all subsequent work) | Add env check: `uv add --dev rope && uv run python -c "import rope"`. Add fallback: if rope fails, use manual find-replace with `sed` + grep verification. |
| S1-T1 | `rope` renames `Agent` too broadly (catches unrelated uses) | Low | Medium | Grep for `Agent` before and after rope to diff changes. Review rope's change preview before applying. |
| S1-T2 | `parsers/` subdirectory imports not updated | High | Medium | Add explicit instruction: "Update `src/orchestrator/agents/parsers/` internal imports. This subdirectory has `__init__.py`, `base.py`, `claude_parser.py`, `codex_parser.py`, `openhands_parser.py` -- all need path updates." |
| S1-T4 | Alembic autogenerate sees drop+create instead of rename | High | High (data loss) | Replace autogenerate instruction with: "Write migration manually using `op.batch_alter_table('runs')` with `alter_column(..., new_column_name=...)`. Do NOT rely on autogenerate for column renames." |
| S1-T4 | SQLite `alter_column` requires batch mode | High | High | Add explicit instruction: "Use `op.batch_alter_table()` context manager for all SQLite column renames." |
| S1-T4 | `agent_type` exists in multiple tables (not just `runs`) | Medium | High | Add env check: `grep -rn "agent_type" src/orchestrator/db/models.py` and enumerate ALL tables needing column renames. |
| S1-T5 | Over-broad rename of "agent" catches agent_metadata, on_agent_metadata | High | Medium | Add exclusion list: "Do NOT rename: `agent_metadata`, `on_agent_metadata`, `AgentMetadataCallback`, `agent_id` (lock manager). These refer to the generic concept, not the runner-specific class." |
| S1-T5 | Routine YAML `agent_type` field rename breaks user routines | Medium | High | Clarify: keep `agent_type` as the YAML field name for backward compatibility, or add an alias that accepts both. |
| S2-T1 | `agentConfigUtils.ts` is at `ui/src/components/` not `ui/src/lib/` | High | Medium | Fix task to reference correct path: `ui/src/components/agentConfigUtils.ts`. |
| S2-T2 | Components are inline in `Agents.tsx`, not separate files | High | Medium | Add instruction: "First check if components are defined as separate files or inline within `Agents.tsx`. If inline, rename within the file instead of using `git mv`." |
| S2-T3 | Frontend field names (`agent_type`, `agent_config`) not updated to match API | High | High (runtime errors) | Add explicit instruction: "Update ALL response type fields: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`, `agent_started_at` -> `runner_started_at`, `agent_type_display` -> `runner_type_display`." |
| S3-T4 | Profile resolution changes affect all runner implementations | Medium | High | Enumerate affected runners: CLIAgent, OpenHandsAgent, ClaudeSdkAgent, CodexServerAgent, UserManagedAgent. Add instruction to update each. |
| S4-T1 | No existing combobox/model selector component | Medium | Medium | Add instruction: "Check for existing model selector patterns in CreateRunModal or AgentConfigForm. If none exists, create a reusable `ModelSelector` component." |
| S5-T3 | Seed script not idempotent (creates duplicates on re-run) | High | Medium | Add instruction: "Use upsert pattern (check by name, update if exists, create if not) for seed script idempotency." |
| S5-T3 | Factory default prompt text not provided | High | High (blocks task) | Add default prompt text to the task instructions or reference a file containing them. |
| S6-T2 | Phase name mismatch ("build" vs "building" vs "BUILDING") | Medium | Medium | Add env check: `grep -rn "phase\|status.*build\|status.*verif" src/orchestrator/` to discover exact phase/status strings used. |
| S7-T2 | Prompt textarea too small for long system prompts | Low | Low | Specify minimum textarea dimensions: "Use a resizable textarea with min-height of 200px." |
| S8-T1 | E2E test requires specific runner to be available | High | High | Specify: "Use USER_MANAGED runner type for E2E tests. Simulate agent callback using direct API calls to task endpoints." |
| S8-T2 | `VITE_API_PORT` env var not supported by vite.config.ts | Medium | Medium | Add env check: `grep -n "VITE_API_PORT\|API_PORT\|proxy" ui/vite.config.ts` to verify proxy configuration supports port override. |
| S8-T2 | No health check before browser navigation | High | Medium | Add instruction: "Poll `http://localhost:8001/health` and `http://localhost:5174` before starting browser verification. Timeout after 30 seconds." |

---

## Plan Changes Recommended

### Critical (must fix before execution)

1. **S1-T4: Rewrite Alembic migration instructions.** Remove `--autogenerate` for column renames. Replace with manual migration using `batch_alter_table()` for SQLite compatibility. Check ALL tables with `agent_type` columns, not just `runs`.

2. **S1-T5: Add exclusion list for "agent" terms.** Explicitly list terms that should NOT be renamed: `agent_metadata`, `on_agent_metadata`, `AgentMetadataCallback`, `agent_id` (lock manager), `AgentFixTestsModal` (frontend -- this is about agents fixing tests, will be renamed to use the new Agent concept in Step 7).

3. **S2-T1: Fix file path.** Change `ui/src/lib/agentConfigUtils.ts` to `ui/src/components/agentConfigUtils.ts`.

4. **S2-T3: Add field name update instructions.** Explicitly list all response/request field name changes that frontend must adopt: `agent_type` -> `runner_type`, `agent_config` -> `runner_config`, `agent_type_display` -> `runner_type_display`, `agent_icon` -> `runner_icon` (if applicable), `agent_started_at` -> `runner_started_at`.

5. **S5-T3: Provide default prompt text.** Either include prompt text in the task or create a reference file `docs/agent-runners2/default-prompts.md` with Planner, Builder, and Verifier default prompts.

6. **S5-T3: Specify idempotent seeding.** Add instruction for upsert-style seed that won't create duplicates.

### Important (reduce failure likelihood)

7. **S1-T1: Add rope fallback plan.** If rope fails to install or produce correct results, fall back to manual `sed` + grep across Python files. Add this as an explicit alternative approach.

8. **S1-T2: Mention parsers subdirectory.** Add explicit instruction to update `src/orchestrator/agents/parsers/` (5 files with internal imports).

9. **S2-T2: Check component structure first.** Add instruction: "Before renaming, run `grep -rn 'function Agent' ui/src/` to discover where components are defined. If inline, rename within file."

10. **S3-T4 & S6-T2: Add environment discovery checks.** Before implementing execution wiring and phase resolution, grep the codebase to discover exact variable names, phase strings, and execution context structure.

11. **S8-T1: Specify E2E test runner strategy.** Use USER_MANAGED runner and simulate callbacks via API. Don't require a real agent subprocess.

12. **S8-T2: Add health checks.** Poll health endpoints before browser verification.

### Nice to Have (improve robustness)

13. **All steps: Add checkpoint verification between tasks.** After each task, run `uv run python -c "import orchestrator"` (backend) or `npx tsc --noEmit` (frontend) as a quick smoke check before proceeding to the next task.

14. **S1-T5: Decide on routine YAML backward compatibility.** Either keep `agent_type` as an alias in YAML parsing or accept the breaking change and update all routine files. Document the decision.

15. **S4-T1: Verify model selector component exists.** Add an early check for existing combobox/model selector patterns before building the profile UI.

16. **S7-T3: Consider sidebar UX.** "Agent Runners" and "Agents" are confusable. Consider adding descriptive subtitles or grouping under a "Configuration" header.
