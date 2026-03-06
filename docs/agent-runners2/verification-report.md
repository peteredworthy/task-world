# Verification Report: Agent-Runners Refactor

Cross-check of intent, plan, step plans, step files, architecture, clarifications, and dry-run notes for mutual consistency and execution readiness.

## 1. Intent-to-Plan Alignment

| Intent Scope Item | Plan Milestone | Aligned? |
|---|---|---|
| Rename "agents" to "agent-runners" (backend) | M1 | Yes |
| Rename "agents" to "agent-runners" (frontend) | M2 | Yes |
| Model Profiles (4 profiles, per-runner config) | M3 (backend), M4 (frontend) | Yes |
| Agents (Planner, Builder, Verifier) with CRUD | M5 (backend), M7 (frontend) | Yes |
| Planner agent: user-assignable, no engine integration | M5 (noted), confirmed by Clarification Q1 | Yes |
| Routine schema: `*_agent` fields with cascading | M6 | Yes |
| Per-run model-profile overrides | M3-M4 (partial), architecture doc | Yes -- resolution chain supports it, full implementation deferred to run creation |
| Non-breaking execution at every milestone | Plan states each milestone ends with working system | Yes |
| Alembic migrations exclusively | Plan + Clarification Q3 | Yes |
| Prefixed Python names (AgentRunner*) | Plan M1 + Clarification Q2 | Yes |
| Factory default prompts with reset | M5 + Clarification Q7 | Yes |
| All 4 profiles from start | M3 + Clarification Q8 | Yes |
| Frontend routes: /agent-runners, /agents | M2, M7 + Clarification Q9 | Yes |

**Result: Full alignment.** All intent scope items are covered by plan milestones. No plan milestones introduce work outside intent scope.

## 2. Plan-to-Step-Plans Alignment

| Plan Milestone | Step Plan File | Task Count | Aligned? |
|---|---|---|---|
| M1: Backend rename | step-01-plan.md | 10 tasks | Yes -- covers rope rename, directory, schemas, API, migration, config, non-Python, tests |
| M2: Frontend rename | step-02-plan.md | 8 tasks | Yes -- types, components, routes, API URLs, labels, tests |
| M3: Model Profiles backend | step-03-plan.md | 9 tasks | Yes -- enum, DB model, migration, schemas, API, execution wiring, tests |
| M4: Model Profiles frontend | step-04-plan.md | 6 tasks | Yes -- profile section UI, combobox, API wiring, tests |
| M5: Agents backend | step-05-plan.md | 9 tasks | Yes -- DB model, migration, schemas, service, API, seed, tests |
| M6: Routine schema | step-06-plan.md | 7 tasks | Yes -- config fields, cascading resolution, prompt generation, tests |
| M7: Agents UI | step-07-plan.md | 9 tasks | Yes -- types, API, page, card, editor, routes, nav, tests |
| M8: Integration & polish | step-08-plan.md | 7 tasks | Yes -- E2E tests, browser verification, full suite, docs |

**Result: Full alignment.** Each plan milestone has a corresponding step plan with appropriate task decomposition.

## 3. Step-Plans-to-Step-Files Alignment

| Step Plan | Step File | Aligned? | Notes |
|---|---|---|---|
| step-01-plan.md (10 tasks) | steps/step-01.md (6 tasks) | Partial | Step file consolidates: Tasks 1-2 are rope+directory, Task 3 is schemas+endpoints, Task 4 is migration, Task 5 is config+engine+non-Python, Task 6 is test suite. Consolidation is reasonable -- all functionality covered. |
| step-02-plan.md (8 tasks) | steps/step-02.md (4 tasks) | Partial | Step file consolidates: Task 1 is types+utils, Task 2 is page+components, Task 3 is routes+API+labels, Task 4 is tests. All functionality covered. |
| step-03-plan.md (9 tasks) | steps/step-03.md (4 tasks) | Partial | Step file consolidates: Task 1 is enum+DB model, Task 2 is migration+schemas, Task 3 is API endpoints, Task 4 is execution wiring+tests. All functionality covered. |
| step-04-plan.md (6 tasks) | steps/step-04.md (3 tasks) | Partial | Consolidated into types/API, UI, tests. All functionality covered. |
| step-05-plan.md (9 tasks) | steps/step-05.md (4 tasks) | Partial | Consolidated into DB model+migration, schemas+service, API+seed, tests. All functionality covered. |
| step-06-plan.md (7 tasks) | steps/step-06.md (3 tasks) | Partial | Consolidated into config models, cascading resolution, prompt+tests. All functionality covered. |
| step-07-plan.md (9 tasks) | steps/step-07.md (4 tasks) | Partial | Consolidated into types+API, page+components, routes+nav, tests. All functionality covered. |
| step-08-plan.md (7 tasks) | steps/step-08.md (4 tasks) | Partial | Consolidated into E2E tests, browser verification, full suite, docs. All functionality covered. |

