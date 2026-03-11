# Plan Summary: Orchestrated Expansion (Option D)

Generated: 2026-03-11
Status: READY WITH REQUIRED FIXES (see Risks section)

---

## Intent Satisfaction Summary

The plan fully satisfies the stated intent: give running builder agents the ability to request additional work through the orchestrator, replacing untracked sub-agent escape hatches with tracked, verified, visible work items. All 17 intent items map directly to plan deliverables:

| Intent Item | Covered By | Status |
|---|---|---|
| Expansion API endpoint (`POST .../expand`) | M2 / Step 5 | ✅ |
| Three expansion types (add_subtask, add_peer_task, add_next_step) | M2 / Steps 3–4 | ✅ |
| ExpansionLimits with 5 fields | M1 / Step 1 | ✅ |
| Provenance tracking (expanded_from_task_id, justification, is_expansion) | M1 / Steps 1–2 | ✅ |
| TaskExpanded event | M1 / Step 1 | ✅ |
| Budget enforcement (429 on exhaustion) | M2 / Step 5 | ✅ |
| add_subtask blocking via FAN_OUT_RUNNING | M2 / Step 3 | ✅ |
| add_next_step index reordering | M2 / Step 4 | ✅ |
| Expansion callback in builder prompt | M3 / Step 6 | ✅ |
| Human approval mode (require_human_approval) | M2 / Steps 4–5 | ✅ |
| MCP tool registration (orchestrator_expand_task) | M3 / Step 6 | ✅ |
| Frontend: expanded task badges, dashed borders, step indicator | M4 / Step 7 | ✅ |
| Frontend: ActivityFeed TaskExpanded events | M4 / Step 7 | ✅ |
| Frontend: budget usage display | M4 / Step 7 | ✅ |
| total_expansions on Run / expansion_count on RunModel | M1 / Step 1 | ✅ |
| DB migration (Alembic) | M1 / Step 2 | ✅ |
| Integration + frontend tests | M2 Step 5 / M4 Step 7 | ✅ |

All five clarification decisions (Q1–Q5) are reflected in the step files.

---

## Ordered Step List

| Step | Name | Tasks | Milestone | Purpose |
|------|------|-------|-----------|---------|
| 1 | Data Models | 6 | M1 core | ExpansionLimits, state fields, DB model columns, schemas, TaskExpanded event, unit tests |
| 2 | DB Migration | 3 | M1 remaining | Alembic migration for 7 new columns (including pending_expansion_request), upgrade/downgrade verified |
| 3 | Engine — add_subtask | 5 | M2 core | WorkflowEngine.expand_task() for subtask type (blocking + non-blocking), budget check, service wrapper, event emission |
| 4 | Engine — add_peer_task + add_next_step + Human Approval | 6 | M2 remaining | Remaining expansion types, step index reordering, approve_expansion() service method |
| 5 | API Endpoint + Integration Tests | 4 | M2 final | Router registration, error handlers (429/409), full integration test suite (13+ cases) |
| 6 | Executor + Prompt Integration | 5 | M3 | Builder prompt expansion section, executor mid-step task discovery, orchestrator_expand_task MCP tool |
| 7 | Frontend Display | 7 | M4 | TypeScript types, expanded task UI, step indicators, ActivityFeed events, budget display, frontend tests |

**Total: 36 tasks across 7 steps.**

### Step Prerequisites

```
Step 1 (no deps)
  └─ Step 2
       └─ Step 3
            └─ Step 4
                 └─ Step 5
                      ├─ Step 6
                      └─ Step 7
```

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Q1: StepModel provenance columns | Both TaskModel and StepModel get is_expansion + expanded_from_task_id | idea.md intent; StepState runtime model must also gain these fields |
| Q2: add_next_step task count | Multiple tasks via tasks[] array in ExpansionRequest | Supports real multi-task steps without artificial one-task limit |
| Q3: FAN_OUT_RUNNING can expand? | Not applicable — agent is not executing in that state | Avoids undefined behavior; FAN_OUT_RUNNING is a wait state, not a build state |
| Q4: Human approval mode | Required — implement fully | New endpoint (expand/approve), pending_expansion_request storage, UI display |
| Q5: MCP tool | Required — register as orchestrator_expand_task | Consistent with orchestrator_submit / orchestrator_update_checklist naming |
| add_subtask blocking implementation | Reuse FAN_OUT_RUNNING + complete_fan_out_parent | Fan-out infrastructure already handles parent-wait-for-children correctly |
| Budget exhaustion response | 429 with message identifying which limit was hit | Standard HTTP semantics for rate limiting |
| Phase restriction | Build phase only (BUILDING status) | Verified/completed tasks should not spawn new work |
| add_next_step index shift | Atomic DB update of order_index on all shifted steps | Consistent with existing order_index pattern; prevents partial states |
| Human approval storage | pending_expansion_request JSON field on TaskModel/TaskState | No separate approvals table; payload stored inline for approve_expansion() deserialization |
| MCP tool prefix | orchestrator_expand_task (with orchestrator_ prefix) | Matches all existing MCP tools |

---

## Risks and Mitigations

### Critical — Must Fix Before Step 1 Begins

