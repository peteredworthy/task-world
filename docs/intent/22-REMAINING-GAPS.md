# Remaining Gaps: System Description vs Implementation

This document records gaps between the system description documents (01-ARCHITECTURE through 06-EXAMPLE-CONFIGS) and the slice-based implementation.

**Last updated:** 2026-02-05 (post Phase 5-8 implementation)

---

## Resolved Gaps (Previously Listed)

The following gaps from the original document have been **implemented**:

| ID | Description | Resolution |
|----|-------------|------------|
| C1 | Pessimistic locking | `workflow/locks.py` - InMemoryLockManager with 5-min timeout |
| C2 | Auto-verify execution | `workflow/auto_verify.py` - LocalAutoVerifyRunner executes commands |
| C4 | Run status transitions | `workflow/engine.py` - queue_run(), cancel_run() methods |
| S1 | Singular `task:` YAML | `config/models.py` - normalize_task_key validator |
| S2 | Embedded routines | `state/models.py` - routine_embedded field, API support |
| S4 | Project entity | `api/routers/projects.py` - minimal project listing |
| M1 | Global config loading | `config/global_config.py` - loads ~/.orchestrator/config.yaml |
| M2 | Artifact storage | `artifacts/registry.py`, `artifacts/models.py` |
| M3 | Cost estimation | `metrics/cost.py` - estimate_cost() with gpt-4o pricing |
| M4 | Step context in prompts | `workflow/prompts.py` - step_context included in builder/verifier |
| M5 | Routine input validation | `state/factory.py` - validate_routine_inputs() |

**Partially resolved:**

| ID | Description | Status |
|----|-------------|--------|
| C3 | Missing API endpoints | queue, cancel, validate, recent_hours implemented; 3 deferred (see below) |
| S3 | External routine fetching | PROJECT source implemented; EXTERNAL git fetch deferred to Phase 7 |

---

## Current Gaps

### C3-REMAINING. User-Managed Agent Endpoints

**Status:** Addressed in Phase K (23-GAP-FIX-PLAN.md)

**Specified in:** 03-PRD section 6, 01-ARCHITECTURE 5.3 (User-Managed Agent UX)

**Requirement:** External agents need guidance endpoints and lifecycle management.