**Result: Functionally aligned.** Step files consolidate step plan tasks into fewer, coarser tasks. No functionality is lost in the consolidation. Each step file includes an "Intent Verification" header that traces back to the original intent.

## 4. Dry-Run Gap Analysis

The dry-run notes identified 16 recommendations in 3 priority tiers. Status of each:

### Critical Gaps (must fix before execution)

| # | Gap | Status | Location | Notes |
|---|---|---|---|---|
| 1 | S1-T4: Rewrite Alembic migration to use `batch_alter_table()` for SQLite; don't rely on autogenerate for column renames | UNRESOLVED | steps/step-01.md Task 4 | Task still says "Generate migration with --autogenerate" then "Edit to use op.alter_column()". Does NOT mention `batch_alter_table()` which is required for SQLite column renames. Does not enumerate all tables with `agent_type` columns. |
| 2 | S1-T5: Add exclusion list for "agent" terms that should NOT be renamed | PARTIALLY ADDRESSED | steps/step-01.md Task 5 | Task says "Do not rename fields that will be used by the new Agent concept" but lacks an explicit exclusion list (`agent_metadata`, `on_agent_metadata`, `AgentMetadataCallback`, `agent_id`). |
| 3 | S2-T1: Fix file path for agentConfigUtils.ts | UNRESOLVED | steps/step-02.md Task 1 | Both step plan and step file reference `ui/src/lib/agentConfigUtils.ts`. Dry run says actual file is at `ui/src/components/agentConfigUtils.ts`. Path needs verification against current codebase. |
| 4 | S2-T3: Add explicit field name update instructions for frontend | PARTIALLY ADDRESSED | steps/step-02.md Task 3 | Task mentions updating CreateRunModal and run-related components but does not explicitly list the field renames: `agent_type`->`runner_type`, `agent_config`->`runner_config`, `agent_started_at`->`runner_started_at`. |
| 5 | S5-T3: Provide default prompt text for seeded agents | UNRESOLVED | steps/step-05.md Task 3 | Task says to seed 3 agents with prompts but provides no actual prompt text. Builder agents need concrete text to implement. |
| 6 | S5-T3: Specify idempotent seeding pattern | UNRESOLVED | steps/step-05.md Task 3 | No mention of upsert/idempotent seeding. Running seed script twice would create duplicates. |

### Important Gaps (reduce failure likelihood)

| # | Gap | Status | Location | Notes |
|---|---|---|---|---|
| 7 | S1-T1: Add rope fallback plan if rope fails | UNRESOLVED | steps/step-01.md Task 1 | No fallback mentioned. If rope fails on Python 3.12+ or Protocol classes, the builder has no alternative. |
| 8 | S1-T2: Mention parsers subdirectory explicitly | UNRESOLVED | steps/step-01.md Task 2 | `src/orchestrator/agents/parsers/` has 5 files with internal imports. Not mentioned in task instructions. |
| 9 | S2-T2: Check if components are inline before git mv | UNRESOLVED | steps/step-02.md Task 2 | Task assumes components are separate files. Dry run notes say AgentCard et al. may be inline in Agents.tsx. |
| 10 | S3-T4 & S6-T2: Add environment discovery checks for exact names | PARTIALLY ADDRESSED | steps/step-03.md Task 4, steps/step-06.md Task 2 | Step 6 Task 2 uses "build"/"verify" phase strings. Dry run warns these may not match codebase (could be "building"/"verifying"). No grep verification step. |
| 11 | S8-T1: Specify E2E test runner strategy (USER_MANAGED) | UNRESOLVED | steps/step-08.md Task 1 | No mention of which runner type to use or how to simulate agent execution. |
| 12 | S8-T2: Add health checks before browser verification | UNRESOLVED | steps/step-08.md Task 2 | No polling/health check before navigating. Also no verification that `VITE_API_PORT` env var works in vite.config.ts. |

### Nice-to-Have Gaps (improve robustness)