| Risk | Impact | Mitigation |
|---|---|---|
| StepState missing is_expansion and expanded_from_task_id fields | Step 4 add_next_step fails with AttributeError when setting provenance on new StepState | Add both fields to StepState in Step 1 Task 2 |
| Missing pending_expansion_request storage | Human approval mode (Steps 3–4) has nowhere to store the ExpansionRequest payload; approve_expansion() cannot deserialize and execute the stored request | Add TaskState.pending_expansion_request: str \| None = None and TaskModel column in Step 1; add DB column in Step 2 migration |
| Wrong Alembic migration path in step-02 | Step 2 fails immediately — alembic commands reference alembic/versions/ but actual path is src/orchestrator/db/migrations/versions/ | Fix all step-02 path references before agent begins; add --config src/orchestrator/db/migrations/alembic.ini to all alembic commands |

### Significant — Must Fix Before Step 3 Begins

| Risk | Impact | Mitigation |
|---|---|---|
| expand_fan_out_task() lives on WorkflowService, not WorkflowEngine | Agent may try to call service method from within engine, breaking separation of concerns | Clarify step-03 Task 2: engine sets FAN_OUT_RUNNING + adds child TaskState; service calls expand_fan_out_task() after engine returns |

### Moderate — Fix Before Relevant Step

| Risk | Impact | Mitigation |
|---|---|---|
| requirements field type: list[str] vs list[dict] | ExpansionRequest schema incompatible with RequirementConfig structure | Fix step-01 Task 4 to use list[dict] \| None with {id, desc, must, priority} keys |
| MCP tool name missing orchestrator_ prefix | Inconsistent with existing tools; agents won't find the tool via expected naming | Fix step-06 Task 3 to use orchestrator_expand_task |
| Executor in-memory state not updated after DB refresh | New peer tasks added mid-step won't be discovered by _get_next_task() | Step-06 Task 2 must explicitly update run.steps[current_step_index].tasks after DB refresh, not just the local pending variable |
| Route shadowing: /expand captures /expand/approve | FastAPI processes routes in order; approve route must be registered first | step-05 already identifies this; agent must register /expand/approve before /expand |
| Autogenerate noise in alembic migration | Migration includes unrelated diffs from out-of-sync DB | Run alembic current first; trim generated migration carefully |
| Peer budget counter too broad | May count subtasks (non-blocking) as peer expansions | Counter must filter: no parent_task_id AND expanded_from_task_id set |
| Blocking subtask from fan-out parent (nested fan-out) | Infinite nesting, undefined state | Guard in step-03: add_subtask blocking disallowed if task already has parent_task_id set |
| Human approval deadlock | Approval never arrives; run stalls indefinitely | No automatic timeout in initial implementation; document this; add expiry as future enhancement |
| task_expanded event type string mismatch | ActivityFeed won't render expansion events if frontend event.type doesn't match backend serialization | Confirm event_type string against workflow/events.py before implementing ActivityFeed handler |

---

## Caveats for Execution

1. **DB state after Step 2 must be clean.** The existing orchestrator.db must be deleted and recreated (`rm orchestrator.db && uv run python scripts/seed_db.py`) after the Alembic migration is applied, or the migration must be run against the live DB with `alembic upgrade head`. Do not rely on `create_all()` to add new columns.

2. **Integration tests require specific DB state.** Steps 3–5 integration tests need a run in ACTIVE state with a task in BUILDING state. Reuse or create a `create_active_run_with_building_task()` fixture in conftest.py rather than duplicating setup across 13+ test cases.

3. **build_prompt() signature change must use defaults.** New parameters (`expansion_limits`, `total_expansions`) must have defaults so all existing call sites continue to work without modification.

4. **Budget string for non-expansion routines.** If expansion_limits is None (routines without explicit config), the prompt section should use ExpansionLimits() defaults and note that expansion is available even if the routine doesn't configure it.

5. **Frontend event type must match backend serialization.** Before implementing ActivityFeed handler, grep workflow/events.py to confirm the exact string value of TaskExpanded's event_type field (expected: "task_expanded").

6. **Step 7 component discovery.** The "step view component" for peer task dashed borders is not immediately obvious — may be StepDetail.tsx, StepCard.tsx, or similar. Search before editing: `grep -r "task.status" ui/src/components`.

7. **Expanded task ID display.** "Added by T-{id}" labels should use truncated IDs (first 8 chars) for readability.

8. **Append-only invariant is non-negotiable.** No expansion type may modify or delete existing tasks, steps, or requirements. Every code path in the expansion engine must be reviewed against this constraint.

9. **Pre-commit must pass.** Run `uv run pre-commit run --all-files` before submitting each step for verification.

---

## References

- [intent.md](intent.md) — Full feature specification and definition of complete
- [plan.md](plan.md) — Four-milestone plan with key decisions and risks
- [architecture.md](architecture.md) — Schema, endpoint, and error type definitions
- [clarifications.md](clarifications.md) — Q&A archive for all five decisions
- [dry-run-notes.md](dry-run-notes.md) — Per-step simulation with blocker analysis
- [verification-report.md](verification-report.md) — Gap resolution status table
- [steps/](steps/) — Detailed task descriptions for each step (step-01.md through step-07.md)