**Missing endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/runs/{id}/guidance` | Get agent guidance (prompt, MCP URL, expected actions) |
| `POST /api/runs/{id}/agent-started` | Mark that user has started their external agent |
| `POST /api/runs/{id}/agent-cancelled` | Cancel waiting for external agent |

**Current state:** The task prompt endpoint (`GET /tasks/{id}/prompt`) provides prompt content with callback instructions. The UI shows MCP URL in AgentGuidancePanel. But there's no way to signal agent start/cancel from the API.

**Workaround:** UI can track agent state locally; external agents use MCP submit directly.

**Severity:** Moderate - affects UX for user-managed agents but doesn't block functionality.

---

### S3-REMAINING. External Git Routine Fetching

**Status:** Addressed in Phase N (23-GAP-FIX-PLAN.md) - deferred to Phase 7 completion

**Specified in:** 01-ARCHITECTURE 1.2, 03-PRD FR-RM-3

**Requirement:** Routines can be loaded from allowlisted external git URLs.

**Current state:** `RoutineSource.LOCAL` and `RoutineSource.PROJECT` work. No `RoutineSource.EXTERNAL`, no git clone, no URL allowlisting.

**Deferred to:** Phase 7 (Git Integration) - requires git clone infrastructure and security considerations.

**Severity:** Moderate - shared routine libraries not supported; all routines must be local.

---

### NEW-1. Backward Transitions API

**Status:** Addressed in Phase L (23-GAP-FIX-PLAN.md)

**Specified in:** 19-SLICES-PHASE-9.md section 9.2, config/models.py (BackwardTransitionConfig)

**Requirement:** Allow returning to an earlier step when conditions are met (e.g., "If conflicts emerge, RETURN to Stage 2").

**Current state:** `BackwardTransitionConfig` model exists in config/models.py. The workflow engine has no method to execute backward transitions. No API endpoint to trigger them.

**Missing:**
- `WorkflowEngine.transition_backward()` method
- `POST /api/runs/{id}/steps/{step_id}/transition-back` endpoint

**Severity:** Significant - Phase 9 feature for advanced workflows not accessible.

---

### NEW-2. CLI Commands Incomplete

**Status:** Addressed in Phase M (23-GAP-FIX-PLAN.md)

**Specified in:** 18-SLICES-PHASE-8.md section 8.1

**Requirement:** Full CLI for run management.

**Missing commands:**

| Command | Status |
|---------|--------|
| `orchestrator runs watch <id>` | Stub exists, not implemented |
| `orchestrator runs pause <id>` | Not implemented |
| `orchestrator runs resume <id>` | Not implemented |
| `orchestrator runs cancel <id>` | Not implemented |
| `orchestrator runs status <id>` | Not implemented |
| `orchestrator routines show <id>` | Not implemented |

**Current state:** Basic `list`, `create`, `start` work. Advanced lifecycle commands missing.

**Severity:** Moderate - users can use API directly; CLI is convenience layer.

---

### NEW-3. WebSocket Event Batching

**Status:** Addressed in Phase O (23-GAP-FIX-PLAN.md)

**Specified in:** 01-ARCHITECTURE 2.2.1, 03-PRD FR-UI-4

**Requirement:** "WebSocket with throttling (100ms), batch related updates"

**Current state:** `api/websocket.py` broadcasts events immediately without batching. High-frequency updates (e.g., token counts during agent execution) could flood clients.

**Impact:** Performance issue under heavy load, not a functional gap.

**Severity:** Minor - optimization for future scale.

---

### NEW-4. Activity Event SSE Streaming

**Status:** Addressed in Phase P (23-GAP-FIX-PLAN.md)

**Specified in:** 01-ARCHITECTURE mentions "real-time updates", 03-PRD FR-UI-4

**Requirement:** Live activity feed via streaming.

**Current state:** `GET /api/runs/{id}/activity` returns static snapshot. WebSocket broadcasts all run events but no dedicated SSE endpoint for activity streaming with proper pagination.

**Impact:** Activity feed requires polling or WebSocket parsing.

**Severity:** Minor - WebSocket provides real-time updates; this is a convenience gap.

---

### NEW-5. Global Config Not Fully Wired

**Status:** Addressed in Phase Q (23-GAP-FIX-PLAN.md)

**Specified in:** 01-ARCHITECTURE 6, 06-EXAMPLE-CONFIGS section 1

**Requirement:** `~/.orchestrator/config.yaml` configures server, database, routines, agents, dashboard, nudger.

**Current state:** `load_global_config()` exists and is called. Database path and routine dirs are used. But:
- `agents.openhands_url` not wired to OpenHands agent
- `dashboard.refresh_interval_seconds` not sent to frontend
- `dashboard.max_recent_runs` not used in API
- `nudger` config not injected into Nudger class

**Severity:** Minor - defaults work; config file partially respected.

---

## Documentation Gaps

### D1. YAML Examples (RESOLVED)

The implementation now accepts both `task:` (singular) and `tasks:` (plural) via the normalize_task_key validator. Documentation examples are now compatible.

### D2. Directory/Module Naming (RESOLVED)

**Status:** ✅ Resolved in Phase R

**Files:** 01-ARCHITECTURE.md section 8, 04-CLAUDE-MD.md

Directory structure and module references have been updated to match the actual implementation:
- `api/` + `routers/` (not `server/` + `routes/`)
- `agents/interface.py` (not `agents/base.py`)
- `routines/loader.py` + `routines/discovery.py` (not `routines/resolver.py`)
- `db/connection.py` (not `state/database.py`)
- `db/event_store.py` (not `state/history.py`)
- `workflow/prompts.py` (not `agents/prompts.py`)

The main `CLAUDE.md` at the project root remains correct.

### D3. Slice Overview File References (RESOLVED)

**Status:** ✅ Resolved in Phase R

**File:** 10-SLICES-OVERVIEW.md

Document index references have been clarified to show the correct numbering (11-SLICES-PHASE-1.md through 21-SLICES-PHASE-10.md).

---

## Summary

| Category | Count | IDs | Plan Status |
|----------|-------|-----|-------------|
| Remaining from original | 2 | C3-REMAINING (3 endpoints), S3-REMAINING (external git) | Phase K ✅, Phase N |
| New gaps found | 5 | NEW-1 (backward transitions), NEW-2 (CLI), NEW-3 (WS batching), NEW-4 (activity SSE), NEW-5 (config wiring) | Phase L ✅, M ✅, O ✅, P ✅, Q ✅ |
| Documentation | 2 | D2 (module names), D3 (slice references) | Phase R ✅ |
| **Total active gaps** | **1** | S3-REMAINING (deferred to Phase 7) | |

**Previously resolved:** 11 gaps (C1, C2, C4, S1, S2, S4, M1-M5, D1)
**Recently resolved:** 8 gaps (C3-REMAINING, NEW-1 through NEW-5, D2, D3)

---

## Implementation Priority (Completed)

All gaps except S3-REMAINING have been addressed. See `23-GAP-FIX-PLAN.md` for implementation details.

**High priority (affects core workflows) - COMPLETED:**
1. NEW-1: Backward transitions API → Phase L ✅
2. C3-REMAINING: User-managed agent endpoints → Phase K ✅

**Medium priority (convenience/polish) - COMPLETED:**
3. NEW-2: CLI commands → Phase M ✅
4. S3-REMAINING: External git routines → Phase N (deferred to Phase 7)

**Low priority (optimization/docs) - COMPLETED:**
5. NEW-3: WebSocket batching → Phase O ✅
6. NEW-4: Activity SSE → Phase P ✅
7. NEW-5: Config wiring → Phase Q ✅
8. D2, D3: Documentation updates → Phase R ✅
