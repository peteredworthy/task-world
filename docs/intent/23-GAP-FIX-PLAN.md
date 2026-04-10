# Plan: Fixing Remaining Gaps

This plan addresses gaps documented in `22-REMAINING-GAPS.md`.

**Last updated:** 2026-02-05 (gap fix phases K-R complete)

---

## Completed Phases

The following phases from the original plan have been **implemented**:

| Phase | Items | Status |
|-------|-------|--------|
| A | Quick Wins (step_context, input validation, singular task:, doc fixes) | ✅ Complete |
| B | Run Lifecycle (queue, cancel, validate endpoints) | ✅ Complete |
| C | Pessimistic Locking (InMemoryLockManager) | ✅ Complete |
| D | Auto-Verify Execution (LocalAutoVerifyRunner) | ✅ Complete |
| E | Embedded Routines (routine_embedded field) | ✅ Complete |
| F1 | Project-Local Routines (RoutineSource.PROJECT) | ✅ Complete |
| G1 | Project Entity (minimal listing) | ✅ Complete |
| H | Global Configuration (load_global_config) | ✅ Partial - loads but not all settings wired |
| I | Cost Estimation (estimate_cost function) | ✅ Complete |

---

## Remaining Work

### Phase K: User-Managed Agent Endpoints (C3-REMAINING)

**Gap:** External agent lifecycle endpoints missing.

**Files:**
- Modify: `src/orchestrator/api/routers/runs.py`
- Modify: `src/orchestrator/api/schemas/runs.py`
- Add: `tests/integration/test_api_user_managed.py`

**Endpoints to add:**

| Endpoint | Purpose | Implementation |
|----------|---------|----------------|
| `GET /api/runs/{id}/guidance` | Aggregate guidance info | Return current task prompt + MCP URL + expected actions |
| `POST /api/runs/{id}/agent-started` | Mark agent started | Set `agent_started_at` timestamp on run |
| `POST /api/runs/{id}/agent-cancelled` | Cancel waiting | Transition run to FAILED with cancellation reason |

**Tests:**
- Integration: Get guidance returns prompt and MCP info
- Integration: Mark agent started updates timestamp
- Integration: Cancel waiting fails the run

**Priority:** High - improves external agent UX

---

### Phase L: Backward Transitions API (NEW-1)

**Gap:** BackwardTransitionConfig exists but no API to trigger.

**Files:**
- Modify: `src/orchestrator/workflow/engine.py` - add `transition_backward()` method
- Modify: `src/orchestrator/workflow/service.py` - add async wrapper
- Modify: `src/orchestrator/api/routers/runs.py` - add endpoint
- Modify: `src/orchestrator/api/schemas/runs.py` - add request/response
- Add: `tests/unit/test_backward_transitions.py`
- Add: `tests/integration/test_api_backward_transitions.py`

**Changes:**
1. `WorkflowEngine.transition_backward(run_id, target_step_index, reason)`:
   - Validate target step exists and is before current
   - Set `current_step_index` to target
   - Reset tasks in skipped steps to PENDING
   - Emit `RunStepBackward` event
2. `POST /api/runs/{id}/transition-back`:
   - Accept `target_step_index` and optional `reason`
   - Call engine method
   - Return updated run

**Tests:**
- Unit: transition_backward resets step state correctly
- Unit: invalid target step raises error
- Integration: API endpoint triggers backward transition

**Priority:** High - enables Phase 9 advanced workflows

---

### Phase M: CLI Commands (NEW-2)

**Gap:** Several CLI commands are stubs or missing.

**Files:**
- Modify: `src/orchestrator/cli/runs.py`
- Modify: `src/orchestrator/cli/routines.py`
- Add: `tests/integration/test_cli.py`

**Commands to implement:**

| Command | Implementation |
|---------|----------------|
| `runs watch <id>` | WebSocket connection, stream events to terminal |
| `runs pause <id>` | Call `POST /api/runs/{id}/pause` |
| `runs resume <id>` | Call `POST /api/runs/{id}/resume` |
| `runs cancel <id>` | Call `POST /api/runs/{id}/cancel` |
| `runs status <id>` | Call `GET /api/runs/{id}`, format output |
| `routines show <id>` | Call `GET /api/routines/{id}`, display YAML |

**Priority:** Medium - convenience layer; API works directly

---

### Phase N: External Git Routines (S3-REMAINING)

**Gap:** Can't fetch routines from external git URLs.

**Deferred to Phase 7 completion.** Requires:
- Git clone infrastructure
- URL allowlist configuration
- Cache management for cloned repos
- Security review