| # | Gap | Status | Location | Notes |
|---|---|---|---|---|
| 13 | Add checkpoint verification between tasks | UNRESOLVED | All steps | No smoke checks between tasks. |
| 14 | Decide routine YAML backward compatibility for `agent_type` field | UNRESOLVED | steps/step-01.md Task 5 | Not decided whether YAML `agent_type` field is renamed or kept for backward compat. |
| 15 | Verify model selector component exists before building profile UI | UNRESOLVED | steps/step-04.md Task 2 | No early check for existing combobox pattern. |
| 16 | Sidebar UX: differentiate "Agent Runners" and "Agents" | UNRESOLVED | steps/step-07.md Task 3 | Task says "use appropriate icons to differentiate" but no specific guidance. |

## 5. Architecture Document Consistency

| Check | Result |
|---|---|
| Architecture file structure matches plan milestones | Yes -- `runners/` (M1), `agents/` (M5), new routers, new schemas all documented |
| Architecture API endpoints match step plans | Yes -- renamed endpoints (M1-M2) and new endpoints (M3, M5) all listed |
| Architecture data model matches step files | Yes -- `runs` column renames, `runner_profile_defaults`, `agent_configs` all specified |
| Architecture execution flow matches step 6 resolution | Yes -- cascading resolution order documented: task -> step -> routine -> default |
| Architecture prompt composition matches clarification Q6 | Yes -- "simple concatenation" documented |
| Architecture per-run profile overrides match clarification Q5 | Yes -- `profile_overrides` on run creation documented |

## 6. Clarification Incorporation

All 10 clarifications have been incorporated into the artifacts:

| Clarification | Incorporated In |
|---|---|
| Q1: Planner is user-assignable only | intent.md, plan.md M5, step-05-plan.md, architecture.md |
| Q2: Use prefixed names (AgentRunner*) | intent.md, plan.md M1, architecture.md, all step files |
| Q3: Alembic migrations only | intent.md, plan.md, step-01-plan.md, step-03-plan.md |
| Q4: Rope for Python + manual for non-Python | plan.md M1, step-01-plan.md |
| Q5: Per-run model-profile overrides | architecture.md (profile_overrides), step-03-plan.md (deferred) |
| Q6: Simple concatenation for prompts | architecture.md, step-06-plan.md, steps/step-06.md |
| Q7: Factory defaults with reset | architecture.md, step-05-plan.md, steps/step-05.md |
| Q8: All 4 profiles from start | architecture.md, step-03-plan.md, steps/step-03.md |
| Q9: /agent-runners and /agents routes | architecture.md, step-02-plan.md, step-07-plan.md |
| Q10: No additional features | Scope unchanged from intent |

## 7. Critical Conflicts

No unresolved critical conflicts exist between artifacts. Specifically:

- **No contradictions** between intent and plan -- all scope items map to milestones.
- **No contradictions** between plan and step files -- task consolidation reduces count but preserves functionality.
- **No contradictions** between architecture and step files -- all data models, APIs, and flows are consistent.
- **No contradictions** between clarifications and implementation plans -- all answers reflected.

The 6 critical dry-run gaps are **execution risks**, not conflicts between documents. They represent missing details in step files that could cause builder agents to fail or produce incorrect results. They should be addressed before execution by updating the step files.

## 8. Summary and Recommendations

### Overall Assessment: READY WITH CAVEATS

The intent, plan, step plans, step files, architecture, and clarifications are mutually consistent and well-aligned. The 8-step execution order is sound. Each milestone preserves a working system.

### Action Items Before Execution

**Must fix (6 critical gaps):**

1. **Step 1, Task 4**: Add `batch_alter_table()` instruction for SQLite column renames. Add `grep` to enumerate ALL tables with `agent_type` columns.
2. **Step 1, Task 5**: Add explicit exclusion list: `agent_metadata`, `on_agent_metadata`, `AgentMetadataCallback`, `agent_id` (lock manager).
3. **Step 2, Task 1**: Verify actual path of `agentConfigUtils.ts` and correct if needed.
4. **Step 2, Task 3**: Add explicit field rename list: `agent_type`->`runner_type`, `agent_config`->`runner_config`, `agent_started_at`->`runner_started_at`, `agent_type_display`->`runner_type_display`.
5. **Step 5, Task 3**: Provide default prompt text for Planner, Builder, Verifier agents (or create a reference file).
6. **Step 5, Task 3**: Add upsert/idempotent seeding instruction.

**Should fix (6 important gaps):**

7. Add rope fallback plan (manual sed + grep) to Step 1, Task 1.
8. Mention `parsers/` subdirectory explicitly in Step 1, Task 2.
9. Add component structure check (inline vs separate files) to Step 2, Task 2.
10. Add phase name verification grep to Step 6, Task 2.
11. Specify USER_MANAGED runner + API callback simulation for E2E tests in Step 8, Task 1.
12. Add health check polling and VITE_API_PORT verification to Step 8, Task 2.
