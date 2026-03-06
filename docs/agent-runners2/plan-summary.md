# Execution Summary: Agent-Runners, Model Profiles, and Agents Refactor

## Intent Satisfaction

All 11 completion criteria from the intent document are addressed by the 8-step plan:

| # | Criterion | Covered By |
|---|-----------|------------|
| 1 | Rename backend "agent" to "agent-runner" with prefixed names | Step 1 |
| 2 | Rename frontend references, routes, labels | Step 2 |
| 3 | Model Profiles: CRUD, DB, per-runner defaults, all 4 profiles | Steps 3-4 |
| 4 | Agents (Planner, Builder, Verifier): CRUD, prompts, profile association, factory reset | Steps 5, 7 |
| 5 | Planner is user-assignable only (no engine integration) | Step 5 |
| 6 | Routine YAML: `*_agent` fields with cascading at routine/step/task | Step 6 |
| 7 | Per-run model-profile overrides | Steps 3-4 (run creation) |
| 8 | All existing tests pass | Every step ends with test verification |
| 9 | System works end-to-end at every milestone | Each step preserves working state |
| 10 | No orphaned "agent" references in runner context | Steps 1-2 (grep verification) |
| 11 | All schema changes use Alembic migrations | Steps 1, 3, 5 |

## Ordered Step List

| Step | Title | Tasks | Key Deliverable |
|------|-------|-------|-----------------|
| 1 | Rename "Agents" to "Agent Runners" (Backend) | 6 | Backend uses `AgentRunner*` naming; Alembic migration renames DB columns; API at `/api/agent-runners` |
| 2 | Rename "Agents" to "Agent Runners" (Frontend) | 4 | Frontend types, components, routes, labels all use "Agent Runner"; route at `/agent-runners` |
| 3 | Model Profiles (Backend + DB) | 4 | `ModelProfile` enum (4 profiles), `runner_profile_defaults` table, profile API endpoints, execution wiring |
| 4 | Model Profiles (Frontend) | 3 | Profile-to-model configuration UI on each runner card |
| 5 | Agents Concept (Backend + DB) | 4 | `agent_configs` table, Agent CRUD API at `/api/agents`, 3 seeded defaults with factory prompt reset |
| 6 | Routine Schema Update | 3 | `planner_agent`/`builder_agent`/`verifier_agent` fields at routine/step/task; cascading resolution; prompt composition |
| 7 | Agents UI | 4 | Agents management page at `/agents` with CRUD, prompt editor, profile selector |
| 8 | Integration Testing and Polish | 4 | E2E lifecycle tests, browser verification, documentation updates |

**Total: 8 steps, 32 tasks**

## Key Decisions

Decisions confirmed via clarifications (all answered by user):

1. **Planner agent** -- user-assignable only; no planning phase added to workflow engine (Q1).
2. **Python naming** -- prefixed names throughout: `AgentRunner`, `AgentRunnerType`, `AgentRunnerExecutor` (Q2).
3. **Database migrations** -- Alembic only, no DB recreation fallback (Q3).
4. **Refactoring tool** -- `rope` for Python AST-level renames + manual find-replace for non-Python files (Q4).
5. **Model overrides** -- per-run profile overrides (not single-model override) when creating a run (Q5).
6. **Prompt composition** -- simple concatenation: agent system prompt + separator + task prompt (Q6).
7. **Factory defaults** -- store separately; users can reset edited prompts to factory defaults (Q7).
8. **All 4 profiles** -- ARCHITECT, DESIGNER, CODER, SUMMARIZER included from start (Q8).
9. **Frontend routes** -- `/agent-runners` for runners, `/agents` for new agents concept (Q9).
10. **Scope** -- no additions or removals from the original intent (Q10).

## Risks and Mitigations

### High Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| `rope` incompatible with Python 3.12+ or Protocol classes | Blocks Step 1 entirely | Fallback to manual `sed` + grep verification. Add early environment check. |
| Alembic autogenerate sees drop+create instead of column rename | Data loss on migration | Write migration manually with `batch_alter_table()` for SQLite. Do not rely on autogenerate for renames. |
| Over-broad "agent" rename catches `agent_metadata`, `on_agent_metadata`, `agent_id` | Breaks execution callbacks and lock manager | Maintain explicit exclusion list of terms that must NOT be renamed. |
| Frontend field names not updated to match renamed API response | Runtime errors across UI | Explicit field rename checklist: `agent_type`->`runner_type`, `agent_config`->`runner_config`, `agent_started_at`->`runner_started_at`. |

### Medium Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| `parsers/` subdirectory imports missed during rename | Import errors at runtime | Enumerate all files under `agents/parsers/` and update explicitly. |
| Frontend components may be inline (not separate files) | `git mv` fails; wrong rename approach | Check structure with grep before renaming; rename within file if inline. |
| Seed script creates duplicate agents on re-run | DB integrity issues | Use upsert pattern (check by name, update if exists). |
| E2E tests require a running agent runner | Tests can't complete lifecycle | Use `USER_MANAGED` runner type and simulate callbacks via API. |
| `VITE_API_PORT` may not be supported in vite.config.ts | Browser testing on wrong port | Verify vite config supports port override before relying on it. |

### Low Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| "Agent Runners" vs "Agents" naming confusion in sidebar | UX confusion | Use distinct icons and consider descriptive subtitles. |
| Routine YAML `agent_type` field rename breaks user routines | Backward compatibility | New `*_agent` fields are additive; existing routines work unchanged with defaults. |

## Caveats for Execution

1. **Step 1, Task 4 (Alembic migration)** -- The step file still references `--autogenerate` for column renames. Builders must write the migration manually using `op.batch_alter_table()` for SQLite compatibility and check ALL tables containing `agent_type` columns, not just `runs`.

2. **Step 1, Task 5 (non-Python rename)** -- Must maintain an exclusion list: `agent_metadata`, `on_agent_metadata`, `AgentMetadataCallback`, `agent_id` (lock manager). These are generic agent concepts, not runner-specific.

3. **Step 2, Task 1 (file path)** -- `agentConfigUtils.ts` may be at `ui/src/components/` not `ui/src/lib/` as documented. Builders should verify the actual path before attempting `git mv`.

4. **Step 5, Task 3 (default prompts)** -- No concrete prompt text is provided for the 3 seeded agents. Builders must draft reasonable default prompts for Planner, Builder, and Verifier, or reference existing prompt templates in the codebase.

5. **Step 6, Task 2 (phase names)** -- The codebase may use "building"/"verifying" or "BUILDING"/"VERIFYING" rather than "build"/"verify". Builders should grep for exact phase strings before implementing cascading resolution.

6. **Step 8 (browser verification)** -- No health check polling is specified before browser navigation. Add a wait-for-ready check against backend (`/health`) and frontend before starting Playwright verification.

7. **Non-breaking execution** -- Each step MUST leave the system in a runnable state. If a step breaks routine execution, fix it before proceeding. Run the full test suite at the end of every step, not just the targeted tests.

8. **Consolidated task counts** -- Step files consolidate the detailed step plans (65 tasks total) into 32 coarser tasks. All functionality is preserved but builders should reference the detailed step plans (`step-0N-plan.md`) when the consolidated task descriptions are ambiguous.