**Files (when implemented):**
- Create: `src/orchestrator/routines/external.py`
- Modify: `src/orchestrator/config/enums.py` - add `RoutineSource.EXTERNAL`
- Modify: `src/orchestrator/routines/discovery.py` - fetch from URLs
- Modify: `src/orchestrator/config/global_config.py` - allowlist config

**Priority:** Medium - enables shared routine libraries

---

### Phase O: WebSocket Batching (NEW-3)

**Gap:** Events broadcast immediately without throttling.

**Files:**
- Modify: `src/orchestrator/api/websocket.py`

**Changes:**
1. Add `BatchingConnectionManager` that:
   - Collects events for 100ms
   - Batches events by run_id
   - Sends batched updates
2. Use asyncio timer for batch window

**Priority:** Low - performance optimization

---

### Phase P: Activity SSE Streaming (NEW-4)

**Gap:** No dedicated streaming endpoint for activity.

**Files:**
- Modify: `src/orchestrator/api/routers/runs.py`

**Changes:**
1. Add `GET /api/runs/{id}/activity/stream` SSE endpoint
2. Subscribe to event store, filter by run_id
3. Yield events as SSE messages

**Priority:** Low - WebSocket provides similar functionality

---

### Phase Q: Global Config Wiring (NEW-5)

**Gap:** Some config options not used.

**Files:**
- Modify: `src/orchestrator/api/app.py`
- Modify: `src/orchestrator/agents/nudger.py`
- Modify: `src/orchestrator/api/routers/runs.py`

**Changes:**
1. Pass `agents.openhands_url` to OpenHands agent initialization
2. Include `dashboard` config in a new endpoint or frontend config fetch
3. Inject `nudger` config when creating Nudger instances
4. Use `dashboard.max_recent_runs` in list queries

**Priority:** Low - defaults work; polish item

---

### Phase R: Documentation Updates (D2, D3) ✅ RESOLVED

**Gap:** Stale module names and file references in docs.

**Files:**
- Modified: `docs/intent/01-ARCHITECTURE.md`
- Modified: `docs/intent/04-CLAUDE-MD.md`
- Modified: `docs/intent/10-SLICES-OVERVIEW.md`
- Modified: `docs/intent/22-REMAINING-GAPS.md` (marked D2, D3 as resolved)

**Changes completed:**
1. ✅ Updated module paths in architecture doc (section 2.2.3, 2.2.7, and directory structure)
2. ✅ Updated directory structure in CLAUDE-MD doc template
3. ✅ Clarified file references in slice overview document index
4. ✅ Updated gap tracking documents

**Priority:** Low - documentation maintenance

---

## Execution Order & Dependencies

```
Phase K (user-managed endpoints) ← no dependencies, high value
Phase L (backward transitions) ← no dependencies, enables Phase 9

Phase M (CLI commands) ← independent, medium value
Phase N (external git) ← requires git infrastructure design

Phase O (WS batching) ← independent, low priority
Phase P (activity SSE) ← independent, low priority
Phase Q (config wiring) ← independent, low priority
Phase R (docs) ← independent, low priority
```

**Recommended order:** K → L → M → N → (O, P, Q, R in any order)

---

## Summary

| Phase | Description | Priority | Status |
|-------|-------------|----------|--------|
| K | User-managed agent endpoints | High | ✅ Complete |
| L | Backward transitions API | High | ✅ Complete |
| M | CLI commands | Medium | ✅ Complete |
| N | External git routines | Medium | Deferred to Phase 7 |
| O | WebSocket batching | Low | ✅ Complete |
| P | Activity SSE | Low | ✅ Complete |
| Q | Config wiring | Low | ✅ Complete |
| R | Documentation | Low | ✅ Complete |

**Total phases:** 8 covering 9 gaps
**Completed:** 7 phases (K, L, M, O, P, Q, R)
**Deferred:** 1 phase (N - external git routines, requires Phase 7 infrastructure)
**Previously completed:** 9 phases covering 11 gaps

---

## Completion Summary

**Completed:** 2026-02-05

**Test Results (post-completion):**
- Unit tests: 503 passing
- Integration tests: 312 passing (2 expected failures for OpenHands SDK not installed)
- Frontend tests: 221 passing
- TypeScript/ESLint: Clean

**Manual Verification:**
- CLI commands (runs list, status, pause, resume, cancel, routines list, show) working
- UI Dashboard loads and displays runs correctly
- Run expand/collapse shows tasks and steps properly
- Create run modal works with routine pre-selection
- Agent selection and run creation functional

**Remaining Work:**
- Phase N (external git routines) requires Phase 7 git infrastructure to be completed first
